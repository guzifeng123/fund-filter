param(
  [Parameter(Mandatory = $true)]
  [string]$BaseRef,
  [string]$ApprovalPath = "packages/contracts/openapi-change-approval.json",
  [string]$OutputDirectory = "output/checks/openapi-approval",
  [string]$Reviewers = ""
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $workspaceRoot

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

function Invoke-GitText {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments,
    [Parameter(Mandatory = $true)]
    [string]$FailureMessage
  )

  $result = & git @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw $FailureMessage
  }
  return [string]::Join([Environment]::NewLine, @($result))
}

function Write-Utf8LfText {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [AllowEmptyString()]
    [string]$Content
  )

  $normalized = $Content.Replace("`r`n", "`n").Replace("`r", "`n")
  if ($normalized -and -not $normalized.EndsWith("`n")) {
    $normalized += "`n"
  }
  [System.IO.File]::WriteAllText($Path, $normalized, [System.Text.UTF8Encoding]::new($false))
}

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

$baseCommit = (Invoke-GitText -Arguments @("rev-parse", "$BaseRef^{commit}") -FailureMessage "Unable to resolve OpenAPI CI base ref: $BaseRef").Trim()
$headCommit = (Invoke-GitText -Arguments @("rev-parse", "HEAD^{commit}") -FailureMessage "Unable to resolve HEAD for OpenAPI CI approval.").Trim()
$baselineContractBlob = (Invoke-GitText -Arguments @("rev-parse", "${baseCommit}:packages/contracts/openapi.json") -FailureMessage "The OpenAPI contract does not exist at CI base ref $BaseRef.").Trim().ToLowerInvariant()
$openApiPath = Join-Path $workspaceRoot "packages\contracts\openapi.json"
$resolvedApprovalPath = Resolve-WorkspacePath -Path $ApprovalPath
$resolvedOutputDirectory = Resolve-WorkspacePath -Path $OutputDirectory
New-Item -ItemType Directory -Path $resolvedOutputDirectory -Force | Out-Null

$beforePath = Join-Path $resolvedOutputDirectory "openapi.before.json"
$diffPath = Join-Path $resolvedOutputDirectory "openapi.diff"
$summaryPath = Join-Path $resolvedOutputDirectory "openapi.diff.md"
$contractCopyPath = Join-Path $resolvedOutputDirectory "openapi.json"
$approvalCopyPath = Join-Path $resolvedOutputDirectory "openapi-change-approval.json"
$contextPath = Join-Path $resolvedOutputDirectory "ci-context.json"

$beforeContract = Invoke-GitText -Arguments @("show", "${baseCommit}:packages/contracts/openapi.json") -FailureMessage "Unable to read the OpenAPI contract from CI base ref $BaseRef."
Write-Utf8LfText -Path $beforePath -Content $beforeContract
$diff = Invoke-GitText -Arguments @("diff", "--no-ext-diff", "--binary", $baseCommit, "--", "packages/contracts/openapi.json") -FailureMessage "Unable to calculate OpenAPI CI drift."
Write-Utf8LfText -Path $diffPath -Content $diff

if ([string]::IsNullOrWhiteSpace($diff)) {
  Write-Host "OpenAPI contract matches the CI base; no approval evidence is required."
  if ($env:GITHUB_OUTPUT) {
    "has_drift=false" | Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8
  }
  exit 0
}

$diffDisplayPath = "output/checks/openapi.diff"
node .\scripts\summarize-openapi-diff.js `
  --before $beforePath `
  --after $openApiPath `
  --diff $diffDisplayPath `
  --summary $summaryPath
if ($LASTEXITCODE -ne 0) {
  throw "OpenAPI CI diff summary generator failed with exit code $LASTEXITCODE."
}

.\scripts\check-openapi-change-approval.ps1 `
  -OpenApiPath $openApiPath `
  -DiffPath $diffPath `
  -SummaryPath $summaryPath `
  -ApprovalPath $resolvedApprovalPath `
  -BaselineContractBlob $baselineContractBlob

Copy-Item -LiteralPath $openApiPath -Destination $contractCopyPath -Force
Copy-Item -LiteralPath $resolvedApprovalPath -Destination $approvalCopyPath -Force
$reviewerList = @(
  $Reviewers.Split(',', [System.StringSplitOptions]::RemoveEmptyEntries) |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ } |
    Sort-Object -Unique
)
$workingTreeContractChanged = -not [string]::IsNullOrWhiteSpace(
  (Invoke-GitText -Arguments @("diff", "--no-ext-diff", "HEAD", "--", "packages/contracts/openapi.json") -FailureMessage "Unable to inspect the exported OpenAPI working tree state.")
)
$context = [ordered]@{
  schema_version = 1
  status = "approved"
  repository = $env:GITHUB_REPOSITORY
  event_name = $env:GITHUB_EVENT_NAME
  workflow = $env:GITHUB_WORKFLOW
  workflow_ref = $env:GITHUB_WORKFLOW_REF
  run_id = $env:GITHUB_RUN_ID
  run_attempt = $env:GITHUB_RUN_ATTEMPT
  actor = $env:GITHUB_ACTOR
  base_ref = $BaseRef
  base_commit = $baseCommit
  head_commit = $headCommit
  working_tree_contract_changed = $workingTreeContractChanged
  approved_reviewers = $reviewerList
  baseline_contract_blob = $baselineContractBlob
  openapi_sha256 = Get-CanonicalTextSha256 -Path $openApiPath
  diff_sha256 = Get-CanonicalTextSha256 -Path $diffPath
  summary_sha256 = Get-CanonicalTextSha256 -Path $summaryPath
  generated_at = [datetime]::UtcNow.ToString("o")
}
$context | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $contextPath -Encoding utf8

if ($env:GITHUB_OUTPUT) {
  "has_drift=true" | Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8
  "evidence_directory=$($resolvedOutputDirectory.Replace('\', '/'))" | Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8
}
Write-Host "OpenAPI CI approval evidence completed: $resolvedOutputDirectory"
