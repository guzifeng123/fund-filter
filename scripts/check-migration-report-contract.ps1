param(
  [string]$SchemaPath = "packages/contracts/migration-report.schema.json",
  [string]$FixturePath = "packages/contracts/migration-report.fixture.json",
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
    throw "Migration report JSON Schema validation failed."
  }
}

function Assert-MigrationReport {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Report,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Report.schema_version -ne 1) {
    throw "$Name must use schema_version 1."
  }
  if (@($Report.python_arguments).Count -lt 5) {
    throw "$Name python_arguments must include alembic command."
  }
  if (@($Report.python_arguments)[0] -ne "-m" -or @($Report.python_arguments)[1] -ne "alembic") {
    throw "$Name python_arguments must start with '-m alembic'."
  }
  if (@($Report.python_arguments) -notcontains $Report.command) {
    throw "$Name python_arguments must include command '$($Report.command)'."
  }
  if ($Report.command -in @("upgrade", "downgrade") -and @($Report.python_arguments) -notcontains $Report.revision) {
    throw "$Name python_arguments must include revision '$($Report.revision)' for $($Report.command)."
  }
  if ($Report.sql -and @($Report.python_arguments) -notcontains "--sql") {
    throw "$Name sql=true requires --sql in python_arguments."
  }
  if ($Report.ok) {
    if ($Report.exit_code -ne 0) {
      throw "$Name ok=true requires exit_code 0."
    }
    if ($null -ne $Report.error) {
      throw "$Name ok=true requires error=null."
    }
  }
  else {
    if (-not $Report.error) {
      throw "$Name ok=false requires error message."
    }
  }
}

$documentPaths = @($FixturePath)
if ($ReportPath) {
  $documentPaths += $ReportPath
}

Invoke-JsonSchemaValidation -SchemaPath $SchemaPath -DocumentPaths $documentPaths

$fixture = Read-JsonFile -Path $FixturePath
Assert-MigrationReport -Report $fixture -Name "fixture"

if ($ReportPath) {
  $report = Read-JsonFile -Path $ReportPath
  Assert-MigrationReport -Report $report -Name "report"
}

Write-Host "Migration report contract check passed."
