function Test-PlaywrightTcpPortAvailable {
  param(
    [Parameter(Mandatory = $true)]
    [int]$Port
  )

  if ($Port -lt 1 -or $Port -gt 65535) {
    return $false
  }

  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
  try {
    $listener.Start()
    return $true
  }
  catch [System.Net.Sockets.SocketException] {
    return $false
  }
  finally {
    $listener.Stop()
  }
}

function Assert-PlaywrightPortValue {
  param(
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Port -lt 1 -or $Port -gt 65535) {
    throw "$Name port must be between 1 and 65535; received $Port."
  }
}

function Assert-PlaywrightPortAvailable {
  param(
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  Assert-PlaywrightPortValue -Port $Port -Name $Name
  if (-not (Test-PlaywrightTcpPortAvailable -Port $Port)) {
    throw "$Name port $Port is already in use on 127.0.0.1. Omit the port parameter to select an available port automatically, or provide a different port."
  }
}

function Get-PlaywrightAvailablePort {
  param(
    [int[]]$ExcludedPorts = @()
  )

  for ($attempt = 0; $attempt -lt 50; $attempt++) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
      $listener.Start()
      $candidate = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
      $listener.Stop()
    }

    if ($candidate -notin $ExcludedPorts) {
      return $candidate
    }
  }

  throw "Unable to select an available TCP port after 50 attempts."
}

function Resolve-PlaywrightPort {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [AllowNull()]
    [Nullable[int]]$RequestedPort,
    [switch]$WasSpecified,
    [int[]]$ExcludedPorts = @()
  )

  if (-not $WasSpecified) {
    return Get-PlaywrightAvailablePort -ExcludedPorts $ExcludedPorts
  }

  if ($null -eq $RequestedPort) {
    throw "$Name port was explicitly specified without a value."
  }

  $port = [int]$RequestedPort
  Assert-PlaywrightPortValue -Port $port -Name $Name
  if ($port -in $ExcludedPorts) {
    throw "$Name port $port conflicts with another Playwright service port. Web and API ports must be different."
  }
  Assert-PlaywrightPortAvailable -Port $port -Name $Name
  return $port
}

function Resolve-PlaywrightPortPair {
  param(
    [AllowNull()]
    [Nullable[int]]$WebPort,
    [switch]$WebPortSpecified,
    [AllowNull()]
    [Nullable[int]]$ApiPort,
    [switch]$ApiPortSpecified
  )

  if ($WebPortSpecified) {
    if ($null -eq $WebPort) {
      throw "Web port was explicitly specified without a value."
    }
    Assert-PlaywrightPortValue -Port ([int]$WebPort) -Name "Web"
  }
  if ($ApiPortSpecified) {
    if ($null -eq $ApiPort) {
      throw "API port was explicitly specified without a value."
    }
    Assert-PlaywrightPortValue -Port ([int]$ApiPort) -Name "API"
  }
  if ($WebPortSpecified -and $ApiPortSpecified -and ([int]$WebPort) -eq ([int]$ApiPort)) {
    throw "Web and API ports must be different; both were set to $([int]$WebPort)."
  }

  if ($WebPortSpecified) {
    Assert-PlaywrightPortAvailable -Port ([int]$WebPort) -Name "Web"
    $resolvedWebPort = [int]$WebPort
  }
  else {
    $excludedWebPorts = if ($ApiPortSpecified) { @([int]$ApiPort) } else { @() }
    $resolvedWebPort = Get-PlaywrightAvailablePort -ExcludedPorts $excludedWebPorts
  }

  if ($ApiPortSpecified) {
    Assert-PlaywrightPortAvailable -Port ([int]$ApiPort) -Name "API"
    $resolvedApiPort = [int]$ApiPort
  }
  else {
    $resolvedApiPort = Get-PlaywrightAvailablePort -ExcludedPorts @($resolvedWebPort)
  }

  [PSCustomObject]@{
    WebPort = $resolvedWebPort
    ApiPort = $resolvedApiPort
  }
}

function New-PlaywrightServiceLogPaths {
  param(
    [Parameter(Mandatory = $true)]
    [string]$LogDirectory,
    [Parameter(Mandatory = $true)]
    [string]$ServiceName,
    [Parameter(Mandatory = $true)]
    [string]$RunId
  )

  if ($ServiceName -notmatch '^[A-Za-z0-9-]+$') {
    throw "Playwright service name may only contain letters, digits, and hyphens: $ServiceName"
  }
  if ($RunId -notmatch '^[A-Za-z0-9-]+$') {
    throw "Playwright run id may only contain letters, digits, and hyphens: $RunId"
  }

  if (-not (Test-Path -LiteralPath $LogDirectory)) {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
  }
  $resolvedLogDirectory = (Resolve-Path -LiteralPath $LogDirectory).Path
  [PSCustomObject]@{
    stdout = Join-Path $resolvedLogDirectory "$ServiceName-$RunId.stdout.log"
    stderr = Join-Path $resolvedLogDirectory "$ServiceName-$RunId.stderr.log"
  }
}

function New-PlaywrightRunMetadata {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Mode,
    [Parameter(Mandatory = $true)]
    [string]$RunId,
    [Parameter(Mandatory = $true)]
    [int]$WebPort,
    [AllowNull()]
    [Nullable[int]]$ApiPort,
    [Parameter(Mandatory = $true)]
    [string]$PlaywrightProject,
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath,
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$ServiceLogs
  )

  $apiPortValue = if ($null -eq $ApiPort) { $null } else { [int]$ApiPort }
  [ordered]@{
    schema_version = 1
    run_id = $RunId
    mode = $Mode
    status = "running"
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    finished_at = $null
    ports = [ordered]@{
      web = $WebPort
      api = $apiPortValue
    }
    playwright = [ordered]@{
      project = $PlaywrightProject
      exit_code = $null
    }
    service_logs = $ServiceLogs
    summary_path = [System.IO.Path]::GetFullPath($SummaryPath)
    error = $null
  }
}

function Complete-PlaywrightRunMetadata {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Metadata,
    [Parameter(Mandatory = $true)]
    [ValidateSet("success", "failed")]
    [string]$Status,
    [AllowNull()]
    [Nullable[int]]$ExitCode,
    [AllowNull()]
    [string]$ErrorMessage
  )

  $Metadata["status"] = $Status
  $Metadata["finished_at"] = (Get-Date).ToUniversalTime().ToString("o")
  $Metadata["error"] = if ([string]::IsNullOrWhiteSpace($ErrorMessage)) { $null } else { $ErrorMessage }
  if ($null -ne $ExitCode) {
    $Metadata["playwright"]["exit_code"] = [int]$ExitCode
  }
}

function Write-PlaywrightRunSummary {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Metadata
  )

  $summaryPath = [string]$Metadata["summary_path"]
  $summaryDirectory = Split-Path -Parent $summaryPath
  if (-not (Test-Path -LiteralPath $summaryDirectory)) {
    New-Item -ItemType Directory -Path $summaryDirectory -Force | Out-Null
  }
  $Metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding utf8
}

function Format-PlaywrightRunDiagnostics {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Metadata
  )

  $parts = [System.Collections.Generic.List[string]]::new()
  $parts.Add("web_port=$($Metadata['ports']['web'])")
  if ($null -ne $Metadata["ports"]["api"]) {
    $parts.Add("api_port=$($Metadata['ports']['api'])")
  }
  $parts.Add("summary=$($Metadata['summary_path'])")
  foreach ($serviceName in $Metadata["service_logs"].Keys) {
    $service = $Metadata["service_logs"][$serviceName]
    $parts.Add("$serviceName.stdout=$($service['stdout'])")
    $parts.Add("$serviceName.stderr=$($service['stderr'])")
  }
  return $parts -join "; "
}

function Start-PlaywrightServer {
  param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [Parameter(Mandatory = $true)]
    [string[]]$ArgumentList,
    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory,
    [hashtable]$Environment = @{},
    [Parameter(Mandatory = $true)]
    [string]$StandardOutputPath,
    [Parameter(Mandatory = $true)]
    [string]$StandardErrorPath
  )

  $standardOutputPath = [System.IO.Path]::GetFullPath($StandardOutputPath)
  $standardErrorPath = [System.IO.Path]::GetFullPath($StandardErrorPath)
  if ($standardOutputPath.Equals($standardErrorPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Playwright server stdout and stderr paths must be different: $standardOutputPath"
  }
  foreach ($path in @($standardOutputPath, $standardErrorPath)) {
    $parent = Split-Path -Parent $path
    if (-not (Test-Path -LiteralPath $parent)) {
      New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
  }

  $previousEnvironment = @{}
  foreach ($entry in $Environment.GetEnumerator()) {
    $previousEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, "Process")
    [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, "Process")
  }

  try {
    return Start-Process `
      -FilePath $FilePath `
      -ArgumentList $ArgumentList `
      -WorkingDirectory $WorkingDirectory `
      -WindowStyle Hidden `
      -RedirectStandardOutput $standardOutputPath `
      -RedirectStandardError $standardErrorPath `
      -PassThru
  }
  finally {
    foreach ($entry in $previousEnvironment.GetEnumerator()) {
      [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
  }
}

function Wait-PlaywrightPort {
  param(
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [Parameter(Mandatory = $true)]
    [System.Diagnostics.Process]$Process,
    [int]$TimeoutSeconds = 120
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  while ([DateTime]::UtcNow -lt $deadline) {
    if ($Process.HasExited) {
      throw "Server process $($Process.Id) exited before port $Port became ready."
    }

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
      $connect = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
      if ($connect.AsyncWaitHandle.WaitOne(500)) {
        $client.EndConnect($connect)
        return
      }
    }
    catch {
      # The server can reject connections while it is still starting.
    }
    finally {
      $client.Dispose()
    }
    Start-Sleep -Milliseconds 250
  }

  throw "Timed out waiting for port $Port after $TimeoutSeconds seconds."
}

function Stop-PlaywrightProcessTree {
  param(
    [AllowNull()]
    [System.Diagnostics.Process]$Process
  )

  if ($null -eq $Process) {
    return
  }

  $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Process.Id)" -ErrorAction SilentlyContinue)
  foreach ($child in $children) {
    try {
      Stop-PlaywrightProcessTree -Process (Get-Process -Id $child.ProcessId -ErrorAction Stop)
    }
    catch {
      # A child may exit between discovery and cleanup.
    }
  }

  Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
}
