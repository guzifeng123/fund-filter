param(
  [ValidateSet("", "local-release")]
  [string]$Profile = "",
  [string[]]$SourcePaths = @("output/checks", "output/smoke", "output/playwright"),
  [string]$OutputDir = "output/release-artifacts",
  [string]$RunName = "",
  [string[]]$RequireArtifacts = @(),
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$startedAt = Get-Date
$stamp = $startedAt.ToString("yyyyMMdd-HHmmss")

if ($Profile -eq "local-release") {
  if (-not $PSBoundParameters.ContainsKey("SourcePaths")) {
    $SourcePaths = @("output/checks", "output/smoke", "output/playwright")
  }
  if (-not $PSBoundParameters.ContainsKey("RequireArtifacts")) {
    $RequireArtifacts = @("output/checks/openapi.diff", "output/smoke/*.json", "output/playwright/*.png")
  }
}

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
$missingRequiredArtifacts = @()

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

function Convert-ToArtifactPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  return $Path.Replace("\", "/")
}

function Test-ArtifactPattern {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Pattern,
    [Parameter(Mandatory = $true)]
    [string[]]$Artifacts
  )

  $normalizedPattern = Convert-ToArtifactPath -Path $Pattern
  foreach ($artifact in $Artifacts) {
    if ($artifact -like $normalizedPattern) {
      return $true
    }
  }

  return $false
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

function Write-ArtifactSummary {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Manifest,
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $lines = New-Object System.Collections.Generic.List[string]
  $status = if ($Manifest.ok) { "OK" } else { "FAILED" }
  $lines.Add("# Release Artifact Summary")
  $lines.Add("")
  $lines.Add("- Status: $status")
  $lines.Add("- Profile: $(Format-MarkdownCell $Manifest.profile)")
  $lines.Add("- Git commit: $(Format-MarkdownCell $Manifest.git_commit)")
  $lines.Add("- Started: $(Format-MarkdownCell $Manifest.started_at)")
  $lines.Add("- Finished: $(Format-MarkdownCell $Manifest.finished_at)")
  $lines.Add("- Duration ms: $(Format-MarkdownCell $Manifest.duration_ms)")
  $lines.Add("- Artifact count: $(Format-MarkdownCell $Manifest.artifact_count)")
  $lines.Add("")

  if (@($Manifest.missing_required_artifacts).Count -gt 0) {
    $lines.Add("## Missing Required Artifacts")
    $lines.Add("")
    foreach ($missing in $Manifest.missing_required_artifacts) {
      $lines.Add("- ``$(Format-MarkdownCell $missing)``")
    }
    $lines.Add("")
  }

  $lines.Add("## Artifacts")
  $lines.Add("")
  $lines.Add("| Source | Size bytes | SHA256 |")
  $lines.Add("| --- | ---: | --- |")
  foreach ($artifact in $Manifest.artifacts) {
    $source = Convert-ToArtifactPath -Path $artifact.source
    $lines.Add("| $(Format-MarkdownCell $source) | $(Format-MarkdownCell $artifact.size_bytes) | ``$(Format-MarkdownCell $artifact.sha256)`` |")
  }

  $lines | Set-Content -LiteralPath $Path -Encoding utf8
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
$artifactSources = @($collectedArtifacts | ForEach-Object { Convert-ToArtifactPath -Path $_.source })
foreach ($requiredArtifact in $RequireArtifacts) {
  if (-not (Test-ArtifactPattern -Pattern $requiredArtifact -Artifacts $artifactSources)) {
    $missingRequiredArtifacts += $requiredArtifact
  }
}

$ok = @($missingRequiredArtifacts).Count -eq 0
$manifest = [ordered]@{
  schema_version = 1
  ok = $ok
  what_if = [bool]$WhatIf
  started_at = $startedAt.ToUniversalTime().ToString("o")
  finished_at = $finishedAt.ToUniversalTime().ToString("o")
  duration_ms = [int][Math]::Round(($finishedAt - $startedAt).TotalMilliseconds)
  workspace_root = $workspaceRoot
  git_commit = Get-OptionalCommandValue { git -C $workspaceRoot rev-parse HEAD }
  output_directory = $resolvedRunDirectory
  profile = $Profile
  source_paths = @($SourcePaths)
  skipped_sources = @($skippedSources)
  required_artifacts = @($RequireArtifacts)
  missing_required_artifacts = @($missingRequiredArtifacts)
  artifact_count = @($collectedArtifacts).Count
  artifacts = @($collectedArtifacts)
}

if (-not $WhatIf) {
  $manifestPath = Join-Path $resolvedRunDirectory "manifest.json"
  $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding utf8
  Write-Host "Artifact manifest completed: $manifestPath"
  $summaryPath = Join-Path $resolvedRunDirectory "summary.md"
  Write-ArtifactSummary -Manifest $manifest -Path $summaryPath
  Write-Host "Artifact summary completed: $summaryPath"
}

if (-not $ok) {
  throw "Missing required artifacts: $($missingRequiredArtifacts -join ', ')"
}

Write-Host "Artifact collection completed. Count: $($manifest.artifact_count)"
