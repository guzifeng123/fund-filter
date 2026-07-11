from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.risk_assessments import latest_assessment

router = APIRouter()


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    risk = latest_assessment(db)
    risk_profile = risk.risk_profile if risk else "未测评"
    risk_alert = (
        "风险测评即将过期，请重新评估"
        if risk and risk.expires_soon
        else "风险测评已过期，请重新评估"
        if risk and risk.is_expired
        else "风险测评仍在有效期内"
        if risk
        else "尚未完成风险测评"
    )
    return envelope(
        {
            "risk_profile": risk_profile,
            "health": "稳健",
            "watchlist_updated_at": "2026-07-08T20:30:00+08:00",
            "alerts": [risk_alert, "自选基金净值已完成 20:30 补偿同步", "当前组合未触发再平衡阈值"],
        }
    )
