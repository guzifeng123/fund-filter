"""Per-domain rate limiting and exponential-backoff retry for the D2 batch runner.

Three concerns live here, kept deliberately small and dependency-free so the
runner can be tested with an injectable clock/sleep and fake upstream calls:

1. **Per-domain minimum-interval limiter** -- one independent limiter each for
   ``eastmoney`` / ``danjuan`` / ``sina``. A slow domain never starves another.
2. **Retry / backoff policy** -- only *transient* upstream failures are retried
   (HTTP 429 / 5xx, timeouts, connection errors), at ``base * 2**attempt``
   seconds capped at ``cap`` (defaults 2/4/8s), up to
   ``settings.fund_batch_max_retries``.
3. **Domain exception taxonomy** -- :class:`TransientUpstreamError` (safe to
   retry, surfaces as checkpoint ``failed(retryable=True)``) vs
   :class:`DeterministicReject` (terminal: 404 / not-for-sale / quality /
   reconciliation mismatch; surfaces as checkpoint ``skipped(reason)``).

This module performs no HTTP and no DB IO. The HTTP clients themselves stay in
``app.data_sources``; the throttle only classifies the exceptions they raise.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from typing import TypeVar

T = TypeVar("T")

#: The upstream domains the batch runner talks to, each with its own limiter.
DOMAINS: tuple[str, ...] = ("eastmoney", "danjuan", "sina")

#: HTTP statuses that are safe to retry. Everything else in the 4xx range is a
#: deterministic rejection (the resource does not exist / will never be there).
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Substrings that mark a secondary source as "this fund is not listed / not for
#: sale" -- a terminal, non-retryable skip, distinct from a transient outage.
_NOT_LISTED_HINTS: tuple[str, ...] = (
    "暂不销售",
    "不销售",
    "无此基金",
    "not_listed",
    "not listed",
    "fund not found",
)


class BatchThrottleError(Exception):
    """Base class for the batch throttle's domain errors."""


class TransientUpstreamError(BatchThrottleError):
    """A transient upstream failure (429/5xx/timeout/connection) that did not
    clear within the configured retry budget. Checkpoint: ``failed(retryable=True)``."""


class DeterministicReject(BatchThrottleError):
    """A terminal, non-retryable upstream rejection (404 / not-for-sale).

    ``reason`` selects the checkpoint skip bucket (e.g. ``danjuan_not_listed``);
    quality failures and reconciliation mismatches are raised by the runner
    itself with the matching reason rather than by the transport layer.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# --------------------------------------------------------------------------- #
# Error classification (pure; works on the exception or its string form)
# --------------------------------------------------------------------------- #
_HTTP_STATUS_RE = re.compile(r"HTTP\s+(\d{3})", re.IGNORECASE)


def _status_from_exception(exc: BaseException) -> int | None:
    """Best-effort HTTP status code from a requests/urllib/stringified error."""
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    match = _HTTP_STATUS_RE.search(str(exc))
    if match:
        return int(match.group(1))
    return None


def _is_requests_transient(exc: BaseException) -> bool:
    name = type(exc).__name__
    module = type(exc).__module__
    transient_names = {
        "Timeout",
        "ConnectTimeout",
        "ReadTimeout",
        "ConnectionError",
        "ChunkedEncodingError",
        "ProxyError",
        "SSLError",
    }
    return module.startswith("requests") and name in transient_names


def is_transient_upstream(exc: BaseException) -> bool:
    """True when ``exc`` looks like a retryable upstream failure."""
    if isinstance(exc, TransientUpstreamError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if _is_requests_transient(exc):
        return True
    status = _status_from_exception(exc)
    if status is not None:
        return status in _TRANSIENT_STATUSES
    return False


def is_deterministic_message(error: str | None) -> bool:
    """True when a *stringified* upstream error is a terminal rejection.

    The reconciliation service stores ``danjuan_error`` as a string (it never
    propagates the exception object); the runner uses this to decide whether an
    unreachable danjuan is a hard "not listed" skip or a transient retryable.
    """
    if not error:
        return False
    match = _HTTP_STATUS_RE.search(error)
    if match:
        status = int(match.group(1))
        return 400 <= status < 500 and status != 429
    lowered = error.lower()
    return any(hint in error or hint in lowered for hint in _NOT_LISTED_HINTS)


# --------------------------------------------------------------------------- #
# Per-domain minimum-interval limiter
# --------------------------------------------------------------------------- #
class DomainLimiter:
    """Sleeps until at least ``interval`` seconds have elapsed since the last call.

    ``clock`` and ``sleep`` are injectable so tests can assert the exact gaps
    without waiting in real time.
    """

    def __init__(
        self,
        interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = max(0.0, float(interval))
        self._clock = clock
        self._sleep = sleep
        self._last = 0.0

    def acquire(self) -> None:
        if self._last:
            elapsed = self._clock() - self._last
            if elapsed < self.interval:
                self._sleep(self.interval - elapsed)

    def mark(self) -> None:
        self._last = self._clock()


# --------------------------------------------------------------------------- #
# Backoff policy
# --------------------------------------------------------------------------- #
class BackoffPolicy:
    """Exponential backoff: ``min(cap, base * 2**(attempt-1))`` seconds."""

    def __init__(
        self,
        *,
        max_retries: int,
        base_seconds: float,
        cap_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_retries = max(0, int(max_retries))
        self.base_seconds = float(base_seconds)
        self.cap_seconds = float(cap_seconds)
        self._sleep = sleep

    def delay_seconds(self, attempt: int) -> float:
        """``attempt`` is 1-based: the delay after the 1st/2nd/... failure."""
        raw = self.base_seconds * (2.0 ** (max(1, attempt) - 1))
        return min(self.cap_seconds, float(raw))

    def sleep(self, attempt: int) -> None:
        self._sleep(self.delay_seconds(attempt))


# --------------------------------------------------------------------------- #
# The composite throttle
# --------------------------------------------------------------------------- #
class BatchThrottle:
    """Govern every upstream call by domain: rate-limit, then retry transient."""

    def __init__(
        self,
        limits: Mapping[str, float],
        *,
        max_retries: int,
        backoff_base_seconds: float,
        backoff_cap_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._limiters = {
            domain: DomainLimiter(limits.get(domain, 0.0), clock=clock, sleep=sleep)
            for domain in DOMAINS
        }
        self._backoff = BackoffPolicy(
            max_retries=max_retries,
            base_seconds=backoff_base_seconds,
            cap_seconds=backoff_cap_seconds,
            sleep=sleep,
        )
        self.max_retries = self._backoff.max_retries

    def limiter(self, domain: str) -> DomainLimiter:
        if domain not in self._limiters:
            raise KeyError(f"unknown throttle domain: {domain!r}; expected one of {DOMAINS}")
        return self._limiters[domain]

    def run(self, domain: str, fn: Callable[[], T]) -> T:
        """Run ``fn`` under the ``domain`` limiter, retrying transient failures.

        * :class:`DeterministicReject` propagates immediately (never retried).
        * Transient failures are retried up to ``max_retries`` with backoff; when
          the budget is exhausted a :class:`TransientUpstreamError` is raised.
        * Any other exception (parsing / validation / bug) propagates unchanged so
          the runner can classify it (e.g. as a per-fund quality rejection).
        """
        limiter = self.limiter(domain)
        attempt = 0
        while True:
            limiter.acquire()
            try:
                result = fn()
            except DeterministicReject:
                limiter.mark()
                raise
            except Exception as exc:  # noqa: BLE001 - classified below
                limiter.mark()
                if is_transient_upstream(exc):
                    if attempt < self._backoff.max_retries:
                        attempt += 1
                        self._backoff.sleep(attempt)
                        continue
                    raise TransientUpstreamError(
                        f"{domain} transient upstream failure after {attempt} "
                        f"retries: {type(exc).__name__}: {exc}"
                    ) from exc
                if isinstance(exc, DeterministicReject) or _looks_like_deterministic(exc):
                    reason = getattr(exc, "reason", None) or "danjuan_not_listed"
                    raise DeterministicReject(
                        f"{domain} deterministic rejection: {type(exc).__name__}: {exc}",
                        reason=reason,
                    ) from exc
                raise
            else:
                limiter.mark()
                return result


def _looks_like_deterministic(exc: BaseException) -> bool:
    status = _status_from_exception(exc)
    if status is not None:
        return 400 <= status < 500 and status != 429
    text = str(exc)
    return any(hint in text for hint in _NOT_LISTED_HINTS)


__all__ = [
    "DOMAINS",
    "BackoffPolicy",
    "BatchThrottle",
    "BatchThrottleError",
    "DeterministicReject",
    "DomainLimiter",
    "TransientUpstreamError",
    "is_deterministic_message",
    "is_transient_upstream",
]
