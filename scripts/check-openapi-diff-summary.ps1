$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$summaryPath = Join-Path $workspaceRoot "output\checks\openapi-diff-fixture.md"
$diffPath = Join-Path $workspaceRoot "output\checks\openapi-diff-fixture.diff"

"fixture diff" | Set-Content -LiteralPath $diffPath -Encoding utf8
node (Join-Path $PSScriptRoot "summarize-openapi-diff.js") `
  --before (Join-Path $workspaceRoot "packages\contracts\openapi-diff-before.fixture.json") `
  --after (Join-Path $workspaceRoot "packages\contracts\openapi-diff-after.fixture.json") `
  --diff $diffPath `
  --summary $summaryPath
if ($LASTEXITCODE -ne 0) {
  throw "OpenAPI diff summary generator failed with exit code $LASTEXITCODE."
}

$summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8
$requiredEvidence = @(
  "GET /items/{id} -> 404",
  "GET /items/{id} -> 422",
  "GET /items/{id} -> query mode",
  "GET /items/{id} -> path id",
  "Item.category",
  "Item.name",
  "Changed Schema Field Definitions",
  "Tightened Schema Constraints",
  "Item.id: type changed from",
  "Item.tags: minItems increased from 1 to 2",
  "Tightened schema constraint may reject existing requests: Item.tags: minItems increased from 1 to 2",
  "New required schema field may break existing requests: Item.category"
)
foreach ($evidence in $requiredEvidence) {
  if (-not $summary.Contains($evidence)) {
    throw "OpenAPI diff summary is missing expected evidence: $evidence"
  }
}

$fixtureOpenApiPath = Join-Path $workspaceRoot "packages\contracts\openapi-diff-after.fixture.json"
$approvalPath = Join-Path $workspaceRoot "output\checks\openapi-change-approval.fixture.json"
$baselineBlob = "1111111111111111111111111111111111111111"

function Get-CanonicalTextSha256 {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $content = [System.IO.File]::ReadAllText($Path)
  $normalized = $content.Replace("`r`n", "`n").Replace("`r", "`n")
  $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($normalized)
  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try {
    return [System.Convert]::ToHexString($sha256.ComputeHash($bytes)).ToLowerInvariant()
  }
  finally {
    $sha256.Dispose()
  }
}

$approval = [ordered]@{
  schema_version = 1
  contract_path = "packages/contracts/openapi.json"
  baseline = [ordered]@{
    git_ref = "HEAD"
    contract_blob = $baselineBlob
  }
  approved_export_sha256 = Get-CanonicalTextSha256 -Path $fixtureOpenApiPath
  approved_diff_sha256 = Get-CanonicalTextSha256 -Path $diffPath
  approved_summary_sha256 = Get-CanonicalTextSha256 -Path $summaryPath
  breaking_hints_reviewed = $true
  review = [ordered]@{
    reviewed_on = "2026-08-14"
    reviewer = "fixture-reviewer"
    reason = "Exercise the reviewed OpenAPI drift approval contract."
  }
  change_list = [ordered]@{
    schema_constraints_tightened = @("Item.tags: minItems increased from 1 to 2")
  }
}
$approval | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $approvalPath -Encoding utf8

& (Join-Path $PSScriptRoot "check-openapi-change-approval.ps1") `
  -OpenApiPath $fixtureOpenApiPath `
  -DiffPath $diffPath `
  -SummaryPath $summaryPath `
  -ApprovalPath $approvalPath `
  -BaselineContractBlob $baselineBlob

$crossPlatformDirectory = Join-Path $workspaceRoot "output\checks\openapi-cross-platform-fixture"
New-Item -ItemType Directory -Path $crossPlatformDirectory -Force | Out-Null
$crlfOpenApiPath = Join-Path $crossPlatformDirectory "openapi.json"
$crlfDiffPath = Join-Path $crossPlatformDirectory "openapi.diff"
$crlfSummaryPath = Join-Path $crossPlatformDirectory "openapi.diff.md"
foreach ($copy in @(
    @{ Source = $fixtureOpenApiPath; Destination = $crlfOpenApiPath },
    @{ Source = $diffPath; Destination = $crlfDiffPath },
    @{ Source = $summaryPath; Destination = $crlfSummaryPath }
  )) {
  $content = [System.IO.File]::ReadAllText($copy.Source).Replace("`r`n", "`n").Replace("`r", "`n").Replace("`n", "`r`n")
  [System.IO.File]::WriteAllText($copy.Destination, $content, [System.Text.UTF8Encoding]::new($false))
}
& (Join-Path $PSScriptRoot "check-openapi-change-approval.ps1") `
  -OpenApiPath $crlfOpenApiPath `
  -DiffPath $crlfDiffPath `
  -SummaryPath $crlfSummaryPath `
  -ApprovalPath $approvalPath `
  -BaselineContractBlob $baselineBlob

function Assert-ApprovalRejected {
  param(
    [Parameter(Mandatory = $true)]
    [System.Collections.IDictionary]$Manifest,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedMessage
  )

  $Manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $approvalPath -Encoding utf8
  try {
    & (Join-Path $PSScriptRoot "check-openapi-change-approval.ps1") `
      -OpenApiPath $fixtureOpenApiPath `
      -DiffPath $diffPath `
      -SummaryPath $summaryPath `
      -ApprovalPath $approvalPath `
      -BaselineContractBlob $baselineBlob
    throw "Expected OpenAPI approval rejection containing: $ExpectedMessage"
  }
  catch {
    if (-not $_.Exception.Message.Contains($ExpectedMessage)) {
      throw
    }
  }
}

function Copy-ApprovalManifest {
  return ($approval | ConvertTo-Json -Depth 8 | ConvertFrom-Json -AsHashtable)
}

$staleDiffApproval = Copy-ApprovalManifest
$staleDiffApproval.approved_diff_sha256 = "0" * 64
Assert-ApprovalRejected -Manifest $staleDiffApproval -ExpectedMessage "approved_diff_sha256"

$unreviewedBreakingApproval = Copy-ApprovalManifest
$unreviewedBreakingApproval.breaking_hints_reviewed = $false
Assert-ApprovalRejected -Manifest $unreviewedBreakingApproval -ExpectedMessage "breaking_hints_reviewed=true"

$staleBaselineApproval = Copy-ApprovalManifest
$staleBaselineApproval.baseline = [ordered]@{
  git_ref = "HEAD"
  contract_blob = "2222222222222222222222222222222222222222"
}
Assert-ApprovalRejected -Manifest $staleBaselineApproval -ExpectedMessage "baseline does not match"

Write-Host "OpenAPI diff summary and approval contract checks passed."
