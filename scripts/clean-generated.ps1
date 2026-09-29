param(
  [switch]$WhatIf,
  [switch]$FixedTargetsOnly,
  [switch]$PatternTargetsOnly,
  [string[]]$SearchRoots = @("."),
  [string[]]$ExcludeDirectories = @("node_modules", ".git", ".next", ".venv", "output", "backups", ".playwright-cli"),
  [string[]]$IncludeExtensions = @(".log"),
  [string[]]$ExcludePatterns = @(),
  [string]$JsonReportPath,
  [string]$MarkdownReportPath
)

$ErrorActionPreference = "Stop"

if ($FixedTargetsOnly -and $PatternTargetsOnly) {
  throw "Use either -FixedTargetsOnly or -PatternTargetsOnly, not both."
}

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$startedAt = Get-Date
$matchedItems = @()
$removedItems = @()
$matchedItemDetails = @()
$removedItemDetails = @()
$skippedRoots = @()
$skippedPatternItems = @()
$cleanupMode = if ($FixedTargetsOnly) { "fixed" } elseif ($PatternTargetsOnly) { "pattern" } else { "all" }
$normalizedIncludeExtensions = New-Object System.Collections.Generic.List[string]
foreach ($includeExtension in $IncludeExtensions) {
  $extension = $includeExtension.Trim().ToLowerInvariant()
  if (-not $extension) {
    continue
  }
  if (-not $extension.StartsWith(".")) {
    $extension = ".$extension"
  }
  $normalizedIncludeExtensions.Add($extension)
}

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
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$TargetType
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }

  $resolved = Assert-InWorkspace -Path $Path
  if (Test-ExcludedPattern -Path $resolved) {
    $script:skippedPatternItems += $resolved
    Write-Host "Skipped by pattern $resolved"
    return
  }

  $script:matchedItems += $resolved
  $script:matchedItemDetails += [ordered]@{
    path = $resolved
    type = $TargetType
  }
  if ($WhatIf) {
    Write-Host "[what-if] Remove $resolved"
    return
  }

  Remove-Item -LiteralPath $resolved -Recurse -Force
  $script:removedItems += $resolved
  $script:removedItemDetails += [ordered]@{
    path = $resolved
    type = $TargetType
  }
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

function Convert-ToRelativePatternPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  return [System.IO.Path]::GetRelativePath($workspaceRoot, $Path).Replace("\", "/")
}

function Test-ExcludedPattern {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if (@($ExcludePatterns).Count -eq 0) {
    return $false
  }

  $itemName = Split-Path -Leaf $Path
  $relativePath = Convert-ToRelativePatternPath -Path $Path
  foreach ($pattern in $ExcludePatterns) {
    $normalizedPattern = $pattern.Replace("\", "/")
    if ($itemName -like $normalizedPattern -or $relativePath -like $normalizedPattern) {
      return $true
    }
  }

  return $false
}

function Get-GeneratedItemType {
  param(
    [Parameter(Mandatory = $true)]
    [System.IO.FileSystemInfo]$Item
  )

  if ($Item.PSIsContainer) {
    if ($Item.Name -eq "__pycache__") {
      return "pycache"
    }
    if ($Item.Name -like "*.egg-info") {
      return "egg-info"
    }
    return "directory"
  }

  return "log"
}

function New-TargetSummary {
  param(
    [object[]]$Items
  )

  $summary = [ordered]@{
    fixed = 0
    log = 0
    pycache = 0
    "egg-info" = 0
    directory = 0
    other = 0
  }

  foreach ($item in $Items) {
    $type = if ($item.type) { $item.type } else { "other" }
    if ($summary.Contains($type)) {
      $summary[$type] += 1
    }
    else {
      $summary["other"] += 1
    }
  }

  return $summary
}

function Format-MarkdownCell {
  param(
    [AllowNull()]
    [object]$Value
  )

  if ($null -eq $Value) {
    return ""
  }

  return ($Value.ToString() -replace "\|", "\|").Replace("`r", " ").Replace("`n", " ")
}

function Convert-ToReportPath {
  param(
    [AllowNull()]
    [string]$Path
  )

  if (-not $Path) {
    return ""
  }

  return [System.IO.Path]::GetRelativePath($workspaceRoot, $Path).Replace("\", "/")
}

function Write-CleanupMarkdownReport {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Report,
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $lines = New-Object System.Collections.Generic.List[string]
  $status = if ($Report.ok) { "OK" } else { "FAILED" }
  $lines.Add("# Cleanup Report Summary")
  $lines.Add("")
  $lines.Add("- Status: $status")
  $lines.Add("- Mode: $(Format-MarkdownCell $Report.cleanup_mode)")
  $lines.Add("- WhatIf: $(Format-MarkdownCell $Report.what_if)")
  $lines.Add("- Started: $(Format-MarkdownCell $Report.started_at)")
  $lines.Add("- Finished: $(Format-MarkdownCell $Report.finished_at)")
  $lines.Add("- Duration ms: $(Format-MarkdownCell $Report.duration_ms)")
  $lines.Add("- Matched count: $(Format-MarkdownCell $Report.matched_count)")
  $lines.Add("- Removed count: $(Format-MarkdownCell $Report.removed_count)")
  $lines.Add("")
  $lines.Add("## Target Types")
  $lines.Add("")
  $lines.Add("| Type | Matched | Removed |")
  $lines.Add("| --- | ---: | ---: |")
  foreach ($type in @("fixed", "log", "pycache", "egg-info", "directory", "other")) {
    $matched = if ($Report.matched_by_type.Contains($type)) { $Report.matched_by_type[$type] } else { 0 }
    $removed = if ($Report.removed_by_type.Contains($type)) { $Report.removed_by_type[$type] } else { 0 }
    $lines.Add("| $(Format-MarkdownCell $type) | $matched | $removed |")
  }
  $lines.Add("")
  $lines.Add("## Scope")
  $lines.Add("")
  $lines.Add("- Search roots: ``$(Format-MarkdownCell (@($Report.search_roots) -join ', '))``")
  $lines.Add("- Excluded directories: ``$(Format-MarkdownCell (@($Report.exclude_directories) -join ', '))``")
  $lines.Add("- Included extensions: ``$(Format-MarkdownCell (@($Report.include_extensions) -join ', '))``")
  $lines.Add("- Excluded patterns: ``$(Format-MarkdownCell (@($Report.exclude_patterns) -join ', '))``")
  $lines.Add("")
  $lines.Add("## Skipped")
  $lines.Add("")
  if (@($Report.skipped_roots).Count -eq 0 -and @($Report.skipped_pattern_items).Count -eq 0) {
    $lines.Add("- None.")
  }
  else {
    foreach ($root in $Report.skipped_roots) {
      $lines.Add("- Missing search root: ``$(Format-MarkdownCell (Convert-ToReportPath -Path $root))``")
    }
    foreach ($item in $Report.skipped_pattern_items) {
      $lines.Add("- Excluded by pattern: ``$(Format-MarkdownCell (Convert-ToReportPath -Path $item))``")
    }
  }
  $lines.Add("")
  $lines.Add("## Matched Items")
  $lines.Add("")
  if (@($Report.matched_item_details).Count -eq 0) {
    $lines.Add("- None.")
  }
  else {
    foreach ($item in @($Report.matched_item_details | Select-Object -First 20)) {
      $lines.Add("- ``$(Format-MarkdownCell (Convert-ToReportPath -Path $item.path))`` ($(Format-MarkdownCell $item.type))")
    }
    if (@($Report.matched_item_details).Count -gt 20) {
      $lines.Add("- ...and $(@($Report.matched_item_details).Count - 20) more.")
    }
  }

  $reportDirectory = Split-Path -Parent $Path
  if ($reportDirectory -and -not (Test-Path -LiteralPath $reportDirectory)) {
    New-Item -ItemType Directory -Path $reportDirectory | Out-Null
  }
  $lines | Set-Content -LiteralPath $Path -Encoding utf8
}

function Get-GeneratedPatternTargets {
  $targets = New-Object System.Collections.Generic.List[object]
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

      foreach ($extension in $normalizedIncludeExtensions) {
        foreach ($file in Get-ChildItem -LiteralPath $directory.FullName -File -Force -Filter "*-dev$extension" -ErrorAction SilentlyContinue) {
          if (Test-ExcludedPattern -Path $file.FullName) {
            $script:skippedPatternItems += $file.FullName
            continue
          }

          $targets.Add([pscustomobject]@{
              Item = $file
              Type = (Get-GeneratedItemType -Item $file)
            })
        }
      }

      foreach ($childDirectory in Get-ChildItem -LiteralPath $directory.FullName -Directory -Force -ErrorAction SilentlyContinue) {
        if (Test-ExcludedDirectory -Directory $childDirectory) {
          continue
        }

        if (Test-ExcludedPattern -Path $childDirectory.FullName) {
          $script:skippedPatternItems += $childDirectory.FullName
          continue
        }

        if ($childDirectory.Name -eq "__pycache__" -or $childDirectory.Name -like "*.egg-info") {
          $targets.Add([pscustomobject]@{
              Item = $childDirectory
              Type = (Get-GeneratedItemType -Item $childDirectory)
            })
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
  "apps/web/tsconfig.tsbuildinfo",
  "apps/api/.pytest_cache",
  "apps/api/.ruff_cache",
  "apps/api/.mypy_cache"
)

if (-not $PatternTargetsOnly) {
  foreach ($target in $fixedTargets) {
    Remove-GeneratedItem -Path (Join-Path $workspaceRoot $target) -TargetType "fixed"
  }
}

if (-not $FixedTargetsOnly) {
  $patternTargets = Get-GeneratedPatternTargets

  foreach ($target in $patternTargets) {
    Remove-GeneratedItem -Path $target.Item.FullName -TargetType $target.Type
  }
}

Write-Host "Cleanup mode: $cleanupMode"
Write-Host "Included extensions: $($normalizedIncludeExtensions -join ', ')"
Write-Host "Skipped directories: $($ExcludeDirectories -join ', ')"

if ($JsonReportPath -or $MarkdownReportPath) {
  $finishedAt = Get-Date
  $report = [ordered]@{
    schema_version = 1
    ok = $true
    what_if = [bool]$WhatIf
    started_at = $startedAt.ToUniversalTime().ToString("o")
    finished_at = $finishedAt.ToUniversalTime().ToString("o")
    duration_ms = [int][Math]::Round(($finishedAt - $startedAt).TotalMilliseconds)
    workspace_root = $workspaceRoot
    cleanup_mode = $cleanupMode
    fixed_targets_only = [bool]$FixedTargetsOnly
    pattern_targets_only = [bool]$PatternTargetsOnly
    search_roots = @($SearchRoots)
    exclude_directories = @($ExcludeDirectories)
    include_extensions = @($normalizedIncludeExtensions)
    exclude_patterns = @($ExcludePatterns)
    skipped_roots = @($skippedRoots)
    skipped_pattern_items = @($skippedPatternItems)
    matched_items = @($matchedItems)
    removed_items = @($removedItems)
    matched_item_details = @($matchedItemDetails)
    removed_item_details = @($removedItemDetails)
    matched_by_type = New-TargetSummary -Items $matchedItemDetails
    removed_by_type = New-TargetSummary -Items $removedItemDetails
    matched_count = @($matchedItems).Count
    removed_count = @($removedItems).Count
  }

  if ($JsonReportPath) {
    $reportPath = Resolve-ReportPath -Path $JsonReportPath
    $reportDirectory = Split-Path -Parent $reportPath
    if ($reportDirectory -and -not (Test-Path -LiteralPath $reportDirectory)) {
      New-Item -ItemType Directory -Path $reportDirectory | Out-Null
    }

    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Host "Cleanup report completed: $reportPath"
  }

  $markdownPath = if ($MarkdownReportPath) {
    Resolve-ReportPath -Path $MarkdownReportPath
  }
  elseif ($JsonReportPath) {
    "$reportPath.md"
  }
  else {
    $null
  }

  if ($markdownPath) {
    Write-CleanupMarkdownReport -Report $report -Path $markdownPath
    Write-Host "Cleanup Markdown report completed: $markdownPath"
  }
}

Write-Host "Generated artifact cleanup completed."
