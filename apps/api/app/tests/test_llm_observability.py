import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from http.client import HTTPMessage
from io import BytesIO
from typing import Any
from urllib.error import URLError
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main_module
import app.repositories.llm_observability as observability_module
from app.core.config import settings
from app.db.models import LlmProviderEvent
from app.repositories.llm_observability import (
    LlmAlert,
    LlmEventDispatcher,
    LlmObservabilityStatus,
    LlmProviderMetrics,
    LlmProviderEventData,
    QueuedLlmProviderEvent,
    aggregate_llm_provider_metrics,
    default_llm_dispatcher_health,
    make_llm_event_recorder,
    notify_llm_provider_alerts,
    sanitize_llm_label,
)
from app.services.llm_gateway import (
    LLMProviderClient,
    SameOriginRedirectHandler,
    find_blocked_provider_output,
    llm_chat_completions_endpoint,
)


class FakeProviderResponse:
    def __init__(self, content: str) -> None:
        self.content = content

    def __enter__(self) -> "FakeProviderResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": self.content}}]},
            ensure_ascii=False,
        ).encode("utf-8")


class RawProviderResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "RawProviderResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]


def _configure_provider(monkeypatch: pytest.MonkeyPatch, *, retries: int = 1) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "https://provider.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", "provider-secret")
    monkeypatch.setattr(settings, "llm_max_retries", retries)
    monkeypatch.setattr(settings, "llm_timeout_seconds", 3)
    monkeypatch.setattr(settings, "llm_audit_enabled", True)
    monkeypatch.setattr("app.services.llm_gateway.time.sleep", lambda _seconds: None)


@pytest.mark.parametrize(
    "unsafe_label",
    (
        "https://private.example?api_key=provider-secret",
        "sk_live_" + "abcdefghijklmnopqrstuvwxyz1234",  # split: fake Stripe-shaped fixture, opaque to secret scanners
        "api.internal.example.",
        "localhost",
        "localhost.",
        "127.0.0.1",
        "127.0.0.1.",
        "0123456789abcdef0123456789abcdef",
        "abcdefghijklmnopqrstuvwxyz0123456789",
    ),
)
def test_provider_event_persists_only_sanitized_bounded_fields(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_label: str,
) -> None:
    _configure_provider(monkeypatch, retries=0)
    monkeypatch.setattr(
        "app.services.llm_gateway.open_llm_provider_request",
        lambda *_args, **_kwargs: FakeProviderResponse("合规解释"),
    )
    dispatcher = LlmEventDispatcher(capacity=4, thread_name="test-llm-persistence")
    try:
        client = LLMProviderClient(
            provider=unsafe_label,
            model=unsafe_label,
            event_recorder=make_llm_event_recorder(
                db_session,
                dispatcher=dispatcher,
            ),
        )

        conclusion = client.generate_conclusion(
            message="user@example.com 的问题",
            evidence=["api_key=evidence-secret"],
            data_date="2026-07-14",
        )
        assert dispatcher.drain(timeout_seconds=1)
    finally:
        assert dispatcher.close(timeout_seconds=1)

    event = db_session.scalar(select(LlmProviderEvent))
    assert conclusion == "合规解释"
    assert event is not None
    assert event.provider_name == "unknown"
    assert event.model_name == "unknown"
    assert event.outcome == "success"
    assert event.attempt_count == 1
    assert event.retry_count == 0
    assert event.error_category is None
    serialized = json.dumps(
        {
            "provider_name": event.provider_name,
            "model_name": event.model_name,
            "outcome": event.outcome,
            "attempt_count": event.attempt_count,
            "retry_count": event.retry_count,
            "latency_ms": event.latency_ms,
            "timed_out": event.timed_out,
            "error_category": event.error_category,
        }
    )
    for secret in (
        unsafe_label,
        "provider-secret",
        "user@example.com",
        "evidence-secret",
        "合规解释",
    ):
        assert secret not in serialized


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
        "ghp_AbC123456789",
        "access-token-value",
        "AbCdEfGhIjKlMnOpQrStUvWxYz012345",
    ),
)
def test_llm_label_sanitizer_rejects_credentials_and_endpoints(
    unsafe_label: str,
) -> None:
    assert sanitize_llm_label(unsafe_label, max_length=128) == "unknown"


@pytest.mark.parametrize(
    "safe_label",
    ("openai-compatible", "gpt-4.1", "mock_compliance_v1"),
)
def test_llm_label_sanitizer_preserves_safe_identifiers(safe_label: str) -> None:
    assert sanitize_llm_label(safe_label, max_length=128) == safe_label


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
def test_provider_events_and_logs_never_emit_unsafe_labels(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    unsafe_label: str,
) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_audit_enabled", True)
    events: list[LlmProviderEventData] = []
    caplog.set_level(logging.INFO, logger="app.services.llm_gateway")

    conclusion = LLMProviderClient(
        unsafe_label,
        unsafe_label,
        events.append,
    ).generate_conclusion(message="问题", evidence=[], data_date="2026-07-14")

    assert conclusion is None
    assert events[0].provider_name == "unknown"
    assert events[0].model_name == "unknown"
    for record in caplog.records:
        assert getattr(record, "provider", "unknown") == "unknown"
        assert getattr(record, "model", "unknown") == "unknown"


def test_bounded_dispatcher_never_waits_for_a_slow_sink_or_grows_workers(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink_started = threading.Event()
    release_sink = threading.Event()

    def slow_sink(_item: object) -> None:
        sink_started.set()
        release_sink.wait(timeout=2)

    dispatcher = LlmEventDispatcher(
        capacity=1,
        sink=slow_sink,
        thread_name="test-llm-slow-sink",
    )
    recorder = make_llm_event_recorder(db_session, dispatcher=dispatcher)
    caplog.set_level(logging.WARNING, logger="app.repositories.llm_observability")
    event = LlmProviderEventData(
        provider_name="sk-proj-AbC123",
        model_name="api.internal.example",
        outcome="success",
        attempt_count=1,
        retry_count=0,
        latency_ms=1,
        timed_out=False,
        error_category=None,
    )
    try:
        started_at = time.perf_counter()
        recorder(event)
        first_enqueue_latency = time.perf_counter() - started_at

        assert first_enqueue_latency < 0.1
        assert sink_started.wait(timeout=1)
        started_at = time.perf_counter()
        recorder(event)
        recorder(event)
        full_queue_enqueue_latency = time.perf_counter() - started_at

        assert full_queue_enqueue_latency < 0.1
        assert dispatcher.worker_count == 1
        assert dispatcher.pending_count <= 2
        assert dispatcher.dropped_count == 1
        assert not any(
            record.message == "llm_provider_event_queue_dropped" for record in caplog.records
        )
    finally:
        release_sink.set()
        assert dispatcher.drain(timeout_seconds=1)
        assert dispatcher.close(timeout_seconds=1)
    dropped_records = [
        record for record in caplog.records if record.message == "llm_provider_event_queue_dropped"
    ]
    assert len(dropped_records) == 1
    assert getattr(dropped_records[0], "dropped_count") == 1
    assert getattr(dropped_records[0], "total_dropped_count") == 1
    assert not hasattr(dropped_records[0], "provider")
    assert not hasattr(dropped_records[0], "model")
    assert dispatcher.worker_count == 0


def test_dispatcher_restarts_worker_after_unexpected_exit(
    db_session: Session,
) -> None:
    class WorkerExit(BaseException):
        pass

    sink_calls = 0
    persisted_providers: list[str] = []

    def flaky_sink(item: QueuedLlmProviderEvent) -> None:
        nonlocal sink_calls
        sink_calls += 1
        if sink_calls == 1:
            raise WorkerExit("simulated worker crash")
        persisted_providers.append(item.event.provider_name)

    dispatcher = LlmEventDispatcher(
        capacity=2,
        sink=flaky_sink,
        thread_name="test-llm-restart",
    )
    recorder = make_llm_event_recorder(db_session, dispatcher=dispatcher)
    first_event = LlmProviderEventData(
        provider_name="provider-one",
        model_name="model",
        outcome="success",
        attempt_count=1,
        retry_count=0,
        latency_ms=1,
        timed_out=False,
        error_category=None,
    )
    second_event = LlmProviderEventData(
        provider_name="provider-two",
        model_name="model",
        outcome="success",
        attempt_count=1,
        retry_count=0,
        latency_ms=1,
        timed_out=False,
        error_category=None,
    )
    try:
        recorder(first_event)
        for _ in range(50):
            if dispatcher.worker_count == 0 and dispatcher.worker_failure_count == 1:
                break
            time.sleep(0.02)
        assert dispatcher.worker_count == 0
        assert dispatcher.worker_failure_count == 1

        recorder(second_event)

        assert dispatcher.drain(timeout_seconds=1)
        assert dispatcher.worker_count == 1
        assert persisted_providers == ["provider-two"]
        assert dispatcher.capacity == 2
    finally:
        assert dispatcher.close(timeout_seconds=1)


def test_dispatcher_close_timeout_drops_leftover_queue_items(
    db_session: Session,
) -> None:
    sink_started = threading.Event()
    release_sink = threading.Event()

    def blocking_sink(_item: QueuedLlmProviderEvent) -> None:
        sink_started.set()
        release_sink.wait(timeout=2)

    dispatcher = LlmEventDispatcher(
        capacity=2,
        sink=blocking_sink,
        thread_name="test-llm-close-timeout",
    )
    recorder = make_llm_event_recorder(db_session, dispatcher=dispatcher)
    event = LlmProviderEventData(
        provider_name="provider",
        model_name="model",
        outcome="success",
        attempt_count=1,
        retry_count=0,
        latency_ms=1,
        timed_out=False,
        error_category=None,
    )
    try:
        recorder(event)
        assert sink_started.wait(timeout=1)
        recorder(event)
        recorder(event)

        assert dispatcher.close(timeout_seconds=0.01) is False

        assert dispatcher.accepting is False
        assert dispatcher.worker_count == 1
        assert dispatcher.pending_count == 1
        assert dispatcher.dropped_count == 2
    finally:
        release_sink.set()
        assert dispatcher.close(timeout_seconds=1)


def test_default_dispatcher_health_reports_safe_aggregate_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_observability_queue_capacity", 8)
    monkeypatch.setattr(observability_module, "_default_dispatcher", None)

    disabled = default_llm_dispatcher_health(enabled=False)
    not_started = default_llm_dispatcher_health(enabled=True)

    assert disabled.status == "disabled"
    assert disabled.capacity == 0
    assert not_started.status == "not_started"
    assert not_started.capacity == 8
    assert not_started.worker_count == 0
    assert not_started.pending_count == 0
    assert not_started.dropped_count == 0


def test_default_dispatcher_health_reports_degraded_after_drops(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink_started = threading.Event()
    release_sink = threading.Event()

    def slow_sink(_item: object) -> None:
        sink_started.set()
        release_sink.wait(timeout=2)

    dispatcher = LlmEventDispatcher(
        capacity=1,
        sink=slow_sink,
        thread_name="test-llm-health",
    )
    monkeypatch.setattr(observability_module, "_default_dispatcher", dispatcher)
    recorder = make_llm_event_recorder(db_session, dispatcher=dispatcher)
    event = LlmProviderEventData(
        provider_name="provider",
        model_name="model",
        outcome="success",
        attempt_count=1,
        retry_count=0,
        latency_ms=1,
        timed_out=False,
        error_category=None,
    )
    try:
        recorder(event)
        assert sink_started.wait(timeout=1)
        recorder(event)
        recorder(event)

        health = default_llm_dispatcher_health(enabled=True)
    finally:
        release_sink.set()
        assert dispatcher.drain(timeout_seconds=1)
        assert dispatcher.close(timeout_seconds=1)
        monkeypatch.setattr(observability_module, "_default_dispatcher", None)

    assert health.status == "degraded"
    assert health.worker_count == 1
    assert health.capacity == 1
    assert health.dropped_count == 1


def test_delayed_event_sink_persists_the_occurrence_time(
    db_session: Session,
) -> None:
    sink_started = threading.Event()
    release_sink = threading.Event()

    def delayed_sink(item: QueuedLlmProviderEvent) -> None:
        sink_started.set()
        release_sink.wait(timeout=2)
        event = item.event
        with item.event_sessionmaker.begin() as event_db:
            event_db.add(
                LlmProviderEvent(
                    provider_name=event.provider_name,
                    model_name=event.model_name,
                    outcome=event.outcome,
                    attempt_count=event.attempt_count,
                    retry_count=event.retry_count,
                    latency_ms=event.latency_ms,
                    timed_out=event.timed_out,
                    error_category=event.error_category,
                    created_at=event.created_at,
                )
            )

    dispatcher = LlmEventDispatcher(
        capacity=1,
        sink=delayed_sink,
        thread_name="test-llm-event-time",
    )
    occurred_at = datetime(2026, 7, 14, 8, 30, tzinfo=timezone.utc)
    recorder = make_llm_event_recorder(db_session, dispatcher=dispatcher)
    try:
        recorder(
            LlmProviderEventData(
                provider_name="provider",
                model_name="model",
                outcome="success",
                attempt_count=1,
                retry_count=0,
                latency_ms=1,
                timed_out=False,
                error_category=None,
                created_at=occurred_at,
            )
        )
        assert sink_started.wait(timeout=1)
        release_sink.set()
        assert dispatcher.drain(timeout_seconds=1)
    finally:
        release_sink.set()
        assert dispatcher.close(timeout_seconds=1)

    db_session.expire_all()
    stored_at = db_session.scalar(
        select(LlmProviderEvent.created_at).where(LlmProviderEvent.provider_name == "provider")
    )
    assert stored_at is not None
    if stored_at.tzinfo is None:
        stored_at = stored_at.replace(tzinfo=timezone.utc)
    assert stored_at == occurred_at


def test_recorder_passes_an_engine_not_a_request_connection_to_worker(
    db_session: Session,
) -> None:
    request_connection = db_session.connection()
    request_session = Session(bind=request_connection)
    worker_binds: list[object] = []

    def inspect_bind(item: QueuedLlmProviderEvent) -> None:
        worker_binds.append(item.event_sessionmaker.kw["bind"])

    dispatcher = LlmEventDispatcher(
        capacity=1,
        sink=inspect_bind,
        thread_name="test-llm-engine-bind",
    )
    try:
        recorder = make_llm_event_recorder(request_session, dispatcher=dispatcher)
        recorder(
            LlmProviderEventData(
                provider_name="provider",
                model_name="model",
                outcome="success",
                attempt_count=1,
                retry_count=0,
                latency_ms=1,
                timed_out=False,
                error_category=None,
            )
        )
        assert dispatcher.drain(timeout_seconds=1)
    finally:
        request_session.close()
        assert dispatcher.close(timeout_seconds=1)

    assert worker_binds == [request_connection.engine]
    assert worker_binds[0] is not request_connection


def test_app_lifespan_closes_event_dispatcher_with_a_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    shutdown_timeouts: list[float] = []
    monkeypatch.setattr(main_module, "start_scheduler", lambda: lifecycle.append("start"))
    monkeypatch.setattr(main_module, "stop_scheduler", lambda: lifecycle.append("stop"))

    def record_shutdown(*, timeout_seconds: float) -> bool:
        shutdown_timeouts.append(timeout_seconds)
        return True

    monkeypatch.setattr(
        main_module,
        "shutdown_default_llm_event_dispatcher",
        record_shutdown,
    )

    with TestClient(main_module.app) as client:
        assert client.get("/health").status_code == 200

    assert lifecycle == ["start", "stop"]
    assert shutdown_timeouts == [settings.llm_observability_shutdown_timeout_seconds]


def test_provider_retry_is_aggregated_into_one_success_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider(monkeypatch)
    events: list[LlmProviderEventData] = []
    call_count = 0

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise URLError("https://private.example?api_key=should-not-be-stored")
        return FakeProviderResponse("重试后成功")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", fake_urlopen)
    client = LLMProviderClient("openai-compatible", "safe-model", events.append)

    conclusion = client.generate_conclusion(
        message="解释指标",
        evidence=["历史指标"],
        data_date="2026-07-14",
    )

    assert conclusion == "重试后成功"
    assert len(events) == 1
    event = events[0]
    assert event.provider_name == "openai-compatible"
    assert event.model_name == "safe-model"
    assert event.outcome == "success"
    assert event.attempt_count == 2
    assert event.retry_count == 1
    assert event.latency_ms >= 0
    assert event.timed_out is False
    assert event.error_category == "network"
    assert event.created_at.utcoffset() == timedelta(0)


def test_provider_timeout_falls_back_with_timeout_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider(monkeypatch)
    events: list[LlmProviderEventData] = []

    def timeout(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        raise TimeoutError("https://private.example?token=not-stored")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", timeout)
    client = LLMProviderClient("openai-compatible", "safe-model", events.append)

    conclusion = client.generate_conclusion(
        message="解释指标",
        evidence=["历史指标"],
        data_date="2026-07-14",
    )

    assert conclusion is None
    assert len(events) == 1
    assert events[0].outcome == "fallback"
    assert events[0].attempt_count == 2
    assert events[0].retry_count == 1
    assert events[0].timed_out is True
    assert events[0].error_category == "timeout"


def test_missing_config_and_policy_rejection_are_categorized_without_raw_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_audit_enabled", True)
    missing_events: list[LlmProviderEventData] = []

    assert (
        LLMProviderClient("provider", "model", missing_events.append).generate_conclusion(
            message="问题",
            evidence=[],
            data_date="2026-07-14",
        )
        is None
    )
    assert missing_events[0].attempt_count == 0
    assert missing_events[0].error_category == "config_missing"

    _configure_provider(monkeypatch, retries=0)
    monkeypatch.setattr(
        "app.services.llm_gateway.open_llm_provider_request",
        lambda *_args, **_kwargs: FakeProviderResponse("你必须立即买入，保证收益。"),
    )
    rejected_events: list[LlmProviderEventData] = []
    assert (
        LLMProviderClient("provider", "model", rejected_events.append).generate_conclusion(
            message="问题",
            evidence=[],
            data_date="2026-07-14",
            output_rejection_reason=find_blocked_provider_output,
        )
        is None
    )
    assert rejected_events[0].outcome == "fallback"
    assert rejected_events[0].error_category == "policy_rejected"


def test_policy_callback_reason_is_allowlisted_before_logging(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _configure_provider(monkeypatch, retries=0)
    sensitive_reason = "raw provider text api_key=must-not-be-logged"
    monkeypatch.setattr(
        "app.services.llm_gateway.open_llm_provider_request",
        lambda *_args, **_kwargs: FakeProviderResponse("合规响应正文"),
    )
    caplog.set_level(logging.WARNING, logger="app.services.llm_gateway")
    events: list[LlmProviderEventData] = []

    conclusion = LLMProviderClient("provider", "model", events.append).generate_conclusion(
        message="解释指标",
        evidence=[],
        data_date="2026-07-14",
        output_rejection_reason=lambda _content: sensitive_reason,
    )

    assert conclusion is None
    rejection_record = next(
        record for record in caplog.records if record.message == "llm_provider_output_rejected"
    )
    assert getattr(rejection_record, "reason") == "policy_rejected"
    assert sensitive_reason not in caplog.text
    assert events[0].error_category == "policy_rejected"


@pytest.mark.parametrize(
    ("provider", "model", "api_key", "base_url"),
    (
        ("", "model", "provider-secret", "https://provider.example/v1"),
        ("provider", "", "provider-secret", "https://provider.example/v1"),
        ("   ", "model", "provider-secret", "https://provider.example/v1"),
        ("provider", "   ", "provider-secret", "https://provider.example/v1"),
        ("provider", "model", "   ", "https://provider.example/v1"),
        ("provider", "model", "provider-secret", "   "),
    ),
)
def test_incomplete_or_blank_provider_configuration_never_attempts_network(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", api_key)
    monkeypatch.setattr(settings, "llm_base_url", base_url)
    monkeypatch.setattr(settings, "llm_audit_enabled", True)
    network_attempts = 0
    events: list[LlmProviderEventData] = []

    def unexpected_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal network_attempts
        network_attempts += 1
        raise AssertionError("network must not be attempted")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", unexpected_urlopen)

    conclusion = LLMProviderClient(provider, model, events.append).generate_conclusion(
        message="解释指标",
        evidence=[],
        data_date="2026-07-14",
    )

    assert conclusion is None
    assert network_attempts == 0
    assert len(events) == 1
    assert events[0].attempt_count == 0
    assert events[0].retry_count == 0
    assert events[0].error_category == "config_missing"


@pytest.mark.parametrize(
    "base_url",
    (
        "ftp://provider.example/v1",
        "https://user:secret@provider.example/v1",
        "https://provider.example/v1?api_key=secret",
        "https://provider.example/v1#fragment",
        "https://provider.example/v1/chat/completions",
        "provider.example/v1",
    ),
)
def test_invalid_provider_base_url_never_attempts_network(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "provider-secret")
    monkeypatch.setattr(settings, "llm_base_url", base_url)
    monkeypatch.setattr(settings, "llm_audit_enabled", True)
    network_attempts = 0
    events: list[LlmProviderEventData] = []

    def unexpected_open(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal network_attempts
        network_attempts += 1
        raise AssertionError("network must not be attempted")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", unexpected_open)

    conclusion = LLMProviderClient("provider", "model", events.append).generate_conclusion(
        message="解释指标",
        evidence=[],
        data_date="2026-07-14",
    )

    assert conclusion is None
    assert network_attempts == 0
    assert len(events) == 1
    assert events[0].attempt_count == 0
    assert events[0].error_category == "config_missing"


def test_provider_base_url_builds_chat_endpoint_without_secret_parts() -> None:
    assert (
        llm_chat_completions_endpoint("HTTPS://Provider.Example:8443/v1/")
        == "https://provider.example:8443/v1/chat/completions"
    )


def test_provider_redirect_handler_blocks_cross_origin_redirects() -> None:
    handler = SameOriginRedirectHandler()
    request = Request("https://provider.example/v1/chat/completions", method="POST")

    with pytest.raises(URLError, match="cross-origin"):
        handler.redirect_request(
            request,
            fp=BytesIO(),
            code=302,
            msg="Found",
            headers=HTTPMessage(),
            newurl="https://evil.example/v1/chat/completions",
        )


@pytest.mark.parametrize("provider_content", ("", "   ", "\n\t"))
def test_blank_provider_content_is_an_invalid_response_fallback(
    monkeypatch: pytest.MonkeyPatch,
    provider_content: str,
) -> None:
    _configure_provider(monkeypatch, retries=1)
    events: list[LlmProviderEventData] = []
    network_attempts = 0

    def blank_response(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal network_attempts
        network_attempts += 1
        return FakeProviderResponse(provider_content)

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", blank_response)

    conclusion = LLMProviderClient("provider", "model", events.append).generate_conclusion(
        message="解释指标",
        evidence=[],
        data_date="2026-07-14",
    )

    assert conclusion is None
    assert network_attempts == 1
    assert len(events) == 1
    assert events[0].outcome == "fallback"
    assert events[0].attempt_count == 1
    assert events[0].retry_count == 0
    assert events[0].error_category == "invalid_response"


def test_oversized_provider_response_body_is_an_invalid_response_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider(monkeypatch, retries=1)
    monkeypatch.setattr(settings, "llm_max_response_bytes", 16)
    events: list[LlmProviderEventData] = []
    network_attempts = 0

    def oversized_response(*_args: Any, **_kwargs: Any) -> RawProviderResponse:
        nonlocal network_attempts
        network_attempts += 1
        return RawProviderResponse(b"x" * 17)

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", oversized_response)

    conclusion = LLMProviderClient("provider", "model", events.append).generate_conclusion(
        message="解释指标",
        evidence=[],
        data_date="2026-07-14",
    )

    assert conclusion is None
    assert network_attempts == 1
    assert len(events) == 1
    assert events[0].attempt_count == 1
    assert events[0].error_category == "invalid_response"


def test_oversized_provider_output_is_an_invalid_response_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider(monkeypatch, retries=1)
    monkeypatch.setattr(settings, "llm_max_output_chars", 4)
    events: list[LlmProviderEventData] = []
    network_attempts = 0

    def long_output(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal network_attempts
        network_attempts += 1
        return FakeProviderResponse("超过四个字符")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", long_output)

    conclusion = LLMProviderClient("provider", "model", events.append).generate_conclusion(
        message="解释指标",
        evidence=[],
        data_date="2026-07-14",
    )

    assert conclusion is None
    assert network_attempts == 1
    assert len(events) == 1
    assert events[0].attempt_count == 1
    assert events[0].error_category == "invalid_response"


def test_event_recorder_failure_never_changes_provider_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider(monkeypatch, retries=0)
    monkeypatch.setattr(
        "app.services.llm_gateway.open_llm_provider_request",
        lambda *_args, **_kwargs: FakeProviderResponse("仍然可用"),
    )

    def broken_recorder(_event: LlmProviderEventData) -> None:
        raise RuntimeError("database unavailable")

    conclusion = LLMProviderClient(
        "provider",
        "model",
        broken_recorder,
    ).generate_conclusion(
        message="解释指标",
        evidence=[],
        data_date="2026-07-14",
    )

    assert conclusion == "仍然可用"


def test_recent_metrics_compute_rates_and_threshold_alerts(db_session: Session) -> None:
    now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
    events = [
        ("success", 0, False, None),
        ("success", 3, False, "network"),
        ("fallback", 0, False, "provider_error"),
        ("fallback", 1, True, "timeout"),
        ("fallback", 0, False, "policy_rejected"),
        ("fallback", 0, False, "config_missing"),
    ]
    for index, (outcome, retries, timed_out, category) in enumerate(events):
        attempt_count = 0 if category == "config_missing" else retries + 1
        db_session.add(
            LlmProviderEvent(
                provider_name="provider",
                model_name="model",
                outcome=outcome,
                attempt_count=attempt_count,
                retry_count=retries,
                latency_ms=100 + index,
                timed_out=timed_out,
                error_category=category,
                created_at=now - timedelta(minutes=index),
            )
        )
    db_session.add(
        LlmProviderEvent(
            provider_name="provider",
            model_name="model",
            outcome="fallback",
            attempt_count=1,
            retry_count=0,
            latency_ms=100,
            timed_out=True,
            error_category="timeout",
            created_at=now - timedelta(hours=2),
        )
    )
    for provider_name, model_name in (
        ("old-provider", "model"),
        ("provider", "other-model"),
    ):
        db_session.add(
            LlmProviderEvent(
                provider_name=provider_name,
                model_name=model_name,
                outcome="fallback",
                attempt_count=1,
                retry_count=0,
                latency_ms=100,
                timed_out=True,
                error_category="timeout",
                created_at=now,
            )
        )
    db_session.commit()

    metrics = aggregate_llm_provider_metrics(
        db_session,
        provider_name="provider",
        model_name="model",
        window_minutes=60,
        minimum_requests=5,
        error_rate_alert_threshold=0.3,
        timeout_rate_alert_threshold=0.1,
        now=now,
    )

    assert metrics.request_count == 5
    assert metrics.success_count == 3
    assert metrics.error_count == 2
    assert metrics.retry_count == 4
    assert metrics.retried_request_count == 2
    assert metrics.timeout_count == 1
    assert metrics.request_rate_per_minute == pytest.approx(5 / 60)
    assert metrics.success_rate == pytest.approx(0.6)
    assert metrics.error_rate == pytest.approx(0.4)
    assert metrics.retry_rate == pytest.approx(0.4)
    assert metrics.timeout_rate == pytest.approx(0.2)
    assert metrics.alerts == ("error_rate", "timeout_rate")
    assert metrics.status == "alert"


def test_alerts_require_the_configured_minimum_sample(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    db_session.add(
        LlmProviderEvent(
            provider_name="provider",
            model_name="model",
            outcome="fallback",
            attempt_count=1,
            retry_count=0,
            latency_ms=100,
            timed_out=True,
            error_category="timeout",
            created_at=now,
        )
    )
    db_session.commit()

    metrics = aggregate_llm_provider_metrics(
        db_session,
        provider_name="provider",
        model_name="model",
        window_minutes=60,
        minimum_requests=5,
        error_rate_alert_threshold=0,
        timeout_rate_alert_threshold=0,
        now=now,
    )

    assert metrics.status == "insufficient_data"
    assert metrics.alerts == ()


def _metrics_with_alerts(
    alerts: tuple[LlmAlert, ...],
    *,
    status: LlmObservabilityStatus = "alert",
) -> LlmProviderMetrics:
    return LlmProviderMetrics(
        window_minutes=60,
        minimum_requests=5,
        request_count=10,
        success_count=6,
        error_count=4,
        retry_count=2,
        retried_request_count=1,
        timeout_count=2,
        request_rate_per_minute=10 / 60,
        success_rate=0.6,
        error_rate=0.4,
        retry_rate=0.1,
        timeout_rate=0.2,
        alerts=alerts,
        status=status,
        last_event_at=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
    )


def test_llm_alert_notifier_deduplicates_with_cooldown() -> None:
    observability_module._llm_alert_delivery_state.clear()
    sent: list[dict[str, object]] = []

    def fake_sender(_url: str, payload: dict[str, object], _timeout: float) -> None:
        sent.append(payload)

    notify_llm_provider_alerts(
        _metrics_with_alerts(("error_rate",)),
        provider_name="provider",
        model_name="model",
        webhook_url="https://hooks.example/llm",
        cooldown_minutes=60,
        timeout_seconds=1,
        now=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
        sender=fake_sender,
    )
    notify_llm_provider_alerts(
        _metrics_with_alerts(("error_rate",)),
        provider_name="provider",
        model_name="model",
        webhook_url="https://hooks.example/llm",
        cooldown_minutes=60,
        timeout_seconds=1,
        now=datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc),
        sender=fake_sender,
    )
    notify_llm_provider_alerts(
        _metrics_with_alerts(("error_rate",)),
        provider_name="provider",
        model_name="model",
        webhook_url="https://hooks.example/llm",
        cooldown_minutes=60,
        timeout_seconds=1,
        now=datetime(2026, 7, 14, 13, 1, tzinfo=timezone.utc),
        sender=fake_sender,
    )

    assert [payload["action"] for payload in sent] == ["triggered", "triggered"]
    assert {payload["alert"] for payload in sent} == {"error_rate"}
    assert all(payload["provider"] == "provider" for payload in sent)


def test_llm_alert_notifier_sends_recovery_when_alert_clears() -> None:
    observability_module._llm_alert_delivery_state.clear()
    sent: list[dict[str, object]] = []

    def fake_sender(_url: str, payload: dict[str, object], _timeout: float) -> None:
        sent.append(payload)

    notify_llm_provider_alerts(
        _metrics_with_alerts(("error_rate", "timeout_rate")),
        provider_name="provider",
        model_name="model",
        webhook_url="https://hooks.example/llm",
        cooldown_minutes=60,
        timeout_seconds=1,
        now=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
        sender=fake_sender,
    )
    notify_llm_provider_alerts(
        _metrics_with_alerts((), status="ok"),
        provider_name="provider",
        model_name="model",
        webhook_url="https://hooks.example/llm",
        cooldown_minutes=60,
        timeout_seconds=1,
        now=datetime(2026, 7, 14, 12, 5, tzinfo=timezone.utc),
        sender=fake_sender,
    )

    assert [payload["action"] for payload in sent] == [
        "triggered",
        "triggered",
        "recovered",
        "recovered",
    ]
    assert [payload["alert"] for payload in sent] == [
        "error_rate",
        "timeout_rate",
        "error_rate",
        "timeout_rate",
    ]


def test_llm_alert_notifier_retries_after_delivery_failure() -> None:
    observability_module._llm_alert_delivery_state.clear()
    sent: list[dict[str, object]] = []

    def flaky_sender(_url: str, payload: dict[str, object], _timeout: float) -> None:
        if not sent:
            sent.append({"failed": payload["alert"]})
            raise OSError("temporary webhook failure")
        sent.append(payload)

    notify_llm_provider_alerts(
        _metrics_with_alerts(("error_rate",)),
        provider_name="provider",
        model_name="model",
        webhook_url="https://hooks.example/llm",
        cooldown_minutes=60,
        timeout_seconds=1,
        now=datetime(2026, 7, 14, 12, tzinfo=timezone.utc),
        sender=flaky_sender,
    )
    notify_llm_provider_alerts(
        _metrics_with_alerts(("error_rate",)),
        provider_name="provider",
        model_name="model",
        webhook_url="https://hooks.example/llm",
        cooldown_minutes=60,
        timeout_seconds=1,
        now=datetime(2026, 7, 14, 12, 1, tzinfo=timezone.utc),
        sender=flaky_sender,
    )

    assert sent[0] == {"failed": "error_rate"}
    assert sent[1]["action"] == "triggered"


