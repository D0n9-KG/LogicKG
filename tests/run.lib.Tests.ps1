Describe "Test-FrontendDependenciesReady" {
  BeforeAll {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $libPath = Join-Path $repoRoot "run.lib.ps1"
    . $libPath
  }

  function New-TestFrontendDir {
    param(
      [switch]$CreateNodeModules,
      [switch]$CreateViteBin
    )

    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ("logickg-run-test-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $dir | Out-Null

    if ($CreateNodeModules) {
      New-Item -ItemType Directory -Path (Join-Path $dir "node_modules") -Force | Out-Null
    }

    if ($CreateViteBin) {
      $viteDir = Join-Path $dir "node_modules\\vite\\bin"
      New-Item -ItemType Directory -Path $viteDir -Force | Out-Null
      Set-Content -Path (Join-Path $viteDir "vite.js") -Value "// stub"
    }

    return $dir
  }

  AfterEach {
    if ($script:testDir -and (Test-Path $script:testDir)) {
      Remove-Item -Recurse -Force $script:testDir
    }
    $script:testDir = $null
  }

  It "returns false when node_modules is missing" {
    $script:testDir = New-TestFrontendDir

    Test-FrontendDependenciesReady $script:testDir | Should Be $false
  }

  It "returns false when vite bin is missing even if node_modules exists" {
    $script:testDir = New-TestFrontendDir -CreateNodeModules

    Test-FrontendDependenciesReady $script:testDir | Should Be $false
  }

  It "returns true when vite bin exists" {
    $script:testDir = New-TestFrontendDir -CreateNodeModules -CreateViteBin

    Test-FrontendDependenciesReady $script:testDir | Should Be $true
  }
}
