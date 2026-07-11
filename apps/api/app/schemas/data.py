from typing import Any, Literal

from pydantic import BaseModel

JobStatus = Literal["running", "success", "failed"]
DataFreshnessStatus = Literal["empty", "fresh", "stale", "failed"]


class LastJob(BaseModel):
    name: str
    status: JobStatus
    finished_at: str | None
    error_detail: str | None = None


class JobRunSummary(BaseModel):
    id: int
    name: str
    status: JobStatus
    started_at: str
    finished_at: str | None
    error_detail: str | None
    details: dict[str, Any]


class DataStatus(BaseModel):
    db_connected: bool
    fund_count: int
    nav_count: int
    latest_data_updated_at: str | None
    freshness_status: DataFreshnessStatus
    stale_after_days: int
    last_job: LastJob | None
