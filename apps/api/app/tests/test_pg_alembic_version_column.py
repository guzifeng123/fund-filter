"""D0: PostgreSQL alembic_version.version_column widening contract.

The revision id ``0004_use_pgvector_for_document_embeddings`` is 40 chars, but
Alembic defaults ``alembic_version.version_num`` to ``VARCHAR(32)``. PostgreSQL
enforces that length strictly (SQLite does not), so a brand-new PG database
failed when stamping 0004. ``alembic/env.py`` now pre-creates / widens the
version table to ``VARCHAR(128)`` before ``ensure_version`` runs.

These tests talk to the local disposable PostgreSQL cluster on
``localhost:55432`` (admin db ``postgres``). When the cluster is unreachable
they skip; SQLite-path behaviour is covered separately in
``test_alembic_sqlite.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

API_ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = "postgresql+psycopg://postgres@localhost:55432/postgres"
BUSINESS_HOST = "localhost:55432"
EXPECTED_HEAD = "0010_add_fund_nav_generation_point_unique"


def _pg_admin_engine() -> Engine:
    return create_engine(
        ADMIN_URL,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )


def _pg_available() -> bool:
    try:
        engine = _pg_admin_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:  # noqa: BLE001 - connectivity probe: any failure means skip
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL is not reachable at localhost:55432; skipping PG dialect test",
)


@pytest.fixture()
def temp_pg_database() -> Generator[str, None, None]:
    """Create a throwaway empty database and yield its URL, then DROP it."""
    db_name = f"fund_d0_smoke_{uuid.uuid4().hex[:12]}"
    admin = _pg_admin_engine()
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{db_name}"'))
        url = f"postgresql+psycopg://postgres@{BUSINESS_HOST}/{db_name}"
        try:
            yield url
        finally:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    finally:
        admin.dispose()


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
        timeout=180,
    )


def _version_column_length(engine: Engine) -> int:
    with engine.connect() as connection:
        value: object = connection.execute(
            text(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
            )
        ).scalar_one()
    return int(str(value))


def test_fresh_pg_upgrade_reaches_head_without_manual_alter(
    temp_pg_database: str,
) -> None:
    """A brand-new PG database must upgrade to head with no manual ALTER."""
    result = _run_alembic(temp_pg_database, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    engine = create_engine(temp_pg_database)
    try:
        with engine.connect() as connection:
            revision: object = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert str(revision) == EXPECTED_HEAD
            table_count: object = connection.execute(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_tables "
                    "WHERE schemaname = 'public'"
                )
            ).scalar_one()
            assert int(str(table_count)) == 16
        # The version table was created at VARCHAR(128), not the default VARCHAR(32).
        assert _version_column_length(engine) == 128
    finally:
        engine.dispose()


def test_pg_upgrade_is_idempotent_version_column_widening(
    temp_pg_database: str,
) -> None:
    """Two consecutive ``upgrade head`` calls exercise both env.py branches.

    The first upgrade hits the "version table absent -> create at VARCHAR(128)"
    branch; the second runs ``ensure_version_column_widened`` again on the
    already-widened table ("present -> ALTER TYPE VARCHAR(128)"), which must
    not raise.
    """
    first = _run_alembic(temp_pg_database, "upgrade", "head")
    assert first.returncode == 0, first.stderr
    second = _run_alembic(temp_pg_database, "upgrade", "head")
    assert second.returncode == 0, second.stderr

    engine = create_engine(temp_pg_database)
    try:
        assert _version_column_length(engine) == 128
    finally:
        engine.dispose()
