param(
  [string]$ApiBase = "http://localhost:8000",
  [switch]$SeedIfEmpty,
  [switch]$RequireFresh,
  [string]$JsonReportPath
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$scriptStartedAt = Get-Date

function Invoke-OptionalCommand {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock]$Command
  )

  try {
    $value = & $Command
    if ($LASTEXITCODE -ne 0) {
      return $null
    }
    return ($value | Select-Object -First 1)
  }
  catch {
    return $null
  }
}

function Get-SmokeEnvironment {
  $openApiPath = Join-Path $workspaceRoot "packages\contracts\openapi.json"
  $openApiHash = if (Test-Path -LiteralPath $openApiPath) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $openApiPath).Hash
  }
  else {
    $null
  }

  return [ordered]@{
    os = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
    powershell_version = $PSVersionTable.PSVersion.ToString()
    node_version = Invoke-OptionalCommand { node --version }
    npm_version = Invoke-OptionalCommand { npm.cmd --version }
    git_commit = Invoke-OptionalCommand { git -C $workspaceRoot rev-parse HEAD }
    openapi_commit = Invoke-OptionalCommand { git -C $workspaceRoot log -1 --format=%H -- packages/contracts/openapi.json }
    openapi_sha256 = $openApiHash
  }
}

$report = [ordered]@{
  schema_version = 1
  api_base = $ApiBase
  started_at = $scriptStartedAt.ToUniversalTime().ToString("o")
  finished_at = $null
  duration_ms = $null
  seed_if_empty = [bool]$SeedIfEmpty
  require_fresh = [bool]$RequireFresh
  ok = $false
  environment = Get-SmokeEnvironment
  steps = @()
  summary = [ordered]@{}
}

function Add-SmokeStep {
  param(
    [Parameter(Mandatory = $true)]
    [hashtable]$Step
  )

  $script:report.steps = @($script:report.steps) + $Step
}

function Write-SmokeReport {
  param(
    [bool]$Ok
  )

  $finishedAt = Get-Date
  $script:report.ok = $Ok
  $script:report.finished_at = $finishedAt.ToUniversalTime().ToString("o")
  $script:report.duration_ms = [int][Math]::Round(($finishedAt - $script:scriptStartedAt).TotalMilliseconds)

  if ($JsonReportPath) {
    $reportPath = $JsonReportPath
    if (-not [System.IO.Path]::IsPathRooted($reportPath)) {
      $reportPath = Join-Path $workspaceRoot $reportPath
    }
    $reportDirectory = Split-Path -Parent $reportPath
    if ($reportDirectory -and -not (Test-Path -LiteralPath $reportDirectory)) {
      New-Item -ItemType Directory -Path $reportDirectory | Out-Null
    }
    $script:report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Host "Wrote JSON smoke report to $reportPath"
  }
}

function Invoke-SmokeRequest {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Request
  )

  Write-Host "==> $Name"
  $startedAt = Get-Date
  try {
    $result = & $Request
    $result | ConvertTo-Json -Depth 8
    Write-Host "[ok] $Name"
    Add-SmokeStep @{
      name = $Name
      ok = $true
      duration_ms = [int][Math]::Round(((Get-Date) - $startedAt).TotalMilliseconds)
      error = $null
    }
    return $result
  }
  catch {
    Add-SmokeStep @{
      name = $Name
      ok = $false
      duration_ms = [int][Math]::Round(((Get-Date) - $startedAt).TotalMilliseconds)
      error = $_.Exception.Message
    }
    Write-Error "[failed] $Name`: $($_.Exception.Message)"
    throw
  }
}

$apiRoot = $ApiBase.TrimEnd("/")

try {
  Invoke-SmokeRequest -Name "GET /health" -Request {
    Invoke-RestMethod -Method Get -Uri "$apiRoot/health"
  }

  $dataStatus = Invoke-SmokeRequest -Name "GET /api/data/status" -Request {
    Invoke-RestMethod -Method Get -Uri "$apiRoot/api/data/status"
  }

  if ($null -eq $dataStatus.data) {
    Add-SmokeStep @{
      name = "Validate data status envelope"
      ok = $false
      duration_ms = 0
      error = "Data status response is missing data envelope."
    }
    throw "Data status response is missing data envelope."
  }
  Add-SmokeStep @{
    name = "Validate data status envelope"
    ok = $true
    duration_ms = 0
    error = $null
  }

  if ($SeedIfEmpty -and $dataStatus.data.fund_count -eq 0) {
    Invoke-SmokeRequest -Name "Seed sample data when empty" -Request {
      Push-Location -LiteralPath (Join-Path $workspaceRoot "apps/api")
      try {
        python -m app.jobs.seed_sample_data
        if ($LASTEXITCODE -ne 0) {
          throw "Seed sample data failed with exit code $LASTEXITCODE."
        }
      }
      finally {
        Pop-Location
      }
      return @{ seeded = $true }
    }

    $dataStatus = Invoke-SmokeRequest -Name "GET /api/data/status after seed" -Request {
      Invoke-RestMethod -Method Get -Uri "$apiRoot/api/data/status"
    }
  }

  if ($RequireFresh -and $dataStatus.data.freshness_status -ne "fresh") {
    Add-SmokeStep @{
      name = "Validate data freshness"
      ok = $false
      duration_ms = 0
      error = "Data freshness is '$($dataStatus.data.freshness_status)', expected 'fresh'."
    }
    throw "Data freshness is '$($dataStatus.data.freshness_status)', expected 'fresh'."
  }
  if ($RequireFresh) {
    Add-SmokeStep @{
      name = "Validate data freshness"
      ok = $true
      duration_ms = 0
      error = $null
    }
  }

  $filterBody = @{
    risk_profile = "C3"
    fund_types = @("mixed", "bond")
    min_years = 3
    size_range = @(0, 500)
    return_rank_percentile = 50
    max_drawdown_lte_category_avg = $true
    sharpe_gte = 0.8
    fee_lte = 1.5
    sort_by = "sharpe_ratio"
    sort_order = "desc"
  } | ConvertTo-Json -Depth 8

  $filterResult = Invoke-SmokeRequest -Name "POST /api/funds/filter" -Request {
    Invoke-RestMethod `
      -Method Post `
      -Uri "$apiRoot/api/funds/filter" `
      -ContentType "application/json" `
      -Body $filterBody
  }

  if ($null -eq $filterResult.data) {
    Add-SmokeStep @{
      name = "Validate fund filter envelope"
      ok = $false
      duration_ms = 0
      error = "Fund filter response is missing data envelope."
    }
    throw "Fund filter response is missing data envelope."
  }
  Add-SmokeStep @{
    name = "Validate fund filter envelope"
    ok = $true
    duration_ms = 0
    error = $null
  }

  $report.summary = [ordered]@{
    db_connected = $dataStatus.data.db_connected
    fund_count = $dataStatus.data.fund_count
    nav_count = $dataStatus.data.nav_count
    freshness_status = $dataStatus.data.freshness_status
    latest_data_updated_at = $dataStatus.data.latest_data_updated_at
    filter_result_count = @($filterResult.data).Count
  }

  Write-SmokeReport -Ok $true
  Write-Host "API smoke test completed."
}
catch {
  Write-SmokeReport -Ok $false
  throw
}
