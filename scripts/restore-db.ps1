param(
  [Parameter(Mandatory = $true)]
  [string]$BackupPath,
  [string]$Service = "postgres",
  [string]$Database = "fund_app",
  [string]$User = "fund_user",
  [string]$ConfirmRestore = "",
  [switch]$SkipRestoreForChecksumTest
)

$ErrorActionPreference = "Stop"

if ($ConfirmRestore -ne "RESTORE") {
  throw "Refusing to restore without explicit confirmation. Re-run with -ConfirmRestore RESTORE after verifying the backup path and target database."
}

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$resolvedBackupPath = (Resolve-Path -LiteralPath $BackupPath).Path

if (-not (Test-Path -LiteralPath $resolvedBackupPath -PathType Leaf)) {
  throw "Backup file not found: $resolvedBackupPath"
}

$backup = Get-Item -LiteralPath $resolvedBackupPath
if ($backup.Length -le 0) {
  throw "Backup file is empty: $resolvedBackupPath"
}

$checksumPath = "$resolvedBackupPath.sha256"
if (Test-Path -LiteralPath $checksumPath) {
  $expectedHash = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split "\s+")[0]
  $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedBackupPath).Hash
  if ($expectedHash -ne $actualHash) {
    throw "Backup checksum mismatch: $resolvedBackupPath"
  }
  Write-Host "Checksum verified: $checksumPath"
}
else {
  Write-Host "Checksum file not found, continuing without checksum verification: $checksumPath"
}

if ($SkipRestoreForChecksumTest) {
  Write-Host "Restore skipped for checksum test."
  return
}

function Read-BackupSql {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if ($Path.EndsWith(".gz", [System.StringComparison]::OrdinalIgnoreCase)) {
    $sourceStream = [System.IO.File]::OpenRead($Path)
    try {
      $gzipStream = [System.IO.Compression.GZipStream]::new($sourceStream, [System.IO.Compression.CompressionMode]::Decompress)
      try {
        $reader = [System.IO.StreamReader]::new($gzipStream, [System.Text.Encoding]::UTF8)
        try {
          return $reader.ReadToEnd()
        }
        finally {
          $reader.Dispose()
        }
      }
      finally {
        $gzipStream.Dispose()
      }
    }
    finally {
      $sourceStream.Dispose()
    }
  }

  return Get-Content -LiteralPath $Path -Raw
}

Push-Location -LiteralPath $workspaceRoot
try {
  Write-Host "Restoring $resolvedBackupPath into $Database on docker compose service '$Service'."
  Write-Host "Consider stopping api/web first: docker compose stop api web"
  Read-BackupSql -Path $resolvedBackupPath | docker compose exec -T $Service psql -U $User -d $Database
}
finally {
  Pop-Location
}

Write-Host "Restore completed. Run .\scripts\smoke-api.ps1 after starting the API."
