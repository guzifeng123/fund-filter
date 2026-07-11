param(
  [string]$OutputDir = "backups",
  [string]$Service = "postgres",
  [string]$Database = "fund_app",
  [string]$User = "fund_user",
  [int]$RetentionCount = 0,
  [switch]$Compress,
  [switch]$SkipDumpForRetentionTest
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
  $OutputDir
}
else {
  Join-Path $workspaceRoot $OutputDir
}

New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

function Invoke-BackupRetention {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Directory,
    [Parameter(Mandatory = $true)]
    [string]$DatabaseName,
    [Parameter(Mandatory = $true)]
    [int]$KeepCount
  )

  if ($KeepCount -le 0) {
    return
  }

  $backups = Get-ChildItem -LiteralPath $Directory -File |
    Where-Object { $_.Name -like "$DatabaseName-*.sql" -or $_.Name -like "$DatabaseName-*.sql.gz" } |
    Sort-Object LastWriteTimeUtc -Descending

  $toRemove = $backups | Select-Object -Skip $KeepCount
  foreach ($item in $toRemove) {
    $checksumPath = "$($item.FullName).sha256"
    Remove-Item -LiteralPath $item.FullName -Force
    Write-Host "Removed old backup: $($item.FullName)"
    if (Test-Path -LiteralPath $checksumPath) {
      Remove-Item -LiteralPath $checksumPath -Force
      Write-Host "Removed old checksum: $checksumPath"
    }
  }
}

function Compress-BackupFile {
  param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,
    [Parameter(Mandatory = $true)]
    [string]$DestinationPath
  )

  $sourceStream = [System.IO.File]::OpenRead($SourcePath)
  try {
    $destinationStream = [System.IO.File]::Create($DestinationPath)
    try {
      $gzipStream = [System.IO.Compression.GZipStream]::new($destinationStream, [System.IO.Compression.CompressionLevel]::Optimal)
      try {
        $sourceStream.CopyTo($gzipStream)
      }
      finally {
        $gzipStream.Dispose()
      }
    }
    finally {
      $destinationStream.Dispose()
    }
  }
  finally {
    $sourceStream.Dispose()
  }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path $resolvedOutputDir "$Database-$stamp.sql"

if ($SkipDumpForRetentionTest) {
  Set-Content -LiteralPath $backupPath -Value "-- retention test backup" -Encoding utf8
}
else {
  Push-Location -LiteralPath $workspaceRoot
  try {
    Write-Host "Creating database backup: $backupPath"
    docker compose exec -T $Service pg_dump -U $User -d $Database | Set-Content -LiteralPath $backupPath -Encoding utf8
  }
  finally {
    Pop-Location
  }
}

if ($Compress) {
  $compressedBackupPath = "$backupPath.gz"
  Compress-BackupFile -SourcePath $backupPath -DestinationPath $compressedBackupPath
  Remove-Item -LiteralPath $backupPath -Force
  $backupPath = $compressedBackupPath
  Write-Host "Compressed backup completed: $backupPath"
}

$backup = Get-Item -LiteralPath $backupPath
if ($backup.Length -le 0) {
  throw "Backup file is empty: $backupPath"
}

Write-Host "Backup completed: $($backup.FullName)"
Write-Host "Size: $($backup.Length) bytes"

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $backup.FullName
$checksumPath = "$($backup.FullName).sha256"
"$($hash.Hash)  $($backup.Name)" | Set-Content -LiteralPath $checksumPath -Encoding ascii
Write-Host "Checksum completed: $checksumPath"

Invoke-BackupRetention -Directory $resolvedOutputDir -DatabaseName $Database -KeepCount $RetentionCount
