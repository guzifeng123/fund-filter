from collections.abc import Callable
from typing import Literal

from anyio import fail_after, to_thread
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.core.config import settings
from app.db.session import get_db, get_sessionmaker
from app.jobs.sync_fund_data import calculate_metrics, sync_all, sync_fund_navs, sync_fund_profiles, sync_risk_levels
from app.repositories.data_status import get_data_status, list_recent_job_runs
from app.schemas.data import DataStatus

router = APIRouter()


def _unavailable_data_status() -> DataStatus:
    return DataStatus(
        db_connected=False,
        fund_count=0,
        nav_count=0,
        latest_data_updated_at=None,
        freshness_status="empty",
        stale_after_days=settings.fund_data_stale_days,
        last_job=None,
    )


def _read_data_status() -> DataStatus:
    with get_sessionmaker()() as db:
        return get_data_status(db)


def get_data_status_reader() -> Callable[[], DataStatus]:
    return _read_data_status


@router.get("/data/status")
async def status(reader: Callable[[], DataStatus] = Depends(get_data_status_reader)):
    try:
        with fail_after(settings.data_status_timeout_seconds):
            result = await to_thread.run_sync(reader, abandon_on_cancel=True)
        return envelope(result)
    except (SQLAlchemyError, TimeoutError):
        return envelope(_unavailable_data_status())


@router.get("/data/jobs/recent")
def recent_jobs(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    return envelope(list_recent_job_runs(db, limit))


@router.post("/data/sync")
def sync_data(
    task: Literal["all", "profiles", "navs", "metrics", "risk_levels"] = "all",
    db: Session = Depends(get_db),
):
    try:
        if task == "profiles":
            result = sync_fund_profiles(db)
        elif task == "navs":
            result = sync_fund_navs(db)
        elif task == "metrics":
            result = calculate_metrics(db)
        elif task == "risk_levels":
            result = sync_risk_levels(db)
        else:
            result = sync_all(db)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "UNKNOWN_DATA_SOURCE", "message": "未知数据源", "detail": str(exc)},
        ) from exc
    return envelope({"task": task, "result": result})
