param(
  [string]$ApiBase = "http://localhost:8000",
  [string]$WebBase = "http://localhost:3000",
  [int]$TimeoutSeconds = 90,
  [switch]$DownAfter
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $workspaceRoot

function Assert-Command {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Command
  )

  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    throw "Command not found: $Command"
  }
}

function Wait-HttpOk {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [Parameter(Mandatory = $true)]
    [int]$Timeout
  )

  $deadline = (Get-Date).AddSeconds($Timeout)
  do {
    try {
      $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        Write-Host "$Url responded with $($response.StatusCode)"
        return
      }
    }
    catch {
      Start-Sleep -Seconds 2
    }
  } while ((Get-Date) -lt $deadline)

  throw "Timed out waiting for $Url"
}

Assert-Command "docker"
docker compose version

try {
  docker compose up --build -d
  Wait-HttpOk -Url "$ApiBase/health" -Timeout $TimeoutSeconds
  Wait-HttpOk -Url $WebBase -Timeout $TimeoutSeconds
  .\scripts\smoke-api.ps1 `
    -ApiBase $ApiBase `
    -SeedIfEmpty `
    -RequireFresh `
    -JsonReportPath "output/smoke/docker-compose-api-smoke.json"
  Write-Host "Docker Compose verification completed."
}
finally {
  if ($DownAfter) {
    docker compose down
  }
}
