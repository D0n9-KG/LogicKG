function Get-FrontendViteBin($frontendDir) {
  return Join-Path $frontendDir "node_modules\\vite\\bin\\vite.js"
}

function Test-FrontendDependenciesReady($frontendDir) {
  $nodeModulesDir = Join-Path $frontendDir "node_modules"
  $viteBin = Get-FrontendViteBin $frontendDir

  return (Test-Path $nodeModulesDir) -and (Test-Path $viteBin)
}

function Get-LogicKGWorkspaceProfile($rootPath) {
  $resolvedRoot = [System.IO.Path]::GetFullPath([string]$rootPath).TrimEnd('\', '/')
  $name = Split-Path $resolvedRoot -Leaf
  $kind = "main"

  if ($resolvedRoot -match '[\\/]\.worktrees[\\/](?<worktree>[^\\/]+)$') {
    $kind = "worktree"
    $name = $Matches.worktree
  }

  return [pscustomobject]@{
    Root = $resolvedRoot
    Kind = $kind
    Name = $name
  }
}

function Get-LogicKGStablePortOffset($name, $modulus = 300) {
  $normalized = [string]$name
  if ([string]::IsNullOrWhiteSpace($normalized)) {
    $normalized = "worktree"
  }

  $accumulator = 17
  foreach ($char in $normalized.ToCharArray()) {
    $accumulator = (($accumulator * 31) + [int][char]$char) % $modulus
  }

  return [int]$accumulator
}

function Get-LogicKGPreferredPorts($rootPath) {
  $profile = Get-LogicKGWorkspaceProfile $rootPath
  if ($profile.Kind -eq "main") {
    return [pscustomobject]@{
      Kind = $profile.Kind
      Name = $profile.Name
      BackendCandidates = @(8000, 8080, 18000, 8001, 8002)
      FrontendCandidates = @(5173, 5180, 15173, 5174, 5175)
    }
  }

  $offset = Get-LogicKGStablePortOffset $profile.Name
  $backendBase = 18100 + $offset
  $frontendBase = 15173 + $offset

  return [pscustomobject]@{
    Kind = $profile.Kind
    Name = $profile.Name
    BackendCandidates = @($backendBase, ($backendBase + 300), ($backendBase + 600))
    FrontendCandidates = @($frontendBase, ($frontendBase + 300), ($frontendBase + 600))
  }
}
