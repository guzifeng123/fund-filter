from collections.abc import Callable
from typing import Any

from anyio import fail_after, to_thread
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.core.config import settings
from app.db.session import get_db, get_sessionmaker
from app.jobs.sync_fund_data import (
    JobAlreadyRunningError,
    calculate_metrics,
    sync_all,
    sync_fund_navs,
    sync_fund_profiles,
    sync_risk_levels,
)
from app.jobs.scheduler import scheduler_runtime_status
from app.repositories.data_status import get_data_status, list_recent_job_runs, list_running_job_runs
from app.schemas.common import ApiErrorResponse, ApiResponse
from app.schemas.data import (
    DataStatus,
    DataSyncResult,
    DataSyncTask,
    JobRunSummary,
    SchedulerStatus,
)

router = APIRouter()


def _unavailable_data_status() -> DataStatus:
    return DataStatus(
        db_connected=False,
        source="unavailable",
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


@router.get("/data/status", response_model=ApiResponse[DataStatus])
async def status(
    reader: Callable[[], DataStatus] = Depends(get_data_status_reader),
) -> dict[str, Any]:
    try:
        with fail_after(settings.data_status_timeout_seconds):
            result = await to_thread.run_sync(reader, abandon_on_cancel=True)
        return envelope(
            result,
            source=result.source,
            data_updated_at=result.latest_data_updated_at,
        )
    except (SQLAlchemyError, TimeoutError):
        result = _unavailable_data_status()
        return envelope(result, source=result.source, data_updated_at=None)


@router.get("/data/jobs/recent", response_model=ApiResponse[list[JobRunSummary]])
def recent_jobs(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return envelope(list_recent_job_runs(db, limit))


@router.get("/data/scheduler/status", response_model=ApiResponse[SchedulerStatus])
def scheduler_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    return envelope(
        SchedulerStatus(
            **scheduler_runtime_status(),
            running_tasks=list_running_job_runs(db),
        )
    )


@router.post(
    "/data/sync",
    response_model=ApiResponse[DataSyncResult],
    responses={400: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
)
def sync_data(
    task: DataSyncTask = "all",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
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
    except JobAlreadyRunningError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "DATA_SYNC_ALREADY_RUNNING", "message": "同类数据同步任务正在运行", "detail": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "UNKNOWN_DATA_SOURCE", "message": "未知数据源", "detail": str(exc)},
        ) from exc
    return envelope({"task": task, "result": result}, source=settings.fund_data_source)
