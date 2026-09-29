param(
  [Parameter(Mandatory = $true)]
  [string]$OpenApiPath,
  [Parameter(Mandatory = $true)]
  [string]$DiffPath,
  [Parameter(Mandatory = $true)]
  [string]$SummaryPath,
  [Parameter(Mandatory = $true)]
  [string]$ApprovalPath,
  [Parameter(Mandatory = $true)]
  [string]$BaselineContractBlob
)

$ErrorActionPreference = "Stop"

function Get-CanonicalTextSha256 {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Required OpenAPI approval input does not exist: $Path"
  }
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

function Get-RequiredText {
  param(
    [AllowNull()]
    [object]$Value,
    [Parameter(Mandatory = $true)]
    [string]$FieldName
  )

  $text = [string]$Value
  if ([string]::IsNullOrWhiteSpace($text)) {
    throw "OpenAPI approval field '$FieldName' must be a non-empty string."
  }
  return $text.Trim()
}

if (-not (Test-Path -LiteralPath $ApprovalPath -PathType Leaf)) {
  throw "OpenAPI contract drift is not approved. Create and review $ApprovalPath."
}

try {
  $approval = Get-Content -LiteralPath $ApprovalPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
catch {
  throw "OpenAPI approval manifest is not valid JSON: $($_.Exception.Message)"
}

if ($approval.schema_version -ne 1) {
  throw "OpenAPI approval schema_version must be 1."
}
if ([string]$approval.contract_path -ne "packages/contracts/openapi.json") {
  throw "OpenAPI approval contract_path must be packages/contracts/openapi.json."
}

$expectedBaselineBlob = (Get-RequiredText -Value $BaselineContractBlob -FieldName "actual baseline contract blob").ToLowerInvariant()
$approvedBaselineBlob = (Get-RequiredText -Value $approval.baseline.contract_blob -FieldName "baseline.contract_blob").ToLowerInvariant()
[void](Get-RequiredText -Value $approval.baseline.git_ref -FieldName "baseline.git_ref")
if ($approvedBaselineBlob -ne $expectedBaselineBlob) {
  throw "OpenAPI approval baseline does not match the reviewed packages/contracts/openapi.json base."
}
if ($approvedBaselineBlob -notmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') {
  throw "OpenAPI approval baseline.contract_blob must be a Git object ID."
}

$hashChecks = @(
  [pscustomobject]@{
    Field = "approved_export_sha256"
    Expected = Get-RequiredText -Value $approval.approved_export_sha256 -FieldName "approved_export_sha256"
    Actual = Get-CanonicalTextSha256 -Path $OpenApiPath
    Failure = "OpenAPI export SHA does not match approved_export_sha256. Re-review the contract change."
  },
  [pscustomobject]@{
    Field = "approved_diff_sha256"
    Expected = Get-RequiredText -Value $approval.approved_diff_sha256 -FieldName "approved_diff_sha256"
    Actual = Get-CanonicalTextSha256 -Path $DiffPath
    Failure = "OpenAPI diff SHA does not match approved_diff_sha256. The approved change set is incomplete or stale."
  },
  [pscustomobject]@{
    Field = "approved_summary_sha256"
    Expected = Get-RequiredText -Value $approval.approved_summary_sha256 -FieldName "approved_summary_sha256"
    Actual = Get-CanonicalTextSha256 -Path $SummaryPath
    Failure = "OpenAPI summary SHA does not match approved_summary_sha256. Re-review the generated change list."
  }
)
foreach ($hashCheck in $hashChecks) {
  $expectedHash = ([string]$hashCheck.Expected).ToLowerInvariant()
  if ($expectedHash -notmatch '^[0-9a-f]{64}$') {
    throw "OpenAPI approval field '$($hashCheck.Field)' must be a SHA-256 digest."
  }
  if ([string]$hashCheck.Actual -ne $expectedHash) {
    throw $hashCheck.Failure
  }
}

if ($approval.breaking_hints_reviewed -ne $true) {
  throw "OpenAPI approval must set breaking_hints_reviewed=true."
}

[void](Get-RequiredText -Value $approval.review.reviewer -FieldName "review.reviewer")
[void](Get-RequiredText -Value $approval.review.reason -FieldName "review.reason")
$reviewedOn = Get-RequiredText -Value $approval.review.reviewed_on -FieldName "review.reviewed_on"
$parsedReviewDate = [datetime]::MinValue
if (-not [datetime]::TryParseExact(
    $reviewedOn,
    "yyyy-MM-dd",
    [System.Globalization.CultureInfo]::InvariantCulture,
    [System.Globalization.DateTimeStyles]::None,
    [ref]$parsedReviewDate
  )) {
  throw "OpenAPI approval review.reviewed_on must use yyyy-MM-dd."
}
if ($null -eq $approval.change_list -or @($approval.change_list.PSObject.Properties).Count -eq 0) {
  throw "OpenAPI approval change_list must contain the reviewed contract changes."
}

Write-Host "OpenAPI contract drift matches the reviewed approval manifest."
