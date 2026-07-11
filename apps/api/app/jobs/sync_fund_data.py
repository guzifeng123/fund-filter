from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.data_sources import get_fund_data_source
from app.db.models import Fund, JobRun
from app.db.session import get_sessionmaker
from app.repositories.funds import upsert_fund_detail
from app.repositories.portfolios import ensure_default_portfolios


def _run_job(db: Session, name: str, fn: Callable[[], dict]) -> dict:
    job = JobRun(name=name, status="running", started_at=datetime.now(timezone.utc), details={})
    db.add(job)
    db.commit()
    try:
        details = fn()
        job.status = "success"
        job.finished_at = datetime.now(timezone.utc)
        job.details = details
        db.commit()
        return details
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.finished_at = datetime.now(timezone.utc)
        job.details = {"error": str(exc)}
        db.add(job)
        db.commit()
        raise


def sync_fund_profiles(db: Session, source_name: str | None = None) -> dict:
    source = get_fund_data_source(source_name)

    def task() -> dict:
        funds = source.fetch_fund_profiles()
        for fund in funds:
            upsert_fund_detail(db, fund)
        ensure_default_portfolios(db)
        return {"source": source.name, "fund_count": len(funds)}

    return _run_job(db, "sync_fund_profiles", task)


def sync_fund_navs(db: Session, source_name: str | None = None) -> dict:
    source = get_fund_data_source(source_name)

    def task() -> dict:
        funds = source.fetch_fund_navs()
        nav_count = 0
        for fund in funds:
            upsert_fund_detail(db, fund)
            nav_count += len(fund.navs)
        return {"source": source.name, "fund_count": len(funds), "nav_count": nav_count}

    return _run_job(db, "sync_fund_navs", task)


def sync_risk_levels(db: Session, source_name: str | None = None) -> dict:
    source = get_fund_data_source(source_name)

    def task() -> dict:
        levels = source.fetch_risk_levels()
        updated = 0
        for code, risk_level in levels.items():
            row = db.get(Fund, code)
            if row is None:
                continue
            row.risk_level = risk_level
            updated += 1
        return {"source": source.name, "updated_count": updated}

    return _run_job(db, "sync_risk_levels", task)


def calculate_metrics(db: Session, source_name: str | None = None) -> dict:
    source = get_fund_data_source(source_name)

    def task() -> dict:
        funds = source.fetch_fund_profiles()
        for fund in funds:
            upsert_fund_detail(db, fund)
        return {"source": source.name, "metric_count": len(funds)}

    return _run_job(db, "calculate_metrics", task)


def sync_all(db: Session, source_name: str | None = None) -> dict:
    return {
        "profiles": sync_fund_profiles(db, source_name),
        "navs": sync_fund_navs(db, source_name),
        "risk_levels": sync_risk_levels(db, source_name),
        "metrics": calculate_metrics(db, source_name),
    }


def run() -> None:
    db = get_sessionmaker()()
    try:
        sync_all(db)
    except SQLAlchemyError:
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
