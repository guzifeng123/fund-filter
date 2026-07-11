param(
  [switch]$WhatIf,
  [string[]]$SearchRoots = @("."),
  [string[]]$ExcludeDirectories = @("node_modules", ".git", ".next", ".venv", "output", "backups", ".playwright-cli"),
  [string]$JsonReportPath
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$startedAt = Get-Date
$matchedItems = @()
$removedItems = @()
$skippedRoots = @()

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
  $script:matchedItems += $resolved
  if ($WhatIf) {
    Write-Host "[what-if] Remove $resolved"
    return
  }

  Remove-Item -LiteralPath $resolved -Recurse -Force
  $script:removedItems += $resolved
  Write-Host "Removed $resolved"
}

function Resolve-ReportPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if ([System.IO.Path]::IsPathRooted($Path)) {
    return $Path
  }

  return Join-Path $workspaceRoot $Path
}

function Resolve-SearchRoot {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $candidate = if ([System.IO.Path]::IsPathRooted($Path)) {
    $Path
  }
  else {
    Join-Path $workspaceRoot $Path
  }

  if (-not (Test-Path -LiteralPath $candidate)) {
    $script:skippedRoots += $candidate
    return $null
  }

  return Assert-InWorkspace -Path $candidate
}

function Test-ExcludedDirectory {
  param(
    [Parameter(Mandatory = $true)]
    [System.IO.DirectoryInfo]$Directory
  )

  foreach ($name in $ExcludeDirectories) {
    if ($Directory.Name -eq $name) {
      return $true
    }
  }

  return $false
}

function Get-GeneratedPatternTargets {
  $targets = New-Object System.Collections.Generic.List[System.IO.FileSystemInfo]
  $visitedRoots = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)

  foreach ($root in $SearchRoots) {
    $resolvedRoot = Resolve-SearchRoot -Path $root
    if ($null -eq $resolvedRoot -or -not $visitedRoots.Add($resolvedRoot)) {
      continue
    }

    $stack = New-Object System.Collections.Generic.Stack[System.IO.DirectoryInfo]
    $stack.Push([System.IO.DirectoryInfo]::new($resolvedRoot))

    while ($stack.Count -gt 0) {
      $directory = $stack.Pop()
      if (Test-ExcludedDirectory -Directory $directory) {
        continue
      }

      foreach ($file in Get-ChildItem -LiteralPath $directory.FullName -File -Force -Filter "*-dev.log" -ErrorAction SilentlyContinue) {
        $targets.Add($file)
      }

      foreach ($childDirectory in Get-ChildItem -LiteralPath $directory.FullName -Directory -Force -ErrorAction SilentlyContinue) {
        if (Test-ExcludedDirectory -Directory $childDirectory) {
          continue
        }

        if ($childDirectory.Name -eq "__pycache__" -or $childDirectory.Name -like "*.egg-info") {
          $targets.Add($childDirectory)
          continue
        }

        $stack.Push($childDirectory)
      }
    }
  }

  return $targets
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

$patternTargets = Get-GeneratedPatternTargets

foreach ($item in $patternTargets) {
  Remove-GeneratedItem -Path $item.FullName
}

Write-Host "Skipped directories: $($ExcludeDirectories -join ', ')"

if ($JsonReportPath) {
  $finishedAt = Get-Date
  $reportPath = Resolve-ReportPath -Path $JsonReportPath
  $reportDirectory = Split-Path -Parent $reportPath
  if ($reportDirectory -and -not (Test-Path -LiteralPath $reportDirectory)) {
    New-Item -ItemType Directory -Path $reportDirectory | Out-Null
  }

  [ordered]@{
    schema_version = 1
    ok = $true
    what_if = [bool]$WhatIf
    started_at = $startedAt.ToUniversalTime().ToString("o")
    finished_at = $finishedAt.ToUniversalTime().ToString("o")
    duration_ms = [int][Math]::Round(($finishedAt - $startedAt).TotalMilliseconds)
    workspace_root = $workspaceRoot
    search_roots = @($SearchRoots)
    exclude_directories = @($ExcludeDirectories)
    skipped_roots = @($skippedRoots)
    matched_items = @($matchedItems)
    removed_items = @($removedItems)
    matched_count = @($matchedItems).Count
    removed_count = @($removedItems).Count
  } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8

  Write-Host "Cleanup report completed: $reportPath"
}

Write-Host "Generated artifact cleanup completed."
