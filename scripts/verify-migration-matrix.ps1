[CmdletBinding()]
param(
  [ValidateSet("sqlite", "postgresql")]
  [string]$Dialect = "sqlite",
  [string]$DatabaseUrl,
  [switch]$RequireUnprivilegedRole,
  [ValidateRange(1, 3600)]
  [int]$CommandTimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$verifierPath = Join-Path $workspaceRoot "scripts\verify_migration_matrix.py"

if (-not (Test-Path -LiteralPath $verifierPath -PathType Leaf)) {
  throw "Migration matrix verifier not found: $verifierPath"
}

if ($Dialect -eq "postgresql" -and -not $DatabaseUrl) {
  $DatabaseUrl = $env:DATABASE_URL
}
if ($Dialect -eq "postgresql" -and -not $DatabaseUrl) {
  throw "PostgreSQL verification requires -DatabaseUrl or DATABASE_URL."
}
if ($RequireUnprivilegedRole -and $Dialect -ne "postgresql") {
  throw "-RequireUnprivilegedRole can only be used with -Dialect postgresql."
}

$arguments = @(
  $verifierPath,
  "--dialect", $Dialect,
  "--command-timeout-seconds", $CommandTimeoutSeconds
)
if ($DatabaseUrl) {
  $arguments += @("--database-url", $DatabaseUrl)
}
if ($RequireUnprivilegedRole) {
  $arguments += "--require-unprivileged-role"
}

& python @arguments
if ($LASTEXITCODE -ne 0) {
  throw "Migration matrix verification failed with exit code $LASTEXITCODE."
}
