param(
  [switch]$StartPostgres,
  [switch]$RunMigrations,
  [switch]$SeedSampleData,
  [switch]$RunSmoke
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $workspaceRoot

$failed = $false

function Write-Check {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Check,
    [switch]$WarningOnly
  )

  Write-Host "==> $Name"
  try {
    & $Check
    Write-Host "[ok] $Name"
  }
  catch {
    if ($WarningOnly) {
      Write-Host "[warn] $Name`: $($_.Exception.Message)"
    }
    else {
      $script:failed = $true
      Write-Host "[failed] $Name`: $($_.Exception.Message)"
    }
  }
}

function Assert-Command {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Command
  )

  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    throw "Command not found: $Command"
  }
}

Write-Check -Name "Workspace files" -Check {
  foreach ($path in @("package.json", ".env.example", "docker-compose.yml", "apps/api/pyproject.toml", "apps/web/package.json")) {
    if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot $path))) {
      throw "Missing required file: $path"
    }
  }
}

Write-Check -Name "Python" -Check {
  Assert-Command "python"
  python --version
}

Write-Check -Name "npm.cmd" -Check {
  Assert-Command "npm.cmd"
  npm.cmd --version
}

Write-Check -Name "Node dependencies" -Check {
  if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot "node_modules"))) {
    throw "node_modules not found. Run npm.cmd install."
  }
}

Write-Check -Name "API package import" -Check {
  python -c "import sys; sys.path.insert(0, r'apps/api'); import app.main; print('api import ok')"
}

Write-Check -Name "Docker CLI" -WarningOnly -Check {
  Assert-Command "docker"
  docker --version
  docker compose version
}

Write-Check -Name "Port hints" -WarningOnly -Check {
  $ports = @(3000, 8000, 5432)
  foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($connections) {
      Write-Host "Port $port is already in use."
    }
    else {
      Write-Host "Port $port is available."
    }
  }
}

Write-Check -Name "Environment file" -WarningOnly -Check {
  if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot ".env"))) {
    throw ".env not found. Copy .env.example to .env if local overrides are needed."
  }
}

if ($StartPostgres) {
  Write-Check -Name "Start PostgreSQL" -Check {
    Assert-Command "docker"
    docker compose up -d postgres
  }
}

if ($RunMigrations) {
  Write-Check -Name "Alembic migrations" -Check {
    .\scripts\db-migrate.ps1
  }
}

if ($SeedSampleData) {
  Write-Check -Name "Seed sample data twice" -Check {
    python -m app.jobs.seed_sample_data
    python -m app.jobs.seed_sample_data
  }
}

if ($RunSmoke) {
  Write-Check -Name "API smoke" -Check {
    .\scripts\smoke-api.ps1
  }
}

if ($failed) {
  throw "Environment check failed. Fix failed checks above before continuing."
}

Write-Host "Environment check completed."
