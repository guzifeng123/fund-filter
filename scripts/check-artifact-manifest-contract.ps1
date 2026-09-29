param(
  [string]$SchemaPath = "packages/contracts/artifact-manifest.schema.json",
  [string]$FixturePath = "packages/contracts/artifact-manifest.fixture.json",
  [string]$ManifestPath,
  [switch]$Strict,
  [switch]$StrictSourcePaths,
  [switch]$StrictDestinations,
  [switch]$StrictGitCommit,
  [string]$ExpectedGitCommit,
  [switch]$StrictRunMetadata,
  [switch]$StrictAlertDestinations,
  [switch]$StrictRequiredArtifacts
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

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

function Read-JsonFile {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $resolved = Resolve-WorkspacePath -Path $Path
  if (-not (Test-Path -LiteralPath $resolved)) {
    throw "JSON file not found: $resolved"
  }

  return Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json
}

function Invoke-JsonSchemaValidation {
  param(
    [Parameter(Mandatory = $true)]
    [string]$SchemaPath,
    [Parameter(Mandatory = $true)]
    [string[]]$DocumentPaths
  )

  $schemaRelative = [System.IO.Path]::GetRelativePath($workspaceRoot, (Resolve-WorkspacePath -Path $SchemaPath))
  $documentRelativePaths = @($DocumentPaths | ForEach-Object {
      [System.IO.Path]::GetRelativePath($workspaceRoot, (Resolve-WorkspacePath -Path $_))
    })
  node (Join-Path $workspaceRoot "scripts\validate-json-schema.js") $schemaRelative @documentRelativePaths
  if ($LASTEXITCODE -ne 0) {
    throw "Artifact manifest JSON Schema validation failed."
  }
}

function Assert-BooleanField {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document,
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$Field
  )

  if ($null -eq $Document.$Field -or $Document.$Field.GetType().Name -ne "Boolean") {
    throw "$Name must include boolean $Field."
  }
}

function Assert-ManifestDocument {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Document.schema_version -ne 1) {
    throw "$Name must use schema_version 1."
  }
  if ($Document.alerts_schema_version -ne 1) {
    throw "$Name must use alerts_schema_version 1."
  }
  foreach ($field in @("ok", "manifest_ok", "alerts_ok", "fail_on_alerts", "what_if")) {
    Assert-BooleanField -Document $Document -Name $Name -Field $field
  }

  foreach ($field in @("started_at", "finished_at", "workspace_root", "output_directory")) {
    if (-not $Document.$field) {
      throw "$Name must include $field."
    }
  }
  if ($null -eq $Document.PSObject.Properties["git_commit"]) {
    throw "$Name must include git_commit."
  }
  if ($Document.duration_ms -lt 0) {
    throw "$Name duration_ms must be non-negative."
  }

  $missingCount = @($Document.missing_required_artifacts).Count
  if ($Document.manifest_ok -ne ($missingCount -eq 0)) {
    throw "$Name manifest_ok must be true only when no required artifacts are missing."
  }
  if ($Document.alert_count -ne @($Document.alerts).Count) {
    throw "$Name alert_count must match alerts length."
  }
  if ($Document.alerts_ok -ne (@($Document.alerts).Count -eq 0)) {
    throw "$Name alerts_ok must be true only when no alerts are present."
  }
  $expectedOk = [bool]($Document.manifest_ok -and (-not $Document.fail_on_alerts -or $Document.alerts_ok))
  if ($Document.ok -ne $expectedOk) {
    throw "$Name ok must match manifest_ok and fail_on_alerts/alerts_ok."
  }
  if ($Document.artifact_count -ne @($Document.artifacts).Count) {
    throw "$Name artifact_count must match artifacts length."
  }

  foreach ($alert in @($Document.alerts)) {
    if (@("missing_required_artifact", "failed_artifact_report") -notcontains $alert.type) {
      throw "$Name contains unsupported alert type: $($alert.type)."
    }
    if ($alert.severity -ne "error") {
      throw "$Name alert severity must be error."
    }
    foreach ($field in @("message", "source")) {
      if (-not $alert.$field) {
        throw "$Name alert must include $field."
      }
    }
    if ($null -eq $alert.PSObject.Properties["destination"]) {
      throw "$Name alert must include destination, even when null."
    }
  }

  foreach ($artifact in @($Document.artifacts)) {
    foreach ($field in @("source", "destination", "sha256")) {
      if (-not $artifact.$field) {
        throw "$Name artifact must include $field."
      }
    }
    if ($artifact.size_bytes -lt 0) {
      throw "$Name artifact size_bytes must be non-negative."
    }
    if ($artifact.sha256 -notmatch "^[A-Fa-f0-9]{64}$") {
      throw "$Name artifact sha256 must be a 64-character hex digest."
    }
  }
}

function Resolve-ArtifactDestinationPath {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Artifact,
    [Parameter(Mandatory = $true)]
    [string]$ManifestDirectory
  )

  $artifactPath = if ([System.IO.Path]::IsPathRooted($Artifact.destination)) {
    $Artifact.destination
  }
  else {
    Resolve-WorkspacePath -Path $Artifact.destination
  }

  if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf) -and -not [System.IO.Path]::IsPathRooted($Artifact.destination)) {
    $artifactPath = Join-Path $ManifestDirectory $Artifact.destination
  }

  return $artifactPath
}

function Assert-ManifestArtifactsExist {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document,
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
  )

  $resolvedManifestPath = Resolve-WorkspacePath -Path $ManifestPath
  $manifestDirectory = Split-Path -Parent $resolvedManifestPath
  $outputDirectory = Resolve-WorkspacePath -Path $Document.output_directory
  if (-not $manifestDirectory.Equals($outputDirectory, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "manifest output_directory must match manifest file directory: expected $manifestDirectory, actual $outputDirectory"
  }

  foreach ($artifact in @($Document.artifacts)) {
    $artifactPath = Resolve-ArtifactDestinationPath -Artifact $artifact -ManifestDirectory $manifestDirectory

    if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
      throw "manifest artifact destination does not exist: $($artifact.destination)"
    }

    $item = Get-Item -LiteralPath $artifactPath
    if ([int64]$artifact.size_bytes -ne [int64]$item.Length) {
      throw "manifest artifact size mismatch for $($artifact.destination): expected $($artifact.size_bytes), actual $($item.Length)"
    }

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifactPath).Hash
    if (-not $hash.Equals($artifact.sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "manifest artifact sha256 mismatch for $($artifact.destination): expected $($artifact.sha256), actual $hash"
    }
  }
}

function Assert-ManifestDestinationsInOutputDirectory {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document,
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
  )

  $resolvedManifestPath = Resolve-WorkspacePath -Path $ManifestPath
  $manifestDirectory = Split-Path -Parent $resolvedManifestPath
  $outputDirectory = Resolve-WorkspacePath -Path $Document.output_directory
  foreach ($artifact in @($Document.artifacts)) {
    $artifactPath = Resolve-ArtifactDestinationPath -Artifact $artifact -ManifestDirectory $manifestDirectory
    $resolvedArtifactPath = if (Test-Path -LiteralPath $artifactPath) {
      (Resolve-Path -LiteralPath $artifactPath).Path
    }
    else {
      [System.IO.Path]::GetFullPath($artifactPath)
    }

    if (-not ($resolvedArtifactPath.Equals($outputDirectory, [System.StringComparison]::OrdinalIgnoreCase) -or $resolvedArtifactPath.StartsWith("$outputDirectory\", [System.StringComparison]::OrdinalIgnoreCase))) {
      throw "manifest artifact destination is outside output_directory: $($artifact.destination)"
    }
  }
}

function Get-CurrentGitCommit {
  try {
    $commit = git -C $workspaceRoot rev-parse HEAD
    if ($LASTEXITCODE -ne 0) {
      return $null
    }
    return ($commit | Select-Object -First 1)
  }
  catch {
    return $null
  }
}

function Assert-ManifestGitCommit {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document,
    [AllowNull()]
    [string]$ExpectedCommit
  )

  if (-not $Document.git_commit) {
    throw "manifest git_commit is required when -StrictGitCommit is used."
  }

  $commit = if ($ExpectedCommit) {
    $ExpectedCommit
  }
  else {
    Get-CurrentGitCommit
  }

  if (-not $commit) {
    throw "Unable to resolve expected git commit for -StrictGitCommit."
  }

  if (-not $Document.git_commit.Equals($commit, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "manifest git_commit mismatch: expected $commit, actual $($Document.git_commit)"
  }
}

function Assert-ManifestRunMetadata {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document,
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
  )

  $rawManifest = Get-Content -LiteralPath (Resolve-WorkspacePath -Path $ManifestPath) -Raw
  $startedAtValue = [regex]::Match($rawManifest, '"started_at"\s*:\s*"([^"]+)"').Groups[1].Value
  $finishedAtValue = [regex]::Match($rawManifest, '"finished_at"\s*:\s*"([^"]+)"').Groups[1].Value
  if (-not $startedAtValue -or -not $finishedAtValue) {
    throw "manifest started_at and finished_at must be present as JSON strings."
  }

  try {
    $startedAt = [DateTimeOffset]::ParseExact($startedAtValue, "O", [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)
    $finishedAt = [DateTimeOffset]::ParseExact($finishedAtValue, "O", [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)
  }
  catch {
    throw "manifest started_at and finished_at must be parseable date-time values."
  }

  if ($finishedAt -lt $startedAt) {
    throw "manifest finished_at must be greater than or equal to started_at."
  }

  $expectedDurationMs = [int][Math]::Round(($finishedAt.UtcDateTime - $startedAt.UtcDateTime).TotalMilliseconds)
  $actualDurationMs = [int]$Document.duration_ms
  if ([Math]::Abs($actualDurationMs - $expectedDurationMs) -gt 1) {
    throw "manifest duration_ms mismatch: expected $expectedDurationMs from timestamps, actual $actualDurationMs"
  }
}

function Get-ArtifactOkFromDestination {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Artifact,
    [Parameter(Mandatory = $true)]
    [string]$ManifestDirectory
  )

  if ($Artifact.destination -notlike "*.json") {
    return $null
  }

  $artifactPath = Resolve-ArtifactDestinationPath -Artifact $Artifact -ManifestDirectory $ManifestDirectory
  if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
    return $null
  }

  try {
    $json = Get-Content -LiteralPath $artifactPath -Raw | ConvertFrom-Json
    if ($null -ne $json.ok) {
      return [bool]$json.ok
    }
  }
  catch {
    return $null
  }

  return $null
}

function Assert-ManifestAlertDestinations {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document,
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
  )

  $resolvedManifestPath = Resolve-WorkspacePath -Path $ManifestPath
  $manifestDirectory = Split-Path -Parent $resolvedManifestPath
  $artifactsByDestination = @{}
  foreach ($artifact in @($Document.artifacts)) {
    $destination = Convert-ToManifestPath -Path $artifact.destination
    $artifactsByDestination[$destination.ToLowerInvariant()] = $artifact
  }

  foreach ($alert in @($Document.alerts | Where-Object { $_.type -eq "failed_artifact_report" })) {
    if (-not $alert.destination) {
      throw "failed artifact alert must include destination: $($alert.source)"
    }

    $alertDestination = Convert-ToManifestPath -Path $alert.destination
    $artifact = $artifactsByDestination[$alertDestination.ToLowerInvariant()]
    if ($null -eq $artifact) {
      throw "failed artifact alert destination does not match any manifest artifact: $($alert.destination)"
    }

    $artifactOk = Get-ArtifactOkFromDestination -Artifact $artifact -ManifestDirectory $manifestDirectory
    if ($artifactOk -ne $false) {
      throw "failed artifact alert must point to a JSON artifact with ok=false: $($alert.destination)"
    }
  }
}

function Test-ArtifactPattern {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Pattern,
    [Parameter(Mandatory = $true)]
    [string[]]$Artifacts
  )

  $normalizedPattern = Convert-ToManifestPath -Path $Pattern
  foreach ($artifact in $Artifacts) {
    if ((Convert-ToManifestPath -Path $artifact) -like $normalizedPattern) {
      return $true
    }
  }

  return $false
}

function Assert-RequiredArtifacts {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document
  )

  $artifactSources = @($Document.artifacts | ForEach-Object { Convert-ToManifestPath -Path $_.source })
  $expectedMissing = @($Document.required_artifacts | Where-Object {
      -not (Test-ArtifactPattern -Pattern $_ -Artifacts $artifactSources)
    } | ForEach-Object { Convert-ToManifestPath -Path $_ } | Sort-Object)
  $actualMissing = @($Document.missing_required_artifacts | ForEach-Object { Convert-ToManifestPath -Path $_ } | Sort-Object)

  if (@($expectedMissing).Count -ne @($actualMissing).Count) {
    throw "manifest missing_required_artifacts count mismatch: expected $(@($expectedMissing).Count), actual $(@($actualMissing).Count)"
  }

  for ($index = 0; $index -lt @($expectedMissing).Count; $index++) {
    if (-not $expectedMissing[$index].Equals($actualMissing[$index], [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "manifest missing_required_artifacts mismatch: expected '$($expectedMissing[$index])', actual '$($actualMissing[$index])'"
    }
  }
}

function Convert-ToManifestPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  return $Path.Replace("\", "/").TrimEnd("/")
}

function Test-ArtifactSourceInScope {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string[]]$SourcePaths
  )

  $normalizedSource = Convert-ToManifestPath -Path $Source
  foreach ($sourcePath in $SourcePaths) {
    $normalizedSourcePath = Convert-ToManifestPath -Path $sourcePath
    if ($normalizedSource.Equals($normalizedSourcePath, [System.StringComparison]::OrdinalIgnoreCase)) {
      return $true
    }
    if ($normalizedSource.StartsWith("$normalizedSourcePath/", [System.StringComparison]::OrdinalIgnoreCase)) {
      return $true
    }
  }

  return $false
}

function Assert-ManifestSourcesInScope {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document
  )

  $sourcePaths = @($Document.source_paths | ForEach-Object { $_.ToString() })
  if (@($sourcePaths).Count -eq 0 -and @($Document.artifacts).Count -gt 0) {
    throw "manifest source_paths must not be empty when artifacts are present."
  }

  foreach ($artifact in @($Document.artifacts)) {
    if (-not (Test-ArtifactSourceInScope -Source $artifact.source -SourcePaths $sourcePaths)) {
      throw "manifest artifact source is outside source_paths: $($artifact.source)"
    }
  }
}

$schema = Read-JsonFile -Path $SchemaPath
if ($schema.properties.schema_version.const -ne 1) {
  throw "Artifact manifest schema must require schema_version 1."
}
if ($schema.properties.alerts_schema_version.const -ne 1) {
  throw "Artifact manifest schema must require alerts_schema_version 1."
}
foreach ($required in @("schema_version", "ok", "manifest_ok", "alerts_ok", "fail_on_alerts", "what_if", "started_at", "finished_at", "duration_ms", "workspace_root", "git_commit", "output_directory", "profile", "source_paths", "skipped_sources", "required_artifacts", "missing_required_artifacts", "alerts_schema_version", "alert_count", "alerts", "artifact_count", "artifacts")) {
  if (@($schema.required) -notcontains $required) {
    throw "Artifact manifest schema missing required field: $required"
  }
}

$documentPaths = @($FixturePath)
if ($ManifestPath) {
  $documentPaths += $ManifestPath
}
Invoke-JsonSchemaValidation -SchemaPath $SchemaPath -DocumentPaths $documentPaths

$fixture = Read-JsonFile -Path $FixturePath
Assert-ManifestDocument -Document $fixture -Name "fixture"

if ($ManifestPath) {
  $manifest = Read-JsonFile -Path $ManifestPath
  Assert-ManifestDocument -Document $manifest -Name "manifest"
  Assert-ManifestArtifactsExist -Document $manifest -ManifestPath $ManifestPath
  if ($Strict -or $StrictSourcePaths) {
    Assert-ManifestSourcesInScope -Document $manifest
  }
  if ($Strict -or $StrictDestinations) {
    Assert-ManifestDestinationsInOutputDirectory -Document $manifest -ManifestPath $ManifestPath
  }
  if ($Strict -or $StrictGitCommit) {
    Assert-ManifestGitCommit -Document $manifest -ExpectedCommit $ExpectedGitCommit
  }
  if ($Strict -or $StrictRunMetadata) {
    Assert-ManifestRunMetadata -Document $manifest -ManifestPath $ManifestPath
  }
  if ($Strict -or $StrictAlertDestinations) {
    Assert-ManifestAlertDestinations -Document $manifest -ManifestPath $ManifestPath
  }
  if ($Strict -or $StrictRequiredArtifacts) {
    Assert-RequiredArtifacts -Document $manifest
  }
}

Write-Host "Artifact manifest contract check passed."
