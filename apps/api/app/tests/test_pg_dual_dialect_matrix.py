"""D3 dual-dialect matrix: PostgreSQL vs SQLite migration + write-path parity.

PG tests talk to the disposable local cluster on ``localhost:55432`` (admin db
``postgres``) and use throwaway databases that are dropped afterwards. When the
cluster is unreachable the PG-only cases skip; the SQLite counterparts always
run. Nothing here touches the read-only business database ``fund_app`` and no
network calls are made (all data is the in-repo synthetic sample).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.nav_quality import NavQualityWarningPayload
from app.db.models import Fund, FundMetric, FundNav
from app.db.session import Base
from app.repositories.fund_archives import MANIFEST_FILE_NAME, archive_generation
from app.repositories.fund_snapshots import ensure_snapshot_state, stage_snapshot
from app.repositories.funds import (
    stage_funds_batch,
    upsert_fund_detail,
    upsert_fund_metrics,
    upsert_fund_navs,
    upsert_fund_profile,
)
from app.services.sample_data import FUNDS
from app.schemas.funds import FundDetail

API_ROOT = Path(__file__).resolve().parents[2]
ADMIN_URL = "postgresql+psycopg://postgres@localhost:55432/postgres"
HOST = "localhost:55432"
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


PG_AVAILABLE = _pg_available()
requires_pg = pytest.mark.skipif(not PG_AVAILABLE, reason="PostgreSQL not reachable at localhost:55432")


def _create_temp_pg_db(purpose: str) -> str:
    db_name = f"fund_d3_{purpose}_{uuid4().hex[:12]}"
    admin = _pg_admin_engine()
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin.dispose()
    return f"postgresql+psycopg://postgres@{HOST}/{db_name}"


def _drop_temp_pg_db(url: str) -> None:
    db_name = url.rsplit("/", 1)[1]
    admin = _pg_admin_engine()
    try:
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


@requires_pg
def test_pg_fresh_db_upgrade_downgrade_upgrade_loop() -> None:
    """A brand-new PG database must survive upgrade->downgrade->upgrade."""
    url = _create_temp_pg_db("loop")
    try:
        up = _run_alembic(url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        down = _run_alembic(url, "downgrade", "base")
        assert down.returncode == 0, down.stderr
        again = _run_alembic(url, "upgrade", "head")
        assert again.returncode == 0, again.stderr

        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                revision: object = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                assert str(revision) == EXPECTED_HEAD
                table_count: object = connection.execute(
                    text("SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname='public'")
                ).scalar_one()
                assert int(str(table_count)) == 16
        finally:
            engine.dispose()
    finally:
        _drop_temp_pg_db(url)


@requires_pg
def test_pg_fund_navs_unique_indexes_reject_duplicates() -> None:
    """The two fund_navs unique constraints exist on PG and reject duplicates."""
    url = _create_temp_pg_db("uniq")
    try:
        up = _run_alembic(url, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        engine = create_engine(url)
        try:
            index_names = {idx["name"] for idx in inspect(engine).get_indexes("fund_navs")}
            constrained = {
                uc["name"] for uc in inspect(engine).get_unique_constraints("fund_navs")
            }
            # The historical global point identity + the per-generation point
            # identity (0010) must both be enforced on PostgreSQL.
            assert "uq_fund_navs_fund_code_trade_date" in index_names | constrained
            assert "uq_fund_navs_generation_point" in index_names

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO fund_data_snapshots "
                        "(generation_id, source, status, fund_count, nav_count, metric_count, "
                        "created_at, promoted_at) VALUES "
                        "('g-d3', 'test', 'active', 0, 0, 0, now(), now())"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO funds (code, name, fund_type, risk_level, manager_name, "
                        "inception_date, fund_size_billion, management_fee, custody_fee, source, "
                        "data_updated_at, ai_summary, raw_data, snapshot_generation_id, "
                        "created_at, updated_at) VALUES "
                        "('d3-fund', 'n', 'mixed', 'R3', 'm', '2020-01-01', 1.0, 1.0, 0.1, "
                        "'test', now(), '', '{}', 'g-d3', now(), now())"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO fund_navs (fund_code, trade_date, trade_date_precision, nav, "
                        "accumulated_nav, raw_data, snapshot_generation_id) VALUES "
                        "('d3-fund', '2026-09-01', 'day', 1.0, 1.0, '{}', 'g-d3')"
                    )
                )
                with pytest.raises(IntegrityError):
                    connection.execute(
                        text(
                            "INSERT INTO fund_navs (fund_code, trade_date, trade_date_precision, "
                            "nav, accumulated_nav, raw_data, snapshot_generation_id) VALUES "
                            "('d3-fund', '2026-09-01', 'day', 2.0, 2.0, '{}', 'g-d3')"
                        )
                    )
        finally:
            engine.dispose()
    finally:
        _drop_temp_pg_db(url)


# --- write-path parity: per-point vs B3 batched stage -----------------------


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    def _fk(dbapi: object, _rec: object) -> None:
        cursor = dbapi.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    event.listen(engine, "connect", _fk)
    Base.metadata.create_all(engine)
    return engine


def _seed(engine: Engine) -> Session:
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
    ensure_snapshot_state(db)
    for fund in FUNDS:
        upsert_fund_detail(db, fund)
    db.commit()
    return db


def _stage_generation_row(db: Session, generation_id: str, funds: list[FundDetail]) -> None:
    """Create the parent fund_data_snapshots row the FK requires before staging."""
    stage_snapshot(
        db,
        generation_id=generation_id,
        source="d3_test",
        fund_count=len(funds),
        nav_count=sum(len(fund.navs) for fund in funds),
        metric_count=len(funds),
    )
    db.flush()


def _per_point_stage(
    db: Session, funds: list[FundDetail], generation_id: str
) -> list[NavQualityWarningPayload]:
    warnings: list[NavQualityWarningPayload] = []
    for fund in funds:
        upsert_fund_profile(db, fund, generation_id)
        db.flush()
        upsert_fund_metrics(db, fund, generation_id)
        warnings.extend(upsert_fund_navs(db, fund, generation_id))
    db.flush()
    return warnings


def _generation_payloads(db: Session, generation_id: str) -> dict[str, object]:
    funds = sorted(
        (row.code, row.name, dict(row.raw_data))
        for row in db.scalars(select(Fund).where(Fund.snapshot_generation_id == generation_id))
    )
    navs = sorted(
        (
            row.fund_code,
            row.trade_date,
            row.nav,
            row.accumulated_nav,
            row.trade_date_precision,
            dict(row.raw_data),
        )
        for row in db.scalars(select(FundNav).where(FundNav.snapshot_generation_id == generation_id))
    )
    metrics = sorted(
        (row.fund_code, dict(row.raw_data))
        for row in db.scalars(
            select(FundMetric).where(FundMetric.snapshot_generation_id == generation_id)
        )
    )
    return {"funds": funds, "navs": navs, "metrics": metrics}


def _candidate_funds() -> list[FundDetail]:
    candidate = [fund.model_copy(deep=True) for fund in FUNDS]
    candidate[0].name = "D3 批量路径等价新名称"
    candidate[0].navs[0] = candidate[0].navs[0].model_copy(update={"nav": 1.99})
    return candidate


def _assert_write_parity(point_engine: Engine, batch_engine: Engine) -> None:
    point_db = _seed(point_engine)
    batch_db = _seed(batch_engine)
    try:
        candidate = _candidate_funds()
        _stage_generation_row(point_db, "gen-point", candidate)
        point_warnings = _per_point_stage(point_db, candidate, "gen-point")
        _stage_generation_row(batch_db, "gen-batch", candidate)
        batch_warnings = stage_funds_batch(batch_db, candidate, "gen-batch", batch_size=2)

        assert len(batch_warnings) == len(point_warnings)
        assert sorted(w["trade_date"] for w in batch_warnings) == sorted(
            w["trade_date"] for w in point_warnings
        )
        assert _generation_payloads(point_db, "gen-point") == _generation_payloads(
            batch_db, "gen-batch"
        )

        expected_navs = sum(len(fund.navs) for fund in candidate)
        before = batch_db.scalar(
            select(func.count()).select_from(FundNav).where(FundNav.snapshot_generation_id == "gen-batch")
        )
        # Re-staging the same generation must be idempotent (no duplicate rows).
        stage_funds_batch(batch_db, candidate, "gen-batch", batch_size=2)
        batch_db.commit()
        after = batch_db.scalar(
            select(func.count()).select_from(FundNav).where(FundNav.snapshot_generation_id == "gen-batch")
        )
        assert before == expected_navs
        assert after == expected_navs
    finally:
        point_db.close()
        batch_db.close()


def test_write_parity_sqlite() -> None:
    point_engine = _sqlite_engine()
    batch_engine = _sqlite_engine()
    try:
        _assert_write_parity(point_engine, batch_engine)
    finally:
        point_engine.dispose()
        batch_engine.dispose()


@requires_pg
def test_write_parity_postgresql() -> None:
    point_url = _create_temp_pg_db("wp_point")
    batch_url = _create_temp_pg_db("wp_batch")
    try:
        for url in (point_url, batch_url):
            result = _run_alembic(url, "upgrade", "head")
            assert result.returncode == 0, result.stderr
        point_engine = create_engine(point_url)
        batch_engine = create_engine(batch_url)
        try:
            _assert_write_parity(point_engine, batch_engine)
        finally:
            point_engine.dispose()
            batch_engine.dispose()
    finally:
        _drop_temp_pg_db(point_url)
        _drop_temp_pg_db(batch_url)


# --- archive manifest parity -------------------------------------------------


def _assert_archive_manifest(engine: Engine, archive_root: Path) -> None:
    db = _seed(engine)
    try:
        candidate = _candidate_funds()
        _stage_generation_row(db, "gen-archive", candidate)
        stage_funds_batch(db, candidate, "gen-archive", batch_size=2)
        db.commit()

        archive = archive_generation(db, "gen-archive", archive_root=archive_root)
        archive_dir = Path(archive.archive_dir)
        manifest = json.loads((archive_dir / MANIFEST_FILE_NAME).read_text(encoding="utf-8"))
        assert manifest["generation_id"] == "gen-archive"
        assert manifest["counts"]["funds"] == len(FUNDS)
        assert manifest["counts"]["navs"] == sum(len(f.navs) for f in FUNDS)
        for name, meta in manifest["files"].items():
            digest = hashlib.sha256((archive_dir / name).read_bytes()).hexdigest()
            assert digest == meta["sha256"]
        assert (
            hashlib.sha256((archive_dir / MANIFEST_FILE_NAME).read_bytes()).hexdigest()
            == archive.manifest_sha256
        )
    finally:
        db.close()


def test_archive_manifest_sqlite(tmp_path: Path) -> None:
    engine = _sqlite_engine()
    try:
        _assert_archive_manifest(engine, tmp_path)
    finally:
        engine.dispose()


@requires_pg
def test_archive_manifest_postgresql(tmp_path: Path) -> None:
    url = _create_temp_pg_db("arch")
    try:
        result = _run_alembic(url, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        engine = create_engine(url)
        try:
            _assert_archive_manifest(engine, tmp_path)
        finally:
            engine.dispose()
    finally:
        _drop_temp_pg_db(url)
