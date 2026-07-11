from datetime import datetime, timezone

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Fund, FundNav, JobRun
from app.schemas.data import DataFreshnessStatus, DataStatus, JobRunSummary, LastJob


def _error_detail(details: dict | None) -> str | None:
    if not details:
        return None
    error = details.get("error") or details.get("error_detail")
    return str(error) if error else None


def _job_status(value: str):
    if value in {"running", "success", "failed"}:
        return value
    return "failed"


def _freshness_status(
    fund_count: int,
    nav_count: int,
    latest_data_updated_at: datetime | None,
    last_job_row: JobRun | None,
) -> DataFreshnessStatus:
    if fund_count == 0 or nav_count == 0 or latest_data_updated_at is None:
        return "empty"
    if last_job_row is not None and last_job_row.status == "failed":
        return "failed"
    latest = latest_data_updated_at
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - latest.astimezone(timezone.utc)).days
    if age_days > settings.fund_data_stale_days:
        return "stale"
    return "fresh"


def _to_last_job(row: JobRun) -> LastJob:
    return LastJob(
        name=row.name,
        status=_job_status(row.status),
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        error_detail=_error_detail(row.details),
    )


def _to_job_summary(row: JobRun) -> JobRunSummary:
    return JobRunSummary(
        id=row.id,
        name=row.name,
        status=_job_status(row.status),
        started_at=row.started_at.isoformat(),
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        error_detail=_error_detail(row.details),
        details=row.details,
    )


def get_data_status(db: Session) -> DataStatus:
    db.execute(text("SELECT 1"))
    fund_count = db.scalar(select(func.count()).select_from(Fund)) or 0
    nav_count = db.scalar(select(func.count()).select_from(FundNav)) or 0
    latest_data_updated_at = db.scalar(select(func.max(Fund.data_updated_at)))
    last_job_row = db.scalars(select(JobRun).order_by(desc(JobRun.finished_at), desc(JobRun.started_at)).limit(1)).first()
    last_job = _to_last_job(last_job_row) if last_job_row else None
    return DataStatus(
        db_connected=True,
        fund_count=fund_count,
        nav_count=nav_count,
        latest_data_updated_at=latest_data_updated_at.isoformat() if latest_data_updated_at else None,
        freshness_status=_freshness_status(fund_count, nav_count, latest_data_updated_at, last_job_row),
        stale_after_days=settings.fund_data_stale_days,
        last_job=last_job,
    )


def list_recent_job_runs(db: Session, limit: int = 10) -> list[JobRunSummary]:
    stmt = select(JobRun).order_by(desc(JobRun.started_at), desc(JobRun.id)).limit(limit)
    return [_to_job_summary(row) for row in db.scalars(stmt).all()]
