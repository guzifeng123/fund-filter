from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

SafeProviderName = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]
SafeModelName = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]
WindowMinutes = Annotated[int, Field(ge=1, le=525_600)]
MinimumRequests = Annotated[int, Field(ge=1, le=1_000_000)]
NonNegativeCount = Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]
NonNegativeRate = Annotated[float, Field(ge=0, le=9_223_372_036_854_775_807)]
UnitRate = Annotated[float, Field(ge=0, le=1)]


class RuntimeDataSourceSettings(BaseModel):
    configured_source: str
    configured_profile: str | None
    actual_source: str
    configured: bool


class RuntimeLlmDispatcherHealth(BaseModel):
    status: Literal["disabled", "not_started", "ok", "degraded"]
    worker_count: NonNegativeCount
    pending_count: NonNegativeCount
    capacity: NonNegativeCount
    dropped_count: NonNegativeCount


class RuntimeLlmObservability(BaseModel):
    enabled: bool
    status: Literal["disabled", "unavailable", "insufficient_data", "ok", "alert"]
    window_minutes: WindowMinutes
    minimum_requests: MinimumRequests
    request_count: NonNegativeCount
    retry_count: NonNegativeCount
    request_rate_per_minute: NonNegativeRate
    success_rate: UnitRate
    error_rate: UnitRate
    retry_rate: UnitRate
    timeout_rate: UnitRate
    error_rate_alert_threshold: UnitRate
    timeout_rate_alert_threshold: UnitRate
    alerts: list[Literal["error_rate", "timeout_rate"]]
    last_event_at: datetime | None
    dispatcher: RuntimeLlmDispatcherHealth


class RuntimeLlmSettings(BaseModel):
    provider: SafeProviderName | None
    model: SafeModelName | None
    configured: bool
    mock_mode: bool
    observability: RuntimeLlmObservability


class RuntimeYingmiMcpSettings(BaseModel):
    configured: bool
    implemented: bool


class RuntimeRiskSettings(BaseModel):
    validity_months: Annotated[int, Field(ge=1, le=120)]


class RuntimeCleanupSettings(BaseModel):
    method: Literal["manual_script"]
    dry_run_supported: bool
    automatic_cleanup_supported: bool


class RuntimeSettingsData(BaseModel):
    data_source: RuntimeDataSourceSettings
    llm: RuntimeLlmSettings
    yingmi_mcp: RuntimeYingmiMcpSettings
    risk_assessment: RuntimeRiskSettings
    cleanup: RuntimeCleanupSettings
