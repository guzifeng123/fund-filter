from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.nav_quality import NavQualityWarningPayload
from app.core.nav_series_quality import assess_nav_series_quality
from app.core.profile_quality import assess_profile_quality
from app.core.snapshot_quality import (
    SnapshotQualityError,
    SnapshotQualityThresholds,
    validate_snapshot_quality,
)
from app.data_sources.base import FundDataSource
from app.data_sources import get_fund_data_source
from app.db.models import FundDataSnapshot, JobRun, JsonObject
from app.db.session import get_sessionmaker
from app.repositories.fund_snapshots import (
    lock_snapshot_state,
    promote_snapshot,
    stage_snapshot,
    validate_staged_snapshot,
)
from app.repositories.fund_archives import (
    GenerationArchive,
    append_archive_details,
    archive_generation,
    resolve_archive_root,
)
from app.repositories.funds import (
    stage_funds_batch,
    upsert_fund_metrics,
    upsert_fund_navs,
    upsert_fund_profile,
)
from app.repositories.portfolios import ensure_default_portfolios
from app.schemas.funds import FundDetail


NAV_WARNING_DETAIL_LIMIT = 100
ATOMIC_PROMOTION_BOUNDARY = "atomic_promotion"


class JobAlreadyRunningError(RuntimeError):
    pass


def _warning_json(payload: NavQualityWarningPayload) -> JsonObject:
    return {
        "code": payload["code"],
        "fund_code": payload["fund_code"],
        "trade_date": payload["trade_date"],
        "field": payload["field"],
        "value": payload["value"],
        "minimum": payload["minimum"],
        "maximum": payload["maximum"],
        "message": payload["message"],
    }


def _new_snapshot_generation_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"snapshot-{timestamp}-{uuid4().hex[:12]}"


def _validate_complete_snapshot(funds: list[FundDetail]) -> None:
    if not funds:
        raise ValueError("fund data source returned an empty snapshot; refusing promotion")
    seen_codes: set[str] = set()
    duplicate_codes: set[str] = set()
    for fund in funds:
        if fund.code in seen_codes:
            duplicate_codes.add(fund.code)
        seen_codes.add(fund.code)
    if duplicate_codes:
        raise ValueError(
            "fund data source returned duplicate fund codes: "
            + ", ".join(sorted(duplicate_codes))
        )


def _thresholds_json(thresholds: SnapshotQualityThresholds) -> JsonObject:
    return {
        "min_fund_count": thresholds.min_fund_count,
        "min_nav_coverage_ratio": thresholds.min_nav_coverage_ratio,
        "max_latest_nav_age_days": thresholds.max_latest_nav_age_days,
        "max_fund_count_drop_ratio": thresholds.max_fund_count_drop_ratio,
    }


def _run_job(
    db: Session,
    name: str,
    fn: Callable[[], JsonObject],
) -> JsonObject:
    started_at = datetime.now(timezone.utc)
    stale_before = started_at - timedelta(minutes=settings.fund_sync_lock_timeout_minutes)
    db.execute(
        update(JobRun)
        .where(JobRun.name == name, JobRun.status == "running", JobRun.started_at < stale_before)
        .values(
            status="failed",
            finished_at=started_at,
            details={"error": "running job lock expired before a new run started"},
        )
    )
    db.commit()
    job = JobRun(name=name, status="running", started_at=started_at, details={})
    db.add(job)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise JobAlreadyRunningError(f"job {name} is already running") from exc
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


def _run_atomic_snapshot_job(
    db: Session,
    *,
    source_name: str | None,
    job_name: str,
    requested_task: str,
    source_override: FundDataSource | None = None,
) -> JsonObject:
    source = source_override or get_fund_data_source(source_name)

    def task() -> JsonObject:
        funds = source.fetch_snapshot()
        _validate_complete_snapshot(funds)
        generation_id = _new_snapshot_generation_id()
        state = lock_snapshot_state(db)
        previous_generation_id = state.active_generation_id
        previous_snapshot = db.get(FundDataSnapshot, previous_generation_id)
        previous_fund_count = previous_snapshot.fund_count if previous_snapshot else 0
        quality_thresholds = validate_snapshot_quality(
            funds,
            source_name=source.name,
            previous_fund_count=previous_fund_count,
        )
        # B2: per-fund NAV series + profile field quality gate, at the same layer
        # as validate_snapshot_quality (fetch done, staging not yet). Structural
        # errors reject the candidate generation so the previous generation keeps
        # serving; warnings flow into the existing quality_warnings contract.
        series_report = assess_nav_series_quality(funds, source_name=source.name)
        profile_report = assess_profile_quality(funds, source_name=source.name)
        if (series_report.errors and settings.fund_nav_series_reject_errors) or (
            profile_report.errors and settings.fund_profile_reject_errors
        ):
            first_error = series_report.errors[0] if series_report.errors else profile_report.errors[0]
            raise SnapshotQualityError(
                "snapshot rejected by NAV series/profile quality gate: "
                f"{first_error.code} on fund {first_error.fund_code}: "
                f"{first_error.message}"
            )
        pre_stage_warnings: list[NavQualityWarningPayload] = [
            issue.as_payload() for issue in series_report.warnings
        ]
        pre_stage_warnings.extend(issue.as_payload() for issue in profile_report.warnings)
        nav_count = sum(len(fund.navs) for fund in funds)
        snapshot = stage_snapshot(
            db,
            generation_id=generation_id,
            source=source.name,
            fund_count=len(funds),
            nav_count=nav_count,
            metric_count=len(funds),
        )

        quality_warnings: list[NavQualityWarningPayload] = []
        archive_result: GenerationArchive | None = None
        archive_warning: str | None = None
        if settings.fund_archive_enabled and previous_snapshot is not None:
            try:
                archive_result = archive_generation(
                    db,
                    previous_generation_id,
                    archive_root=resolve_archive_root(settings.fund_archive_dir),
                )
            except Exception as exc:  # pragma: no cover - defensive by contract
                archive_warning = f"fund archive failed: {exc}"
        if settings.fund_write_batch_enabled:
            quality_warnings = stage_funds_batch(
                db,
                funds,
                generation_id,
                batch_size=settings.fund_write_batch_size,
            )
        else:
            for fund in funds:
                upsert_fund_profile(db, fund, generation_id)
                db.flush()
                upsert_fund_metrics(db, fund, generation_id)
                quality_warnings.extend(upsert_fund_navs(db, fund, generation_id))
        ensure_default_portfolios(db)
        validate_staged_snapshot(db, snapshot)
        promote_snapshot(db, state=state, snapshot=snapshot)

        details: JsonObject = {
            "source": source.name,
            "requested_task": requested_task,
            "effective_scope": "full_snapshot",
            "snapshot_generation_id": generation_id,
            "previous_snapshot_generation_id": previous_generation_id,
            "generation_boundary": ATOMIC_PROMOTION_BOUNDARY,
            "fund_count": len(funds),
            "nav_count": nav_count,
            "metric_count": len(funds),
            "updated_count": len(funds),
            "write_path": "batch" if settings.fund_write_batch_enabled else "per_point",
            "snapshot_quality_thresholds": _thresholds_json(quality_thresholds),
        }
        if archive_result is not None:
            append_archive_details(details, archive_result)
        elif archive_warning is not None:
            details["archive_warning"] = archive_warning
        quality_warning_payloads = [*pre_stage_warnings, *quality_warnings]
        if quality_warning_payloads:
            details.update(
                {
                    "quality_warning_count": len(quality_warning_payloads),
                    "quality_warnings": [
                        _warning_json(warning)
                        for warning in quality_warning_payloads[:NAV_WARNING_DETAIL_LIMIT]
                    ],
                    "quality_warnings_truncated": len(quality_warning_payloads)
                    > NAV_WARNING_DETAIL_LIMIT,
                }
            )
        # Optional: adapters such as eastmoney_direct publish an incremental/full
        # pull report (mode, per-fund nav fetch mode, skipped discovery). This is
        # purely additive and ignored by sources that do not set the attribute.
        incremental_report = getattr(source, "last_run_report", None)
        if isinstance(incremental_report, dict) and incremental_report:
            details["source_run_report"] = incremental_report
        return details

    return _run_job(db, job_name, task)


def sync_fund_profiles(
    db: Session,
    source_name: str | None = None,
) -> JsonObject:
    return _run_atomic_snapshot_job(
        db,
        source_name=source_name,
        job_name="sync_fund_profiles",
        requested_task="profiles",
    )


def sync_fund_navs(
    db: Session,
    source_name: str | None = None,
) -> JsonObject:
    return _run_atomic_snapshot_job(
        db,
        source_name=source_name,
        job_name="sync_fund_navs",
        requested_task="navs",
    )


def sync_risk_levels(
    db: Session,
    source_name: str | None = None,
) -> JsonObject:
    return _run_atomic_snapshot_job(
        db,
        source_name=source_name,
        job_name="sync_risk_levels",
        requested_task="risk_levels",
    )


def calculate_metrics(
    db: Session,
    source_name: str | None = None,
) -> JsonObject:
    return _run_atomic_snapshot_job(
        db,
        source_name=source_name,
        job_name="calculate_metrics",
        requested_task="metrics",
    )


def sync_all(
    db: Session,
    source_name: str | None = None,
    *,
    source_override: FundDataSource | None = None,
) -> JsonObject:
    return _run_atomic_snapshot_job(
        db,
        source_name=source_name,
        job_name="sync_all",
        requested_task="all",
        source_override=source_override,
    )


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
