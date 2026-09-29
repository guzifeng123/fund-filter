import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

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


def test_fund_nav_generation_point_unique_migration_round_trips(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'gen-point-unique.db').as_posix()}"
    before = run_alembic(database_url, "upgrade", "0009_add_llm_provider_events")
    assert before.returncode == 0, before.stderr

    upgraded = run_alembic(database_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    engine = create_engine(database_url)
    indexes = {index["name"] for index in inspect(engine).get_indexes("fund_navs")}
    assert "uq_fund_navs_generation_point" in indexes
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0010_add_fund_nav_generation_point_unique"
        )

    downgraded = run_alembic(database_url, "downgrade", "0009_add_llm_provider_events")
    assert downgraded.returncode == 0, downgraded.stderr
    indexes_after = {index["name"] for index in inspect(engine).get_indexes("fund_navs")}
    assert "uq_fund_navs_generation_point" not in indexes_after

    round_trip = run_alembic(database_url, "upgrade", "head")
    assert round_trip.returncode == 0, round_trip.stderr
    indexes_final = {index["name"] for index in inspect(engine).get_indexes("fund_navs")}
    assert "uq_fund_navs_generation_point" in indexes_final


def test_generation_point_unique_constraint_rejects_duplicate_in_same_generation(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'gen-point-dup.db').as_posix()}"
    upgraded = run_alembic(database_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.execute(
            text(
                """
                INSERT INTO fund_data_snapshots
                    (generation_id, source, status, fund_count, nav_count, metric_count,
                     created_at, promoted_at)
                VALUES ('g-dup', 'test', 'active', 0, 0, 0,
                        '2026-09-29 00:00:00', '2026-09-29 00:00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO funds
                    (code, name, fund_type, risk_level, manager_name, inception_date,
                     fund_size_billion, management_fee, custody_fee, source,
                     data_updated_at, ai_summary, raw_data, snapshot_generation_id,
                     created_at, updated_at)
                VALUES ('dup-fund', 'n', 'mixed', 'R3', 'm', '2020-01-01', 1.0, 1.0, 0.1,
                        'test', '2026-09-29 00:00:00', '', '{}', 'g-dup',
                        '2026-09-29 00:00:00', '2026-09-29 00:00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO fund_navs
                    (fund_code, trade_date, trade_date_precision, nav, accumulated_nav,
                     raw_data, snapshot_generation_id)
                VALUES ('dup-fund', '2026-09-01', 'day', 1.0, 1.0, '{}', 'g-dup')
                """
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO fund_navs
                        (fund_code, trade_date, trade_date_precision, nav,
                         accumulated_nav, raw_data, snapshot_generation_id)
                    VALUES ('dup-fund', '2026-09-01', 'day', 2.0, 2.0, '{}', 'g-dup')
                    """
                )
            )
