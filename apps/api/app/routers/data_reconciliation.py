from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.models import JobRun
from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.data_reconciliation import (
    DataReconciliationReport,
    FundReconciliationView,
)

router = APIRouter()

# Never echo more than this many per-fund rows into the envelope; the full report
# always lives on disk under FUND_RECONCILE_REPORT_DIR.
FUND_VIEW_LIMIT = 200


def _to_fund_view(raw: dict[str, Any]) -> FundReconciliationView:
    return FundReconciliationView(
        code=str(raw.get("code", "")),
        status=raw.get("status", "unverified"),
        critical=bool(raw.get("critical", False)),
        nav_coverage=(
            float(raw["nav_coverage"]) if raw.get("nav_coverage") is not None else None
        ),
        nav_agreement=(
            float(raw["nav_agreement"]) if raw.get("nav_agreement") is not None else None
        ),
        critical_failures=int(raw.get("critical_failures", 0)),
        critical_failure_details=[
            str(item) for item in raw.get("critical_failure_details", [])
        ],
        nav_mismatch_points=[str(item) for item in raw.get("nav_mismatch_points", [])],
        warnings=int(raw.get("warnings", 0)),
        field_diffs=[item for item in raw.get("field_diffs", []) if isinstance(item, dict)],
        source_values=dict(raw.get("source_values", {}) or {}),
    )


def _empty_report(threshold_version: str) -> DataReconciliationReport:
    return DataReconciliationReport(
        threshold_version=threshold_version,
        overall_status="never_run",
        sources=[],
        generated_at=None,
        source=None,
        snapshot_generation_id=None,
        job_name=None,
        job_status=None,
        started_at=None,
        finished_at=None,
        fund_count=0,
        critical_failure_count=0,
        warning_count=0,
        funds=[],
        funds_truncated=False,
        report_path=None,
        error=None,
    )


def build_data_reconciliation_report(db: Session) -> DataReconciliationReport:
    row = db.scalars(
        select(JobRun)
        .order_by(desc(JobRun.finished_at), desc(JobRun.started_at), desc(JobRun.id))
        .limit(1)
    ).first()
    if row is None:
        return _empty_report("reconciliation/v1")

    details: dict[str, Any] = dict(row.details or {})
    threshold_version = str(details.get("reconcile_threshold_version", "reconciliation/v1"))
    rec = details.get("reconciliation")

    if isinstance(rec, dict) and rec:
        raw_funds = rec.get("funds") or []
        funds = [
            _to_fund_view(item) for item in raw_funds if isinstance(item, dict)
        ]
        truncated = len(funds) > FUND_VIEW_LIMIT
        return DataReconciliationReport(
            threshold_version=threshold_version,
            overall_status=rec.get("overall_status", "unverified"),
            sources=[str(s) for s in (rec.get("sources") or [])],
            generated_at=rec.get("generated_at"),
            source=details.get("source"),
            snapshot_generation_id=details.get("snapshot_generation_id"),
            job_name=row.name,
            job_status=row.status,
            started_at=row.started_at.isoformat() if row.started_at else None,
            finished_at=row.finished_at.isoformat() if row.finished_at else None,
            fund_count=int(rec.get("fund_count", len(funds))),
            critical_failure_count=int(rec.get("critical_failure_count", 0)),
            warning_count=int(rec.get("warning_count", 0)),
            funds=funds[:FUND_VIEW_LIMIT],
            funds_truncated=truncated,
            report_path=rec.get("report_path"),
            error=details.get("error") if isinstance(details.get("error"), str) else None,
        )

    # No reconciliation payload on the latest run. If that run failed with a
    # reconciliation rejection the error string is the audit trail; otherwise the
    # endpoint simply reports that reconciliation has never run.
    error = details.get("error")
    looks_like_reject = isinstance(error, str) and "reconcil" in error.lower()
    report = _empty_report(threshold_version)
    report.job_name = row.name
    report.job_status = row.status
    report.started_at = row.started_at.isoformat() if row.started_at else None
    report.finished_at = row.finished_at.isoformat() if row.finished_at else None
    report.source = details.get("source")
    report.snapshot_generation_id = details.get("snapshot_generation_id")
    if looks_like_reject:
        report.overall_status = "rejected"
        report.error = str(error)
    return report


@router.get("/data/reconciliation", response_model=ApiResponse[DataReconciliationReport])
def data_reconciliation(db: Session = Depends(get_db)) -> dict[str, Any]:
    report = build_data_reconciliation_report(db)
    return envelope(report, source=report.source or "sample_local")
