import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


API_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_HEAD = "0010_add_fund_nav_generation_point_unique"


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
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


def test_sqlite_database_upgrades_from_empty_to_head(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=API_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    engine = create_engine(database_url)
    assert {
        "funds",
        "fund_navs",
        "fund_metrics",
        "portfolios",
        "backtest_runs",
        "ai_threads",
        "ai_messages",
        "documents",
        "document_chunks",
        "job_runs",
        "fund_data_snapshots",
        "fund_data_snapshot_state",
        "llm_provider_events",
    }.issubset(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            EXPECTED_HEAD
        )


def test_sqlite_upgrade_downgrade_upgrade_round_trip(tmp_path: Path) -> None:
    database_path = tmp_path / "roundtrip.db"
    database_url = f"sqlite:///{database_path.as_posix()}"

    upgraded = _run_alembic(database_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    downgraded = _run_alembic(database_url, "downgrade", "base")
    assert downgraded.returncode == 0, downgraded.stderr

    engine = create_engine(database_url)
    try:
        remaining = {
            table
            for table in inspect(engine).get_table_names()
            if table != "alembic_version"
        }
        assert remaining == set()
    finally:
        engine.dispose()

    re_upgraded = _run_alembic(database_url, "upgrade", "head")
    assert re_upgraded.returncode == 0, re_upgraded.stderr

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == EXPECTED_HEAD
    finally:
        engine.dispose()
