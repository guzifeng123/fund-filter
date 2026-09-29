from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Fund, FundNav, JobRun
from app.repositories.fund_snapshots import active_snapshot_generation_expression
from app.repositories.funds import fund_data_source_summary, latest_fund_data_updated_at
from app.schemas.data import DataFreshnessStatus, DataStatus, JobRunSummary, JobStatus, LastJob


def _error_detail(details: dict[str, Any] | None) -> str | None:
    if not details:
        return None
    error = details.get("error") or details.get("error_detail")
    return str(error) if error else None


def _job_status(value: str) -> JobStatus:
    if value == "running":
        return "running"
    if value == "success":
        return "success"
    if value == "failed":
        return "failed"
    return "failed"


def _freshness_status(
    fund_count: int,
    nav_count: int,
    latest_data_updated_at: datetime | None,
    last_job_row: JobRun | None,
    now: datetime | None = None,
) -> DataFreshnessStatus:
    if fund_count == 0 or nav_count == 0 or latest_data_updated_at is None:
        return "empty"
    if last_job_row is not None and last_job_row.status == "failed":
        return "failed"
    latest = latest_data_updated_at
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    reference_now = now or datetime.now(timezone.utc)
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=timezone.utc)
    age_days = (reference_now.astimezone(timezone.utc) - latest.astimezone(timezone.utc)).days
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


def get_data_status(db: Session, now: datetime | None = None) -> DataStatus:
    db.execute(text("SELECT 1"))
    generation_id = active_snapshot_generation_expression()
    fund_count = db.scalar(
        select(func.count()).select_from(Fund).where(
            Fund.snapshot_generation_id == generation_id
        )
    ) or 0
    nav_count = db.scalar(
        select(func.count())
        .select_from(FundNav)
        .join(Fund, Fund.code == FundNav.fund_code)
        .where(
            FundNav.snapshot_generation_id == generation_id,
            Fund.snapshot_generation_id == generation_id,
        )
    ) or 0
    latest_data_updated_at = latest_fund_data_updated_at(db)
    last_job_row = db.scalars(select(JobRun).order_by(desc(JobRun.finished_at), desc(JobRun.started_at)).limit(1)).first()
    last_job = _to_last_job(last_job_row) if last_job_row else None
    return DataStatus(
        db_connected=True,
        source=fund_data_source_summary(db),
        fund_count=fund_count,
        nav_count=nav_count,
        latest_data_updated_at=latest_data_updated_at.isoformat() if latest_data_updated_at else None,
        freshness_status=_freshness_status(
            fund_count, nav_count, latest_data_updated_at, last_job_row, now
        ),
        stale_after_days=settings.fund_data_stale_days,
        last_job=last_job,
    )


def list_recent_job_runs(db: Session, limit: int = 10) -> list[JobRunSummary]:
    stmt = select(JobRun).order_by(desc(JobRun.started_at), desc(JobRun.id)).limit(limit)
    return [_to_job_summary(row) for row in db.scalars(stmt).all()]


def list_running_job_runs(db: Session) -> list[JobRunSummary]:
    stmt = select(JobRun).where(JobRun.status == "running").order_by(JobRun.started_at, JobRun.id)
    return [_to_job_summary(row) for row in db.scalars(stmt).all()]
