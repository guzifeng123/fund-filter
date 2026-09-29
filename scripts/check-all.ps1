param(
  [switch]$SkipBuild,
  [switch]$CheckOpenApiDrift,
  [string]$OpenApiDiffPath,
  [string]$OpenApiDiffSummaryPath,
  [string]$OpenApiApprovalPath = "packages/contracts/openapi-change-approval.json"
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $workspaceRoot

function Invoke-Step {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Command
  )

  Write-Host "==> $Name"
  & $Command
  Write-Host "[ok] $Name"
}

function Test-GitRepository {
  try {
    git rev-parse --is-inside-work-tree | Out-Null
    return $LASTEXITCODE -eq 0
  }
  catch {
    return $false
  }
}

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

function Write-Utf8LfLines {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [AllowEmptyCollection()]
    [string[]]$Lines
  )

  $content = if (@($Lines).Count -eq 0) { "" } else { [string]::Join("`n", @($Lines)) + "`n" }
  [System.IO.File]::WriteAllText($Path, $content, [System.Text.UTF8Encoding]::new($false))
}

function Get-OpenApiOperations {
  param(
    [AllowNull()]
    [object]$OpenApi
  )

  if ($null -eq $OpenApi -or $null -eq $OpenApi.paths) {
    return @()
  }

  $operations = New-Object System.Collections.Generic.List[string]
  $methods = @("get", "put", "post", "delete", "options", "head", "patch", "trace")
  foreach ($pathProperty in $OpenApi.paths.PSObject.Properties) {
    foreach ($methodProperty in $pathProperty.Value.PSObject.Properties) {
      $method = $methodProperty.Name.ToLowerInvariant()
      if ($methods -contains $method) {
        $operations.Add("$($method.ToUpperInvariant()) $($pathProperty.Name)")
      }
    }
  }

  return @($operations | Sort-Object -Unique)
}

function Get-OpenApiSchemas {
  param(
    [AllowNull()]
    [object]$OpenApi
  )

  if ($null -eq $OpenApi -or $null -eq $OpenApi.components -or $null -eq $OpenApi.components.schemas) {
    return @()
  }

  return @($OpenApi.components.schemas.PSObject.Properties.Name | Sort-Object -Unique)
}

function Compare-StringSet {
  param(
    [string[]]$Before,
    [string[]]$After
  )

  $beforeSet = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::Ordinal)
  foreach ($item in $Before) {
    [void]$beforeSet.Add($item)
  }

  $afterSet = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::Ordinal)
  foreach ($item in $After) {
    [void]$afterSet.Add($item)
  }

  $added = @($After | Where-Object { -not $beforeSet.Contains($_) } | Sort-Object)
  $removed = @($Before | Where-Object { -not $afterSet.Contains($_) } | Sort-Object)
  [pscustomobject]@{
    Added = $added
    Removed = $removed
  }
}

function Add-MarkdownList {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Lines,
    [Parameter(Mandatory = $true)]
    [string]$EmptyText,
    [string[]]$Items
  )

  if (@($Items).Count -eq 0) {
    $Lines.Add("- $EmptyText")
    return
  }

  foreach ($item in $Items) {
    $Lines.Add("- ``$item``")
  }
}

function Write-OpenApiDiffSummary {
  param(
    [AllowNull()]
    [object]$BeforeOpenApi,
    [Parameter(Mandatory = $true)]
    [object]$AfterOpenApi,
    [Parameter(Mandatory = $true)]
    [string]$DiffPath,
    [Parameter(Mandatory = $true)]
    [string]$SummaryPath
  )

  $beforeOperations = Get-OpenApiOperations -OpenApi $BeforeOpenApi
  $afterOperations = Get-OpenApiOperations -OpenApi $AfterOpenApi
  $operationDiff = Compare-StringSet -Before $beforeOperations -After $afterOperations

  $beforeSchemas = Get-OpenApiSchemas -OpenApi $BeforeOpenApi
  $afterSchemas = Get-OpenApiSchemas -OpenApi $AfterOpenApi
  $schemaDiff = Compare-StringSet -Before $beforeSchemas -After $afterSchemas

  $hasBreakingHints = @($operationDiff.Removed).Count -gt 0 -or @($schemaDiff.Removed).Count -gt 0
  $lines = New-Object System.Collections.Generic.List[string]
  $lines.Add("# OpenAPI Drift Summary")
  $lines.Add("")
  $lines.Add("- Raw diff: ``$([System.IO.Path]::GetRelativePath($workspaceRoot, $DiffPath).Replace('\', '/'))``")
  $lines.Add("- Operations before: $(@($beforeOperations).Count)")
  $lines.Add("- Operations after: $(@($afterOperations).Count)")
  $lines.Add("- Schemas before: $(@($beforeSchemas).Count)")
  $lines.Add("- Schemas after: $(@($afterSchemas).Count)")
  $lines.Add("- Potential breaking changes: $(if ($hasBreakingHints) { 'yes' } else { 'none detected' })")
  $lines.Add("")
  $lines.Add("## Added Operations")
  $lines.Add("")
  Add-MarkdownList -Lines $lines -EmptyText "None." -Items $operationDiff.Added
  $lines.Add("")
  $lines.Add("## Removed Operations")
  $lines.Add("")
  Add-MarkdownList -Lines $lines -EmptyText "None." -Items $operationDiff.Removed
  $lines.Add("")
  $lines.Add("## Added Schemas")
  $lines.Add("")
  Add-MarkdownList -Lines $lines -EmptyText "None." -Items $schemaDiff.Added
  $lines.Add("")
  $lines.Add("## Removed Schemas")
  $lines.Add("")
  Add-MarkdownList -Lines $lines -EmptyText "None." -Items $schemaDiff.Removed
  $lines.Add("")
  $lines.Add("## Breaking Change Hints")
  $lines.Add("")
  if ($hasBreakingHints) {
    foreach ($operation in $operationDiff.Removed) {
      $lines.Add("- Removed operation may break API clients: ``$operation``")
    }
    foreach ($schema in $schemaDiff.Removed) {
      $lines.Add("- Removed schema may break generated clients or docs: ``$schema``")
    }
  }
  else {
    $lines.Add("- No removed operations or schemas detected. Review the raw diff for field-level contract changes.")
  }

  $summaryDirectory = Split-Path -Parent $SummaryPath
  if ($summaryDirectory -and -not (Test-Path -LiteralPath $summaryDirectory)) {
    New-Item -ItemType Directory -Path $summaryDirectory | Out-Null
  }
  $lines | Set-Content -LiteralPath $SummaryPath -Encoding utf8
}

Invoke-Step -Name "Backend tests" -Command {
  python -m pytest apps/api/app/tests
}

Invoke-Step -Name "Backend Ruff" -Command {
  python -m ruff check apps/api/app
}

Invoke-Step -Name "Backend mypy strict" -Command {
  python -m mypy apps/api/app --strict
}

Invoke-Step -Name "Compliance text" -Command {
  .\scripts\check-compliance-text.ps1
}

Invoke-Step -Name "JSON report contracts" -Command {
  .\scripts\check-report-contracts.ps1 -JsonReportPath output/checks/report-contracts-summary.json
}

Invoke-Step -Name "OpenAPI diff summary contract" -Command {
  .\scripts\check-openapi-diff-summary.ps1
}

Invoke-Step -Name "Release notes template contract" -Command {
  .\scripts\check-release-notes-template.ps1
}

Invoke-Step -Name "Documentation contracts" -Command {
  python .\scripts\check_doc_contracts.py --json-report-path output/checks/doc-contracts.json
}

Invoke-Step -Name "Web lint" -Command {
  npm.cmd run lint:web
}

Invoke-Step -Name "Web TypeScript (including tests)" -Command {
  npm.cmd --workspace apps/web exec tsc -- --noEmit
}

Invoke-Step -Name "Web tests" -Command {
  npm.cmd run test:web
}

if (-not $SkipBuild) {
  Invoke-Step -Name "Web build" -Command {
    npm.cmd run build:web
  }
}

Invoke-Step -Name "OpenAPI export" -Command {
  $openApiPath = Join-Path $workspaceRoot "packages\contracts\openapi.json"
  $beforeHash = if (Test-Path -LiteralPath $openApiPath) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $openApiPath).Hash
  }
  else {
    $null
  }

  npm.cmd run export:openapi

  .\scripts\check-openapi-response-schemas.ps1

  if ($CheckOpenApiDrift) {
    if (Test-GitRepository) {
      $diff = git diff -- packages/contracts/openapi.json
      if ($OpenApiDiffPath) {
        $diffPath = Resolve-WorkspacePath -Path $OpenApiDiffPath
        $diffDirectory = Split-Path -Parent $diffPath
        if ($diffDirectory -and -not (Test-Path -LiteralPath $diffDirectory)) {
          New-Item -ItemType Directory -Path $diffDirectory | Out-Null
        }
        Write-Utf8LfLines -Path $diffPath -Lines @($diff)

        $summaryPath = if ($OpenApiDiffSummaryPath) {
          Resolve-WorkspacePath -Path $OpenApiDiffSummaryPath
        }
        else {
          "$diffPath.md"
        }
        $beforeOpenApiPath = "$diffPath.before.json"
        $diffDisplayPath = [System.IO.Path]::GetRelativePath($workspaceRoot, $diffPath).Replace('\', '/')
        git show HEAD:packages/contracts/openapi.json | Set-Content -LiteralPath $beforeOpenApiPath -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
          "" | Set-Content -LiteralPath $beforeOpenApiPath -Encoding utf8
        }
        node .\scripts\summarize-openapi-diff.js `
          --before $beforeOpenApiPath `
          --after $openApiPath `
          --diff $diffDisplayPath `
          --summary $summaryPath
        if ($LASTEXITCODE -ne 0) {
          throw "OpenAPI diff summary generator failed with exit code $LASTEXITCODE."
        }
        Write-Host "OpenAPI diff summary completed: $summaryPath"
      }

      $openApiDiff = [string]::Join("`n", @($diff))
      if (-not $OpenApiDiffPath) {
        $diffPath = Join-Path $workspaceRoot "output\checks\openapi.diff"
        $diffDirectory = Split-Path -Parent $diffPath
        if ($diffDirectory -and -not (Test-Path -LiteralPath $diffDirectory)) {
          New-Item -ItemType Directory -Path $diffDirectory | Out-Null
        }
        Write-Utf8LfLines -Path $diffPath -Lines @($diff)
        $summaryPath = if ($OpenApiDiffSummaryPath) {
          Resolve-WorkspacePath -Path $OpenApiDiffSummaryPath
        }
        else {
          "$diffPath.md"
        }
        $beforeOpenApiPath = "$diffPath.before.json"
        $diffDisplayPath = [System.IO.Path]::GetRelativePath($workspaceRoot, $diffPath).Replace('\', '/')
        git show HEAD:packages/contracts/openapi.json | Set-Content -LiteralPath $beforeOpenApiPath -Encoding utf8
        node .\scripts\summarize-openapi-diff.js `
          --before $beforeOpenApiPath `
          --after $openApiPath `
          --diff $diffDisplayPath `
          --summary $summaryPath
        if ($LASTEXITCODE -ne 0) {
          throw "OpenAPI diff summary generator failed with exit code $LASTEXITCODE."
        }
      }

      if (-not [string]::IsNullOrWhiteSpace($openApiDiff)) {
        $baselineContractBlob = (git rev-parse HEAD:packages/contracts/openapi.json).Trim().ToLowerInvariant()
        if ($LASTEXITCODE -ne 0) {
          throw "Unable to resolve HEAD:packages/contracts/openapi.json for OpenAPI approval."
        }
        .\scripts\check-openapi-change-approval.ps1 `
          -OpenApiPath $openApiPath `
          -DiffPath $diffPath `
          -SummaryPath $summaryPath `
          -ApprovalPath (Resolve-WorkspacePath -Path $OpenApiApprovalPath) `
          -BaselineContractBlob $baselineContractBlob
      }
      else {
        Write-Host "OpenAPI contract matches the Git baseline; no drift approval is required."
      }
    }
    else {
      $afterHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $openApiPath).Hash
      if ($beforeHash -ne $afterHash) {
        throw "OpenAPI contract changed after export. Review packages/contracts/openapi.json and commit the updated contract if expected."
      }
    }
  }
}

Write-Host "All checks completed."
