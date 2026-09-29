param(
  [string]$JsonReportPath,
  [string]$MarkdownReportPath
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$startedAt = Get-Date
$results = @()

function Resolve-ReportPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if ([System.IO.Path]::IsPathRooted($Path)) {
    return $Path
  }

  return Join-Path $workspaceRoot $Path
}

function Format-MarkdownCell {
  param(
    [AllowNull()]
    [object]$Value
  )

  if ($null -eq $Value) {
    return ""
  }

  return ($Value.ToString() -replace "\|", "\|").Replace("`r", " ").Replace("`n", " ")
}

function Write-ContractsMarkdownReport {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Report,
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $status = if ($Report.ok) { "OK" } else { "FAILED" }
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add("# JSON Report Contract Summary")
  $lines.Add("")
  $lines.Add("- Status: $status")
  $lines.Add("- Started: $(Format-MarkdownCell $Report.started_at)")
  $lines.Add("- Finished: $(Format-MarkdownCell $Report.finished_at)")
  $lines.Add("- Duration ms: $(Format-MarkdownCell $Report.duration_ms)")
  $lines.Add("- Contract count: $(Format-MarkdownCell $Report.contract_count)")
  $lines.Add("- Failed count: $(Format-MarkdownCell $Report.failed_count)")
  $lines.Add("")
  $lines.Add("## Contracts")
  $lines.Add("")
  $lines.Add("| Contract | Script | Status | Duration ms | Error |")
  $lines.Add("| --- | --- | --- | ---: | --- |")
  foreach ($result in @($Report.results)) {
    $resultStatus = if ($result.ok) { "OK" } else { "FAILED" }
    $lines.Add("| $(Format-MarkdownCell $result.name) | ``$(Format-MarkdownCell $result.script)`` | $resultStatus | $(Format-MarkdownCell $result.duration_ms) | $(Format-MarkdownCell $result.error) |")
  }

  $reportDirectory = Split-Path -Parent $Path
  if ($reportDirectory -and -not (Test-Path -LiteralPath $reportDirectory)) {
    New-Item -ItemType Directory -Path $reportDirectory | Out-Null
  }
  $lines | Set-Content -LiteralPath $Path -Encoding utf8
}

function Write-ContractsReport {
  param(
    [Parameter(Mandatory = $true)]
    [bool]$Ok
  )

  if (-not $JsonReportPath -and -not $MarkdownReportPath) {
    return
  }

  $finishedAt = Get-Date
  $report = [ordered]@{
    schema_version = 1
    ok = $Ok
    started_at = $startedAt.ToUniversalTime().ToString("o")
    finished_at = $finishedAt.ToUniversalTime().ToString("o")
    duration_ms = [int][Math]::Round(($finishedAt - $startedAt).TotalMilliseconds)
    contract_count = @($results).Count
    failed_count = @($results | Where-Object { -not $_.ok }).Count
    results = @($results)
  }

  if ($JsonReportPath) {
    $reportPath = Resolve-ReportPath -Path $JsonReportPath
    $reportDirectory = Split-Path -Parent $reportPath
    if ($reportDirectory -and -not (Test-Path -LiteralPath $reportDirectory)) {
      New-Item -ItemType Directory -Path $reportDirectory | Out-Null
    }

    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Host "JSON report contract summary completed: $reportPath"
  }

  $markdownPath = if ($MarkdownReportPath) {
    Resolve-ReportPath -Path $MarkdownReportPath
  }
  elseif ($JsonReportPath) {
    "$((Resolve-ReportPath -Path $JsonReportPath)).md"
  }
  else {
    $null
  }

  if ($markdownPath) {
    Write-ContractsMarkdownReport -Report $report -Path $markdownPath
    Write-Host "Markdown report contract summary completed: $markdownPath"
  }
}

function Invoke-ContractCheck {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$ScriptPath
  )

  Write-Host "==> $Name"
  $contractStartedAt = Get-Date
  try {
    & (Join-Path $workspaceRoot $ScriptPath)
    $script:results += [ordered]@{
      name = $Name
      script = $ScriptPath
      ok = $true
      duration_ms = [int][Math]::Round(((Get-Date) - $contractStartedAt).TotalMilliseconds)
      error = $null
    }
    Write-Host "[ok] $Name"
  }
  catch {
    $script:results += [ordered]@{
      name = $Name
      script = $ScriptPath
      ok = $false
      duration_ms = [int][Math]::Round(((Get-Date) - $contractStartedAt).TotalMilliseconds)
      error = $_.Exception.Message
    }
    throw
  }
}

$schemaDirectory = Join-Path $workspaceRoot "packages\contracts"
$schemaFiles = Get-ChildItem -LiteralPath $schemaDirectory -File -Filter "*.schema.json" |
  Where-Object { $_.Name -eq "artifact-alerts.schema.json" -or $_.Name -eq "artifact-manifest.schema.json" -or $_.Name -like "*-report.schema.json" } |
  Sort-Object Name

$checks = @($schemaFiles | ForEach-Object {
    $contractName = $_.BaseName -replace "\.schema$", ""
    $scriptName = "check-$contractName-contract.ps1"
    $scriptPath = "scripts\$scriptName"
    if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot $scriptPath))) {
      throw "Missing contract check script for $($_.Name): $scriptPath"
    }

    [ordered]@{
      Name = "$($contractName -replace '-', ' ') contract"
      Script = $scriptPath
    }
  })

try {
  foreach ($check in $checks) {
    Invoke-ContractCheck -Name $check.Name -ScriptPath $check.Script
  }

  Write-ContractsReport -Ok $true
}
catch {
  Write-ContractsReport -Ok $false
  throw
}

Write-Host "All JSON report contract checks completed."
