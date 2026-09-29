from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import LlmProviderEvent
from app.db.session import get_db
from app.main import app
from app.routers.settings import _public_actual_source


def _client(db: Session) -> TestClient:
    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_runtime_settings_exposes_only_safe_configuration_state(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_data_source", "public_http_json")
    monkeypatch.setattr(
        settings, "public_fund_data_base_url", "https://private.example/funds?token=data-secret"
    )
    monkeypatch.setattr(settings, "public_fund_data_profile", "eastmoney_snapshot_v1")
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "llm_model", "gpt-safe-model")
    monkeypatch.setattr(settings, "llm_api_key", "llm-super-secret")
    monkeypatch.setattr(
        settings, "llm_base_url", "https://llm.example/private?token=endpoint-secret"
    )
    monkeypatch.setattr(
        settings, "yingmi_mcp_endpoint", "https://yingmi.example/mcp?token=mcp-secret"
    )

    try:
        response = _client(db_session).get("/api/settings/runtime")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    runtime = body["data"]
    assert set(runtime) == {"data_source", "llm", "yingmi_mcp", "risk_assessment", "cleanup"}
    assert runtime["data_source"] == {
        "configured_source": "public_http_json",
        "configured_profile": "eastmoney_snapshot_v1",
        "actual_source": "sample_local",
        "configured": True,
    }
    assert runtime["llm"] == {
        "provider": "openai-compatible",
        "model": "gpt-safe-model",
        "configured": True,
        "mock_mode": False,
        "observability": {
            "enabled": True,
            "status": "insufficient_data",
            "window_minutes": settings.llm_observability_window_minutes,
            "minimum_requests": settings.llm_observability_minimum_requests,
            "request_count": 0,
            "retry_count": 0,
            "request_rate_per_minute": 0.0,
            "success_rate": 0.0,
            "error_rate": 0.0,
            "retry_rate": 0.0,
            "timeout_rate": 0.0,
            "error_rate_alert_threshold": settings.llm_error_rate_alert_threshold,
            "timeout_rate_alert_threshold": settings.llm_timeout_rate_alert_threshold,
            "alerts": [],
            "last_event_at": None,
            "dispatcher": {
                "status": "not_started",
                "worker_count": 0,
                "pending_count": 0,
                "capacity": settings.llm_observability_queue_capacity,
                "dropped_count": 0,
            },
        },
    }
    assert runtime["yingmi_mcp"] == {"configured": True, "implemented": False}
    assert runtime["risk_assessment"] == {"validity_months": 12}
    assert runtime["cleanup"] == {
        "method": "manual_script",
        "dry_run_supported": True,
        "automatic_cleanup_supported": False,
    }
    assert body["meta"]["source"] == "sample_local"

    serialized = response.text
    for secret in (
        "data-secret",
        "llm-super-secret",
        "endpoint-secret",
        "mcp-secret",
        "private.example",
        "llm.example",
        "yingmi.example",
    ):
        assert secret not in serialized
    for forbidden_key in ("api_key", "token", "base_url", "endpoint", "database_url"):
        assert forbidden_key not in serialized.lower()


def test_runtime_settings_marks_incomplete_external_configuration(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_data_source", "public_http_json")
    monkeypatch.setattr(settings, "public_fund_data_base_url", "")
    monkeypatch.setattr(settings, "public_fund_data_profile", "generic_aliases_v1")
    monkeypatch.setattr(settings, "llm_provider", "openai-compatible")
    monkeypatch.setattr(settings, "llm_model", "gpt-safe-model")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "yingmi_mcp_endpoint", "")

    try:
        response = _client(db_session).get("/api/settings/runtime")
    finally:
        app.dependency_overrides.clear()

    runtime = response.json()["data"]
    assert response.status_code == 200
    assert runtime["data_source"]["configured"] is False
    assert runtime["data_source"]["configured_profile"] == "generic_aliases_v1"
    assert runtime["llm"]["configured"] is False
    assert runtime["llm"]["mock_mode"] is False
    assert runtime["yingmi_mcp"] == {"configured": False, "implemented": False}


def test_runtime_settings_does_not_echo_an_unknown_public_profile(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_data_source", "public_http_json")
    monkeypatch.setattr(settings, "public_fund_data_base_url", "https://public.example/funds/")
    monkeypatch.setattr(settings, "public_fund_data_profile", "secret-profile-token")

    try:
        response = _client(db_session).get("/api/settings/runtime")
    finally:
        app.dependency_overrides.clear()

    data_source = response.json()["data"]["data_source"]
    assert response.status_code == 200
    assert data_source["configured_profile"] == "unknown"
    assert data_source["configured"] is False
    assert "secret-profile-token" not in response.text


def test_runtime_settings_allows_registered_persisted_profile_sources_only() -> None:
    assert _public_actual_source("eastmoney_snapshot") == "eastmoney_snapshot"
    assert (
        _public_actual_source("mixed(eastmoney_snapshot,sample_local)")
        == "mixed(eastmoney_snapshot,sample_local)"
    )
    assert _public_actual_source("https://secret.example/source") == "unknown"


def test_runtime_settings_openapi_response_has_a_concrete_schema() -> None:
    response_schema = app.openapi()["paths"]["/api/settings/runtime"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]

    assert response_schema["$ref"].endswith("ApiResponse_RuntimeSettingsData_")


def test_runtime_settings_openapi_constrains_observability_numbers_and_labels() -> None:
    schemas = app.openapi()["components"]["schemas"]
    observability = schemas["RuntimeLlmObservability"]["properties"]
    llm = schemas["RuntimeLlmSettings"]["properties"]

    assert observability["window_minutes"] == {
        "type": "integer",
        "maximum": 525600.0,
        "minimum": 1.0,
        "title": "Window Minutes",
    }
    for field_name in ("request_count", "retry_count", "request_rate_per_minute"):
        assert observability[field_name]["minimum"] == 0.0
        assert "maximum" in observability[field_name]
    dispatcher = schemas["RuntimeLlmDispatcherHealth"]["properties"]
    assert dispatcher["status"]["enum"] == ["disabled", "not_started", "ok", "degraded"]
    for field_name in ("worker_count", "pending_count", "capacity", "dropped_count"):
        assert dispatcher[field_name]["minimum"] == 0.0
        assert "maximum" in dispatcher[field_name]
    for field_name in (
        "success_rate",
        "error_rate",
        "retry_rate",
        "timeout_rate",
        "error_rate_alert_threshold",
        "timeout_rate_alert_threshold",
    ):
        assert observability[field_name]["minimum"] == 0.0
        assert observability[field_name]["maximum"] == 1.0

    provider_schema = llm["provider"]["anyOf"][0]
    model_schema = llm["model"]["anyOf"][0]
    assert provider_schema["maxLength"] == 64
    assert model_schema["maxLength"] == 128
    assert provider_schema["pattern"] == r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    assert model_schema["pattern"] == r"^[A-Za-z0-9][A-Za-z0-9._-]*$"


def test_runtime_settings_exposes_llm_alerts_without_event_payloads(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_audit_enabled", True)
    monkeypatch.setattr(settings, "llm_observability_window_minutes", 60)
    monkeypatch.setattr(settings, "llm_observability_minimum_requests", 2)
    monkeypatch.setattr(settings, "llm_error_rate_alert_threshold", 0.4)
    monkeypatch.setattr(settings, "llm_timeout_rate_alert_threshold", 0.4)
    monkeypatch.setattr(settings, "llm_provider", "safe-provider")
    monkeypatch.setattr(settings, "llm_model", "safe-model")
    monkeypatch.setattr(settings, "llm_alert_webhook_url", "https://hooks.example/llm")
    monkeypatch.setattr(settings, "llm_alert_cooldown_minutes", 30)
    monkeypatch.setattr(settings, "llm_alert_timeout_seconds", 1.0)
    notifier_calls: list[dict[str, Any]] = []

    def fake_notifier(metrics: Any, **kwargs: Any) -> None:
        notifier_calls.append({"alerts": metrics.alerts, **kwargs})

    monkeypatch.setattr(
        "app.routers.settings.notify_llm_provider_alerts",
        fake_notifier,
    )
    event_time = datetime.now(timezone.utc)
    for category in (None, "timeout"):
        retries = 3 if category is None else 0
        db_session.add(
            LlmProviderEvent(
                provider_name="safe-provider",
                model_name="safe-model",
                outcome="success" if category is None else "fallback",
                attempt_count=retries + 1,
                retry_count=retries,
                latency_ms=50,
                timed_out=category == "timeout",
                error_category=category,
                created_at=event_time,
            )
        )
    db_session.commit()

    try:
        response = _client(db_session).get("/api/settings/runtime")
    finally:
        app.dependency_overrides.clear()

    observability = response.json()["data"]["llm"]["observability"]
    assert response.status_code == 200
    assert observability["status"] == "alert"
    assert observability["request_count"] == 2
    assert observability["retry_count"] == 3
    assert observability["retry_rate"] == 0.5
    assert observability["error_rate"] == 0.5
    assert observability["timeout_rate"] == 0.5
    assert observability["alerts"] == ["error_rate", "timeout_rate"]
    assert observability["last_event_at"].endswith(("Z", "+00:00"))
    assert observability["dispatcher"]["status"] in {"not_started", "ok"}
    assert notifier_calls == [
        {
            "alerts": ("error_rate", "timeout_rate"),
            "provider_name": "safe-provider",
            "model_name": "safe-model",
            "webhook_url": "https://hooks.example/llm",
            "cooldown_minutes": 30,
            "timeout_seconds": 1.0,
        }
    ]


@pytest.mark.parametrize(
    "unsafe_label",
    (
        "sk-proj-AbC123",
        "eyJhbGciOiJIUzI1NiJ9.abc.def",
        "api.internal.example:8443",
        "api.internal.example",
        "api.internal.example.",
        "sk_live_" + "abcdefghijklmnopqrstuvwxyz1234",  # split: fake Stripe-shaped fixture, opaque to secret scanners
        "localhost",
        "localhost.",
        "127.0.0.1",
        "127.0.0.1.",
        "0123456789abcdef0123456789abcdef",
        "abcdefghijklmnopqrstuvwxyz0123456789",
    ),
)
def test_runtime_settings_sanitizes_unsafe_llm_labels(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_label: str,
) -> None:
    monkeypatch.setattr(settings, "llm_provider", unsafe_label)
    monkeypatch.setattr(settings, "llm_model", unsafe_label)
    monkeypatch.setattr(settings, "llm_api_key", "configured-secret")
    monkeypatch.setattr(settings, "llm_base_url", "https://private.example")

    try:
        response = _client(db_session).get("/api/settings/runtime")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["llm"]["provider"] == "unknown"
    assert response.json()["data"]["llm"]["model"] == "unknown"
    for secret in (unsafe_label, "private.example", "configured-secret"):
        assert secret not in response.text
