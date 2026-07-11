param(
  [switch]$SkipBuild,
  [switch]$CheckOpenApiDrift
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $workspaceRoot

function Invoke-Step {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Command
  )

  Write-Host "==> $Name"
  & $Command
  Write-Host "[ok] $Name"
}

Invoke-Step -Name "Backend tests" -Command {
  python -m pytest apps/api/app/tests
}

Invoke-Step -Name "Backend Ruff" -Command {
  python -m ruff check apps/api/app
}

Invoke-Step -Name "Compliance text" -Command {
  .\scripts\check-compliance-text.ps1
}

Invoke-Step -Name "Web lint" -Command {
  npm.cmd run lint:web
}

Invoke-Step -Name "Web tests" -Command {
  npm.cmd run test:web
}

if (-not $SkipBuild) {
  Invoke-Step -Name "Web build" -Command {
    npm.cmd run build:web
  }
}

Invoke-Step -Name "OpenAPI export" -Command {
  $openApiPath = Join-Path $workspaceRoot "packages\contracts\openapi.json"
  $beforeHash = if (Test-Path -LiteralPath $openApiPath) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $openApiPath).Hash
  }
  else {
    $null
  }

  npm.cmd run export:openapi

  if ($CheckOpenApiDrift) {
    $afterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $openApiPath).Hash
    if ($beforeHash -ne $afterHash) {
      throw "OpenAPI contract changed after export. Review packages/contracts/openapi.json and commit the updated contract if expected."
    }
  }
}

Write-Host "All checks completed."
