from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.nav_series_quality import THRESHOLD_VERSION
from app.core.snapshot_quality import SnapshotQualityError
from app.db.models import FundDataSnapshotState, JobRun
from app.db.session import get_db
from app.jobs import sync_fund_data
from app.main import app
from app.repositories.fund_snapshots import SNAPSHOT_STATE_ROW_ID
from app.repositories.funds import search_funds
from app.schemas.funds import FundDetail, NavPoint
from app.services.sample_data import FUNDS


class StubSource:
    name = "b2_stub"

    def __init__(self, funds: list[FundDetail]) -> None:
        self._funds = funds

    def fetch_snapshot(self) -> list[FundDetail]:
        return self._funds


def install_source(monkeypatch: pytest.MonkeyPatch, source: StubSource) -> None:
    monkeypatch.setattr(sync_fund_data, "get_fund_data_source", lambda _: source)


def day_navs(*pairs: tuple[str, float, float]) -> list[NavPoint]:
    return [NavPoint(trade_date=d, nav=n, accumulated_nav=a) for d, n, a in pairs]


def clean_fund() -> FundDetail:
    fund = FUNDS[0].model_copy(deep=True)
    fund.source = StubSource.name
    fund.navs = day_navs(("2026-07-01", 1.0, 1.0), ("2026-07-02", 1.01, 1.01))
    return fund


def _client(db: Session) -> TestClient:
    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_series_error_rejects_candidate_and_keeps_previous_generation(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = sync_fund_data.sync_all(db_session, "sample_local")
    active_before = str(baseline["snapshot_generation_id"])

    bad = clean_fund()
    bad.navs = day_navs(("2026-07-01", 1.0, 1.0), ("2026-07-01", 1.01, 1.01))
    install_source(monkeypatch, StubSource([bad]))

    with pytest.raises(SnapshotQualityError, match="duplicate NAV trade_date"):
        sync_fund_data.sync_all(db_session, StubSource.name)

    db_session.expire_all()
    state = db_session.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert state is not None
    assert state.active_generation_id == active_before
    visible, total = search_funds(db_session, "", page_size=20)
    assert total == len(FUNDS)
    latest_job = db_session.scalars(
        select(JobRun).order_by(JobRun.id.desc())
    ).first()
    assert latest_job is not None
    assert latest_job.status == "failed"


def test_series_warning_lands_in_job_details(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_gap_days", 5)
    fund = clean_fund()
    fund.navs = day_navs(("2026-07-01", 1.0, 1.0), ("2026-07-20", 1.01, 1.01))
    install_source(monkeypatch, StubSource([fund]))

    details = sync_fund_data.sync_all(db_session, StubSource.name)

    warning_count = details["quality_warning_count"]
    assert isinstance(warning_count, int) and warning_count >= 1
    stored_warnings = details["quality_warnings"]
    assert isinstance(stored_warnings, list)
    codes = {
        warning.get("code")
        for warning in stored_warnings
        if isinstance(warning, dict)
    }
    assert "nav_series_gap_exceeded" in codes
    latest_job = db_session.scalars(
        select(JobRun).order_by(JobRun.id.desc())
    ).first()
    assert latest_job is not None
    assert latest_job.status == "success"
    assert latest_job.details["quality_warning_count"] == details["quality_warning_count"]


def test_data_quality_api_reports_latest_sync(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_gap_days", 5)
    fund = clean_fund()
    fund.navs = day_navs(("2026-07-01", 1.0, 1.0), ("2026-07-20", 1.01, 1.01))
    install_source(monkeypatch, StubSource([fund]))
    sync_fund_data.sync_all(db_session, StubSource.name)

    try:
        response = _client(db_session).get("/api/data/quality")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    report = body["data"]
    assert report["threshold_version"] == THRESHOLD_VERSION
    assert report["source"] == StubSource.name
    assert report["job_status"] == "success"
    assert "nav_series_gap_exceeded" in report["issue_codes"]
    assert report["funds_with_issues"] == [fund.code]
    assert body["meta"]["disclaimer"]


def test_data_quality_api_handles_empty_history(db_session: Session) -> None:
    try:
        response = _client(db_session).get("/api/data/quality")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    report = response.json()["data"]
    assert report["threshold_version"] == THRESHOLD_VERSION
    assert report["issue_count"] == 0
    assert report["issues"] == []
