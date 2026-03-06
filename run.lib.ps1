function Get-FrontendViteBin($frontendDir) {
  return Join-Path $frontendDir "node_modules\\vite\\bin\\vite.js"
}

function Test-FrontendDependenciesReady($frontendDir) {
  $nodeModulesDir = Join-Path $frontendDir "node_modules"
  $viteBin = Get-FrontendViteBin $frontendDir

  return (Test-Path $nodeModulesDir) -and (Test-Path $viteBin)
}
