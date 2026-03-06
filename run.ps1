$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "run.lib.ps1")

function Ensure-Command($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "Missing required command: $name"
  }
}

Ensure-Command node

function Resolve-PythonExecutable() {
  if ($env:LOGICKG_PYTHON) {
    if (Test-Path $env:LOGICKG_PYTHON) { return $env:LOGICKG_PYTHON }
    throw "LOGICKG_PYTHON points to a missing file: $($env:LOGICKG_PYTHON)"
  }

  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCmd) {
    try {
      $resolved = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $resolved) {
        return (($resolved | Select-Object -First 1).Trim())
      }
    } catch { }
  }

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    return $pythonCmd.Source
  }
  throw "Missing required command: python (or py launcher)"
}

$pythonExe = Resolve-PythonExecutable

# ---- Port selection helpers (avoid WinError 10013/10048) ----
function Get-ExcludedTcpPortRanges() {
  $ranges = @()
  try {
    $out = & netsh interface ipv4 show excludedportrange protocol=tcp 2>$null
    foreach ($line in ($out | Select-Object -Skip 4)) {
      $t = ($line -replace "\s+", " ").Trim()
      if (-not $t) { continue }
      if ($t -match "^(?<start>\d+)\s+(?<end>\d+)\s*(\*.*)?$") {
        $ranges += @(@{ start = [int]$Matches.start; end = [int]$Matches.end })
      }
    }
  } catch { }
  return $ranges
}

function Test-PortExcluded($port, $ranges) {
  foreach ($r in ($ranges | Where-Object { $_ -and $_.start -and $_.end })) {
    if ($port -ge $r.start -and $port -le $r.end) { return $true }
  }
  return $false
}

function Test-PortListening($port) {
  try {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    return [bool]$c
  } catch {
    # Fallback to netstat if Get-NetTCPConnection is unavailable.
    try {
      $out = & netstat -aon 2>$null | Select-String -Pattern (":$port\s+LISTENING") -SimpleMatch
      return [bool]$out
    } catch {
      return $false
    }
  }
}

function Find-FreePort($candidates, $excludedRanges) {
  foreach ($p in $candidates) {
    $port = [int]$p
    if ($port -lt 1024 -or $port -gt 65535) { continue }
    if (Test-PortExcluded $port $excludedRanges) { continue }
    if (Test-PortListening $port) { continue }
    return $port
  }
  # Last resort: pick a high port that's not excluded/listening.
  for ($p = 18000; $p -lt 18100; $p++) {
    if (Test-PortExcluded $p $excludedRanges) { continue }
    if (Test-PortListening $p) { continue }
    return $p
  }
  throw "Could not find a free TCP port"
}

# Avoid PowerShell execution policy issues with npm.ps1 shims by preferring npm.cmd.
$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) { $npmCmd = (Get-Command npm -ErrorAction Stop).Source }

$root = $scriptDir

Write-Host "[LogicKG] Root: $root"
Write-Host "[LogicKG] Python: $pythonExe"

# 1) Backend venv + deps
$backendDir = Join-Path $root "backend"
$venvPy = Join-Path $backendDir ".venv\\Scripts\\python.exe"
$venvPip = Join-Path $backendDir ".venv\\Scripts\\pip.exe"
$req = Join-Path $backendDir "requirements.txt"
$marker = Join-Path $backendDir ".venv\\.logickg_requirements_hash"

if (-not (Test-Path $venvPy)) {
  Write-Host "[LogicKG] Creating backend venv..."
  Push-Location $backendDir
  & $pythonExe -m venv .venv | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "Failed to create backend venv with $pythonExe (exit code $LASTEXITCODE)" }
  Pop-Location
}

$reqHash = (Get-FileHash $req -Algorithm SHA256).Hash
$needPipInstall = $true
if (Test-Path $marker) {
  $old = (Get-Content $marker -ErrorAction SilentlyContinue | Select-Object -First 1)
  if ($old -eq $reqHash) { $needPipInstall = $false }
}
if ($needPipInstall) {
  Write-Host "[LogicKG] Installing backend requirements..."
  Push-Location $backendDir
  & $venvPip install -r requirements.txt | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }
  $reqHash | Out-File -FilePath $marker -Encoding ascii -Force
  Pop-Location
}

# 2) Frontend deps + env.local
$frontendDir = Join-Path $root "frontend"
if (-not (Test-FrontendDependenciesReady $frontendDir)) {
  Write-Host "[LogicKG] Installing frontend npm dependencies..."
  Push-Location $frontendDir
  & $npmCmd install | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
  Pop-Location
}

$feEnvLocal = Join-Path $frontendDir ".env.local"
if (-not (Test-Path $feEnvLocal) -and (Test-Path (Join-Path $frontendDir ".env.example"))) {
  Copy-Item (Join-Path $frontendDir ".env.example") $feEnvLocal -Force
}

function Set-FrontendApiUrl($envFile, $port) {
  $targetLine = "VITE_API_URL=http://127.0.0.1:$port"
  $lines = @()
  if (Test-Path $envFile) {
    $lines = @(Get-Content $envFile -ErrorAction SilentlyContinue)
  }

  $updated = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*VITE_API_URL\s*=') {
      $lines[$i] = $targetLine
      $updated = $true
      break
    }
  }

  if (-not $updated) {
    $lines += $targetLine
  }

  Set-Content -Path $envFile -Value $lines -Encoding UTF8
}

Write-Host "[LogicKG] Starting dev servers..."

$excludedRanges = Get-ExcludedTcpPortRanges
$backendPort = $null
$frontendPort = $null
try {
  if ($env:LOGICKG_BACKEND_PORT) { $backendPort = [int]$env:LOGICKG_BACKEND_PORT }
} catch { $backendPort = $null }
try {
  if ($env:LOGICKG_FRONTEND_PORT) { $frontendPort = [int]$env:LOGICKG_FRONTEND_PORT }
} catch { $frontendPort = $null }

if (-not $backendPort) {
  $backendPort = Find-FreePort @(8000,8001,8002,8080,18000) $excludedRanges
}
if (-not $frontendPort) {
  $frontendPort = Find-FreePort @(5173,5174,5175,5180,15173) $excludedRanges
}
if ($frontendPort -eq $backendPort) {
  $frontendPort = Find-FreePort @($frontendPort+1, $frontendPort+2, 5173,5174,5175,5180,15173) $excludedRanges
}

Set-FrontendApiUrl $feEnvLocal $backendPort

Write-Host "[LogicKG] Backend:  http://127.0.0.1:$backendPort/docs"
Write-Host "[LogicKG] Frontend: http://127.0.0.1:$frontendPort/"
Write-Host "[LogicKG] Frontend API URL synced: http://127.0.0.1:$backendPort"
Write-Host "[LogicKG] Press Ctrl+C to stop."

$backendProc = $null
$frontendProc = $null

$cancelHandler = $null
$script:stopRequested = $false

try {
  # Intercept Ctrl+C so we can stop child processes cleanly without triggering
  # cmd.exe's "Terminate batch job (Y/N)?" prompt.
  $cancelHandler = [ConsoleCancelEventHandler]{
    param($sender, $e)
    $e.Cancel = $true
    $script:stopRequested = $true
    Write-Host "`n[LogicKG] Stopping..."
    if ($script:backendProc -and -not $script:backendProc.HasExited) { Stop-Process -Id $script:backendProc.Id -Force -ErrorAction SilentlyContinue }
    if ($script:frontendProc -and -not $script:frontendProc.HasExited) { Stop-Process -Id $script:frontendProc.Id -Force -ErrorAction SilentlyContinue }
    exit 0
  }
  [Console]::add_CancelKeyPress($cancelHandler)

  $backendProc = Start-Process -FilePath $venvPy -WorkingDirectory $backendDir -NoNewWindow -PassThru -ArgumentList @(
    "-m", "uvicorn",
    "app.main:app",
    "--reload",
    "--host", "127.0.0.1",
    "--port", "$backendPort"
  )

  $nodeExe = (Get-Command node -ErrorAction Stop).Source
  $viteBin = Get-FrontendViteBin $frontendDir
  if (-not (Test-Path $viteBin)) {
    throw "Vite not found: $viteBin (did frontend dependencies install correctly?)"
  }

  # Start Vite via node directly to avoid cmd.exe "Terminate batch job (Y/N)?" prompts.
  $frontendProc = Start-Process -FilePath $nodeExe -WorkingDirectory $frontendDir -NoNewWindow -PassThru -ArgumentList @(
    $viteBin,
    "--host", "127.0.0.1",
    "--port", "$frontendPort"
  )

  while (-not $backendProc.HasExited -and -not $frontendProc.HasExited) {
    Start-Sleep -Seconds 1
  }
} finally {
  if ($cancelHandler) { [Console]::remove_CancelKeyPress($cancelHandler) }
  if ($backendProc -and -not $backendProc.HasExited) { Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue }
  if ($frontendProc -and -not $frontendProc.HasExited) { Stop-Process -Id $frontendProc.Id -Force -ErrorAction SilentlyContinue }
}

if (-not $script:stopRequested) {
  if ($backendProc -and $backendProc.ExitCode -ne 0) { throw "Backend exited with code $($backendProc.ExitCode)" }
  if ($frontendProc -and $frontendProc.ExitCode -ne 0) { throw "Frontend exited with code $($frontendProc.ExitCode)" }
}
