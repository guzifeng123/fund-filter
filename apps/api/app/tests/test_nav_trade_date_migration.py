import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

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


def test_nav_trade_date_precision_migration_is_non_destructive_and_repeatable(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'nav-date-migration.db').as_posix()}"
    before = run_alembic(database_url, "upgrade", "0006_add_running_job_lock")
    assert before.returncode == 0, before.stderr

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO funds (
                    code, name, fund_type, risk_level, manager_name, inception_date,
                    fund_size_billion, management_fee, custody_fee, source,
                    data_updated_at, ai_summary, raw_data, created_at, updated_at
                ) VALUES (
                    'legacy', 'legacy', 'mixed', 'R3', 'manager', '2020-01-01',
                    1.0, 1.0, 0.2, 'sample_local',
                    '2026-07-13 00:00:00', '', '{}',
                    '2026-07-13 00:00:00', '2026-07-13 00:00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO fund_navs
                    (fund_code, trade_date, nav, accumulated_nav, raw_data)
                VALUES
                    ('legacy', '2024', 1.0, 1.0, '{}'),
                    ('legacy', '2025-01-02', 1.1, 1.1, '{}'),
                    ('legacy', 'not-a-date', 1.2, 1.2, '{}')
                """
            )
        )

    upgraded = run_alembic(database_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    with engine.connect() as connection:
        rows = [
            (str(row.trade_date), str(row.trade_date_precision))
            for row in connection.execute(
                text(
                    "SELECT trade_date, trade_date_precision "
                    "FROM fund_navs ORDER BY id"
                )
            )
        ]
    assert rows == [
        ("2024", "year"),
        ("2025-01-02", "day"),
        ("not-a-date", "unknown"),
    ]

    repeated = run_alembic(database_url, "upgrade", "head")
    assert repeated.returncode == 0, repeated.stderr
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM fund_navs")).scalar_one() == 3

    downgraded = run_alembic(
        database_url,
        "downgrade",
        "0006_add_running_job_lock",
    )
    assert downgraded.returncode == 0, downgraded.stderr
    assert "trade_date_precision" not in {
        column["name"] for column in inspect(engine).get_columns("fund_navs")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT trade_date FROM fund_navs ORDER BY id")
        ).scalars().all() == ["2024", "2025-01-02", "not-a-date"]

    round_trip = run_alembic(database_url, "upgrade", "head")
    assert round_trip.returncode == 0, round_trip.stderr


def test_nav_trade_date_precision_migration_generates_offline_sql(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'offline-nav-date-migration.db').as_posix()}"
    result = run_alembic(
        database_url,
        "upgrade",
        "0007_add_nav_trade_date_precision",
        "--sql",
    )

    assert result.returncode == 0, result.stderr
    assert (
        "ALTER TABLE fund_navs ADD COLUMN trade_date_precision"
        in result.stdout
    )
    assert "UPDATE fund_navs SET trade_date_precision = CASE" in result.stdout


def test_nav_trade_date_precision_migration_backfills_large_tables_in_batches(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'nav-date-large-migration.db').as_posix()}"
    before = run_alembic(database_url, "upgrade", "0006_add_running_job_lock")
    assert before.returncode == 0, before.stderr

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO funds (
                    code, name, fund_type, risk_level, manager_name, inception_date,
                    fund_size_billion, management_fee, custody_fee, source,
                    data_updated_at, ai_summary, raw_data, created_at, updated_at
                ) VALUES (
                    'large-legacy', 'large-legacy', 'mixed', 'R3', 'manager',
                    '2020-01-01', 1.0, 1.0, 0.2, 'sample_local',
                    '2026-07-13 00:00:00', '', '{}',
                    '2026-07-13 00:00:00', '2026-07-13 00:00:00'
                )
                """
            )
        )
        start = date(2020, 1, 1)
        for index in range(1105):
            trade_date = (start + timedelta(days=index)).isoformat()
            connection.execute(
                text(
                    """
                    INSERT INTO fund_navs
                        (fund_code, trade_date, nav, accumulated_nav, raw_data)
                    VALUES
                        ('large-legacy', :trade_date, 1.0, 1.0, '{}')
                    """
                ),
                {"trade_date": trade_date},
            )

    upgraded = run_alembic(database_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    with engine.connect() as connection:
        assert connection.execute(
            text(
                """
                SELECT COUNT(*) FROM fund_navs
                WHERE fund_code = 'large-legacy'
                  AND trade_date_precision = 'day'
                """
            )
        ).scalar_one() == 1105
