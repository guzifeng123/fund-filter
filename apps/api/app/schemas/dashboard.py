from typing import Literal

from pydantic import BaseModel

from app.schemas.data import DataStatus, JobRunSummary

FeatureStatus = Literal["available", "unavailable", "not_configured"]
RiskStatus = Literal["not_assessed", "valid", "expires_soon", "expired"]


class DashboardData(BaseModel):
    risk_profile: str
    risk_status: RiskStatus
    risk_notice: str
    health: str
    portfolio_health_status: FeatureStatus
    watchlist_updated_at: str | None
    watchlist_status: FeatureStatus
    alerts: list[str]
    alerts_status: FeatureStatus
    data_status: DataStatus
    recent_job: JobRunSummary | None
