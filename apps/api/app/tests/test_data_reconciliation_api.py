"""Read-only GET /api/data/reconciliation endpoint tests (C3)."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.reconciliation_service import THRESHOLD_VERSION
from app.db.session import get_db
from app.jobs import sync_fund_data
from app.main import app
from app.tests.test_reconciliation_gate import (
    RECONCILED_SOURCE,
    FakeDanjuan,
    FakeSina,
    StubSource,
    _consistent_danjuan_navs,
    _consistent_danjuan_profile,
    _fund,
    install_gate,
)


def _client(db: Session) -> TestClient:
    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_reconciliation_api_empty_state(db_session: Session) -> None:
    try:
        response = _client(db_session).get("/api/data/reconciliation")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["overall_status"] == "never_run"
    assert body["data"]["funds"] == []
    assert body["data"]["threshold_version"] == THRESHOLD_VERSION
    assert body["meta"]["disclaimer"]


def test_reconciliation_api_returns_latest_summary(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "fund_reconcile_report_dir", tmp_path / "reconciliation")
    source = StubSource([_fund()])
    install_gate(
        monkeypatch,
        source,
        danjuan=FakeDanjuan(navs=_consistent_danjuan_navs(), profile=_consistent_danjuan_profile()),
        sina=FakeSina(acc=1.02),
    )
    sync_fund_data.sync_all(db_session, RECONCILED_SOURCE)

    try:
        response = _client(db_session).get("/api/data/reconciliation")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    report = body["data"]
    assert report["overall_status"] == "verified"
    assert report["source"] == RECONCILED_SOURCE
    assert report["fund_count"] == 1
    assert report["funds"][0]["code"] == "000001"
    assert report["funds"][0]["status"] == "verified"
    assert 0.0 <= report["funds"][0]["nav_coverage"] <= 1.0
    assert body["meta"]["source"] == RECONCILED_SOURCE
