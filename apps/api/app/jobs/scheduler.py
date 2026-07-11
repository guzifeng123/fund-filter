from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.db.session import get_sessionmaker
from app.jobs.sync_fund_data import sync_all

_scheduler: BackgroundScheduler | None = None


def _scheduled_sync() -> None:
    db = get_sessionmaker()()
    try:
        sync_all(db)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.fund_sync_scheduler_enabled:
        return None
    if _scheduler and _scheduler.running:
        return _scheduler
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        _scheduled_sync,
        trigger="interval",
        hours=settings.fund_sync_interval_hours,
        id="fund_data_sync",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
