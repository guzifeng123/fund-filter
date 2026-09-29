param(
  [string]$OpenApiPath = "packages/contracts/openapi.json",
  [string]$InvalidFixturePath = "packages/contracts/openapi-empty-response.fixture.json"
)

$ErrorActionPreference = "Stop"
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Resolve-WorkspacePath {
  param([Parameter(Mandatory = $true)][string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) {
    return $Path
  }
  return Join-Path $workspaceRoot $Path
}

$validator = Join-Path $PSScriptRoot "validate-openapi-response-schemas.js"
node $validator (Resolve-WorkspacePath -Path $OpenApiPath)
if ($LASTEXITCODE -ne 0) {
  throw "OpenAPI response schema validation failed."
}

node $validator (Resolve-WorkspacePath -Path $InvalidFixturePath) --expect-invalid
if ($LASTEXITCODE -ne 0) {
  throw "OpenAPI empty-response fixture contract failed."
}

Write-Host "OpenAPI response schema contract check passed."
