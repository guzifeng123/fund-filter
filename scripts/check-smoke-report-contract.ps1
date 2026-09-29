param(
  [string]$SchemaPath = "packages/contracts/smoke-report.schema.json",
  [string]$FixturePath = "packages/contracts/smoke-report.fixture.json",
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
    throw "Smoke report JSON Schema validation failed."
  }
}

function Assert-SmokeReport {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Report,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Report.schema_version -ne 1) {
    throw "$Name must use schema_version 1."
  }
  if (@($Report.steps).Count -eq 0) {
    throw "$Name must include at least one smoke step."
  }
  if ($Report.ok -and @($Report.steps | Where-Object { $_.ok -eq $false }).Count -gt 0) {
    throw "$Name cannot be ok=true when any step failed."
  }
  foreach ($step in @($Report.steps)) {
    if ($step.ok -and $null -ne $step.error) {
      throw "$Name step '$($step.name)' cannot include error when ok=true."
    }
    if (-not $step.ok -and -not $step.error) {
      throw "$Name step '$($step.name)' must include error when ok=false."
    }
  }

  if ($Report.ok) {
    foreach ($field in @("db_connected", "fund_count", "nav_count", "freshness_status", "filter_result_count")) {
      if ($null -eq $Report.summary.PSObject.Properties[$field]) {
        throw "$Name ok=true summary must include $field."
      }
    }
  }
}

$documentPaths = @($FixturePath)
if ($ReportPath) {
  $documentPaths += $ReportPath
}

Invoke-JsonSchemaValidation -SchemaPath $SchemaPath -DocumentPaths $documentPaths

$fixture = Read-JsonFile -Path $FixturePath
Assert-SmokeReport -Report $fixture -Name "fixture"

if ($ReportPath) {
  $report = Read-JsonFile -Path $ReportPath
  Assert-SmokeReport -Report $report -Name "report"
}

Write-Host "Smoke report contract check passed."
