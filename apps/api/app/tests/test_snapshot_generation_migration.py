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


def test_snapshot_generation_migration_backfills_and_round_trips_legacy_rows(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'snapshot-generation.db').as_posix()}"
    before = run_alembic(database_url, "upgrade", "0007_add_nav_trade_date_precision")
    assert before.returncode == 0, before.stderr

    engine = create_engine(database_url)
    source_a = "a" * 64
    source_b = "b" * 64
    with engine.begin() as connection:
        for code, source in (("legacy-a", source_a), ("legacy-b", source_b)):
            connection.execute(
                text(
                    """
                    INSERT INTO funds (
                        code, name, fund_type, risk_level, manager_name,
                        inception_date, fund_size_billion, management_fee,
                        custody_fee, source, data_updated_at, ai_summary,
                        raw_data, created_at, updated_at
                    ) VALUES (
                        :code, :code, 'mixed', 'R3', 'manager', '2020-01-01',
                        1.0, 1.0, 0.2, :source, '2026-07-13 00:00:00', '',
                        '{}', '2026-07-13 00:00:00', '2026-07-13 00:00:00'
                    )
                    """
                ),
                {"code": code, "source": source},
            )

    upgraded = run_alembic(database_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    inspector = inspect(engine)
    assert {
        "fund_data_snapshots",
        "fund_data_snapshot_state",
    }.issubset(inspector.get_table_names())
    assert "ix_fund_data_snapshots_status" in {
        index["name"] for index in inspector.get_indexes("fund_data_snapshots")
    }
    assert "ck_fund_data_snapshot_state_singleton" in {
        constraint["name"]
        for constraint in inspector.get_check_constraints(
            "fund_data_snapshot_state"
        )
    }
    snapshot_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("fund_data_snapshots")
    }
    assert {
        "ck_fund_data_snapshots_status",
        "ck_fund_data_snapshots_fund_count_nonnegative",
        "ck_fund_data_snapshots_nav_count_nonnegative",
        "ck_fund_data_snapshots_metric_count_nonnegative",
    }.issubset(snapshot_checks)
    for table_name in ("funds", "fund_navs", "fund_metrics"):
        foreign_keys = inspector.get_foreign_keys(table_name)
        assert any(
            foreign_key["referred_table"] == "fund_data_snapshots"
            and foreign_key["constrained_columns"] == ["snapshot_generation_id"]
            for foreign_key in foreign_keys
        )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.execute(
            text(
                "SELECT DISTINCT snapshot_generation_id FROM funds ORDER BY 1"
            )
        ).scalars().all() == ["legacy-0008"]
        assert connection.execute(
            text(
                """
                SELECT source, status, fund_count, nav_count, metric_count
                FROM fund_data_snapshots
                WHERE generation_id = 'legacy-0008'
                """
            )
        ).one() == ("mixed(2 sources)", "active", 2, 0, 0)
        assert connection.execute(
            text("SELECT id, active_generation_id FROM fund_data_snapshot_state")
        ).one() == (1, "legacy-0008")
        for invalid_status in ("candidate", "failed", ""):
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        """
                        INSERT INTO fund_data_snapshots (
                            generation_id, source, status, fund_count, nav_count,
                            metric_count, created_at, promoted_at
                        ) VALUES (
                            :generation_id, 'sample_local', :status, 0, 0, 0,
                            '2026-07-13 00:00:00', NULL
                        )
                        """
                    ),
                    {"generation_id": f"bad-status-{invalid_status}", "status": invalid_status},
                )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO fund_data_snapshots (
                        generation_id, source, status, fund_count, nav_count,
                        metric_count, created_at, promoted_at
                    ) VALUES (
                        'bad-negative-count', 'sample_local', 'staging', -1, 0, 0,
                        '2026-07-13 00:00:00', NULL
                    )
                    """
                )
            )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO funds (
                        code, name, fund_type, risk_level, manager_name,
                        inception_date, fund_size_billion, management_fee,
                        custody_fee, source, data_updated_at, ai_summary,
                        raw_data, snapshot_generation_id, created_at, updated_at
                    ) VALUES (
                        'orphan-generation', 'orphan-generation', 'mixed', 'R3',
                        'manager', '2020-01-01', 1.0, 1.0, 0.2, 'sample_local',
                        '2026-07-13 00:00:00', '', '{}', 'missing-generation',
                        '2026-07-13 00:00:00', '2026-07-13 00:00:00'
                    )
                    """
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO fund_data_snapshot_state
                        (id, active_generation_id, updated_at)
                    VALUES (2, 'legacy-0008', '2026-07-13 00:00:00')
                    """
                )
            )

    downgraded = run_alembic(
        database_url,
        "downgrade",
        "0007_add_nav_trade_date_precision",
    )
    assert downgraded.returncode == 0, downgraded.stderr
    assert "snapshot_generation_id" not in {
        column["name"] for column in inspect(engine).get_columns("funds")
    }
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM funds")).scalar_one() == 2

    round_trip = run_alembic(database_url, "upgrade", "head")
    assert round_trip.returncode == 0, round_trip.stderr
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM fund_data_snapshot_state")
        ).scalar_one() == 1
