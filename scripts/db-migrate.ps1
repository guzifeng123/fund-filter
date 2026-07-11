param(
  [ValidateSet("upgrade", "downgrade", "current", "history", "heads")]
  [string]$Command = "upgrade",
  [string]$Revision = "head",
  [switch]$Sql
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$apiRoot = Join-Path $workspaceRoot "apps\api"
$alembicConfig = Join-Path $apiRoot "alembic.ini"

if (-not (Test-Path -LiteralPath $alembicConfig)) {
  throw "Alembic config not found: $alembicConfig"
}

Push-Location -LiteralPath $apiRoot
try {
  $args = @("-m", "alembic", "-c", "alembic.ini", $Command)

  if ($Command -in @("upgrade", "downgrade")) {
    $args += $Revision
  }

  if ($Sql) {
    $args += "--sql"
  }

  python @args
}
finally {
  Pop-Location
}
