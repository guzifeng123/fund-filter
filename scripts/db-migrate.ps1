param(
  [ValidateSet("upgrade", "downgrade", "current", "history", "heads")]
  [string]$Command = "upgrade",
  [string]$Revision = "head",
  [switch]$Sql,
  [string]$DatabaseUrl,
  [switch]$DryRun,
  [string]$JsonReportPath
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$apiRoot = Join-Path $workspaceRoot "apps\api"
$alembicConfig = Join-Path $apiRoot "alembic.ini"
$startedAt = Get-Date
$exitCode = $null
$ok = $false
$errorMessage = $null

if (-not (Test-Path -LiteralPath $alembicConfig)) {
  throw "Alembic config not found: $alembicConfig"
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

function Write-MigrationReport {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments
  )

  if (-not $JsonReportPath) {
    return
  }

  $finishedAt = Get-Date
  $reportPath = Resolve-ReportPath -Path $JsonReportPath
  $reportDirectory = Split-Path -Parent $reportPath
  if ($reportDirectory -and -not (Test-Path -LiteralPath $reportDirectory)) {
    New-Item -ItemType Directory -Path $reportDirectory | Out-Null
  }

  [ordered]@{
    schema_version = 1
    ok = $script:ok
    started_at = $startedAt.ToUniversalTime().ToString("o")
    finished_at = $finishedAt.ToUniversalTime().ToString("o")
    duration_ms = [int][Math]::Round(($finishedAt - $startedAt).TotalMilliseconds)
    working_directory = $apiRoot
    command = $Command
    revision = $Revision
    sql = [bool]$Sql
    dry_run = [bool]$DryRun
    database_url_override = [bool]$DatabaseUrl
    python_arguments = @($Arguments)
    exit_code = $script:exitCode
    error = $script:errorMessage
  } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8

  Write-Host "Migration report completed: $reportPath"
}

Push-Location -LiteralPath $apiRoot
$previousDatabaseUrl = $env:DATABASE_URL
try {
  if ($DatabaseUrl) {
    $env:DATABASE_URL = $DatabaseUrl
  }

  $args = @("-m", "alembic", "-c", "alembic.ini", $Command)

  if ($Command -in @("upgrade", "downgrade")) {
    $args += $Revision
  }

  if ($Sql) {
    $args += "--sql"
  }

  if ($DryRun) {
    Write-Host "Working directory: $apiRoot"
    Write-Host "DATABASE_URL override: $([bool]$DatabaseUrl)"
    Write-Host "Command: python $($args -join ' ')"
    $script:ok = $true
    $script:exitCode = 0
    return
  }

  python @args
  $script:exitCode = $LASTEXITCODE
  if ($LASTEXITCODE -ne 0) {
    throw "Alembic command failed with exit code $LASTEXITCODE."
  }
  $script:ok = $true
}
catch {
  $script:errorMessage = $_.Exception.Message
  throw
}
finally {
  Write-MigrationReport -Arguments $args
  if ($null -eq $previousDatabaseUrl) {
    Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
  }
  else {
    $env:DATABASE_URL = $previousDatabaseUrl
  }
  Pop-Location
}
