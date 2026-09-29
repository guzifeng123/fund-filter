from typing import Literal, TypedDict

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

from app.core.config import settings
from app.db.session import get_sessionmaker
from app.jobs.sync_fund_data import sync_all

_scheduler: BackgroundScheduler | None = None


class SchedulerRuntimeStatus(TypedDict):
    enabled: bool
    running: bool
    schedule_mode: Literal["interval", "cron"]
    schedule_expression: str
    timezone: str
    jitter_seconds: int
    misfire_grace_seconds: int
    next_run_at: str | None


def _scheduled_sync() -> None:
    db = get_sessionmaker()()
    try:
        sync_all(db)
    finally:
        db.close()


def _sync_trigger() -> CronTrigger | IntervalTrigger:
    if settings.fund_sync_schedule_mode == "cron":
        fields = settings.fund_sync_cron.split()
        if len(fields) != 5:
            raise ValueError("FUND_SYNC_CRON must contain five fields: minute hour day month day_of_week")
        minute, hour, day, month, day_of_week = fields
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone="Asia/Shanghai",
            jitter=settings.fund_sync_jitter_seconds,
        )
    return IntervalTrigger(
        minutes=settings.fund_sync_interval_minutes,
        timezone="Asia/Shanghai",
        jitter=settings.fund_sync_jitter_seconds,
    )


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.fund_sync_scheduler_enabled:
        return None
    if _scheduler and _scheduler.running:
        return _scheduler
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        _scheduled_sync,
        trigger=_sync_trigger(),
        id="fund_data_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.fund_sync_misfire_grace_seconds,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def scheduler_runtime_status() -> SchedulerRuntimeStatus:
    job = _scheduler.get_job("fund_data_sync") if _scheduler and _scheduler.running else None
    next_run_time = job.next_run_time if job else None
    schedule_mode: Literal["interval", "cron"] = (
        "cron" if settings.fund_sync_schedule_mode == "cron" else "interval"
    )
    schedule_expression = (
        settings.fund_sync_cron
        if schedule_mode == "cron"
        else f"every {settings.fund_sync_interval_minutes} minute(s)"
    )
    return {
        "enabled": settings.fund_sync_scheduler_enabled,
        "running": bool(_scheduler and _scheduler.running),
        "schedule_mode": schedule_mode,
        "schedule_expression": schedule_expression,
        "timezone": "Asia/Shanghai",
        "jitter_seconds": settings.fund_sync_jitter_seconds,
        "misfire_grace_seconds": settings.fund_sync_misfire_grace_seconds,
        "next_run_at": next_run_time.isoformat() if next_run_time else None,
    }
