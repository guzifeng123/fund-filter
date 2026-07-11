param(
  [string]$ApiBase = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

function Invoke-SmokeRequest {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Request
  )

  Write-Host "==> $Name"
  try {
    $result = & $Request
    $result | ConvertTo-Json -Depth 8
    Write-Host "[ok] $Name"
    return $result
  }
  catch {
    Write-Error "[failed] $Name`: $($_.Exception.Message)"
    throw
  }
}

$apiRoot = $ApiBase.TrimEnd("/")

Invoke-SmokeRequest -Name "GET /health" -Request {
  Invoke-RestMethod -Method Get -Uri "$apiRoot/health"
}

$dataStatus = Invoke-SmokeRequest -Name "GET /api/data/status" -Request {
  Invoke-RestMethod -Method Get -Uri "$apiRoot/api/data/status"
}

if ($null -eq $dataStatus.data) {
  throw "Data status response is missing data envelope."
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
  throw "Fund filter response is missing data envelope."
}

Write-Host "API smoke test completed."
