param(
  [AllowNull()]
  [Nullable[int]]$WebPort
)

$ErrorActionPreference = "Stop"
$webPortSpecified = $PSBoundParameters.ContainsKey("WebPort")

. (Join-Path $PSScriptRoot "playwright-server-helpers.ps1")

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$webRoot = Join-Path $workspaceRoot "apps\web"
$nextCli = Join-Path $workspaceRoot "node_modules\next\dist\bin\next"
$resolvedWebPort = Resolve-PlaywrightPort `
  -Name "Web" `
  -RequestedPort $WebPort `
  -WasSpecified:$webPortSpecified
$runId = "{0}-{1}-{2}" -f (Get-Date -Format "yyyyMMdd-HHmmssfff"), $PID, ([Guid]::NewGuid().ToString("N").Substring(0, 8))
$playwrightOutputDirectory = Join-Path $workspaceRoot "output\playwright"
$serviceLogDirectory = Join-Path $playwrightOutputDirectory "service-logs"
$webLogs = New-PlaywrightServiceLogPaths `
  -LogDirectory $serviceLogDirectory `
  -ServiceName "mock-web-$resolvedWebPort" `
  -RunId $runId
$summaryPath = Join-Path $playwrightOutputDirectory "web-e2e-launcher-$runId.json"
$serviceLogs = [ordered]@{
  web = [ordered]@{
    stdout = $webLogs.stdout
    stderr = $webLogs.stderr
  }
}
$runMetadata = New-PlaywrightRunMetadata `
  -Mode "mocked-api" `
  -RunId $runId `
  -WebPort $resolvedWebPort `
  -ApiPort $null `
  -PlaywrightProject "chromium" `
  -SummaryPath $summaryPath `
  -ServiceLogs $serviceLogs
$webProcess = $null
$runStatus = "failed"
$runError = $null
$playwrightExitCode = $null
$previousExternalServers = $env:PLAYWRIGHT_EXTERNAL_SERVERS
$previousWebPort = $env:PLAYWRIGHT_WEB_PORT
$previousNextPublicApiBase = $env:NEXT_PUBLIC_API_BASE

try {
  # Mocked E2E routes are registered on the web origin.  Point the browser
  # client there explicitly; otherwise the production localhost:8000 default
  # bypasses Playwright's route handlers and produces misleading blank/error
  # states when no API process is running.
  $env:NEXT_PUBLIC_API_BASE = "http://127.0.0.1:$resolvedWebPort/api"
  Write-PlaywrightRunSummary -Metadata $runMetadata
  Write-Host "Starting mocked API E2E on web port $resolvedWebPort."
  $webProcess = Start-PlaywrightServer `
    -FilePath "node" `
    -ArgumentList @($nextCli, "dev", "--hostname", "127.0.0.1", "--port", $resolvedWebPort.ToString()) `
    -WorkingDirectory $webRoot `
    -StandardOutputPath $webLogs.stdout `
    -StandardErrorPath $webLogs.stderr
  Wait-PlaywrightPort -Port $resolvedWebPort -Process $webProcess

  $env:PLAYWRIGHT_EXTERNAL_SERVERS = "1"
  $env:PLAYWRIGHT_WEB_PORT = $resolvedWebPort.ToString()
  npm.cmd --workspace apps/web run e2e -- --project=chromium
  $playwrightExitCode = $LASTEXITCODE
  if ($playwrightExitCode -ne 0) {
    throw "Playwright tests failed with exit code $playwrightExitCode."
  }
  $runStatus = "success"
}
catch {
  $runError = $_.Exception.Message
  $diagnostics = Format-PlaywrightRunDiagnostics -Metadata $runMetadata
  throw "Mocked API Playwright run failed: $runError Diagnostics: $diagnostics"
}
finally {
  $env:PLAYWRIGHT_EXTERNAL_SERVERS = $previousExternalServers
  $env:PLAYWRIGHT_WEB_PORT = $previousWebPort
  $env:NEXT_PUBLIC_API_BASE = $previousNextPublicApiBase
  Stop-PlaywrightProcessTree -Process $webProcess
  Complete-PlaywrightRunMetadata `
    -Metadata $runMetadata `
    -Status $runStatus `
    -ExitCode $playwrightExitCode `
    -ErrorMessage $runError
  Write-PlaywrightRunSummary -Metadata $runMetadata
  Write-Host "Playwright launcher summary: $summaryPath"
  Write-Host "Web service logs: stdout=$($webLogs.stdout); stderr=$($webLogs.stderr)"
}
