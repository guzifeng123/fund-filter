"""Pre-staging multi-source reconciliation gate tests (C3).

All secondary sources are hand-written fakes; no network and no C2 clients. The
gate is exercised end-to-end through ``sync_fund_data.sync_all`` so we can assert
that a strict rejection rolls the transaction back, keeps the previous generation
visible, and records the divergence in ``job_runs.details``.
"""

from datetime import date
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import reconciliation as engine
from app.core.config import settings
from app.core.reconciliation_service import ReconciliationError, ReconciliationService
from app.db.models import FundDataSnapshotState, JobRun
from app.jobs import sync_fund_data
from app.repositories.fund_snapshots import SNAPSHOT_STATE_ROW_ID
from app.repositories.funds import search_funds
from app.schemas.funds import FundDetail, NavPoint
from app.services.sample_data import FUNDS

RECONCILED_SOURCE = "eastmoney_direct"


def _nav(day: str, unit: float) -> engine.ReconcilableNavPoint:
    return engine.ReconcilableNavPoint(
        date=date.fromisoformat(day),
        unit_nav=unit,
        accumulated_nav=None,
        daily_change_pct=None,
        source="danjuan",
    )


def _days() -> list[tuple[str, float, float]]:
    return [
        ("2026-07-01", 1.0, 1.0),
        ("2026-07-02", 1.01, 1.01),
        ("2026-07-03", 1.02, 1.02),
    ]


def _fund() -> FundDetail:
    fund = FUNDS[0].model_copy(deep=True)
    fund.source = RECONCILED_SOURCE
    fund.upstream_provider = "eastmoney"
    fund.provider_profile = "eastmoney_snapshot_v1"
    fund.manager_name = "陈安"
    fund.inception_date = "2018-03-15"
    fund.fund_size_billion = 42.6
    fund.navs = [NavPoint(trade_date=d, nav=u, accumulated_nav=a) for d, u, a in _days()]
    return fund


class StubSource:
    name = RECONCILED_SOURCE

    def __init__(self, funds: list[FundDetail]) -> None:
        self._funds = funds

    def fetch_snapshot(self) -> list[FundDetail]:
        return self._funds


class FakeDanjuan:
    source_name = "danjuan"

    def __init__(
        self,
        *,
        navs: list[engine.ReconcilableNavPoint] | None = None,
        raise_navs: bool = False,
        profile: engine.ReconcilableProfile | None = None,
        raise_profile: bool = False,
    ) -> None:
        self._navs = navs
        self._raise_navs = raise_navs
        self._profile = profile
        self._raise_profile = raise_profile

    def fetch_navs(self, code: str, *, since: object = None) -> list[engine.ReconcilableNavPoint]:
        if self._raise_navs:
            raise RuntimeError("danjuan timeout")
        return list(self._navs or [])

    def fetch_profile(self, code: str) -> engine.ReconcilableProfile | None:
        if self._raise_profile:
            raise RuntimeError("profile boom")
        return self._profile

    def fetch_quotes(self, codes: list[str]) -> dict[str, object]:
        raise NotImplementedError("danjuan does not provide quotes")


class FakeSina:
    source_name = "sina"

    def __init__(self, *, acc: float | None = 1.02, raise_quotes: bool = False) -> None:
        self._acc = acc
        self._raise = raise_quotes

    def fetch_navs(self, code: str, *, since: object = None) -> list[engine.ReconcilableNavPoint]:
        raise NotImplementedError("sina does not provide nav history")

    def fetch_profile(self, code: str) -> engine.ReconcilableProfile | None:
        raise NotImplementedError("sina does not provide a profile")

    def fetch_quotes(self, codes: list[str]) -> dict[str, dict[str, float | None]]:
        if self._raise:
            raise RuntimeError("sina timeout")
        return {codes[0]: {"accumulated_nav": self._acc}}


def _consistent_danjuan_navs() -> list[engine.ReconcilableNavPoint]:
    return [_nav(d, u) for d, u, _ in _days()]


def _consistent_danjuan_profile(code: str = "000001") -> engine.ReconcilableProfile:
    return engine.ReconcilableProfile(
        code=code,
        name="稳健成长混合A",
        full_name=None,
        found_date=date(2018, 3, 15),
        company="华夏基金管理有限公司",
        custodian="中国建设银行股份有限公司",
        managers=["陈安"],
        fund_type_raw="混合型-灵活配置",
        benchmark=None,
        scale_text="43.0亿",
        rates=None,
        source="danjuan",
    )


def install_gate(
    monkeypatch: pytest.MonkeyPatch,
    source: StubSource,
    *,
    danjuan: FakeDanjuan,
    sina: FakeSina,
    apply_list: tuple[str, ...] = (RECONCILED_SOURCE,),
) -> None:
    monkeypatch.setattr(settings, "fund_reconcile_enabled", True)
    monkeypatch.setattr(settings, "fund_reconcile_strict", True)
    monkeypatch.setattr(settings, "fund_reconcile_apply_to_sources", list(apply_list))
    monkeypatch.setattr(sync_fund_data, "get_fund_data_source", lambda _: source)

    def fake_builder(src: object) -> ReconciliationService | None:
        if not settings.fund_reconcile_enabled:
            return None
        if getattr(src, "name", None) not in settings.fund_reconcile_apply_to_sources:
            return None
        return ReconciliationService(src, danjuan, sina, settings)

    monkeypatch.setattr(sync_fund_data, "_build_reconciliation_service", fake_builder)


def _report_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    report_dir = tmp_path / "reconciliation"
    monkeypatch.setattr(settings, "fund_reconcile_report_dir", report_dir)
    return report_dir


def _latest_job(db: Session) -> JobRun:
    job = db.scalars(select(JobRun).order_by(JobRun.id.desc())).first()
    assert job is not None
    return job


def test_verified_promotes_and_writes_details_report(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = sync_fund_data.sync_all(db_session, "sample_local")
    active_before = str(baseline["snapshot_generation_id"])
    _report_dir(tmp_path, monkeypatch)

    source = StubSource([_fund()])
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(navs=_consistent_danjuan_navs(), profile=_consistent_danjuan_profile()),
        sina=FakeSina(acc=1.02),
    )

    details = sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)

    assert details["source"] == RECONCILED_SOURCE
    rec = cast(dict[str, Any], details["reconciliation"])
    assert rec["overall_status"] == "verified"
    assert rec["fund_count"] == 1
    assert rec["critical_failure_count"] == 0
    assert rec["funds"][0]["status"] == "verified"
    assert rec["report_path"]
    assert Path(rec["report_path"]).exists()

    # previous generation replaced by the new reconciled one
    state = db_session.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert state is not None
    assert state.active_generation_id != active_before
    job = _latest_job(db_session)
    assert job.status == "success"


def test_tampered_unit_nav_strict_rejects_and_keeps_previous_generation(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = sync_fund_data.sync_all(db_session, "sample_local")
    active_before = str(baseline["snapshot_generation_id"])
    _report_dir(tmp_path, monkeypatch)

    fund = _fund()
    tampered = [_nav(d, u) for d, u, _ in _days()]
    tampered[-1] = engine.ReconcilableNavPoint(
        date=date(2026, 7, 3),
        unit_nav=1.99,  # way beyond tolerance vs primary 1.02
        accumulated_nav=None,
        daily_change_pct=None,
        source="danjuan",
    )
    source = StubSource([fund])
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(navs=tampered, profile=_consistent_danjuan_profile()),
        sina=FakeSina(acc=1.02),
    )

    with pytest.raises(ReconciliationError, match="reconciliation gate rejected"):
        sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)

    db_session.expire_all()
    state = db_session.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert state is not None
    assert state.active_generation_id == active_before
    visible, total = search_funds(db_session, "", page_size=50)
    assert total == len(FUNDS)
    job = _latest_job(db_session)
    assert job.status == "failed"
    assert "reconciliation" in (job.details or {}) or "error" in (job.details or {})


def test_danjuan_unavailable_strict_rejects(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_fund_data.sync_all(db_session, "sample_local")
    _report_dir(tmp_path, monkeypatch)
    source = StubSource([_fund()])
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(raise_navs=True),
        sina=FakeSina(acc=1.02),
    )
    with pytest.raises(ReconciliationError, match="source_unavailable|rejected"):
        sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)
    job = _latest_job(db_session)
    assert job.status == "failed"


def test_danjuan_unavailable_nonstrict_degrades_and_promotes(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_fund_data.sync_all(db_session, "sample_local")
    _report_dir(tmp_path, monkeypatch)
    source = StubSource([_fund()])
    danjuan = FakeDanjuan(raise_navs=True)
    sina = FakeSina(acc=1.02)
    monkeypatch.setattr(settings, "fund_reconcile_enabled", True)
    monkeypatch.setattr(settings, "fund_reconcile_strict", False)
    monkeypatch.setattr(settings, "fund_reconcile_apply_to_sources", [RECONCILED_SOURCE])
    monkeypatch.setattr(sync_fund_data, "get_fund_data_source", lambda _: source)
    monkeypatch.setattr(
        sync_fund_data,
        "_build_reconciliation_service",
        lambda src: ReconciliationService(src, danjuan, sina, settings),
    )

    details = sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)
    rec = cast(dict[str, Any], details["reconciliation"])
    assert rec["overall_status"] in {"unverified", "source_unavailable"}
    assert rec["funds"][0]["status"] == "unverified"
    assert any(
        "downgraded" in w or "unavailable" in w
        for w in rec["funds"][0].get("field_diffs", [])
    ) or rec["funds"][0]["warnings"] >= 1
    assert rec["report_path"] and Path(rec["report_path"]).exists()
    job = _latest_job(db_session)
    assert job.status == "success"


def test_low_nav_coverage_rejects(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_fund_data.sync_all(db_session, "sample_local")
    _report_dir(tmp_path, monkeypatch)
    source = StubSource([_fund()])
    # secondary only shares the latest date -> coverage ~= 1/3 < 0.99
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(navs=[_nav("2026-07-03", 1.02)], profile=_consistent_danjuan_profile()),
        sina=FakeSina(acc=1.02),
    )
    with pytest.raises(ReconciliationError):
        sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)


def test_minor_scale_drift_is_warning_only(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_fund_data.sync_all(db_session, "sample_local")
    _report_dir(tmp_path, monkeypatch)
    source = StubSource([_fund()])
    drifted = engine.ReconcilableProfile(
        code="000001",
        name="稳健成长混合A",
        full_name=None,
        found_date=date(2018, 3, 15),
        company="华夏基金管理有限公司",
        custodian="中国建设银行股份有限公司",
        managers=["陈安"],
        fund_type_raw="混合型-灵活配置",
        benchmark=None,
        scale_text="90.00亿",  # >50% drift, but scale_blocks defaults off
        rates=None,
        source="danjuan",
    )
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(navs=_consistent_danjuan_navs(), profile=drifted),
        sina=FakeSina(acc=1.02),
    )
    details = sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)
    rec = cast(dict[str, Any], details["reconciliation"])
    assert rec["overall_status"] == "verified"
    job = _latest_job(db_session)
    assert job.status == "success"


def test_sina_unavailable_is_not_fatal(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_fund_data.sync_all(db_session, "sample_local")
    _report_dir(tmp_path, monkeypatch)
    source = StubSource([_fund()])
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(navs=_consistent_danjuan_navs(), profile=_consistent_danjuan_profile()),
        sina=FakeSina(raise_quotes=True),
    )
    details = sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)
    rec = cast(dict[str, Any], details["reconciliation"])
    assert rec["funds"][0]["status"] == "verified"
    job = _latest_job(db_session)
    assert job.status == "success"


def test_sina_accumulated_mismatch_is_critical(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_fund_data.sync_all(db_session, "sample_local")
    _report_dir(tmp_path, monkeypatch)
    source = StubSource([_fund()])
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(navs=_consistent_danjuan_navs(), profile=_consistent_danjuan_profile()),
        sina=FakeSina(acc=9.99),  # wildly off primary accumulated 1.02
    )
    with pytest.raises(ReconciliationError, match="reconciliation gate rejected"):
        sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)
    job = _latest_job(db_session)
    assert job.status == "failed"


def test_source_outside_apply_list_skips_gate(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sync_fund_data.sync_all(db_session, "sample_local")
    _report_dir(tmp_path, monkeypatch)
    # A sample_local run must never trigger the gate even if reconciliation is on.
    monkeypatch.setattr(settings, "fund_reconcile_enabled", True)
    details = sync_fund_data.sync_all(db_session, "sample_local")
    assert "reconciliation" not in details


def test_assembly_missing_c2_module_skips_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate C2 not deployed: poisoning sys.modules with None makes
    # importlib.import_module raise ImportError -> the builder must log + return
    # None rather than fail the run.
    monkeypatch.setattr(settings, "fund_reconcile_enabled", True)
    monkeypatch.setattr(settings, "fund_reconcile_apply_to_sources", [RECONCILED_SOURCE])
    monkeypatch.setitem(sys.modules, "app.data_sources.secondary.danjuan", None)
    monkeypatch.setitem(sys.modules, "app.data_sources.secondary.sina", None)

    result = sync_fund_data._build_reconciliation_service(cast(Any, StubSource([])))
    assert result is None


def test_assembly_constructor_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    # C2 present but mis-wired (constructor TypeError) must NOT be swallowed: the
    # gate may not silently close. Inject fake modules whose clients raise on init.
    monkeypatch.setattr(settings, "fund_reconcile_enabled", True)
    monkeypatch.setattr(settings, "fund_reconcile_apply_to_sources", [RECONCILED_SOURCE])

    def _boom(self: object, **_: object) -> None:
        raise TypeError("bad config wiring")

    danjuan_mod = ModuleType("app.data_sources.secondary.danjuan")
    sina_mod = ModuleType("app.data_sources.secondary.sina")
    setattr(danjuan_mod, "DanjuanSource", type("DanjuanSource", (), {"__init__": _boom}))
    setattr(sina_mod, "SinaSource", type("SinaSource", (), {"__init__": _boom}))
    monkeypatch.setitem(sys.modules, "app.data_sources.secondary.danjuan", danjuan_mod)
    monkeypatch.setitem(sys.modules, "app.data_sources.secondary.sina", sina_mod)

    with pytest.raises(TypeError, match="bad config wiring"):
        sync_fund_data._build_reconciliation_service(cast(Any, StubSource([])))


def test_primary_missing_company_custodian_is_skip_not_block(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Real recording scenario: eastmoney primary discloses neither the management
    # company nor the custodian; danjuan does. C1 must treat the one-sided major
    # field as a skip (warning), so the fund still verifies.
    sync_fund_data.sync_all(db_session, "sample_local")
    _report_dir(tmp_path, monkeypatch)
    source = StubSource([_fund()])
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(navs=_consistent_danjuan_navs(), profile=_consistent_danjuan_profile()),
        sina=FakeSina(acc=1.02),
    )
    details = sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)
    rec = cast(dict[str, Any], details["reconciliation"])
    assert rec["overall_status"] == "verified"
    fund_row = rec["funds"][0]
    assert fund_row["status"] == "verified"
    # company / custodian one-sided disclosure surfaces as a warning, not a critical.
    assert fund_row["critical"] is False
    assert fund_row["warnings"] >= 1
