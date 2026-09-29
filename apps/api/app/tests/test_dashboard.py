from collections.abc import Generator
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import JobRun, RiskAssessment
from app.db.session import get_db
from app.main import app


def _client(db: Session) -> TestClient:
    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_dashboard_uses_persisted_data_status_and_recent_job(db_session: Session) -> None:
    job = JobRun(
        name="sync_fund_navs",
        status="failed",
        started_at=datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 12, 12, 1, tzinfo=timezone.utc),
        details={"error": "upstream timeout"},
    )
    db_session.add(job)
    db_session.commit()

    try:
        response = _client(db_session).get("/api/dashboard")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    dashboard = body["data"]
    assert dashboard["risk_profile"] == "未测评"
    assert dashboard["risk_status"] == "not_assessed"
    assert dashboard["risk_notice"] == "尚未完成风险测评"
    assert dashboard["health"] == "unavailable"
    assert dashboard["portfolio_health_status"] == "unavailable"
    assert dashboard["watchlist_updated_at"] is None
    assert dashboard["watchlist_status"] == "not_configured"
    assert dashboard["alerts"] == []
    assert dashboard["alerts_status"] == "not_configured"
    assert dashboard["data_status"]["source"] == "sample_local"
    assert dashboard["data_status"]["fund_count"] == 4
    assert job.finished_at is not None
    assert dashboard["recent_job"] == {
        "id": job.id,
        "name": "sync_fund_navs",
        "status": "failed",
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat(),
        "error_detail": "upstream timeout",
        "details": {"error": "upstream timeout"},
    }
    assert body["meta"]["source"] == dashboard["data_status"]["source"]
    assert body["meta"]["data_updated_at"] == dashboard["data_status"]["latest_data_updated_at"]
    assert "补偿同步" not in response.text
    assert "当前组合未触发再平衡阈值" not in response.text


def test_dashboard_exposes_real_risk_assessment_without_fabricating_alerts(
    db_session: Session,
) -> None:
    db_session.add(
        RiskAssessment(
            user_id="local-user",
            risk_profile="C4",
            answers={"score": 23, "items": []},
            assessed_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    try:
        response = _client(db_session).get("/api/dashboard")
    finally:
        app.dependency_overrides.clear()

    dashboard = response.json()["data"]
    assert response.status_code == 200
    assert dashboard["risk_profile"] == "C4"
    assert dashboard["risk_status"] == "valid"
    assert dashboard["risk_notice"] == "风险测评仍在有效期内"
    assert dashboard["alerts"] == []
    assert dashboard["alerts_status"] == "not_configured"


def test_dashboard_openapi_response_has_a_concrete_schema() -> None:
    response_schema = app.openapi()["paths"]["/api/dashboard"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]

    assert response_schema
    assert response_schema["$ref"].endswith("ApiResponse_DashboardData_")
