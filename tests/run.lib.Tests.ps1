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

Describe "Workspace-aware port helpers" {
  BeforeAll {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $libPath = Join-Path $repoRoot "run.lib.ps1"
    . $libPath
  }

  It "classifies the main workspace separately from worktrees" {
    $profile = Get-LogicKGWorkspaceProfile "C:\Users\D0n9\Desktop\LogicKG"

    $profile.Kind | Should Be "main"
    $profile.Name | Should Be "LogicKG"
  }

  It "detects a git worktree and preserves its worktree name" {
    $profile = Get-LogicKGWorkspaceProfile "C:\Users\D0n9\Desktop\LogicKG\.worktrees\discovery-self-evolving-migration"

    $profile.Kind | Should Be "worktree"
    $profile.Name | Should Be "discovery-self-evolving-migration"
  }

  It "keeps canonical dev ports for the main workspace" {
    $ports = Get-LogicKGPreferredPorts "C:\Users\D0n9\Desktop\LogicKG"

    $ports.BackendCandidates[0] | Should Be 8000
    $ports.FrontendCandidates[0] | Should Be 5173
  }

  It "assigns worktrees to a separate stable port range" {
    $portsA = Get-LogicKGPreferredPorts "C:\Users\D0n9\Desktop\LogicKG\.worktrees\discovery-self-evolving-migration"
    $portsB = Get-LogicKGPreferredPorts "C:\Users\D0n9\Desktop\LogicKG\.worktrees\discovery-self-evolving-migration"

    $portsA.Kind | Should Be "worktree"
    $portsA.BackendCandidates[0] | Should BeGreaterThan 18099
    $portsA.FrontendCandidates[0] | Should BeGreaterThan 15172
    $portsA.BackendCandidates[0] | Should Not Be 8000
    $portsA.FrontendCandidates[0] | Should Not Be 5173
    $portsA.BackendCandidates[0] | Should Be $portsB.BackendCandidates[0]
    $portsA.FrontendCandidates[0] | Should Be $portsB.FrontendCandidates[0]
    $portsA.BackendCandidates.Count | Should Be 3
    $portsA.FrontendCandidates.Count | Should Be 3
    $portsA.BackendCandidates[1] | Should BeGreaterThan $portsA.BackendCandidates[0]
    $portsA.BackendCandidates[2] | Should BeGreaterThan $portsA.BackendCandidates[1]
    $portsA.FrontendCandidates[1] | Should BeGreaterThan $portsA.FrontendCandidates[0]
    $portsA.FrontendCandidates[2] | Should BeGreaterThan $portsA.FrontendCandidates[1]
  }
}
