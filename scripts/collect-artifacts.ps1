param(
  [string[]]$SourcePaths = @("output/checks", "output/smoke", "output/playwright"),
  [string]$OutputDir = "output/release-artifacts",
  [string]$RunName = "",
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$startedAt = Get-Date
$stamp = $startedAt.ToString("yyyyMMdd-HHmmss")
$resolvedOutputRoot = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
  $OutputDir
}
else {
  Join-Path $workspaceRoot $OutputDir
}
$runDirectoryName = if ($RunName) { $RunName } else { $stamp }
$resolvedRunDirectory = Join-Path $resolvedOutputRoot $runDirectoryName
$artifactExtensions = @(".json", ".diff", ".txt", ".log", ".png", ".jpg", ".jpeg", ".webp", ".zip", ".html")
$collectedArtifacts = @()
$skippedSources = @()

function Resolve-WorkspacePath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if ([System.IO.Path]::IsPathRooted($Path)) {
    return $Path
  }

  return Join-Path $workspaceRoot $Path
}

function Assert-InWorkspace {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $resolved = (Resolve-Path -LiteralPath $Path).Path
  if (-not ($resolved -eq $workspaceRoot -or $resolved.StartsWith("$workspaceRoot\", [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "Refusing to collect path outside workspace: $resolved"
  }
  return $resolved
}

function Get-OptionalCommandValue {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock]$Command
  )

  try {
    $value = & $Command
    if ($LASTEXITCODE -ne 0) {
      return $null
    }
    return ($value | Select-Object -First 1)
  }
  catch {
    return $null
  }
}

function Convert-ToRelativePath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  return [System.IO.Path]::GetRelativePath($workspaceRoot, $Path)
}

if (-not $WhatIf) {
  New-Item -ItemType Directory -Force -Path $resolvedRunDirectory | Out-Null
}

foreach ($source in $SourcePaths) {
  $candidate = Resolve-WorkspacePath -Path $source
  if (-not (Test-Path -LiteralPath $candidate)) {
    $skippedSources += $candidate
    continue
  }

  $resolvedSource = Assert-InWorkspace -Path $candidate
  $sourceItem = Get-Item -LiteralPath $resolvedSource
  $files = if ($sourceItem.PSIsContainer) {
    Get-ChildItem -LiteralPath $resolvedSource -File -Recurse -Force |
      Where-Object { $artifactExtensions -contains $_.Extension.ToLowerInvariant() }
  }
  else {
    @($sourceItem)
  }

  foreach ($file in $files) {
    $relativeSource = Convert-ToRelativePath -Path $file.FullName
    $targetPath = Join-Path $resolvedRunDirectory $relativeSource
    $targetDirectory = Split-Path -Parent $targetPath

    if ($WhatIf) {
      Write-Host "[what-if] Collect $($file.FullName) -> $targetPath"
    }
    else {
      if ($targetDirectory -and -not (Test-Path -LiteralPath $targetDirectory)) {
        New-Item -ItemType Directory -Path $targetDirectory | Out-Null
      }
      Copy-Item -LiteralPath $file.FullName -Destination $targetPath -Force
      Write-Host "Collected $($file.FullName) -> $targetPath"
    }

    $collectedArtifacts += [ordered]@{
      source = $relativeSource
      destination = Convert-ToRelativePath -Path $targetPath
      size_bytes = $file.Length
      sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    }
  }
}

$finishedAt = Get-Date
$manifest = [ordered]@{
  schema_version = 1
  ok = $true
  what_if = [bool]$WhatIf
  started_at = $startedAt.ToUniversalTime().ToString("o")
  finished_at = $finishedAt.ToUniversalTime().ToString("o")
  duration_ms = [int][Math]::Round(($finishedAt - $startedAt).TotalMilliseconds)
  workspace_root = $workspaceRoot
  git_commit = Get-OptionalCommandValue { git -C $workspaceRoot rev-parse HEAD }
  output_directory = $resolvedRunDirectory
  source_paths = @($SourcePaths)
  skipped_sources = @($skippedSources)
  artifact_count = @($collectedArtifacts).Count
  artifacts = @($collectedArtifacts)
}

if (-not $WhatIf) {
  $manifestPath = Join-Path $resolvedRunDirectory "manifest.json"
  $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding utf8
  Write-Host "Artifact manifest completed: $manifestPath"
}

Write-Host "Artifact collection completed. Count: $($manifest.artifact_count)"
