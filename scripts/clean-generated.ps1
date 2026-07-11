param(
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Assert-InWorkspace {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $resolved = (Resolve-Path -LiteralPath $Path).Path
  if (-not ($resolved -eq $workspaceRoot -or $resolved.StartsWith("$workspaceRoot\", [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "Refusing to remove path outside workspace: $resolved"
  }
  return $resolved
}

function Remove-GeneratedItem {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }

  $resolved = Assert-InWorkspace -Path $Path
  if ($WhatIf) {
    Write-Host "[what-if] Remove $resolved"
    return
  }

  Remove-Item -LiteralPath $resolved -Recurse -Force
  Write-Host "Removed $resolved"
}

$fixedTargets = @(
  ".next",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
  "apps/web/.next",
  "apps/api/.pytest_cache",
  "apps/api/.ruff_cache",
  "apps/api/.mypy_cache"
)

foreach ($target in $fixedTargets) {
  Remove-GeneratedItem -Path (Join-Path $workspaceRoot $target)
}

$patternTargets = @()
$patternTargets += Get-ChildItem -LiteralPath $workspaceRoot -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue
$patternTargets += Get-ChildItem -LiteralPath $workspaceRoot -Directory -Recurse -Force -Filter "*.egg-info" -ErrorAction SilentlyContinue
$patternTargets += Get-ChildItem -LiteralPath $workspaceRoot -File -Recurse -Force -Filter "*-dev.log" -ErrorAction SilentlyContinue

foreach ($item in $patternTargets) {
  Remove-GeneratedItem -Path $item.FullName
}

Write-Host "Generated artifact cleanup completed."
