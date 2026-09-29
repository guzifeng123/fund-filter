param(
  [string]$SchemaPath = "packages/contracts/cleanup-report.schema.json",
  [string]$FixturePath = "packages/contracts/cleanup-report.fixture.json",
  [string]$ReportPath
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
    throw "Cleanup report JSON Schema validation failed."
  }
}

function Get-TypeCount {
  param(
    [object[]]$Items,
    [string]$Type
  )

  return @($Items | Where-Object { $_.type -eq $Type }).Count
}

function Assert-TypeSummary {
  param(
    [object[]]$Details,
    [Parameter(Mandatory = $true)]
    [object]$Summary,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  foreach ($type in @("fixed", "log", "pycache", "egg-info", "directory", "other")) {
    $expected = Get-TypeCount -Items $Details -Type $type
    if ($Summary.$type -ne $expected) {
      throw "$Name summary for $type expected $expected, got $($Summary.$type)."
    }
  }
}

function Assert-CleanupReport {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Report,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Report.schema_version -ne 1) {
    throw "$Name must use schema_version 1."
  }
  if ($Report.fixed_targets_only -and $Report.pattern_targets_only) {
    throw "$Name cannot have both fixed_targets_only and pattern_targets_only."
  }
  if ($Report.matched_count -ne @($Report.matched_items).Count) {
    throw "$Name matched_count must match matched_items length."
  }
  if ($Report.removed_count -ne @($Report.removed_items).Count) {
    throw "$Name removed_count must match removed_items length."
  }
  if (@($Report.matched_item_details).Count -ne @($Report.matched_items).Count) {
    throw "$Name matched_item_details length must match matched_items length."
  }
  if (@($Report.removed_item_details).Count -ne @($Report.removed_items).Count) {
    throw "$Name removed_item_details length must match removed_items length."
  }

  Assert-TypeSummary -Details @($Report.matched_item_details) -Summary $Report.matched_by_type -Name "$Name matched_by_type"
  Assert-TypeSummary -Details @($Report.removed_item_details) -Summary $Report.removed_by_type -Name "$Name removed_by_type"
}

$documentPaths = @($FixturePath)
if ($ReportPath) {
  $documentPaths += $ReportPath
}

Invoke-JsonSchemaValidation -SchemaPath $SchemaPath -DocumentPaths $documentPaths

$fixture = Read-JsonFile -Path $FixturePath
Assert-CleanupReport -Report $fixture -Name "fixture"

if ($ReportPath) {
  $report = Read-JsonFile -Path $ReportPath
  Assert-CleanupReport -Report $report -Name "report"
}

Write-Host "Cleanup report contract check passed."
