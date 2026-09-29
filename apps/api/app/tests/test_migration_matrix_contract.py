import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_PATH = WORKSPACE_ROOT / ".github" / "workflows" / "migration-matrix.yml"
VERIFIER_PATH = WORKSPACE_ROOT / "scripts" / "verify_migration_matrix.py"
POWERSHELL_WRAPPER_PATH = WORKSPACE_ROOT / "scripts" / "verify-migration-matrix.ps1"


def test_sqlite_migration_matrix_entrypoint_verifies_full_lifecycle() -> None:
    result = subprocess.run(
        [sys.executable, str(VERIFIER_PATH), "--dialect", "sqlite"],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert "Running: alembic upgrade head" in result.stdout
    assert "Running: alembic downgrade base" in result.stdout
    assert "dialect=sqlite" in result.stdout


def test_migration_matrix_entrypoint_refuses_nonempty_database(tmp_path: Path) -> None:
    database_path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE user_data (id INTEGER PRIMARY KEY)")

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER_PATH),
            "--dialect",
            "sqlite",
            "--database-url",
            f"sqlite:///{database_path.as_posix()}",
        ],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "requires an empty disposable database" in result.stderr
    with sqlite3.connect(database_path) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_data'"
        ).fetchone()
    assert table_exists == (1,)


def test_migration_workflow_contract() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    assert isinstance(workflow, dict)
    assert workflow["permissions"] == {"contents": "read"}

    job = workflow["jobs"]["migrations"]
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["database"] == ["sqlite", "postgresql"]
    assert job["timeout-minutes"] == 15

    service = job["services"]["postgres"]
    assert service["image"] == "pgvector/pgvector:0.8.1-pg17"
    assert service["env"]["POSTGRES_USER"] == "fund_migration_admin"
    health_options = service["options"]
    for required_option in (
        "pg_isready",
        "--health-interval",
        "--health-timeout",
        "--health-retries",
    ):
        assert required_option in health_options

    step_by_name = {step["name"]: step for step in job["steps"]}
    privilege_step = step_by_name[
        "Install pgvector and provision a non-owner migration role"
    ]
    privilege_command = privilege_step["run"]
    for required_fragment in (
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE ROLE fund_migration_ci",
        "GRANT CONNECT ON DATABASE fund_migration_ci",
        "GRANT USAGE, CREATE ON SCHEMA public",
        "NOSUPERUSER",
        "NOCREATEDB",
        "NOCREATEROLE",
        "NOREPLICATION",
        "NOBYPASSRLS",
    ):
        assert required_fragment in privilege_command

    sqlite_command = step_by_name["Verify SQLite migration lifecycle"]["run"]
    postgres_command = step_by_name["Verify PostgreSQL and pgvector migration lifecycle"]["run"]
    assert "scripts/verify_migration_matrix.py --dialect sqlite" in sqlite_command
    assert "scripts/verify_migration_matrix.py" in postgres_command
    assert "--dialect postgresql" in postgres_command
    assert "--require-unprivileged-role" in postgres_command


def test_powershell_wrapper_delegates_to_shared_verifier() -> None:
    wrapper = POWERSHELL_WRAPPER_PATH.read_text(encoding="utf-8")
    assert "verify_migration_matrix.py" in wrapper
    assert 'ValidateSet("sqlite", "postgresql")' in wrapper
    assert "--require-unprivileged-role" in wrapper
