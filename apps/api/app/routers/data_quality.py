from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.core.nav_series_quality import THRESHOLD_VERSION
from app.db.models import JobRun
from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.schemas.data_quality import DataQualityIssue, DataQualityReport

router = APIRouter()


def _to_issue(raw: dict[str, Any]) -> DataQualityIssue:
    return DataQualityIssue(
        code=str(raw.get("code", "")),
        fund_code=str(raw.get("fund_code", "")),
        trade_date=str(raw.get("trade_date", "")),
        field=str(raw.get("field", "")),
        message=str(raw.get("message", "")),
        value=raw.get("value"),
        minimum=raw.get("minimum"),
        maximum=raw.get("maximum"),
    )


def build_data_quality_report(db: Session) -> DataQualityReport:
    row = db.scalars(
        select(JobRun)
        .order_by(desc(JobRun.finished_at), desc(JobRun.started_at), desc(JobRun.id))
        .limit(1)
    ).first()
    if row is None:
        return DataQualityReport(
            threshold_version=THRESHOLD_VERSION,
            source=None,
            snapshot_generation_id=None,
            previous_snapshot_generation_id=None,
            job_name=None,
            job_status="running",
            started_at=None,
            finished_at=None,
            issue_count=0,
            issue_codes={},
            funds_with_issues=[],
            issues=[],
            issues_truncated=False,
        )

    details: dict[str, Any] = dict(row.details or {})
    raw_issues = details.get("quality_warnings") or []
    issues = [_to_issue(item) for item in raw_issues if isinstance(item, dict)]
    code_counts = Counter(issue.code for issue in issues if issue.code)
    funds_with_issues = sorted({issue.fund_code for issue in issues if issue.fund_code})
    error = details.get("error")
    status = row.status if row.status in {"running", "success", "failed"} else "failed"
    return DataQualityReport(
        threshold_version=THRESHOLD_VERSION,
        source=details.get("source"),
        snapshot_generation_id=details.get("snapshot_generation_id"),
        previous_snapshot_generation_id=details.get("previous_snapshot_generation_id"),
        job_name=row.name,
        job_status=status,  # type: ignore[arg-type]
        started_at=row.started_at.isoformat() if row.started_at else None,
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        issue_count=int(details.get("quality_warning_count", len(issues))),
        issue_codes=dict(sorted(code_counts.items())),
        funds_with_issues=funds_with_issues,
        issues=issues,
        issues_truncated=bool(details.get("quality_warnings_truncated", False)),
        snapshot_quality_thresholds=details.get("snapshot_quality_thresholds"),
        error=str(error) if error is not None else None,
    )


@router.get("/data/quality", response_model=ApiResponse[DataQualityReport])
def data_quality(db: Session = Depends(get_db)) -> dict[str, Any]:
    report = build_data_quality_report(db)
    return envelope(report, source=report.source or "sample_local")
