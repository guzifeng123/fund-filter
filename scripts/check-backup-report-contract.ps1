param(
  [string]$SchemaPath = "packages/contracts/backup-report.schema.json",
  [string]$FixturePath = "packages/contracts/backup-report.fixture.json",
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
    throw "Backup report JSON Schema validation failed."
  }
}

function Assert-BackupReport {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Report,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Report.schema_version -ne 1) {
    throw "$Name must use schema_version 1."
  }
  if (-not $Report.ok) {
    throw "$Name backup report currently only supports ok=true reports."
  }
  if ([System.IO.Path]::GetFileName($Report.backup_path) -ne $Report.backup_file) {
    throw "$Name backup_file must match backup_path file name."
  }
  if ($Report.compressed -and -not $Report.backup_file.EndsWith(".sql.gz", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "$Name compressed backup_file must end with .sql.gz."
  }
  if (-not $Report.compressed -and -not $Report.backup_file.EndsWith(".sql", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "$Name uncompressed backup_file must end with .sql."
  }
  if ($Report.checksum_path -ne "$($Report.backup_path).sha256") {
    throw "$Name checksum_path must equal backup_path plus .sha256."
  }
}

$documentPaths = @($FixturePath)
if ($ReportPath) {
  $documentPaths += $ReportPath
}

Invoke-JsonSchemaValidation -SchemaPath $SchemaPath -DocumentPaths $documentPaths

$fixture = Read-JsonFile -Path $FixturePath
Assert-BackupReport -Report $fixture -Name "fixture"

if ($ReportPath) {
  $report = Read-JsonFile -Path $ReportPath
  Assert-BackupReport -Report $report -Name "report"
}

Write-Host "Backup report contract check passed."
