$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$outputDir = "output/contract-fixtures/release-notes"
$runName = "fixture"

& (Join-Path $PSScriptRoot "collect-artifacts.ps1") `
  -SourcePaths "packages/contracts/artifact-manifest.fixture.json" `
  -OutputDir $outputDir `
  -RunName $runName
if ($LASTEXITCODE -ne 0) {
  throw "Release notes fixture generation failed with exit code $LASTEXITCODE."
}

$releaseNotesPath = Join-Path $workspaceRoot "$outputDir/$runName/release-notes-snippet.md"
$releaseNotes = Get-Content -LiteralPath $releaseNotesPath -Raw -Encoding UTF8
$requiredSections = @(
  "# Release Notes",
  "## Release Metadata",
  "## Release Summary",
  "## Validation",
  "## Data, Migrations, and API Contracts",
  "## Compliance Review",
  "## Deployment and Rollback",
  "## Known Limitations and Deferred Work",
  "## Approval Checklist"
)
foreach ($section in $requiredSections) {
  if (-not $releaseNotes.Contains($section)) {
    throw "Release notes template is missing required section: $section"
  }
}
if (-not $releaseNotes.Contains("TODO")) {
  throw "Release notes template must retain explicit TODO markers for facts not available in the manifest."
}
if (-not $releaseNotes.Contains("Release decision: do not release until missing artifacts and alerts are resolved")) {
  throw "Release notes must not report green readiness when fixture alerts are present."
}

& (Join-Path $PSScriptRoot "collect-artifacts.ps1") `
  -SourcePaths "packages/contracts/smoke-report.fixture.json" `
  -OutputDir $outputDir `
  -RunName "green"
if ($LASTEXITCODE -ne 0) {
  throw "Green release notes fixture generation failed with exit code $LASTEXITCODE."
}
$greenReleaseNotesPath = Join-Path $workspaceRoot "$outputDir/green/release-notes-snippet.md"
$greenReleaseNotes = Get-Content -LiteralPath $greenReleaseNotesPath -Raw -Encoding UTF8
if (-not $greenReleaseNotes.Contains("Release readiness: READY")) {
  throw "Release notes must report READY when required artifacts and alerts are both OK."
}
if (-not $greenReleaseNotes.Contains("Release decision: validation evidence is currently green")) {
  throw "Release notes green fixture is missing the green release decision."
}

Write-Host "Release notes template contract check passed."
