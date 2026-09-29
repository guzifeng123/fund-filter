import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.core.config import settings as app_settings
from app.data_sources.profiles import available_public_fund_data_profiles
from app.db.session import get_db
from app.repositories.funds import fund_data_source_summary
from app.repositories.llm_observability import (
    aggregate_llm_provider_metrics,
    default_llm_dispatcher_health,
    notify_llm_provider_alerts,
    sanitize_llm_label,
)
from app.repositories.risk_assessments import VALID_DAYS
from app.schemas.common import ApiResponse
from app.schemas.settings import (
    RuntimeCleanupSettings,
    RuntimeDataSourceSettings,
    RuntimeLlmDispatcherHealth,
    RuntimeLlmObservability,
    RuntimeLlmSettings,
    RuntimeRiskSettings,
    RuntimeSettingsData,
    RuntimeYingmiMcpSettings,
)

router = APIRouter()
logger = logging.getLogger(__name__)

SUPPORTED_DATA_SOURCES = {
    "sample_local",
    "csv_local",
    "public_http_json",
    "eastmoney_snapshot",
}
SUPPORTED_PUBLIC_PROFILES = set(available_public_fund_data_profiles())


def _configured_data_source() -> tuple[str, bool]:
    source = app_settings.fund_data_source.strip()
    if source == "sample_local":
        return source, True
    if source == "csv_local":
        return source, bool(app_settings.fund_csv_dir.strip())
    if source == "public_http_json":
        profile_is_known = app_settings.public_fund_data_profile.strip() in SUPPORTED_PUBLIC_PROFILES
        return source, bool(app_settings.public_fund_data_base_url.strip()) and profile_is_known
    return "unknown", False


def _public_configured_profile(configured_source: str) -> str | None:
    if configured_source != "public_http_json":
        return None
    profile = app_settings.public_fund_data_profile.strip()
    return profile if profile in SUPPORTED_PUBLIC_PROFILES else "unknown"


def _public_actual_source(source: str) -> str:
    if source in SUPPORTED_DATA_SOURCES:
        return source
    if source.startswith("mixed(") and source.endswith(")"):
        members = source[6:-1].split(",")
        if members and all(member in SUPPORTED_DATA_SOURCES for member in members):
            return source
    return "unknown"


def _empty_llm_observability(
    *,
    status: Literal["disabled", "unavailable"],
    enabled: bool,
) -> RuntimeLlmObservability:
    return RuntimeLlmObservability(
        enabled=enabled,
        status=status,
        window_minutes=app_settings.llm_observability_window_minutes,
        minimum_requests=app_settings.llm_observability_minimum_requests,
        request_count=0,
        retry_count=0,
        request_rate_per_minute=0,
        success_rate=0,
        error_rate=0,
        retry_rate=0,
        timeout_rate=0,
        error_rate_alert_threshold=app_settings.llm_error_rate_alert_threshold,
        timeout_rate_alert_threshold=app_settings.llm_timeout_rate_alert_threshold,
        alerts=[],
        last_event_at=None,
        dispatcher=_llm_dispatcher_health(enabled=enabled),
    )


def _llm_dispatcher_health(*, enabled: bool) -> RuntimeLlmDispatcherHealth:
    health = default_llm_dispatcher_health(enabled=enabled)
    return RuntimeLlmDispatcherHealth(
        status=health.status,
        worker_count=health.worker_count,
        pending_count=health.pending_count,
        capacity=health.capacity,
        dropped_count=health.dropped_count,
    )


def _llm_observability(
    db: Session,
    *,
    provider_name: str,
    model_name: str,
) -> RuntimeLlmObservability:
    if not app_settings.llm_audit_enabled:
        return _empty_llm_observability(status="disabled", enabled=False)
    try:
        metrics = aggregate_llm_provider_metrics(
            db,
            provider_name=provider_name,
            model_name=model_name,
            window_minutes=app_settings.llm_observability_window_minutes,
            minimum_requests=app_settings.llm_observability_minimum_requests,
            error_rate_alert_threshold=app_settings.llm_error_rate_alert_threshold,
            timeout_rate_alert_threshold=app_settings.llm_timeout_rate_alert_threshold,
        )
    except Exception:
        logger.warning("llm_observability_summary_unavailable")
        return _empty_llm_observability(status="unavailable", enabled=True)
    notify_llm_provider_alerts(
        metrics,
        provider_name=provider_name,
        model_name=model_name,
        webhook_url=app_settings.llm_alert_webhook_url,
        cooldown_minutes=app_settings.llm_alert_cooldown_minutes,
        timeout_seconds=app_settings.llm_alert_timeout_seconds,
    )
    return RuntimeLlmObservability(
        enabled=True,
        status=metrics.status,
        window_minutes=metrics.window_minutes,
        minimum_requests=metrics.minimum_requests,
        request_count=metrics.request_count,
        retry_count=metrics.retry_count,
        request_rate_per_minute=metrics.request_rate_per_minute,
        success_rate=metrics.success_rate,
        error_rate=metrics.error_rate,
        retry_rate=metrics.retry_rate,
        timeout_rate=metrics.timeout_rate,
        error_rate_alert_threshold=app_settings.llm_error_rate_alert_threshold,
        timeout_rate_alert_threshold=app_settings.llm_timeout_rate_alert_threshold,
        alerts=list(metrics.alerts),
        last_event_at=metrics.last_event_at,
        dispatcher=_llm_dispatcher_health(enabled=True),
    )


def _llm_settings(db: Session) -> RuntimeLlmSettings:
    raw_provider = app_settings.llm_provider.strip()
    raw_model = app_settings.llm_model.strip()
    provider = sanitize_llm_label(raw_provider, max_length=64) if raw_provider else None
    model = sanitize_llm_label(raw_model, max_length=128) if raw_model else None
    mock_mode = raw_provider == "mock"
    configured = mock_mode or bool(
        raw_provider
        and raw_model
        and app_settings.llm_api_key.strip()
        and app_settings.llm_base_url.strip()
    )
    return RuntimeLlmSettings(
        provider=provider,
        model=model,
        configured=configured,
        mock_mode=mock_mode,
        observability=_llm_observability(
            db,
            provider_name=provider or "unknown",
            model_name=model or "unknown",
        ),
    )


@router.get("/runtime", response_model=ApiResponse[RuntimeSettingsData])
def runtime_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    configured_source, source_configured = _configured_data_source()
    actual_source = _public_actual_source(fund_data_source_summary(db))
    result = RuntimeSettingsData(
        data_source=RuntimeDataSourceSettings(
            configured_source=configured_source,
            configured_profile=_public_configured_profile(configured_source),
            actual_source=actual_source,
            configured=source_configured,
        ),
        llm=_llm_settings(db),
        yingmi_mcp=RuntimeYingmiMcpSettings(
            configured=bool(app_settings.yingmi_mcp_endpoint.strip()),
            implemented=False,
        ),
        risk_assessment=RuntimeRiskSettings(validity_months=round(VALID_DAYS / 30)),
        cleanup=RuntimeCleanupSettings(
            method="manual_script",
            dry_run_supported=True,
            automatic_cleanup_supported=False,
        ),
    )
    return envelope(result, source=actual_source)
