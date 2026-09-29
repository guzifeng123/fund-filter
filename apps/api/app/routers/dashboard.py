from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Any

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.data_status import get_data_status, list_recent_job_runs
from app.repositories.risk_assessments import latest_assessment
from app.schemas.common import ApiResponse
from app.schemas.dashboard import DashboardData, RiskStatus

router = APIRouter()


@router.get("/dashboard", response_model=ApiResponse[DashboardData])
def dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    risk = latest_assessment(db)
    risk_status: RiskStatus
    if risk is None:
        risk_profile = "未测评"
        risk_status = "not_assessed"
        risk_notice = "尚未完成风险测评"
    elif risk.is_expired:
        risk_profile = risk.risk_profile
        risk_status = "expired"
        risk_notice = "风险测评已过期，请重新评估"
    elif risk.expires_soon:
        risk_profile = risk.risk_profile
        risk_status = "expires_soon"
        risk_notice = "风险测评即将过期，请重新评估"
    else:
        risk_profile = risk.risk_profile
        risk_status = "valid"
        risk_notice = "风险测评仍在有效期内"

    data_status = get_data_status(db)
    recent_jobs = list_recent_job_runs(db, limit=1)
    return envelope(
        DashboardData(
            risk_profile=risk_profile,
            risk_status=risk_status,
            risk_notice=risk_notice,
            health="unavailable",
            portfolio_health_status="unavailable",
            watchlist_updated_at=None,
            watchlist_status="not_configured",
            alerts=[],
            alerts_status="not_configured",
            data_status=data_status,
            recent_job=recent_jobs[0] if recent_jobs else None,
        ),
        source=data_status.source,
        data_updated_at=data_status.latest_data_updated_at,
    )
