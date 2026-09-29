param(
  [AllowNull()]
  [Nullable[int]]$WebPort,
  [AllowNull()]
  [Nullable[int]]$ApiPort
)

$ErrorActionPreference = "Stop"
$webPortSpecified = $PSBoundParameters.ContainsKey("WebPort")
$apiPortSpecified = $PSBoundParameters.ContainsKey("ApiPort")

. (Join-Path $PSScriptRoot "playwright-server-helpers.ps1")

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$apiRoot = Join-Path $workspaceRoot "apps\api"
$webRoot = Join-Path $workspaceRoot "apps\web"
$nextCli = Join-Path $workspaceRoot "node_modules\next\dist\bin\next"
$resolvedPorts = Resolve-PlaywrightPortPair `
  -WebPort $WebPort `
  -WebPortSpecified:$webPortSpecified `
  -ApiPort $ApiPort `
  -ApiPortSpecified:$apiPortSpecified
$resolvedWebPort = $resolvedPorts.WebPort
$resolvedApiPort = $resolvedPorts.ApiPort
$runId = "{0}-{1}-{2}" -f (Get-Date -Format "yyyyMMdd-HHmmssfff"), $PID, ([Guid]::NewGuid().ToString("N").Substring(0, 8))
$databaseDirectory = Join-Path $workspaceRoot "output\playwright"
$databasePath = Join-Path $databaseDirectory "real-api.db"
$databaseUrl = "sqlite:///" + $databasePath.Replace("\", "/")
$visualCheckReportPath = Join-Path $databaseDirectory "real-api-visual-check.json"
$visualCheckContractScript = Join-Path $PSScriptRoot "check-visual-check-report-contract.ps1"
$playwrightProjects = @("real-api-chromium", "real-api-mobile-chromium", "real-api-firefox")
$serviceLogDirectory = Join-Path $databaseDirectory "service-logs"
$apiLogs = New-PlaywrightServiceLogPaths `
  -LogDirectory $serviceLogDirectory `
  -ServiceName "real-api-$resolvedApiPort" `
  -RunId $runId
$webLogs = New-PlaywrightServiceLogPaths `
  -LogDirectory $serviceLogDirectory `
  -ServiceName "real-web-$resolvedWebPort" `
  -RunId $runId
$summaryPath = Join-Path $databaseDirectory "real-api-e2e-launcher-$runId.json"
$serviceLogs = [ordered]@{
  api = [ordered]@{
    stdout = $apiLogs.stdout
    stderr = $apiLogs.stderr
  }
  web = [ordered]@{
    stdout = $webLogs.stdout
    stderr = $webLogs.stderr
  }
}
$runMetadata = New-PlaywrightRunMetadata `
  -Mode "real-api" `
  -RunId $runId `
  -WebPort $resolvedWebPort `
  -ApiPort $resolvedApiPort `
  -PlaywrightProject ($playwrightProjects -join ",") `
  -SummaryPath $summaryPath `
  -ServiceLogs $serviceLogs
$runMetadata["database_path"] = [System.IO.Path]::GetFullPath($databasePath)
$runMetadata["runtime"] = [ordered]@{
  next_public_api_base = "http://127.0.0.1:$resolvedApiPort/api"
  cors_origins = "http://127.0.0.1:$resolvedWebPort"
}
$runMetadata["visual_check_report"] = [ordered]@{
  path = [System.IO.Path]::GetFullPath($visualCheckReportPath)
  contract_script = [System.IO.Path]::GetFullPath($visualCheckContractScript)
  contract_status = "not-run"
  validated_at = $null
}
$apiProcess = $null
$webProcess = $null
$runStatus = "failed"
$runError = $null
$playwrightExitCode = $null

$previousDatabaseUrl = $env:DATABASE_URL
$previousRealApi = $env:PLAYWRIGHT_REAL_API
$previousExternalServers = $env:PLAYWRIGHT_EXTERNAL_SERVERS
$previousPlaywrightDatabaseUrl = $env:PLAYWRIGHT_DATABASE_URL
$previousWebPort = $env:PLAYWRIGHT_WEB_PORT
$previousApiPort = $env:PLAYWRIGHT_API_PORT

try {
  Write-PlaywrightRunSummary -Metadata $runMetadata
  Write-Host "Starting real API E2E on web port $resolvedWebPort and API port $resolvedApiPort."

  if (-not (Test-Path -LiteralPath $databaseDirectory)) {
    New-Item -ItemType Directory -Path $databaseDirectory -Force | Out-Null
  }
  if (Test-Path -LiteralPath $databasePath) {
    Remove-Item -LiteralPath $databasePath -Force
  }
  if (Test-Path -LiteralPath $visualCheckReportPath) {
    Remove-Item -LiteralPath $visualCheckReportPath -Force
  }

  & (Join-Path $PSScriptRoot "db-migrate.ps1") `
    -DatabaseUrl $databaseUrl `
    -JsonReportPath ".\output\playwright\real-api-migration.json"

  $env:DATABASE_URL = $databaseUrl
  Push-Location -LiteralPath $apiRoot
  try {
    python -m app.jobs.seed_sample_data
    if ($LASTEXITCODE -ne 0) {
      throw "Seed sample data failed with exit code $LASTEXITCODE."
    }
  }
  finally {
    Pop-Location
  }

  $apiProcess = Start-PlaywrightServer `
    -FilePath "python" `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $resolvedApiPort.ToString()) `
    -WorkingDirectory $apiRoot `
    -Environment @{
      DATABASE_URL = $databaseUrl
      FUND_SYNC_SCHEDULER_ENABLED = "false"
      CORS_ORIGINS = "http://127.0.0.1:$resolvedWebPort"
      PYTHONUNBUFFERED = "1"
    } `
    -StandardOutputPath $apiLogs.stdout `
    -StandardErrorPath $apiLogs.stderr
  Wait-PlaywrightPort -Port $resolvedApiPort -Process $apiProcess

  $webProcess = Start-PlaywrightServer `
    -FilePath "node" `
    -ArgumentList @($nextCli, "dev", "--hostname", "127.0.0.1", "--port", $resolvedWebPort.ToString()) `
    -WorkingDirectory $webRoot `
    -Environment @{ NEXT_PUBLIC_API_BASE = "http://127.0.0.1:$resolvedApiPort/api" } `
    -StandardOutputPath $webLogs.stdout `
    -StandardErrorPath $webLogs.stderr
  Wait-PlaywrightPort -Port $resolvedWebPort -Process $webProcess

  $env:PLAYWRIGHT_REAL_API = "1"
  $env:PLAYWRIGHT_EXTERNAL_SERVERS = "1"
  $env:PLAYWRIGHT_DATABASE_URL = $databaseUrl
  $env:PLAYWRIGHT_WEB_PORT = $resolvedWebPort.ToString()
  $env:PLAYWRIGHT_API_PORT = $resolvedApiPort.ToString()
  npm.cmd --workspace apps/web run e2e -- `
    --project=real-api-chromium `
    --project=real-api-mobile-chromium `
    --project=real-api-firefox
  $playwrightExitCode = $LASTEXITCODE
  if ($playwrightExitCode -ne 0) {
    throw "Real API Playwright tests failed with exit code $playwrightExitCode."
  }

  $runMetadata["visual_check_report"]["contract_status"] = "running"
  try {
    & $visualCheckContractScript -ReportPath $visualCheckReportPath
    if ($LASTEXITCODE -ne 0) {
      throw "Visual check report contract failed with exit code $LASTEXITCODE."
    }
    $runMetadata["visual_check_report"]["contract_status"] = "passed"
    $runMetadata["visual_check_report"]["validated_at"] = (Get-Date).ToUniversalTime().ToString("o")
  }
  catch {
    $runMetadata["visual_check_report"]["contract_status"] = "failed"
    throw
  }
  $runStatus = "success"
}
catch {
  $runError = $_.Exception.Message
  $diagnostics = Format-PlaywrightRunDiagnostics -Metadata $runMetadata
  throw "Real API Playwright run failed: $runError Diagnostics: $diagnostics"
}
finally {
  $env:DATABASE_URL = $previousDatabaseUrl
  $env:PLAYWRIGHT_REAL_API = $previousRealApi
  $env:PLAYWRIGHT_EXTERNAL_SERVERS = $previousExternalServers
  $env:PLAYWRIGHT_DATABASE_URL = $previousPlaywrightDatabaseUrl
  $env:PLAYWRIGHT_WEB_PORT = $previousWebPort
  $env:PLAYWRIGHT_API_PORT = $previousApiPort
  Stop-PlaywrightProcessTree -Process $webProcess
  Stop-PlaywrightProcessTree -Process $apiProcess
  Complete-PlaywrightRunMetadata `
    -Metadata $runMetadata `
    -Status $runStatus `
    -ExitCode $playwrightExitCode `
    -ErrorMessage $runError
  Write-PlaywrightRunSummary -Metadata $runMetadata
  Write-Host "Playwright launcher summary: $summaryPath"
  Write-Host "API service logs: stdout=$($apiLogs.stdout); stderr=$($apiLogs.stderr)"
  Write-Host "Web service logs: stdout=$($webLogs.stdout); stderr=$($webLogs.stderr)"
}
