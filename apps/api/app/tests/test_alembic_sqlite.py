import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


API_ROOT = Path(__file__).resolve().parents[2]


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
            "0010_add_fund_nav_generation_point_unique"
        )
