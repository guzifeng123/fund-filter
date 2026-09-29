$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot "playwright-server-helpers.ps1")

function Assert-Contract {
  param(
    [Parameter(Mandatory = $true)]
    [bool]$Condition,
    [Parameter(Mandatory = $true)]
    [string]$Message
  )

  if (-not $Condition) {
    throw "Playwright launcher contract failed: $Message"
  }
}

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "fund-playwright-launcher-contract-$([Guid]::NewGuid().ToString('N'))"
$occupiedListener = $null

try {
  $pair = Resolve-PlaywrightPortPair
  Assert-Contract `
    -Condition ($pair.WebPort -ne $pair.ApiPort) `
    -Message "automatically selected Web and API ports must be different"
  Assert-Contract `
    -Condition (Test-PlaywrightTcpPortAvailable -Port $pair.WebPort) `
    -Message "automatically selected Web port must be available"
  Assert-Contract `
    -Condition (Test-PlaywrightTcpPortAvailable -Port $pair.ApiPort) `
    -Message "automatically selected API port must be available"

  $samePort = Get-PlaywrightAvailablePort
  $samePortRejected = $false
  try {
    Resolve-PlaywrightPortPair `
      -WebPort $samePort `
      -WebPortSpecified `
      -ApiPort $samePort `
      -ApiPortSpecified | Out-Null
  }
  catch {
    $samePortRejected = $_.Exception.Message -like "*must be different*"
  }
  Assert-Contract `
    -Condition $samePortRejected `
    -Message "explicit identical Web and API ports must be rejected"

  $occupiedListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  $occupiedListener.Start()
  $occupiedPort = ([System.Net.IPEndPoint]$occupiedListener.LocalEndpoint).Port
  $conflictStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
  $occupiedPortRejected = $false
  try {
    Resolve-PlaywrightPort `
      -Name "Web" `
      -RequestedPort $occupiedPort `
      -WasSpecified | Out-Null
  }
  catch {
    $occupiedPortRejected = $_.Exception.Message -like "*already in use*"
  }
  finally {
    $conflictStopwatch.Stop()
  }
  Assert-Contract `
    -Condition $occupiedPortRejected `
    -Message "an occupied explicit port must be rejected"
  Assert-Contract `
    -Condition ($conflictStopwatch.Elapsed.TotalSeconds -lt 2) `
    -Message "an occupied explicit port must fail fast"

  $logDirectory = Join-Path $testRoot "output\playwright\service-logs"
  $webLogs = New-PlaywrightServiceLogPaths `
    -LogDirectory $logDirectory `
    -ServiceName "contract-web-$($pair.WebPort)" `
    -RunId "contract-run"
  $apiLogs = New-PlaywrightServiceLogPaths `
    -LogDirectory $logDirectory `
    -ServiceName "contract-api-$($pair.ApiPort)" `
    -RunId "contract-run"

  $logProbeCommand = "[Console]::Out.WriteLine('contract-stdout'); [Console]::Error.WriteLine('contract-stderr')"
  $encodedLogProbeCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($logProbeCommand))
  $logProbeProcess = Start-PlaywrightServer `
    -FilePath "pwsh.exe" `
    -ArgumentList @("-NoProfile", "-EncodedCommand", $encodedLogProbeCommand) `
    -WorkingDirectory $testRoot `
    -StandardOutputPath $webLogs.stdout `
    -StandardErrorPath $webLogs.stderr
  $logProbeProcess.WaitForExit()
  Assert-Contract -Condition ($logProbeProcess.ExitCode -eq 0) -Message "stdout/stderr log probe must exit successfully"
  Assert-Contract `
    -Condition ((Get-Content -LiteralPath $webLogs.stdout -Raw -Encoding UTF8) -like "*contract-stdout*") `
    -Message "Start-PlaywrightServer must redirect stdout to its retained log"
  Assert-Contract `
    -Condition ((Get-Content -LiteralPath $webLogs.stderr -Raw -Encoding UTF8) -like "*contract-stderr*") `
    -Message "Start-PlaywrightServer must redirect stderr to its retained log"
  $logProbeProcess.Dispose()

  $summaryPath = Join-Path $testRoot "output\playwright\launcher-summary.json"
  $serviceLogs = [ordered]@{
    web = [ordered]@{
      stdout = $webLogs.stdout
      stderr = $webLogs.stderr
    }
    api = [ordered]@{
      stdout = $apiLogs.stdout
      stderr = $apiLogs.stderr
    }
  }
  $metadata = New-PlaywrightRunMetadata `
    -Mode "contract-test" `
    -RunId "contract-run" `
    -WebPort $pair.WebPort `
    -ApiPort $pair.ApiPort `
    -PlaywrightProject "contract-project" `
    -SummaryPath $summaryPath `
    -ServiceLogs $serviceLogs
  $visualCheckReportPath = Join-Path $testRoot "output\playwright\real-api-visual-check.json"
  $metadata["visual_check_report"] = [ordered]@{
    path = [System.IO.Path]::GetFullPath($visualCheckReportPath)
    contract_status = "passed"
  }
  Complete-PlaywrightRunMetadata `
    -Metadata $metadata `
    -Status "success" `
    -ExitCode 0 `
    -ErrorMessage $null
  Write-PlaywrightRunSummary -Metadata $metadata

  $report = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Contract -Condition ($report.status -eq "success") -Message "summary must retain success status"
  Assert-Contract -Condition ($report.ports.web -eq $pair.WebPort) -Message "summary must record the actual Web port"
  Assert-Contract -Condition ($report.ports.api -eq $pair.ApiPort) -Message "summary must record the actual API port"
  Assert-Contract -Condition ($report.playwright.exit_code -eq 0) -Message "summary must record the Playwright exit code"
  Assert-Contract -Condition (-not [string]::IsNullOrWhiteSpace($report.finished_at)) -Message "summary must record completion time"
  Assert-Contract -Condition ($report.service_logs.web.stdout -eq $webLogs.stdout) -Message "summary must record Web stdout path"
  Assert-Contract -Condition ($report.service_logs.web.stderr -eq $webLogs.stderr) -Message "summary must record Web stderr path"
  Assert-Contract -Condition ($report.service_logs.api.stdout -eq $apiLogs.stdout) -Message "summary must record API stdout path"
  Assert-Contract -Condition ($report.service_logs.api.stderr -eq $apiLogs.stderr) -Message "summary must record API stderr path"
  Assert-Contract `
    -Condition ($report.visual_check_report.path -eq [System.IO.Path]::GetFullPath($visualCheckReportPath)) `
    -Message "summary must retain the real API visual check report path"
  Assert-Contract `
    -Condition ($report.visual_check_report.contract_status -eq "passed") `
    -Message "summary must retain visual check contract status"

  $diagnostics = Format-PlaywrightRunDiagnostics -Metadata $metadata
  Assert-Contract -Condition ($diagnostics -like "*web_port=$($pair.WebPort)*") -Message "failure diagnostics must include Web port"
  Assert-Contract -Condition ($diagnostics -like "*api_port=$($pair.ApiPort)*") -Message "failure diagnostics must include API port"
  Assert-Contract -Condition ($diagnostics -like "*$($webLogs.stderr)*") -Message "failure diagnostics must include service log paths"

  Write-Host "Playwright launcher contract check passed."
}
finally {
  if ($null -ne $occupiedListener) {
    $occupiedListener.Stop()
  }

  if (Test-Path -LiteralPath $testRoot) {
    $resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
    $resolvedTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if (-not $resolvedTestRoot.StartsWith($resolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to clean launcher contract directory outside the system temp directory: $resolvedTestRoot"
    }
    Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
  }
}
