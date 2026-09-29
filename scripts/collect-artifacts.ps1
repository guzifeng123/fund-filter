param(
  [ValidateSet("", "local-release")]
  [string]$Profile = "",
  [string[]]$SourcePaths = @("output/checks", "output/smoke", "output/playwright"),
  [string]$OutputDir = "output/release-artifacts",
  [string]$RunName = "",
  [string[]]$RequireArtifacts = @(),
  [switch]$FailOnAlerts,
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$startedAt = Get-Date
$stamp = $startedAt.ToString("yyyyMMdd-HHmmss")

if ($Profile -eq "local-release") {
  if (-not $PSBoundParameters.ContainsKey("SourcePaths")) {
    $SourcePaths = @("output/checks", "output/smoke", "output/playwright")
  }
  if (-not $PSBoundParameters.ContainsKey("RequireArtifacts")) {
    $RequireArtifacts = @("output/checks/openapi.diff", "output/smoke/*.json", "output/playwright/*.png")
  }
}

$resolvedOutputRoot = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
  $OutputDir
}
else {
  Join-Path $workspaceRoot $OutputDir
}
$runDirectoryName = if ($RunName) { $RunName } else { $stamp }
$resolvedRunDirectory = Join-Path $resolvedOutputRoot $runDirectoryName
$artifactExtensions = @(".json", ".diff", ".md", ".txt", ".log", ".png", ".jpg", ".jpeg", ".webp", ".zip", ".html")
$collectedArtifacts = @()
$skippedSources = @()
$missingRequiredArtifacts = @()

function Resolve-WorkspacePath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if ([System.IO.Path]::IsPathRooted($Path)) {
    return $Path
  }

  return Join-Path $workspaceRoot $Path
}

function Assert-InWorkspace {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $resolved = (Resolve-Path -LiteralPath $Path).Path
  if (-not ($resolved -eq $workspaceRoot -or $resolved.StartsWith("$workspaceRoot\", [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "Refusing to collect path outside workspace: $resolved"
  }
  return $resolved
}

function Get-OptionalCommandValue {
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

function Convert-ToRelativePath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  return [System.IO.Path]::GetRelativePath($workspaceRoot, $Path)
}

function Convert-ToArtifactPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  return $Path.Replace("\", "/")
}

function Test-ArtifactPattern {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Pattern,
    [Parameter(Mandatory = $true)]
    [string[]]$Artifacts
  )

  $normalizedPattern = Convert-ToArtifactPath -Path $Pattern
  foreach ($artifact in $Artifacts) {
    if ($artifact -like $normalizedPattern) {
      return $true
    }
  }

  return $false
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

function Get-ArtifactReportOk {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Artifact
  )

  if ($Artifact.source -notlike "*.json") {
    return $null
  }

  $artifactPath = Resolve-WorkspacePath -Path $Artifact.destination
  if (-not (Test-Path -LiteralPath $artifactPath)) {
    return $null
  }

  try {
    $json = Get-Content -LiteralPath $artifactPath -Raw | ConvertFrom-Json
    if ($null -ne $json.ok) {
      return [bool]$json.ok
    }
  }
  catch {
    return $null
  }

  return $null
}

function New-ArtifactAlerts {
  param(
    [object[]]$Artifacts,
    [string[]]$MissingRequiredArtifacts
  )

  $alerts = @()
  foreach ($missing in $MissingRequiredArtifacts) {
    $alerts += [ordered]@{
      type = "missing_required_artifact"
      severity = "error"
      message = "Missing required artifact: $missing"
      source = $missing
      destination = $null
    }
  }

  foreach ($artifact in $Artifacts) {
    $ok = Get-ArtifactReportOk -Artifact $artifact
    if ($ok -eq $false) {
      $source = Convert-ToArtifactPath -Path $artifact.source
      $alerts += [ordered]@{
        type = "failed_artifact_report"
        severity = "error"
        message = "Failed artifact report: $source"
        source = $source
        destination = Convert-ToArtifactPath -Path $artifact.destination
      }
    }
  }

  return @($alerts)
}

function Get-ArtifactCategory {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Source
  )

  $normalized = Convert-ToArtifactPath -Path $Source
  if ($normalized -like "*report-contracts*" -or $normalized -like "*contract-summary*") { return "contract" }
  if ($normalized -like "*smoke*") { return "smoke" }
  if ($normalized -like "*openapi*" -or $normalized -like "*.diff") { return "openapi" }
  if ($normalized -like "*backup*") { return "backup" }
  if ($normalized -like "*migration*") { return "migration" }
  if ($normalized -like "*cleanup*") { return "cleanup" }
  if ($normalized -like "*playwright*" -or $normalized -match "\.(png|jpg|jpeg|webp)$") { return "visual" }
  return "other"
}

function Get-FailedContractResults {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Manifest
  )

  $failedResults = @()
  foreach ($artifact in @($Manifest.artifacts)) {
    $source = Convert-ToArtifactPath -Path $artifact.source
    if ($source -notlike "*report-contracts-summary.json") {
      continue
    }

    $artifactPath = Resolve-WorkspacePath -Path $artifact.destination
    if (-not (Test-Path -LiteralPath $artifactPath)) {
      continue
    }

    try {
      $json = Get-Content -LiteralPath $artifactPath -Raw | ConvertFrom-Json
      foreach ($result in @($json.results | Where-Object { $_.ok -eq $false })) {
        $failedResults += [pscustomobject]@{
          Name = $result.name
          Script = $result.script
          Error = $result.error
          Source = $source
        }
      }
    }
    catch {
      $failedResults += [pscustomobject]@{
        Name = "Unreadable contract summary"
        Script = ""
        Error = $_.Exception.Message
        Source = $source
      }
    }
  }

  return @($failedResults)
}

function Write-ArtifactSummary {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Manifest,
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  function Get-ArtifactOk {
    param(
      [Parameter(Mandatory = $true)]
      [object]$Artifact
    )

    if ($Artifact.source -notlike "*.json") {
      return $null
    }

    $artifactPath = Resolve-WorkspacePath -Path $Artifact.destination
    if (-not (Test-Path -LiteralPath $artifactPath)) {
      return $null
    }

    try {
      $json = Get-Content -LiteralPath $artifactPath -Raw | ConvertFrom-Json
      if ($null -ne $json.ok) {
        return [bool]$json.ok
      }
    }
    catch {
      return $null
    }

    return $null
  }

  $lines = New-Object System.Collections.Generic.List[string]
  $releaseReady = [bool]$Manifest.manifest_ok -and [bool]$Manifest.alerts_ok
  $status = if ($releaseReady) { "READY" } else { "NOT READY" }
  $categoryRows = @($Manifest.artifacts | ForEach-Object {
    [pscustomobject]@{
      Category = Get-ArtifactCategory -Source $_.source
      Artifact = $_
      Ok = Get-ArtifactOk -Artifact $_
    }
  })
  $lines.Add("# Release Artifact Summary")
  $lines.Add("")
  $lines.Add("- Status: $status")
  $lines.Add("- Profile: $(Format-MarkdownCell $Manifest.profile)")
  $lines.Add("- Git commit: $(Format-MarkdownCell $Manifest.git_commit)")
  $lines.Add("- Started: $(Format-MarkdownCell $Manifest.started_at)")
  $lines.Add("- Finished: $(Format-MarkdownCell $Manifest.finished_at)")
  $lines.Add("- Duration ms: $(Format-MarkdownCell $Manifest.duration_ms)")
  $lines.Add("- Artifact count: $(Format-MarkdownCell $Manifest.artifact_count)")
  $lines.Add("- Required artifacts OK: $(Format-MarkdownCell $Manifest.manifest_ok)")
  $lines.Add("- Alerts OK: $(Format-MarkdownCell $Manifest.alerts_ok)")
  $lines.Add("- Fail on alerts: $(Format-MarkdownCell $Manifest.fail_on_alerts)")
  $lines.Add("")

  if (@($Manifest.missing_required_artifacts).Count -gt 0) {
    $lines.Add("## Missing Required Artifacts")
    $lines.Add("")
    foreach ($missing in $Manifest.missing_required_artifacts) {
      $lines.Add("- ``$(Format-MarkdownCell $missing)``")
    }
    $lines.Add("")
  }

  $lines.Add("## Category Summary")
  $lines.Add("")
  $lines.Add("| Category | Count | OK | Failed | Unknown |")
  $lines.Add("| --- | ---: | ---: | ---: | ---: |")
  foreach ($group in ($categoryRows | Group-Object Category | Sort-Object Name)) {
    $okCount = @($group.Group | Where-Object { $_.Ok -eq $true }).Count
    $failedCount = @($group.Group | Where-Object { $_.Ok -eq $false }).Count
    $unknownCount = @($group.Group | Where-Object { $null -eq $_.Ok }).Count
    $lines.Add("| $(Format-MarkdownCell $group.Name) | $($group.Count) | $okCount | $failedCount | $unknownCount |")
  }
  $lines.Add("")

  $lines.Add("## Artifacts")
  $lines.Add("")
  foreach ($group in ($categoryRows | Group-Object Category | Sort-Object Name)) {
    $lines.Add("### $(Format-MarkdownCell $group.Name)")
    $lines.Add("")
    $lines.Add("| Source | OK | Size bytes | SHA256 |")
    $lines.Add("| --- | --- | ---: | --- |")
    foreach ($row in $group.Group) {
      $artifact = $row.Artifact
      $source = Convert-ToArtifactPath -Path $artifact.source
      $okValue = if ($null -eq $row.Ok) { "n/a" } elseif ($row.Ok) { "true" } else { "false" }
      $lines.Add("| $(Format-MarkdownCell $source) | $okValue | $(Format-MarkdownCell $artifact.size_bytes) | ``$(Format-MarkdownCell $artifact.sha256)`` |")
    }
    $lines.Add("")
  }

  $lines | Set-Content -LiteralPath $Path -Encoding utf8
}

function Write-ReleaseNotesSnippet {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Manifest,
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  function Get-ArtifactOk {
    param(
      [Parameter(Mandatory = $true)]
      [object]$Artifact
    )

    if ($Artifact.source -notlike "*.json") {
      return $null
    }

    $artifactPath = Resolve-WorkspacePath -Path $Artifact.destination
    if (-not (Test-Path -LiteralPath $artifactPath)) {
      return $null
    }

    try {
      $json = Get-Content -LiteralPath $artifactPath -Raw | ConvertFrom-Json
      if ($null -ne $json.ok) {
        return [bool]$json.ok
      }
    }
    catch {
      return $null
    }

    return $null
  }

  $lines = New-Object System.Collections.Generic.List[string]
  $releaseNotesReady = [bool]$Manifest.manifest_ok -and [bool]$Manifest.alerts_ok
  $status = if ($releaseNotesReady) { "READY" } else { "NOT READY" }
  $categoryRows = @($Manifest.artifacts | ForEach-Object {
    [pscustomobject]@{
      Category = Get-ArtifactCategory -Source $_.source
      Artifact = $_
      Ok = Get-ArtifactOk -Artifact $_
    }
  })
  $keyArtifacts = @($Manifest.artifacts |
    Where-Object {
      $normalized = Convert-ToArtifactPath -Path $_.source
      $normalized -like "*smoke*" -or
        $normalized -like "*openapi*" -or
        $normalized -like "*.diff" -or
        $normalized -like "*report-contracts*" -or
        $normalized -like "*contract-summary*" -or
        $normalized -like "*playwright*" -or
        $normalized -like "*migration*" -or
        $normalized -like "*eastmoney-mirror*" -or
        $normalized -like "*backup*" -or
        $normalized -like "*cleanup*"
    } |
    Select-Object -First 8)
  $manifestRelativePath = Convert-ToArtifactPath -Path (Convert-ToRelativePath -Path (Join-Path $Manifest.output_directory "manifest.json"))
  $summaryRelativePath = Convert-ToArtifactPath -Path (Convert-ToRelativePath -Path (Join-Path $Manifest.output_directory "summary.md"))
  $releaseSnippetRelativePath = Convert-ToArtifactPath -Path (Convert-ToRelativePath -Path $Path)
  $testCommands = if ($Manifest.profile -eq "local-release") {
    @(
      "pwsh.exe -ExecutionPolicy Bypass -File scripts/check-all.ps1 -SkipBuild -CheckOpenApiDrift -OpenApiDiffPath output/checks/openapi.diff",
      "pwsh.exe -ExecutionPolicy Bypass -File scripts/smoke-api.ps1 -JsonReportPath output/smoke/api-smoke.json",
      "node scripts/playwright-mobile-visual-check.js"
    )
  }
  else {
    @(
      "pwsh.exe -ExecutionPolicy Bypass -File scripts/check-all.ps1 -SkipBuild -CheckOpenApiDrift",
      "pwsh.exe -ExecutionPolicy Bypass -File scripts/smoke-api.ps1"
    )
  }

  $lines.Add("# Release Notes")
  $lines.Add("")
  $lines.Add("## Release Metadata")
  $lines.Add("")
  $lines.Add("- Version: TODO")
  $lines.Add("- Release owner: TODO")
  $lines.Add("- Deployment target: TODO")
  $lines.Add("- Validation profile: $(Format-MarkdownCell $Manifest.profile)")
  $lines.Add("- Git commit: $(Format-MarkdownCell $Manifest.git_commit)")
  $lines.Add("- Artifact collection started: $(Format-MarkdownCell $Manifest.started_at)")
  $lines.Add("- Artifact collection finished: $(Format-MarkdownCell $Manifest.finished_at)")
  $lines.Add("")
  $lines.Add("## Release Summary")
  $lines.Add("")
  $lines.Add("- User-visible changes: TODO")
  $lines.Add("- Technical changes: TODO")
  $lines.Add("- Compatibility impact: TODO")
  $lines.Add("- Release decision: $(if ($releaseNotesReady) { 'validation evidence is currently green' } else { 'do not release until missing artifacts and alerts are resolved' })")
  $lines.Add("")
  $lines.Add("## Validation")
  $lines.Add("")
  $lines.Add("- Release readiness: $status")
  $lines.Add("- Artifact collection command completed: $(Format-MarkdownCell $Manifest.ok)")
  $lines.Add("- Git commit: $(Format-MarkdownCell $Manifest.git_commit)")
  $lines.Add("- Profile: $(Format-MarkdownCell $Manifest.profile)")
  $lines.Add("- Collected artifacts: $(Format-MarkdownCell $Manifest.artifact_count)")
  $lines.Add("- Required artifacts OK: $(Format-MarkdownCell $Manifest.manifest_ok)")
  $lines.Add("- Alerts OK: $(Format-MarkdownCell $Manifest.alerts_ok)")
  $lines.Add("- Fail on alerts: $(Format-MarkdownCell $Manifest.fail_on_alerts)")
  $lines.Add("- Manifest: ``$(Format-MarkdownCell $manifestRelativePath)``")
  $lines.Add("- Summary: ``$(Format-MarkdownCell $summaryRelativePath)``")
  $lines.Add("- Release notes snippet: ``$(Format-MarkdownCell $releaseSnippetRelativePath)``")
  $lines.Add("")

  $alerts = @($Manifest.alerts)
  $lines.Add("## Alerts")
  $lines.Add("")
  if (@($alerts).Count -eq 0) {
    $lines.Add("- None.")
  }
  else {
    foreach ($alert in $alerts) {
      $lines.Add("- $(Format-MarkdownCell $alert.message)")
    }
  }
  $lines.Add("")

  $failedContracts = Get-FailedContractResults -Manifest $Manifest
  $lines.Add("## Contract Failures")
  $lines.Add("")
  if (@($failedContracts).Count -eq 0) {
    $lines.Add("- None.")
  }
  else {
    foreach ($failure in $failedContracts) {
      $scriptText = if ($failure.Script) { " (``$(Format-MarkdownCell $failure.Script)``)" } else { "" }
      $lines.Add("- $(Format-MarkdownCell $failure.Name)${scriptText}: $(Format-MarkdownCell $failure.Error)")
    }
  }
  $lines.Add("")

  $lines.Add("## Test Commands")
  $lines.Add("")
  foreach ($command in $testCommands) {
    $lines.Add("- ``$(Format-MarkdownCell $command)``")
  }
  $lines.Add("")

  $lines.Add("## Check Results")
  $lines.Add("")
  if (@($categoryRows).Count -eq 0) {
    $lines.Add("- No artifacts were collected.")
  }
  else {
    foreach ($group in ($categoryRows | Group-Object Category | Sort-Object Name)) {
      $okCount = @($group.Group | Where-Object { $_.Ok -eq $true }).Count
      $failedCount = @($group.Group | Where-Object { $_.Ok -eq $false }).Count
      $unknownCount = @($group.Group | Where-Object { $null -eq $_.Ok }).Count
      $lines.Add("- $(Format-MarkdownCell $group.Name): $($group.Count) artifact(s), OK $okCount, failed $failedCount, unknown $unknownCount.")
    }
  }
  $lines.Add("")

  $lines.Add("## Key Artifacts")
  $lines.Add("")
  if (@($keyArtifacts).Count -eq 0) {
    $lines.Add("- No smoke, OpenAPI, contract, visual, or backup artifacts were collected.")
  }
  else {
    foreach ($artifact in $keyArtifacts) {
      $source = Convert-ToArtifactPath -Path $artifact.source
      $destination = Convert-ToArtifactPath -Path $artifact.destination
      $lines.Add("- ``$(Format-MarkdownCell $source)`` -> ``$(Format-MarkdownCell $destination)``")
    }
  }
  $lines.Add("")

  $lines.Add("## Data, Migrations, and API Contracts")
  $lines.Add("")
  $lines.Add("- Database migration required: TODO")
  $lines.Add("- Migration/rollback command: TODO")
  $lines.Add("- Seed or data synchronization required: TODO")
  $lines.Add("- OpenAPI diff reviewed: TODO")
  $lines.Add("- Data-source snapshot and field provenance reviewed: TODO")
  $lines.Add("")
  $lines.Add("## Compliance Review")
  $lines.Add("")
  $lines.Add("- [ ] Fund, portfolio, backtest, and AI surfaces show source and update time.")
  $lines.Add("- [ ] Historical-performance disclaimer is visible where required.")
  $lines.Add("- [ ] Risk-mismatch states do not enter recommendation or creation paths.")
  $lines.Add("- [ ] AI output contains data date, evidence, risk, and disclaimer.")
  $lines.Add("- [ ] No return prediction, trading instruction, or automatic execution was introduced.")
  $lines.Add("")
  $lines.Add("## Deployment and Rollback")
  $lines.Add("")
  $lines.Add("1. Confirm backup and checksum: TODO")
  $lines.Add("2. Apply migrations and start services: TODO")
  $lines.Add("3. Run API smoke and browser main path: TODO")
  $lines.Add("4. Rollback trigger and owner: TODO")
  $lines.Add("5. Restore command and post-restore smoke: TODO")
  $lines.Add("")
  $lines.Add("## Known Limitations and Deferred Work")
  $lines.Add("")
  $lines.Add("- TODO: list environment limitations, unavailable providers, stale fixtures, and deferred P1/P2 work.")
  $lines.Add("- TODO: record any unverified database, Docker, browser, or external-provider path.")
  $lines.Add("")
  $lines.Add("## Approval Checklist")
  $lines.Add("")
  $lines.Add("- [ ] Engineering review")
  $lines.Add("- [ ] Data-source/provenance review")
  $lines.Add("- [ ] Compliance copy review")
  $lines.Add("- [ ] Backup and rollback review")
  $lines.Add("- [ ] Final release approval")
  $lines.Add("")

  $lines | Set-Content -LiteralPath $Path -Encoding utf8
}

function Write-MarkdownArtifactIndex {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Manifest,
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseNotesSnippetPath
  )

  function Get-MarkdownCategory {
    param(
      [Parameter(Mandatory = $true)]
      [string]$ArtifactPath
    )

    $normalized = Convert-ToArtifactPath -Path $ArtifactPath
    if ($normalized -like "*release-notes*") { return "release notes" }
    if ($normalized -like "*report-contracts*" -or $normalized -like "*contract-summary*") { return "contract" }
    if ($normalized -like "*summary*") { return "summary" }
    if ($normalized -like "*cleanup*") { return "cleanup" }
    if ($normalized -like "*openapi*") { return "openapi" }
    if ($normalized -like "*smoke*") { return "smoke" }
    return "other"
  }

  function Convert-ToIndexLink {
    param(
      [Parameter(Mandatory = $true)]
      [string]$TargetPath
    )

    $indexDirectory = Split-Path -Parent $Path
    return [System.IO.Path]::GetRelativePath($indexDirectory, $TargetPath).Replace("\", "/")
  }

  function Get-MarkdownStatus {
    param(
      [Parameter(Mandatory = $true)]
      [string]$MarkdownPath
    )

    if (-not $MarkdownPath.EndsWith(".json.md", [System.StringComparison]::OrdinalIgnoreCase)) {
      return "unknown"
    }

    $jsonPath = $MarkdownPath.Substring(0, $MarkdownPath.Length - 3)
    if (-not (Test-Path -LiteralPath $jsonPath)) {
      return "unknown"
    }

    try {
      $json = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
      if ($null -eq $json.ok) {
        return "unknown"
      }
      if ([bool]$json.ok) {
        return "OK"
      }
      return "failed"
    }
    catch {
      return "unknown"
    }
  }

  function Get-MarkdownPreview {
    param(
      [Parameter(Mandatory = $true)]
      [string]$MarkdownPath
    )

    if (-not (Test-Path -LiteralPath $MarkdownPath)) {
      return ""
    }

    try {
      $lines = Get-Content -LiteralPath $MarkdownPath
      foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if (-not $trimmed) {
          continue
        }
        if ($trimmed.StartsWith("#")) {
          continue
        }
        if ($trimmed -match "^\|?\s*-{3,}") {
          continue
        }

        $preview = $trimmed
        if ($preview.Length -gt 140) {
          $preview = "$($preview.Substring(0, 137))..."
        }
        return $preview
      }
    }
    catch {
      return ""
    }

    return ""
  }

  $indexItems = @()
  $indexItems += [pscustomobject]@{
      Category = "summary"
      Label = "Release artifact summary"
      Link = Convert-ToIndexLink -TargetPath $SummaryPath
      Source = "generated"
      Status = "generated"
      Preview = Get-MarkdownPreview -MarkdownPath $SummaryPath
    }
  $indexItems += [pscustomobject]@{
      Category = "release notes"
      Label = "Release notes snippet"
      Link = Convert-ToIndexLink -TargetPath $ReleaseNotesSnippetPath
      Source = "generated"
      Status = "generated"
      Preview = Get-MarkdownPreview -MarkdownPath $ReleaseNotesSnippetPath
    }

  foreach ($artifact in $Manifest.artifacts) {
    if ($artifact.destination -notlike "*.md") {
      continue
    }

    $destinationPath = Resolve-WorkspacePath -Path $artifact.destination
    $source = Convert-ToArtifactPath -Path $artifact.source
    $indexItems += [pscustomobject]@{
        Category = Get-MarkdownCategory -ArtifactPath $artifact.source
        Label = $source
        Link = Convert-ToIndexLink -TargetPath $destinationPath
        Source = $source
        Status = Get-MarkdownStatus -MarkdownPath $destinationPath
        Preview = Get-MarkdownPreview -MarkdownPath $destinationPath
      }
  }

  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add("# Markdown Artifact Index")
  $lines.Add("")
  $releaseReady = [bool]$Manifest.manifest_ok -and [bool]$Manifest.alerts_ok
  $lines.Add("- Release readiness: $(if ($releaseReady) { 'READY' } else { 'NOT READY' })")
  $lines.Add("- Artifact collection command completed: $(Format-MarkdownCell $Manifest.ok)")
  $lines.Add("- Profile: $(Format-MarkdownCell $Manifest.profile)")
  $lines.Add("- Git commit: $(Format-MarkdownCell $Manifest.git_commit)")
  $lines.Add("- Markdown artifact count: $(@($indexItems).Count)")
  $lines.Add("- Required artifacts OK: $(Format-MarkdownCell $Manifest.manifest_ok)")
  $lines.Add("- Alerts OK: $(Format-MarkdownCell $Manifest.alerts_ok)")
  $lines.Add("- Fail on alerts: $(Format-MarkdownCell $Manifest.fail_on_alerts)")
  $lines.Add("")

  $alerts = @($Manifest.alerts)
  $lines.Add("## Alerts")
  $lines.Add("")
  if (@($alerts).Count -eq 0) {
    $lines.Add("- None.")
  }
  else {
    foreach ($alert in $alerts) {
      if ($alert.destination) {
        $link = Convert-ToIndexLink -TargetPath (Resolve-WorkspacePath -Path $alert.destination)
        $lines.Add("- [$(Format-MarkdownCell $alert.message)]($(Format-MarkdownCell $link))")
      }
      else {
        $lines.Add("- $(Format-MarkdownCell $alert.message)")
      }
    }
  }
  $lines.Add("")

  foreach ($group in ($indexItems | Group-Object Category | Sort-Object Name)) {
    $lines.Add("## $(Format-MarkdownCell $group.Name)")
    $lines.Add("")
    $lines.Add("| Markdown | Status | Preview | Source |")
    $lines.Add("| --- | --- | --- | --- |")
    foreach ($item in ($group.Group | Sort-Object Label)) {
      $lines.Add("| [$(Format-MarkdownCell $item.Label)]($(Format-MarkdownCell $item.Link)) | $(Format-MarkdownCell $item.Status) | $(Format-MarkdownCell $item.Preview) | $(Format-MarkdownCell $item.Source) |")
    }
    $lines.Add("")
  }

  $lines | Set-Content -LiteralPath $Path -Encoding utf8
}

if (-not $WhatIf) {
  New-Item -ItemType Directory -Force -Path $resolvedRunDirectory | Out-Null
}

foreach ($source in $SourcePaths) {
  $candidate = Resolve-WorkspacePath -Path $source
  if (-not (Test-Path -LiteralPath $candidate)) {
    $skippedSources += $candidate
    continue
  }

  $resolvedSource = Assert-InWorkspace -Path $candidate
  $sourceItem = Get-Item -LiteralPath $resolvedSource
  $files = if ($sourceItem.PSIsContainer) {
    Get-ChildItem -LiteralPath $resolvedSource -File -Recurse -Force |
      Where-Object { $artifactExtensions -contains $_.Extension.ToLowerInvariant() }
  }
  else {
    @($sourceItem)
  }

  foreach ($file in $files) {
    $relativeSource = Convert-ToRelativePath -Path $file.FullName
    $targetPath = Join-Path $resolvedRunDirectory $relativeSource
    $targetDirectory = Split-Path -Parent $targetPath

    if ($WhatIf) {
      Write-Host "[what-if] Collect $($file.FullName) -> $targetPath"
    }
    else {
      if ($targetDirectory -and -not (Test-Path -LiteralPath $targetDirectory)) {
        New-Item -ItemType Directory -Path $targetDirectory | Out-Null
      }
      Copy-Item -LiteralPath $file.FullName -Destination $targetPath -Force
      Write-Host "Collected $($file.FullName) -> $targetPath"
    }

    $collectedArtifacts += [ordered]@{
      source = $relativeSource
      destination = Convert-ToRelativePath -Path $targetPath
      size_bytes = $file.Length
      sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    }
  }
}

$finishedAt = Get-Date
$artifactSources = @($collectedArtifacts | ForEach-Object { Convert-ToArtifactPath -Path $_.source })
foreach ($requiredArtifact in $RequireArtifacts) {
  if (-not (Test-ArtifactPattern -Pattern $requiredArtifact -Artifacts $artifactSources)) {
    $missingRequiredArtifacts += $requiredArtifact
  }
}

$alerts = New-ArtifactAlerts -Artifacts $collectedArtifacts -MissingRequiredArtifacts $missingRequiredArtifacts
$manifestOk = @($missingRequiredArtifacts).Count -eq 0
$alertsOk = @($alerts).Count -eq 0
$ok = $manifestOk -and (-not $FailOnAlerts -or $alertsOk)
$manifest = [ordered]@{
  schema_version = 1
  ok = $ok
  manifest_ok = $manifestOk
  alerts_ok = $alertsOk
  fail_on_alerts = [bool]$FailOnAlerts
  what_if = [bool]$WhatIf
  started_at = $startedAt.ToUniversalTime().ToString("o")
  finished_at = $finishedAt.ToUniversalTime().ToString("o")
  duration_ms = [int][Math]::Round(($finishedAt - $startedAt).TotalMilliseconds)
  workspace_root = $workspaceRoot
  git_commit = Get-OptionalCommandValue { git -C $workspaceRoot rev-parse HEAD }
  output_directory = $resolvedRunDirectory
  profile = $Profile
  source_paths = @($SourcePaths)
  skipped_sources = @($skippedSources)
  required_artifacts = @($RequireArtifacts)
  missing_required_artifacts = @($missingRequiredArtifacts)
  alerts_schema_version = 1
  alert_count = @($alerts).Count
  alerts = @($alerts)
  artifact_count = @($collectedArtifacts).Count
  artifacts = @($collectedArtifacts)
}

if (-not $WhatIf) {
  $manifestPath = Join-Path $resolvedRunDirectory "manifest.json"
  $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding utf8
  Write-Host "Artifact manifest completed: $manifestPath"
  $alertsPath = Join-Path $resolvedRunDirectory "alerts.json"
  [ordered]@{
    schema_version = 1
    ok = $alertsOk
    manifest_ok = $manifest.manifest_ok
    alerts_ok = $alertsOk
    fail_on_alerts = [bool]$FailOnAlerts
    started_at = $manifest.started_at
    finished_at = $manifest.finished_at
    git_commit = $manifest.git_commit
    run_directory = $manifest.output_directory
    alert_count = @($alerts).Count
    alerts = @($alerts)
  } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $alertsPath -Encoding utf8
  Write-Host "Artifact alerts completed: $alertsPath"
  $summaryPath = Join-Path $resolvedRunDirectory "summary.md"
  Write-ArtifactSummary -Manifest $manifest -Path $summaryPath
  Write-Host "Artifact summary completed: $summaryPath"
  $releaseNotesSnippetPath = Join-Path $resolvedRunDirectory "release-notes-snippet.md"
  Write-ReleaseNotesSnippet -Manifest $manifest -Path $releaseNotesSnippetPath
  Write-Host "Release notes snippet completed: $releaseNotesSnippetPath"
  $markdownIndexPath = Join-Path $resolvedRunDirectory "markdown-index.md"
  Write-MarkdownArtifactIndex -Manifest $manifest -Path $markdownIndexPath -SummaryPath $summaryPath -ReleaseNotesSnippetPath $releaseNotesSnippetPath
  Write-Host "Markdown artifact index completed: $markdownIndexPath"
}

if (-not $ok) {
  if (-not $manifestOk) {
    throw "Missing required artifacts: $($missingRequiredArtifacts -join ', ')"
  }
  if ($FailOnAlerts -and -not $alertsOk) {
    $alertMessages = @($alerts | ForEach-Object { $_.message })
    throw "Artifact alerts present: $($alertMessages -join '; ')"
  }
  throw "Artifact collection failed."
}

Write-Host "Artifact collection completed. Count: $($manifest.artifact_count)"
