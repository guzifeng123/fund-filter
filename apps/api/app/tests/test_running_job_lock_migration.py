import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text


API_ROOT = Path(__file__).resolve().parents[2]


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=API_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _decode_details(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        assert isinstance(decoded, dict)
        return decoded
    raise AssertionError(f"unexpected details payload: {value!r}")


def test_running_job_lock_migration_marks_legacy_running_jobs_failed(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'running-job-lock.db').as_posix()}"
    before = run_alembic(database_url, "upgrade", "0005_add_document_chunk_vector_index")
    assert before.returncode == 0, before.stderr

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO job_runs
                    (name, status, started_at, finished_at, details)
                VALUES
                    (
                        'sync_all', 'running', '2026-07-13 00:00:00',
                        NULL, '{"preexisting": true}'
                    )
                """
            )
        )

    upgraded = run_alembic(database_url, "upgrade", "0006_add_running_job_lock")
    assert upgraded.returncode == 0, upgraded.stderr

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, finished_at, details FROM job_runs WHERE name = 'sync_all'")
        ).one()
        assert row.status == "failed"
        assert row.finished_at is not None
        details = _decode_details(row.details)
        assert details == {
            "error": "running job was marked failed by migration before adding unique running-job lock",
            "migration_revision": "0006_add_running_job_lock",
            "migration_action": "terminate_legacy_running_job",
            "previous_status": "running",
        }
    assert "uq_job_runs_running_name" in {
        index["name"] for index in inspect(engine).get_indexes("job_runs")
    }

    downgraded = run_alembic(
        database_url,
        "downgrade",
        "0005_add_document_chunk_vector_index",
    )
    assert downgraded.returncode == 0, downgraded.stderr
    assert "uq_job_runs_running_name" not in {
        index["name"] for index in inspect(engine).get_indexes("job_runs")
    }
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, details FROM job_runs WHERE name = 'sync_all'")
        ).one()
        assert row.status == "failed"
        assert _decode_details(row.details)["migration_action"] == (
            "terminate_legacy_running_job"
        )


def test_running_job_lock_migration_generates_offline_sql(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'offline-running-job-lock.db').as_posix()}"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            "upgrade",
            "0006_add_running_job_lock",
            "--sql",
        ],
        cwd=API_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "UPDATE job_runs SET status = 'failed'" in result.stdout
    assert "terminate_legacy_running_job" in result.stdout
