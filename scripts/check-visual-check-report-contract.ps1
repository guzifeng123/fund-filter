param(
  [string]$SchemaPath = "packages/contracts/visual-check-report.schema.json",
  [string]$FixturePath = "packages/contracts/visual-check-report.fixture.json",
  [string]$ReportPath
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

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

function Read-JsonFile {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $resolved = Resolve-WorkspacePath -Path $Path
  if (-not (Test-Path -LiteralPath $resolved)) {
    throw "JSON file not found: $resolved"
  }

  return Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json
}

function Invoke-JsonSchemaValidation {
  param(
    [Parameter(Mandatory = $true)]
    [string]$SchemaPath,
    [Parameter(Mandatory = $true)]
    [string[]]$DocumentPaths
  )

  $schemaRelative = [System.IO.Path]::GetRelativePath($workspaceRoot, (Resolve-WorkspacePath -Path $SchemaPath))
  $documentRelativePaths = @($DocumentPaths | ForEach-Object {
      [System.IO.Path]::GetRelativePath($workspaceRoot, (Resolve-WorkspacePath -Path $_))
    })
  node (Join-Path $workspaceRoot "scripts\validate-json-schema.js") $schemaRelative @documentRelativePaths
  if ($LASTEXITCODE -ne 0) {
    throw "Visual check report JSON Schema validation failed."
  }
}

function Assert-VisualReport {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Report,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  if ($Report.schema_version -ne 1) {
    throw "$Name must use schema_version 1."
  }

  $hasFailures = @($Report.failures).Count -gt 0 -or @($Report.chartFailures).Count -gt 0
  if ($Report.ok -eq $hasFailures) {
    throw "$Name ok must be true only when failures and chartFailures are empty."
  }

  $resultNames = @($Report.results | ForEach-Object { $_.name })
  foreach ($failure in @($Report.failures + $Report.chartFailures)) {
    if ($resultNames -notcontains $failure) {
      throw "$Name failure '$failure' must reference a result name."
    }
  }

  foreach ($result in @($Report.results)) {
    if ($result.bodyScrollWidth -gt $result.viewportWidth -or $result.documentScrollWidth -gt $result.viewportWidth -or @($result.overflowingElements).Count -gt 0) {
      if (@($Report.failures) -notcontains $result.name) {
        throw "$Name result '$($result.name)' has overflow but is not listed in failures."
      }
    }
  }

  foreach ($chartName in @("compare", "portfolio", "backtestResult")) {
    $result = @($Report.results | Where-Object { $_.name -eq $chartName } | Select-Object -First 1)
    if ($result.Count -eq 0) {
      continue
    }
    $hasNonBlankCanvas = @($result.canvases | Where-Object { $_.width -gt 0 -and $_.height -gt 0 }).Count -gt 0
    if (-not $hasNonBlankCanvas -and @($Report.chartFailures) -notcontains $chartName) {
      throw "$Name chart result '$chartName' has no nonblank canvas but is not listed in chartFailures."
    }
  }
}

$documentPaths = @($FixturePath)
if ($ReportPath) {
  $documentPaths += $ReportPath
}

Invoke-JsonSchemaValidation -SchemaPath $SchemaPath -DocumentPaths $documentPaths

$fixture = Read-JsonFile -Path $FixturePath
Assert-VisualReport -Report $fixture -Name "fixture"

if ($ReportPath) {
  $report = Read-JsonFile -Path $ReportPath
  Assert-VisualReport -Report $report -Name "report"
}

Write-Host "Visual check report contract check passed."
