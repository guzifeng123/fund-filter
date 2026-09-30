from typing import Any, Literal

from pydantic import BaseModel

# Per-fund adjudication statuses produced by the reconciliation engine.
#   verified          -- agreement within tolerances (minor warnings allowed)
#   unverified        -- degraded: secondary source missing or mismatch downgraded
#                        in non-strict mode; the generation was still promoted
#   mismatch          -- cross-source disagreement beyond tolerance (rejects in strict)
#   source_unavailable-- a required secondary source could not be reached
FundReconciliationStatus = Literal[
    "verified",
    "unverified",
    "mismatch",
    "source_unavailable",
]

# Overall state surfaced by the read-only endpoint:
#   never_run  -- no reconciliation has been recorded for any job run yet
#   verified   -- the last reconciliation passed (possibly with warnings)
#   unverified  -- the last reconciliation ran in non-strict mode and degraded funds
#   rejected    -- the last reconciliation run rejected the candidate generation
ReconciliationOverallStatus = Literal[
    "never_run",
    "verified",
    "unverified",
    "rejected",
]


class FundReconciliationView(BaseModel):
    code: str
    status: FundReconciliationStatus
    critical: bool = False
    nav_coverage: float | None = None
    nav_agreement: float | None = None
    critical_failures: int = 0
    critical_failure_details: list[str] = []
    nav_mismatch_points: list[str] = []
    warnings: int = 0
    field_diffs: list[dict[str, Any]] = []
    source_values: dict[str, Any] = {}


class DataReconciliationReport(BaseModel):
    threshold_version: str
    overall_status: ReconciliationOverallStatus
    sources: list[str] = []
    generated_at: str | None = None
    source: str | None = None
    snapshot_generation_id: str | None = None
    job_name: str | None = None
    job_status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    fund_count: int = 0
    critical_failure_count: int = 0
    warning_count: int = 0
    funds: list[FundReconciliationView] = []
    funds_truncated: bool = False
    report_path: str | None = None
    error: str | None = None
