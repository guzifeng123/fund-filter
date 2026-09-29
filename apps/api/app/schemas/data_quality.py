from typing import Any, Literal

from pydantic import BaseModel

JobStatus = Literal["running", "success", "failed"]


class DataQualityIssue(BaseModel):
    code: str
    fund_code: str
    trade_date: str
    field: str
    message: str
    value: float | None = None
    minimum: float | None = None
    maximum: float | None = None


class DataQualityReport(BaseModel):
    threshold_version: str
    source: str | None
    snapshot_generation_id: str | None
    previous_snapshot_generation_id: str | None
    job_name: str | None
    job_status: JobStatus
    started_at: str | None
    finished_at: str | None
    issue_count: int
    issue_codes: dict[str, int]
    funds_with_issues: list[str]
    issues: list[DataQualityIssue]
    issues_truncated: bool
    snapshot_quality_thresholds: dict[str, Any] | None = None
    error: str | None = None
