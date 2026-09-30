"""D2: tests for app/jobs/batch_runner.py (per-fund isolation + one generation/batch).

Everything is mocked: the business DB is a tmp SQLite created by SQLAlchemy
metadata (no alembic subprocess), the checkpoint is an on-disk BatchState, the
primary pull is a fake, and the cross-check gate is a controllable fake. No
akshare / HTTP / real time.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.fund_classifier import ClassifyDecision
from app.core.reconciliation import FundReconciliationReport
from app.core.reconciliation_service import IsolatedReconciliation
from app.data_sources.universe import UniverseFund
from app.db.models import (
    LEGACY_SNAPSHOT_GENERATION_ID,
    Fund,
    FundDataSnapshot,
    FundDataSnapshotState,
    FundMetric,
    FundNav,
)
from app.db.session import Base
from app.jobs.batch_runner import BatchRunner
from app.jobs.batch_state import BatchState
from app.jobs.batch_throttle import BatchThrottle, DeterministicReject
from app.repositories.fund_snapshots import (
    SNAPSHOT_STATE_ROW_ID,
    ensure_snapshot_state,
    refresh_snapshot_metadata,
)
from app.repositories.funds import upsert_fund_detail
from app.repositories.portfolios import ensure_default_portfolios
from app.services.sample_data import FUNDS
from app.schemas.funds import FundDetail, NavPoint


# --------------------------------------------------------------------------- #
# Fixtures / fakes
# --------------------------------------------------------------------------- #
def _make_db() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
    ensure_snapshot_state(db)
    for fund in FUNDS:
        upsert_fund_detail(db, fund)
    refresh_snapshot_metadata(
        db,
        generation_id=LEGACY_SNAPSHOT_GENERATION_ID,
        fallback_source="sample_local",
    )
    ensure_default_portfolios(db)
    db.commit()
    return db


def _fund(code: str) -> UniverseFund:
    return UniverseFund(
        code=code,
        name=f"基金{code}",
        type_major="混合型",
        type_detail="混合型-灵活",
        has_3y=True,
        scale=None,
        unit_nav=None,
        acc_nav=None,
        nav_date=date(2026, 9, 30),
    )


def _plan(state: BatchState, codes: list[str]) -> None:
    records = [_fund(c) for c in codes]
    decisions = {
        c: ClassifyDecision(route="supported", reason="eligible_open_end", detail={})
        for c in codes
    }
    state.build_plan(records, decisions, shards=1, include_short_history=False)


def _throttle() -> BatchThrottle:
    return BatchThrottle(
        limits={"eastmoney": 0.0, "danjuan": 0.0, "sina": 0.0},
        max_retries=3,
        backoff_base_seconds=2.0,
        backoff_cap_seconds=8.0,
        sleep=lambda _s: None,
    )


class FakeFetcher:
    name = "eastmoney_snapshot"

    def __init__(
        self,
        funds_by_code: dict[str, FundDetail],
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._funds = funds_by_code
        self._errors = errors or {}
        self.calls: list[tuple[str, object]] = []

    def fetch_fund(self, code: str, *, as_of: object, start_date: object) -> FundDetail:
        self.calls.append((code, start_date))
        if code in self._errors:
            raise self._errors[code]
        return self._funds[code].model_copy(deep=True)


def _report(code: str, status: str) -> FundReconciliationReport:
    return FundReconciliationReport(
        code=code,
        display_name=code,
        status=status,  # type: ignore[arg-type]
        sources=["eastmoney_snapshot", "danjuan"],
        field_checks=[],
        nav_total=10,
        nav_matched=10,
        nav_missing=0,
        nav_mismatch=0,
        nav_coverage=1.0,
        nav_agreement=1.0,
        critical_failures=["nav unit mismatch"] if status == "mismatch" else [],
        warnings=[],
    )


class FakeRecon:
    def __init__(
        self,
        *,
        mismatch: set[str] | None = None,
        unavailable: dict[str, str] | None = None,
    ) -> None:
        self.mismatch = mismatch or set()
        self.unavailable = unavailable or {}

    def reconcile_one_fund_isolated(self, fund: FundDetail) -> IsolatedReconciliation:
        if fund.code in self.mismatch:
            return IsolatedReconciliation(
                report=_report(fund.code, "mismatch"), danjuan_available=True, danjuan_error=None
            )
        if fund.code in self.unavailable:
            return IsolatedReconciliation(
                report=_report(fund.code, "source_unavailable"),
                danjuan_available=False,
                danjuan_error=self.unavailable[fund.code],
            )
        return IsolatedReconciliation(
            report=_report(fund.code, "verified"), danjuan_available=True, danjuan_error=None
        )


def _runner(
    db: Session,
    state: BatchState,
    fetcher: FakeFetcher,
    recon: object | None,
) -> BatchRunner:
    from app.core.reconciliation_service import ReconciliationService

    return BatchRunner(
        db,
        state,
        fetcher=fetcher,
        reconciliation=cast(ReconciliationService, recon),
        throttle=_throttle(),
        job_id="test-job",
    )


class FakeHTTPError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"GET url returned HTTP {status}")
        self.response = SimpleNamespace(status_code=status)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_all_pass_promotes_one_generation_and_marks_done(tmp_path: Path) -> None:
    db = _make_db()
    codes = [FUNDS[0].code, FUNDS[1].code]
    fetcher = FakeFetcher({c: f for c, f in zip(codes, [FUNDS[0], FUNDS[1]])})
    snapshots_before = set(db.scalars(select(FundDataSnapshot.generation_id)).all())

    with BatchState(tmp_path / "s.db") as state:
        _plan(state, codes)
        summary = _runner(db, state, fetcher, FakeRecon()).run(batch_size=50)

    assert summary.batches == 1
    assert summary.passed == 2
    assert summary.skipped == 0
    assert summary.failed == 0
    assert len(summary.generations) == 1

    snapshots_after = set(db.scalars(select(FundDataSnapshot.generation_id)).all())
    new_generations = snapshots_after - snapshots_before
    assert len(new_generations) == 1
    generation_id = summary.generations[0]

    state2 = BatchState(tmp_path / "s.db")
    rows = {
        r["code"]: r
        for r in state2._conn.execute("SELECT * FROM fund_sync_state WHERE status='done'").fetchall()  # noqa: SLF001
    }
    for code in codes:
        assert rows[code]["generation_id"] == generation_id
        assert rows[code]["fund_written"] == 1
        assert rows[code]["nav_points"] == len(FUNDS[0].navs)

    active = db.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert active is not None
    assert active.active_generation_id == generation_id
    for code in codes:
        fund = db.get(Fund, code)
        assert fund is not None
        assert fund.snapshot_generation_id == generation_id


def test_danjuan_not_listed_is_skipped_and_not_staged(tmp_path: Path) -> None:
    db = _make_db()
    good_code = FUNDS[0].code
    bad_code = FUNDS[1].code
    fetcher = FakeFetcher(
        {good_code: FUNDS[0]},
        errors={bad_code: DeterministicReject("danjuan not listed", reason="danjuan_not_listed")},
    )
    with BatchState(tmp_path / "s.db") as state:
        _plan(state, [good_code, bad_code])
        summary = _runner(db, state, fetcher, FakeRecon()).run(batch_size=50)

    assert summary.passed == 1
    assert summary.skipped == 1
    state2 = BatchState(tmp_path / "s.db")
    bad = state2._conn.execute(  # noqa: SLF001
        "SELECT status, reason FROM fund_sync_state WHERE code=?", (bad_code,)
    ).fetchone()
    assert bad["status"] == "skipped"
    assert bad["reason"] == "danjuan_not_listed"
    # The skipped fund must NOT be in the promoted generation.
    promoted = db.get(Fund, bad_code)
    assert promoted is not None
    assert promoted.snapshot_generation_id == LEGACY_SNAPSHOT_GENERATION_ID


def test_young_inception_is_skipped_insufficient_history_and_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-phase: the precise >=3y check runs here, per fund. A fund founded <3y
    (and short-history off) is skipped as insufficient_history -- never staged,
    never promoted, never written."""
    monkeypatch.setattr(settings, "fund_batch_include_short_history", False)
    db = _make_db()
    old = FUNDS[0]  # inception 2018-03-15, well over 3y
    young = FUNDS[1].model_copy(update={"inception_date": "2025-06-01"})  # <3y
    codes = [old.code, young.code]
    fetcher = FakeFetcher({old.code: old, young.code: young})

    with BatchState(tmp_path / "s.db") as state:
        _plan(state, codes)
        summary = _runner(db, state, fetcher, FakeRecon()).run(batch_size=50)

    assert summary.passed == 1  # only the old fund promotes
    assert summary.skipped == 1
    state2 = BatchState(tmp_path / "s.db")
    row = state2._conn.execute(  # noqa: SLF001
        "SELECT status, reason FROM fund_sync_state WHERE code=?", (young.code,)
    ).fetchone()
    assert row["status"] == "skipped"
    assert row["reason"] == "insufficient_history"
    # The young fund must NOT be written into a new generation.
    fund_row = db.get(Fund, young.code)
    assert fund_row is None or fund_row.snapshot_generation_id == LEGACY_SNAPSHOT_GENERATION_ID


def test_young_inception_passes_when_short_history_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "fund_batch_include_short_history", True)
    db = _make_db()
    young = FUNDS[0].model_copy(update={"inception_date": "2025-06-01"})
    fetcher = FakeFetcher({young.code: young})
    with BatchState(tmp_path / "s.db") as state:
        _plan(state, [young.code])
        summary = _runner(db, state, fetcher, FakeRecon()).run(batch_size=50)
    assert summary.passed == 1
    assert summary.skipped == 0


def test_reconciliation_mismatch_is_isolated_others_promote(tmp_path: Path) -> None:
    db = _make_db()
    mismatch_code = FUNDS[0].code
    ok_codes = [FUNDS[1].code, FUNDS[2].code]
    all_codes = [mismatch_code, *ok_codes]
    funds = {c: f for c, f in zip(all_codes, [FUNDS[0], FUNDS[1], FUNDS[2]])}
    fetcher = FakeFetcher(funds)
    recon = FakeRecon(mismatch={mismatch_code})

    with BatchState(tmp_path / "s.db") as state:
        _plan(state, all_codes)
        summary = _runner(db, state, fetcher, recon).run(batch_size=50)

    assert summary.passed == 2
    assert summary.skipped == 1
    generation_id = summary.generations[0]
    for code in ok_codes:
        promoted = db.get(Fund, code)
        assert promoted is not None
        assert promoted.snapshot_generation_id == generation_id
    # Tampered fund stays on the legacy generation.
    tampered = db.get(Fund, mismatch_code)
    assert tampered is not None
    assert tampered.snapshot_generation_id == LEGACY_SNAPSHOT_GENERATION_ID
    state2 = BatchState(tmp_path / "s.db")
    row = state2._conn.execute(  # noqa: SLF001
        "SELECT reason FROM fund_sync_state WHERE code=?", (mismatch_code,)
    ).fetchone()
    assert row["reason"] == "reconciliation_mismatch"


def test_quality_error_marks_quality_failed(tmp_path: Path) -> None:
    db = _make_db()
    bad = FUNDS[0].model_copy(deep=True)
    bad.navs = [
        NavPoint(trade_date="2026-01-01", nav=1.0, accumulated_nav=1.0),
        NavPoint(trade_date="2026-01-01", nav=1.1, accumulated_nav=1.1),  # duplicate date
    ]
    codes = [bad.code]
    fetcher = FakeFetcher({bad.code: bad})
    with BatchState(tmp_path / "s.db") as state:
        _plan(state, codes)
        summary = _runner(db, state, fetcher, FakeRecon()).run(batch_size=50)

    assert summary.passed == 0
    assert summary.skipped == 1
    state2 = BatchState(tmp_path / "s.db")
    row = state2._conn.execute(  # noqa: SLF001
        "SELECT status, reason FROM fund_sync_state WHERE code=?", (bad.code,)
    ).fetchone()
    assert row["status"] == "skipped"
    assert row["reason"] == "quality_failed"


def test_transient_5xx_twice_then_success_marks_done(tmp_path: Path) -> None:
    db = _make_db()
    code = FUNDS[0].code
    calls = {"n": 0}

    def flaky_fetch(c: str, *, as_of: object, start_date: object) -> FundDetail:
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeHTTPError(503)
        return FUNDS[0].model_copy(deep=True)

    fetcher = SimpleNamespace(name="eastmoney_snapshot", fetch_fund=flaky_fetch)
    with BatchState(tmp_path / "s.db") as state:
        _plan(state, [code])
        summary = _runner(db, state, fetcher, FakeRecon()).run(batch_size=50)  # type: ignore[arg-type]

    assert calls["n"] == 3  # two retried failures + success
    assert summary.passed == 1
    assert summary.failed == 0


def test_transient_exhausted_marks_failed_retryable(tmp_path: Path) -> None:
    db = _make_db()
    code = FUNDS[0].code

    def always_fail(c: str, *, as_of: object, start_date: object) -> FundDetail:
        raise FakeHTTPError(503)

    fetcher = SimpleNamespace(name="eastmoney_snapshot", fetch_fund=always_fail)
    with BatchState(tmp_path / "s.db") as state:
        _plan(state, [code])
        summary = _runner(db, state, fetcher, FakeRecon()).run(batch_size=50)  # type: ignore[arg-type]

    assert summary.failed == 1
    state2 = BatchState(tmp_path / "s.db")
    row = state2._conn.execute(  # noqa: SLF001
        "SELECT status, last_error FROM fund_sync_state WHERE code=?", (code,)
    ).fetchone()
    assert row["status"] == "failed"
    assert "transient" in row["last_error"].lower()


def test_dry_run_writes_neither_business_db_nor_checkpoint(tmp_path: Path) -> None:
    db = _make_db()
    codes = [FUNDS[0].code, FUNDS[1].code]
    fetcher = FakeFetcher({c: f for c, f in zip(codes, [FUNDS[0], FUNDS[1]])})
    snapshots_before = set(db.scalars(select(FundDataSnapshot.generation_id)).all())

    with BatchState(tmp_path / "s.db") as state:
        _plan(state, codes)
        summary = _runner(db, state, fetcher, FakeRecon()).run(batch_size=50, dry_run=True)

    assert summary.passed == 2
    assert summary.generations == []
    # No new business generation promoted.
    assert set(db.scalars(select(FundDataSnapshot.generation_id)).all()) == snapshots_before
    # Checkpoint never reaches a terminal state: codes stay pending/in_flight and
    # will be re-claimed by the next real run (dry-run consumes nothing terminal).
    state2 = BatchState(tmp_path / "s.db")
    statuses = state2._conn.execute(  # noqa: SLF001
        "SELECT status FROM fund_sync_state WHERE code IN (?,?)", (codes[0], codes[1])
    ).fetchall()
    assert {r["status"] for r in statuses} <= {"pending", "in_flight"}
    assert all(r["status"] not in {"done", "skipped", "failed"} for r in statuses)


def test_interrupted_in_flight_is_reclaimed_on_restart(tmp_path: Path) -> None:
    db = _make_db()
    codes = [FUNDS[0].code, FUNDS[1].code]
    fetcher = FakeFetcher({c: f for c, f in zip(codes, [FUNDS[0], FUNDS[1]])})

    state = BatchState(tmp_path / "s.db", claim_timeout_seconds=1800)
    _plan(state, codes)
    # Simulate a crash: claim a batch but never finish it.
    claimed = state.claim_batch(50, "worker-1")
    assert claimed == codes
    state.close()

    # No promotion happened during the crashed run.
    snapshots_before = set(db.scalars(select(FundDataSnapshot.generation_id)).all())

    # Restart with a short timeout so the in_flight rows are reclaimed.
    state2 = BatchState(tmp_path / "s.db", claim_timeout_seconds=0)
    summary = _runner(db, state2, fetcher, FakeRecon()).run(batch_size=50)
    state2.close()

    assert summary.passed == 2
    new_gens = set(db.scalars(select(FundDataSnapshot.generation_id)).all()) - snapshots_before
    assert len(new_gens) == 1


def test_retry_resets_failed_then_runs_again(tmp_path: Path) -> None:
    db = _make_db()
    code = FUNDS[0].code
    state: dict[str, object] = {"phase": 1}

    def flaky(c: str, *, as_of: object, start_date: object) -> FundDetail:
        if state["phase"] == 1:
            raise FakeHTTPError(503)  # first run: exhaust all retries -> failed
        return FUNDS[0].model_copy(deep=True)

    fetcher = SimpleNamespace(name="eastmoney_snapshot", fetch_fund=flaky)
    with BatchState(tmp_path / "s.db") as state_db:
        _plan(state_db, [code])
        first = _runner(db, state_db, fetcher, FakeRecon()).run(batch_size=50)  # type: ignore[arg-type]
        assert first.failed == 1
        reset = state_db.retry_failed()
        assert reset == 1
        state["phase"] = 2
        second = _runner(db, state_db, fetcher, FakeRecon()).run(batch_size=50)  # type: ignore[arg-type]

    assert second.passed == 1


def test_rerun_same_batch_is_idempotent_no_duplicate_nav_rows(tmp_path: Path) -> None:
    db = _make_db()
    codes = [FUNDS[0].code]
    fetcher = FakeFetcher({codes[0]: FUNDS[0]})
    with BatchState(tmp_path / "s.db") as state:
        _plan(state, codes)
        _runner(db, state, fetcher, FakeRecon()).run(batch_size=50)
    nav_count_after_first = db.scalar(
        select(func.count()).select_from(FundNav).where(FundNav.fund_code == codes[0])
    )

    # Force the done fund back to pending and re-run into a NEW generation.
    state2 = BatchState(tmp_path / "s.db")
    state2._conn.execute(  # noqa: SLF001
        "UPDATE fund_sync_state SET status='pending' WHERE code=?", (codes[0],)
    )
    state2._conn.commit()
    _runner(db, state2, fetcher, FakeRecon()).run(batch_size=50)
    state2.close()

    nav_count_after_second = db.scalar(
        select(func.count()).select_from(FundNav).where(FundNav.fund_code == codes[0])
    )
    assert nav_count_after_second == nav_count_after_first
    # Exactly one metric row per code (upserted, not duplicated).
    metric_count = db.scalar(
        select(func.count()).select_from(FundMetric).where(FundMetric.fund_code == codes[0])
    )
    assert metric_count == 1


def test_default_workers_is_one() -> None:
    assert settings.fund_batch_workers == 1
