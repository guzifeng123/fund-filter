from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EndpointHealth(BaseModel):
    """Reachability of a single upstream Eastmoney endpoint used by the direct adapter."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    reachable: bool
    latency_ms: float | None = None
    error: str | None = None


class DataSourceHealthReport(BaseModel):
    """Result of a minimal, rate-limited upstream probe. Never writes to the database."""

    model_config = ConfigDict(extra="forbid")

    source: str
    checked_at: str
    overall_reachable: bool
    enabled: bool
    endpoints: list[EndpointHealth] = Field(default_factory=list)
    configured_fund_codes: list[str] = Field(default_factory=list)
    discovery_enabled: bool = False
    discovery_limit: int = 0
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    note: str | None = None
