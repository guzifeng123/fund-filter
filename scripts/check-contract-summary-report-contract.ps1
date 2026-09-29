param(
  [string]$SchemaPath = "packages/contracts/contract-summary-report.schema.json",
  [string]$FixturePath = "packages/contracts/contract-summary-report.fixture.json",
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
    throw "Contract summary report JSON Schema validation failed."
  }
}

function Assert-ContractSummaryReport {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Report,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Report.schema_version -ne 1) {
    throw "$Name must use schema_version 1."
  }

  $results = @($Report.results)
  $failedResults = @($results | Where-Object { -not $_.ok })
  if ($Report.contract_count -ne $results.Count) {
    throw "$Name contract_count must match results length."
  }
  if ($Report.failed_count -ne $failedResults.Count) {
    throw "$Name failed_count must match failed results length."
  }
  if ($Report.ok -ne ($Report.failed_count -eq 0)) {
    throw "$Name ok must be true only when failed_count is 0."
  }

  foreach ($result in $results) {
    if ($result.ok -and $null -ne $result.error) {
      throw "$Name result '$($result.name)' cannot include error when ok=true."
    }
    if (-not $result.ok -and -not $result.error) {
      throw "$Name result '$($result.name)' must include error when ok=false."
    }
    if (-not $result.script.EndsWith(".ps1", [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "$Name result '$($result.name)' script must reference a PowerShell script."
    }
  }
}

$documentPaths = @($FixturePath)
if ($ReportPath) {
  $documentPaths += $ReportPath
}

Invoke-JsonSchemaValidation -SchemaPath $SchemaPath -DocumentPaths $documentPaths

$fixture = Read-JsonFile -Path $FixturePath
Assert-ContractSummaryReport -Report $fixture -Name "fixture"

if ($ReportPath) {
  $report = Read-JsonFile -Path $ReportPath
  Assert-ContractSummaryReport -Report $report -Name "report"
}

Write-Host "Contract summary report contract check passed."
