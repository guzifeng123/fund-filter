param(
  [string]$SchemaPath = "packages/contracts/artifact-alerts.schema.json",
  [string]$FixturePath = "packages/contracts/artifact-alerts.fixture.json",
  [string]$AlertsPath
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
  node (Join-Path $workspaceRoot "scripts\validate-artifact-alerts-schema.js") $schemaRelative @documentRelativePaths
  if ($LASTEXITCODE -ne 0) {
    throw "Artifact alerts JSON Schema validation failed."
  }
}

function Assert-AlertDocument {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Document,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Document.schema_version -ne 1) {
    throw "$Name must use schema_version 1."
  }
  if ($null -eq $Document.ok -or $Document.ok.GetType().Name -ne "Boolean") {
    throw "$Name must include boolean ok."
  }
  if ($null -eq $Document.manifest_ok -or $Document.manifest_ok.GetType().Name -ne "Boolean") {
    throw "$Name must include boolean manifest_ok."
  }
  if ($null -eq $Document.alerts_ok -or $Document.alerts_ok.GetType().Name -ne "Boolean") {
    throw "$Name must include boolean alerts_ok."
  }
  if ($null -eq $Document.fail_on_alerts -or $Document.fail_on_alerts.GetType().Name -ne "Boolean") {
    throw "$Name must include boolean fail_on_alerts."
  }
  foreach ($field in @("started_at", "finished_at", "run_directory")) {
    if (-not $Document.$field) {
      throw "$Name must include $field."
    }
  }
  if ($null -eq $Document.PSObject.Properties["git_commit"]) {
    throw "$Name must include git_commit."
  }
  if ($Document.alert_count -ne @($Document.alerts).Count) {
    throw "$Name alert_count must match alerts length."
  }
  if ($Document.ok -ne (@($Document.alerts).Count -eq 0)) {
    throw "$Name ok must be true only when no alerts are present."
  }
  if ($Document.alerts_ok -ne (@($Document.alerts).Count -eq 0)) {
    throw "$Name alerts_ok must be true only when no alerts are present."
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
}

$schema = Read-JsonFile -Path $SchemaPath
if ($schema.properties.schema_version.const -ne 1) {
  throw "Artifact alerts schema must require schema_version 1."
}
foreach ($required in @("schema_version", "ok", "manifest_ok", "alerts_ok", "fail_on_alerts", "started_at", "finished_at", "git_commit", "run_directory", "alert_count", "alerts")) {
  if (@($schema.required) -notcontains $required) {
    throw "Artifact alerts schema missing required field: $required"
  }
}

$documentPaths = @($FixturePath)
if ($AlertsPath) {
  $documentPaths += $AlertsPath
}
Invoke-JsonSchemaValidation -SchemaPath $SchemaPath -DocumentPaths $documentPaths

$fixture = Read-JsonFile -Path $FixturePath
Assert-AlertDocument -Document $fixture -Name "fixture"

if ($AlertsPath) {
  $alerts = Read-JsonFile -Path $AlertsPath
  Assert-AlertDocument -Document $alerts -Name "alerts"
}

Write-Host "Artifact alerts contract check passed."
