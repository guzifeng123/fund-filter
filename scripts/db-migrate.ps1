param(
  [ValidateSet("upgrade", "downgrade", "current", "history", "heads")]
  [string]$Command = "upgrade",
  [string]$Revision = "head",
  [switch]$Sql,
  [string]$DatabaseUrl,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$apiRoot = Join-Path $workspaceRoot "apps\api"
$alembicConfig = Join-Path $apiRoot "alembic.ini"

if (-not (Test-Path -LiteralPath $alembicConfig)) {
  throw "Alembic config not found: $alembicConfig"
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
    return
  }

  python @args
  if ($LASTEXITCODE -ne 0) {
    throw "Alembic command failed with exit code $LASTEXITCODE."
  }
}
finally {
  if ($null -eq $previousDatabaseUrl) {
    Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
  }
  else {
    $env:DATABASE_URL = $previousDatabaseUrl
  }
  Pop-Location
}
