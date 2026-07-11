$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$sourceRoots = @(
  Join-Path $workspaceRoot "apps\web\src",
  Join-Path $workspaceRoot "apps\api\app"
)

$allowedFiles = @(
  (Join-Path $workspaceRoot "apps\web\src\lib\compliance\constants.ts").ToLowerInvariant(),
  (Join-Path $workspaceRoot "apps\api\app\core\compliance.py").ToLowerInvariant()
)

$allowedPathFragments = @(
  "\tests\"
)

$phrases = @(
  "不构成投资建议",
  "历史表现不预示未来收益",
  "仅供分析学习",
  "不提供交易指令",
  "必须买入",
  "立即卖出",
  "保证赚钱"
)

$violations = @()

foreach ($root in $sourceRoots) {
  if (-not (Test-Path -LiteralPath $root)) {
    continue
  }

  $files = Get-ChildItem -LiteralPath $root -Recurse -File -Include *.ts,*.tsx,*.py
  foreach ($file in $files) {
    $fullName = $file.FullName
    $normalized = $fullName.ToLowerInvariant()
    if ($allowedFiles -contains $normalized) {
      continue
    }
    if ($allowedPathFragments | Where-Object { $normalized.Contains($_) }) {
      continue
    }

    $lines = Get-Content -LiteralPath $fullName
    for ($index = 0; $index -lt $lines.Count; $index++) {
      foreach ($phrase in $phrases) {
        if ($lines[$index].Contains($phrase)) {
          $relativePath = [System.IO.Path]::GetRelativePath($workspaceRoot, $fullName)
          $lineNumber = $index + 1
          $violations += "$relativePath`:$lineNumber contains centralized compliance phrase '$phrase'"
        }
      }
    }
  }
}

if ($violations.Count -gt 0) {
  Write-Error ("Compliance text check failed:`n" + ($violations -join "`n"))
  exit 1
}

Write-Host "Compliance text check passed."
