import json
from email.message import Message
from typing import Any
from urllib.error import HTTPError

import pytest

from app.core.config import settings
from app.repositories.llm_observability import LlmProviderEventData
from app.services.llm_gateway import LLMProviderClient


class FakeProviderResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeProviderResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def _provider_response(content: object = "合规解释") -> FakeProviderResponse:
    return FakeProviderResponse({"choices": [{"message": {"content": content}}]})


def _http_error(status_code: int, *, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(
        url="https://provider.example/v1/chat/completions",
        code=status_code,
        msg=f"HTTP {status_code}",
        hdrs=headers,
        fp=None,
    )


def _configure_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    retries: int,
) -> list[float]:
    sleep_calls: list[float] = []
    monkeypatch.setattr(settings, "llm_base_url", "https://provider.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", "provider-secret")
    monkeypatch.setattr(settings, "llm_max_retries", retries)
    monkeypatch.setattr(settings, "llm_timeout_seconds", 3)
    monkeypatch.setattr(settings, "llm_audit_enabled", True)
    monkeypatch.setattr("app.services.llm_gateway.random.uniform", lambda _lower, _upper: 0.0)
    monkeypatch.setattr(
        "app.services.llm_gateway.time.sleep",
        sleep_calls.append,
    )
    return sleep_calls


def _generate(client: LLMProviderClient, **kwargs: Any) -> str | None:
    return client.generate_conclusion(
        message="解释历史指标",
        evidence=["历史数据"],
        data_date="2026-07-14",
        **kwargs,
    )


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_non_retryable_http_client_errors_fail_fast(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    sleep_calls = _configure_provider(monkeypatch, retries=3)
    events: list[LlmProviderEventData] = []
    call_count = 0

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal call_count
        call_count += 1
        raise _http_error(status_code)

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", fake_urlopen)

    conclusion = _generate(LLMProviderClient("provider", "model", events.append))

    assert conclusion is None
    assert call_count == 1
    assert sleep_calls == []
    assert len(events) == 1
    assert events[0].outcome == "fallback"
    assert events[0].attempt_count == 1
    assert events[0].retry_count == 0
    assert events[0].timed_out is False
    assert events[0].error_category == "http_client"


@pytest.mark.parametrize("status_code", [408, 504])
def test_http_timeout_statuses_are_recorded_as_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    sleep_calls = _configure_provider(monkeypatch, retries=0)
    events: list[LlmProviderEventData] = []

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        raise _http_error(status_code)

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", fake_urlopen)

    conclusion = _generate(LLMProviderClient("provider", "model", events.append))

    assert conclusion is None
    assert sleep_calls == []
    assert len(events) == 1
    assert events[0].attempt_count == 1
    assert events[0].retry_count == 0
    assert events[0].timed_out is True
    assert events[0].error_category == "timeout"


@pytest.mark.parametrize(
    ("retry_after", "expected_delay"),
    [("1", 1.0), ("999", 2.0)],
)
def test_rate_limit_retries_and_bounds_retry_after_delay(
    monkeypatch: pytest.MonkeyPatch,
    retry_after: str,
    expected_delay: float,
) -> None:
    sleep_calls = _configure_provider(monkeypatch, retries=1)
    events: list[LlmProviderEventData] = []
    call_count = 0

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _http_error(429, retry_after=retry_after)
        return _provider_response("限流后成功")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", fake_urlopen)

    conclusion = _generate(LLMProviderClient("provider", "model", events.append))

    assert conclusion == "限流后成功"
    assert call_count == 2
    assert sleep_calls == [expected_delay]
    assert len(events) == 1
    assert events[0].outcome == "success"
    assert events[0].attempt_count == 2
    assert events[0].retry_count == 1


def test_retry_after_http_date_is_honored_for_rate_limited_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls = _configure_provider(monkeypatch, retries=1)
    events: list[LlmProviderEventData] = []
    call_count = 0

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _http_error(503, retry_after="Wed, 21 Oct 2099 07:28:00 GMT")
        return _provider_response("日期格式限流后成功")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", fake_urlopen)

    conclusion = _generate(LLMProviderClient("provider", "model", events.append))

    assert conclusion == "日期格式限流后成功"
    assert call_count == 2
    assert sleep_calls == [2.0]
    assert len(events) == 1
    assert events[0].outcome == "success"
    assert events[0].attempt_count == 2
    assert events[0].retry_count == 1


def test_http_server_error_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls = _configure_provider(monkeypatch, retries=1)
    events: list[LlmProviderEventData] = []
    call_count = 0

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _http_error(500)
        return _provider_response("服务端恢复后成功")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", fake_urlopen)

    conclusion = _generate(LLMProviderClient("provider", "model", events.append))

    assert conclusion == "服务端恢复后成功"
    assert call_count == 2
    assert sleep_calls == [1]
    assert len(events) == 1
    assert events[0].outcome == "success"
    assert events[0].attempt_count == 2
    assert events[0].retry_count == 1


def test_invalid_provider_response_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls = _configure_provider(monkeypatch, retries=3)
    events: list[LlmProviderEventData] = []
    call_count = 0

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal call_count
        call_count += 1
        return _provider_response(content={"unexpected": "object"})

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", fake_urlopen)

    conclusion = _generate(LLMProviderClient("provider", "model", events.append))

    assert conclusion is None
    assert call_count == 1
    assert sleep_calls == []
    assert len(events) == 1
    assert events[0].outcome == "fallback"
    assert events[0].attempt_count == 1
    assert events[0].retry_count == 0
    assert events[0].timed_out is False
    assert events[0].error_category == "invalid_response"


def test_policy_callback_failure_fails_closed_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls = _configure_provider(monkeypatch, retries=3)
    events: list[LlmProviderEventData] = []
    provider_call_count = 0
    policy_call_count = 0

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> FakeProviderResponse:
        nonlocal provider_call_count
        provider_call_count += 1
        return _provider_response("原始模型输出")

    def broken_policy_callback(_content: str) -> str | None:
        nonlocal policy_call_count
        policy_call_count += 1
        raise RuntimeError("policy engine unavailable")

    monkeypatch.setattr("app.services.llm_gateway.open_llm_provider_request", fake_urlopen)

    conclusion = _generate(
        LLMProviderClient("provider", "model", events.append),
        output_rejection_reason=broken_policy_callback,
    )

    assert conclusion is None
    assert provider_call_count == 1
    assert policy_call_count == 1
    assert sleep_calls == []
    assert len(events) == 1
    assert events[0].outcome == "fallback"
    assert events[0].attempt_count == 1
    assert events[0].retry_count == 0
    assert events[0].timed_out is False
    assert events[0].error_category == "policy_rejected"


