"""D2: tests for app/jobs/batch_throttle.py (per-domain limiter + retry/backoff).

All tests use an injectable clock / sleep and fake upstream errors -- no real
time, no network, no requests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.jobs.batch_throttle import (
    BackoffPolicy,
    BatchThrottle,
    DeterministicReject,
    TransientUpstreamError,
    is_deterministic_message,
    is_transient_upstream,
)


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeHTTPError(Exception):
    """Stand-in for requests.HTTPError / urllib HTTPError with a status code."""

    def __init__(self, status: int) -> None:
        super().__init__(f"GET url returned HTTP {status}")
        self.response = SimpleNamespace(status_code=status)


def _throttle(
    *,
    limits: dict[str, float] | None = None,
    max_retries: int = 3,
    clock: FakeClock | None = None,
    slept: list[float] | None = None,
) -> BatchThrottle:
    clock = clock or FakeClock()
    slept = slept if slept is not None else []

    def sleepy(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds)

    return BatchThrottle(
        limits=limits or {"eastmoney": 0.5, "danjuan": 0.5, "sina": 0.5},
        max_retries=max_retries,
        backoff_base_seconds=2.0,
        backoff_cap_seconds=8.0,
        clock=clock,
        sleep=sleepy,
    )


def test_backoff_delays_are_2_4_8_capped() -> None:
    policy = BackoffPolicy(max_retries=3, base_seconds=2.0, cap_seconds=8.0)
    assert [policy.delay_seconds(i) for i in (1, 2, 3)] == [2.0, 4.0, 8.0]
    policy_cap = BackoffPolicy(max_retries=5, base_seconds=2.0, cap_seconds=5.0)
    assert [policy_cap.delay_seconds(i) for i in (1, 2, 3, 4, 5)] == [2.0, 4.0, 5.0, 5.0, 5.0]


def test_limiter_enforces_per_domain_interval_and_domains_are_independent() -> None:
    clock = FakeClock()
    slept: list[float] = []
    throttle = _throttle(clock=clock, slept=slept)

    throttle.run("eastmoney", lambda: "a")  # first call: no wait
    clock.advance(0.2)  # only 0.2s elapsed since the eastmoney call
    throttle.run("eastmoney", lambda: "b")  # must sleep 0.3 to reach 0.5s
    assert slept == [pytest.approx(0.3)]

    # danjuan / sina limiters are independent: no wait on their first call.
    throttle.run("danjuan", lambda: "c")
    throttle.run("sina", lambda: "d")
    assert slept == [pytest.approx(0.3)]


def test_transient_5xx_is_retried_with_backoff_then_succeeds() -> None:
    clock = FakeClock()
    slept: list[float] = []
    throttle = _throttle(clock=clock, slept=slept)
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeHTTPError(503)
        return "ok"

    assert throttle.run("eastmoney", flaky) == "ok"
    assert calls["n"] == 3
    assert slept == [2.0, 4.0]


def test_transient_exhausted_raises_retryable_error() -> None:
    clock = FakeClock()
    slept: list[float] = []
    throttle = _throttle(clock=clock, slept=slept)
    calls = {"n": 0}

    def always() -> str:
        calls["n"] += 1
        raise FakeHTTPError(503)

    with pytest.raises(TransientUpstreamError):
        throttle.run("eastmoney", always)
    # 1 initial + 3 retries = 4 attempts; backoff 2/4/8 between them.
    assert calls["n"] == 4
    assert slept == [2.0, 4.0, 8.0]


def test_deterministic_404_is_not_retried() -> None:
    clock = FakeClock()
    slept: list[float] = []
    throttle = _throttle(clock=clock, slept=slept)
    calls = {"n": 0}

    def not_found() -> str:
        calls["n"] += 1
        raise FakeHTTPError(404)

    with pytest.raises(DeterministicReject) as excinfo:
        throttle.run("eastmoney", not_found)
    assert excinfo.value.reason == "danjuan_not_listed"
    assert calls["n"] == 1  # never retried
    assert slept == []


def test_timeout_and_connection_errors_are_transient() -> None:
    assert is_transient_upstream(TimeoutError("boom"))
    assert is_transient_upstream(ConnectionError("reset"))
    assert is_transient_upstream(FakeHTTPError(429))
    assert is_transient_upstream(FakeHTTPError(502))
    assert not is_transient_upstream(FakeHTTPError(404))
    assert not is_transient_upstream(ValueError("parse failed"))


def test_is_deterministic_message_classifies_danjuan_outage() -> None:
    assert is_deterministic_message("danjuan GET url returned HTTP 404")
    assert is_deterministic_message("fund not found")
    assert is_deterministic_message("该基金暂不销售")
    assert not is_deterministic_message("danjuan GET url returned HTTP 503")
    assert not is_deterministic_message("")
    assert not is_deterministic_message(None)


def test_non_http_exception_propagates_unchanged() -> None:
    throttle = _throttle()

    def parse_error() -> str:
        raise ValueError("requires at least two NAV points")

    with pytest.raises(ValueError, match="at least two NAV points"):
        throttle.run("eastmoney", parse_error)
