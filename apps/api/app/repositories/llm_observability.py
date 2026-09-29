import logging
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from queue import Empty, Full, Queue
from typing import Literal, TypeAlias, cast
from urllib.request import Request, urlopen

from sqlalchemy import case, delete, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.models import LlmProviderEvent

logger = logging.getLogger(__name__)

LlmProviderOutcome: TypeAlias = Literal["success", "fallback"]
LlmErrorCategory: TypeAlias = Literal[
    "config_missing",
    "timeout",
    "network",
    "rate_limited",
    "http_client",
    "http_server",
    "invalid_response",
    "policy_rejected",
    "provider_error",
]
LlmAlert: TypeAlias = Literal["error_rate", "timeout_rate"]
LlmAlertAction: TypeAlias = Literal["triggered", "recovered"]
LlmObservabilityStatus: TypeAlias = Literal["ok", "alert", "insufficient_data"]
EventRecorder: TypeAlias = Callable[["LlmProviderEventData"], None]
LlmAlertSender: TypeAlias = Callable[[str, dict[str, object], float], None]

SAFE_LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
JWT_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}")
HOST_PORT_PATTERN = re.compile(
    r"(?i)(?:localhost|(?:[a-z0-9-]+\.)+[a-z]{2,}\.?|\d{1,3}(?:\.\d{1,3}){3}):\d{1,5}"
)
LOCALHOST_PATTERN = re.compile(r"(?i)localhost\.?")
IPV4_PATTERN = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}\.?")
BARE_HOSTNAME_PATTERN = re.compile(r"(?i)(?:[a-z0-9-]+\.)+[a-z]{2,}\.?")
CREDENTIAL_PREFIX_PATTERN = re.compile(
    r"(?i)(?:sk|pk|rk)(?:[-_][a-z0-9]+)+|"
    r"(?:gh[pousr]_|github_pat_|xox[baprs]-|aiza|akia)[a-z0-9_-]+"
)
SENSITIVE_LABEL_TERM_PATTERN = re.compile(
    r"(?i)(?:^|[._-])(?:api[-_]?key|access[-_]?token|refresh[-_]?token|"
    r"token|secret|password|passwd|credential|bearer)(?:$|[._-])"
)
HIGH_ENTROPY_TOKEN_PATTERN = re.compile(r"(?=.{24,}$)(?=.*[A-Z])(?=.*[a-z])(?=.*\d)[A-Za-z0-9_-]+")
OPAQUE_ALNUM_TOKEN_PATTERN = re.compile(r"(?=.{24,}$)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+")
VALID_ERROR_CATEGORIES: frozenset[str] = frozenset(
    {
        "config_missing",
        "timeout",
        "network",
        "rate_limited",
        "http_client",
        "http_server",
        "invalid_response",
        "policy_rejected",
        "provider_error",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LlmProviderEventData:
    provider_name: str
    model_name: str
    outcome: LlmProviderOutcome
    attempt_count: int
    retry_count: int
    latency_ms: int
    timed_out: bool
    error_category: LlmErrorCategory | None
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class LlmProviderMetrics:
    window_minutes: int
    minimum_requests: int
    request_count: int
    success_count: int
    error_count: int
    retry_count: int
    retried_request_count: int
    timeout_count: int
    request_rate_per_minute: float
    success_rate: float
    error_rate: float
    retry_rate: float
    timeout_rate: float
    alerts: tuple[LlmAlert, ...]
    status: LlmObservabilityStatus
    last_event_at: datetime | None


@dataclass(frozen=True)
class LlmDispatcherHealth:
    status: Literal["disabled", "not_started", "ok", "degraded"]
    worker_count: int
    pending_count: int
    capacity: int
    dropped_count: int


@dataclass(frozen=True)
class LlmProviderCleanupReport:
    schema_version: int
    ok: bool
    dry_run: bool
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    retention_days: int
    cutoff_at: datetime
    matched_count: int
    deleted_count: int
    remaining_count: int


@dataclass
class LlmAlertDeliveryState:
    active: bool
    last_sent_at: datetime


@dataclass(frozen=True)
class QueuedLlmProviderEvent:
    event: LlmProviderEventData
    event_sessionmaker: sessionmaker[Session]


LlmEventSink: TypeAlias = Callable[[QueuedLlmProviderEvent], None]


def sanitize_llm_label(value: str, *, max_length: int) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > max_length
        or SAFE_LABEL_PATTERN.fullmatch(normalized) is None
        or JWT_PATTERN.fullmatch(normalized) is not None
        or HOST_PORT_PATTERN.fullmatch(normalized) is not None
        or LOCALHOST_PATTERN.fullmatch(normalized) is not None
        or IPV4_PATTERN.fullmatch(normalized) is not None
        or BARE_HOSTNAME_PATTERN.fullmatch(normalized) is not None
        or CREDENTIAL_PREFIX_PATTERN.fullmatch(normalized) is not None
        or SENSITIVE_LABEL_TERM_PATTERN.search(normalized) is not None
        or HIGH_ENTROPY_TOKEN_PATTERN.fullmatch(normalized) is not None
        or OPAQUE_ALNUM_TOKEN_PATTERN.fullmatch(normalized) is not None
    ):
        return "unknown"
    return normalized


def _safe_error_category(value: str | None) -> LlmErrorCategory | None:
    if value is None:
        return None
    if value in VALID_ERROR_CATEGORIES:
        return cast(LlmErrorCategory, value)
    return "provider_error"


def _normalized_event(event: LlmProviderEventData) -> LlmProviderEventData:
    attempt_count = max(0, event.attempt_count)
    retry_count = min(max(0, event.retry_count), max(0, attempt_count - 1))
    error_category = _safe_error_category(event.error_category)
    outcome = event.outcome
    timed_out = event.timed_out
    if attempt_count == 0:
        outcome = "fallback"
        error_category = "config_missing"
        timed_out = False
    elif outcome == "fallback" and error_category is None:
        error_category = "provider_error"
    created_at = event.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)
    return LlmProviderEventData(
        provider_name=sanitize_llm_label(event.provider_name, max_length=64),
        model_name=sanitize_llm_label(event.model_name, max_length=128),
        outcome=outcome,
        attempt_count=attempt_count,
        retry_count=retry_count,
        latency_ms=max(0, event.latency_ms),
        timed_out=timed_out,
        error_category=error_category,
        created_at=created_at,
    )


_llm_alert_delivery_state: dict[tuple[str, str, LlmAlert], LlmAlertDeliveryState] = {}
_llm_alert_delivery_lock = threading.Lock()


def _post_json_webhook(url: str, payload: dict[str, object], timeout_seconds: float) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        response.read(1)


def _alert_payload(
    *,
    provider_name: str,
    model_name: str,
    alert: LlmAlert,
    action: LlmAlertAction,
    metrics: LlmProviderMetrics,
    now: datetime,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "component": "llm_provider",
        "action": action,
        "alert": alert,
        "provider": provider_name,
        "model": model_name,
        "status": metrics.status,
        "window_minutes": metrics.window_minutes,
        "minimum_requests": metrics.minimum_requests,
        "request_count": metrics.request_count,
        "error_rate": metrics.error_rate,
        "timeout_rate": metrics.timeout_rate,
        "retry_rate": metrics.retry_rate,
        "error_rate_alert_threshold": settings.llm_error_rate_alert_threshold,
        "timeout_rate_alert_threshold": settings.llm_timeout_rate_alert_threshold,
        "last_event_at": metrics.last_event_at.isoformat() if metrics.last_event_at else None,
        "notified_at": now.isoformat(),
    }


def notify_llm_provider_alerts(
    metrics: LlmProviderMetrics,
    *,
    provider_name: str,
    model_name: str,
    webhook_url: str,
    cooldown_minutes: int,
    timeout_seconds: float,
    now: datetime | None = None,
    sender: LlmAlertSender = _post_json_webhook,
) -> None:
    if not webhook_url:
        return
    effective_now = now or datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    else:
        effective_now = effective_now.astimezone(timezone.utc)
    provider = sanitize_llm_label(provider_name, max_length=64)
    model = sanitize_llm_label(model_name, max_length=128)
    current_alerts = set(metrics.alerts)
    cooldown = timedelta(minutes=cooldown_minutes)
    payloads: list[tuple[LlmAlertAction, LlmAlert, dict[str, object]]] = []
    with _llm_alert_delivery_lock:
        tracked_keys = [
            key
            for key in _llm_alert_delivery_state
            if key[0] == provider and key[1] == model
        ]
        for key in tracked_keys:
            alert = key[2]
            if alert in current_alerts:
                continue
            recovered_state = _llm_alert_delivery_state.get(key)
            if recovered_state is not None and recovered_state.active:
                payloads.append(
                    (
                        "recovered",
                        alert,
                        _alert_payload(
                            provider_name=provider,
                            model_name=model,
                            alert=alert,
                            action="recovered",
                            metrics=metrics,
                            now=effective_now,
                        ),
                    )
                )
        for alert in sorted(current_alerts):
            key = (provider, model, alert)
            active_state = _llm_alert_delivery_state.get(key)
            if active_state is not None and effective_now - active_state.last_sent_at < cooldown:
                continue
            payloads.append(
                (
                    "triggered",
                    alert,
                    _alert_payload(
                        provider_name=provider,
                        model_name=model,
                        alert=alert,
                        action="triggered",
                        metrics=metrics,
                        now=effective_now,
                    ),
                )
            )
    for action, alert, payload in payloads:
        try:
            sender(webhook_url, payload, timeout_seconds)
        except Exception:
            logger.warning(
                "llm_provider_alert_delivery_failed",
                extra={
                    "provider": provider,
                    "model": model,
                    "alert": alert,
                    "action": action,
                },
            )
            continue
        with _llm_alert_delivery_lock:
            key = (provider, model, alert)
            if action == "triggered":
                _llm_alert_delivery_state[key] = LlmAlertDeliveryState(
                    active=True,
                    last_sent_at=effective_now,
                )
            else:
                _llm_alert_delivery_state.pop(key, None)


def _persist_queued_event(item: QueuedLlmProviderEvent) -> None:
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


class LlmEventDispatcher:
    def __init__(
        self,
        *,
        capacity: int,
        sink: LlmEventSink = _persist_queued_event,
        thread_name: str = "llm-provider-event-writer",
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be greater than 0")
        self._queue: Queue[QueuedLlmProviderEvent] = Queue(maxsize=capacity)
        self._sink = sink
        self._condition = threading.Condition()
        self._stop_requested = threading.Event()
        self._accepting = True
        self._pending_count = 0
        self._dropped_count = 0
        self._reported_dropped_count = 0
        self._worker_failure_count = 0
        self._thread_name = thread_name
        self._thread = self._start_worker()

    def _start_worker(self) -> threading.Thread:
        thread = threading.Thread(
            target=self._run,
            name=self._thread_name,
            daemon=True,
        )
        thread.start()
        return thread

    @property
    def capacity(self) -> int:
        return self._queue.maxsize

    @property
    def pending_count(self) -> int:
        with self._condition:
            return self._pending_count

    @property
    def dropped_count(self) -> int:
        with self._condition:
            return self._dropped_count

    @property
    def worker_count(self) -> int:
        return int(self._thread.is_alive())

    @property
    def worker_failure_count(self) -> int:
        with self._condition:
            return self._worker_failure_count

    @property
    def accepting(self) -> bool:
        with self._condition:
            return self._accepting

    def ensure_worker_running(self) -> bool:
        with self._condition:
            if self._stop_requested.is_set() or not self._accepting:
                return False
            if self._thread.is_alive():
                return True
            self._thread = self._start_worker()
            return True

    def submit(self, item: QueuedLlmProviderEvent) -> bool:
        item = QueuedLlmProviderEvent(
            event=_normalized_event(item.event),
            event_sessionmaker=item.event_sessionmaker,
        )
        self.ensure_worker_running()
        with self._condition:
            if not self._accepting:
                self._dropped_count += 1
            else:
                self._pending_count += 1
                try:
                    self._queue.put_nowait(item)
                except Full:
                    self._pending_count -= 1
                    self._dropped_count += 1
                    self._condition.notify_all()
                else:
                    return True
        return False

    def drain(self, *, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0, timeout_seconds)
        with self._condition:
            while self._pending_count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def close(self, *, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0, timeout_seconds)
        with self._condition:
            self._accepting = False
        drained = self.drain(timeout_seconds=max(0, deadline - time.monotonic()))
        self._stop_requested.set()
        self._thread.join(timeout=max(0, deadline - time.monotonic()))
        if self._thread.is_alive():
            self._drop_queued_events()
        self._report_dropped_events()
        return drained and not self._thread.is_alive()

    def _drop_queued_events(self) -> None:
        dropped_count = 0
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                break
            self._queue.task_done()
            dropped_count += 1
        if dropped_count <= 0:
            return
        with self._condition:
            self._pending_count = max(0, self._pending_count - dropped_count)
            self._dropped_count += dropped_count
            self._condition.notify_all()

    def _report_dropped_events(self) -> None:
        with self._condition:
            dropped_count = self._dropped_count - self._reported_dropped_count
            if dropped_count <= 0:
                return
            self._reported_dropped_count = self._dropped_count
            total_dropped_count = self._dropped_count
        logger.warning(
            "llm_provider_event_queue_dropped",
            extra={
                "dropped_count": dropped_count,
                "total_dropped_count": total_dropped_count,
            },
        )

    def _run(self) -> None:
        try:
            while not self._stop_requested.is_set() or not self._queue.empty():
                try:
                    item = self._queue.get(timeout=0.05)
                except Empty:
                    continue
                try:
                    self._sink(item)
                except Exception:
                    logger.warning(
                        "llm_provider_event_persistence_failed",
                        extra={
                            "provider": item.event.provider_name,
                            "model": item.event.model_name,
                            "outcome": item.event.outcome,
                        },
                    )
                finally:
                    self._queue.task_done()
                    with self._condition:
                        self._pending_count -= 1
                        self._condition.notify_all()
                    self._report_dropped_events()
        except BaseException:
            with self._condition:
                self._worker_failure_count += 1
                self._condition.notify_all()
            logger.exception("llm_provider_event_worker_exited")


_default_dispatcher: LlmEventDispatcher | None = None
_default_dispatcher_lock = threading.Lock()


def get_default_llm_event_dispatcher() -> LlmEventDispatcher:
    global _default_dispatcher
    with _default_dispatcher_lock:
        if _default_dispatcher is None or not _default_dispatcher.accepting:
            _default_dispatcher = LlmEventDispatcher(
                capacity=settings.llm_observability_queue_capacity
            )
        else:
            _default_dispatcher.ensure_worker_running()
        return _default_dispatcher


def drain_default_llm_event_dispatcher(*, timeout_seconds: float) -> bool:
    with _default_dispatcher_lock:
        dispatcher = _default_dispatcher
    return True if dispatcher is None else dispatcher.drain(timeout_seconds=timeout_seconds)


def shutdown_default_llm_event_dispatcher(*, timeout_seconds: float) -> bool:
    global _default_dispatcher
    with _default_dispatcher_lock:
        dispatcher = _default_dispatcher
    if dispatcher is None:
        return True
    closed = dispatcher.close(timeout_seconds=timeout_seconds)
    with _default_dispatcher_lock:
        if _default_dispatcher is dispatcher:
            _default_dispatcher = None
    return closed


def default_llm_dispatcher_health(*, enabled: bool) -> LlmDispatcherHealth:
    if not enabled:
        return LlmDispatcherHealth(
            status="disabled",
            worker_count=0,
            pending_count=0,
            capacity=0,
            dropped_count=0,
        )
    with _default_dispatcher_lock:
        dispatcher = _default_dispatcher
    if dispatcher is None:
        return LlmDispatcherHealth(
            status="not_started",
            worker_count=0,
            pending_count=0,
            capacity=settings.llm_observability_queue_capacity,
            dropped_count=0,
        )
    worker_count = dispatcher.worker_count
    dropped_count = dispatcher.dropped_count
    worker_failure_count = dispatcher.worker_failure_count
    return LlmDispatcherHealth(
        status=(
            "ok"
            if worker_count > 0 and dropped_count == 0 and worker_failure_count == 0 and dispatcher.accepting
            else "degraded"
        ),
        worker_count=worker_count,
        pending_count=dispatcher.pending_count,
        capacity=dispatcher.capacity,
        dropped_count=dropped_count,
    )


def make_llm_event_recorder(
    db: Session,
    *,
    dispatcher: LlmEventDispatcher | None = None,
) -> EventRecorder:
    bind = db.get_bind()
    engine = bind.engine if isinstance(bind, Connection) else bind
    event_sessionmaker = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    selected_dispatcher = dispatcher or get_default_llm_event_dispatcher()

    def record(event: LlmProviderEventData) -> None:
        selected_dispatcher.submit(
            QueuedLlmProviderEvent(
                event=event,
                event_sessionmaker=event_sessionmaker,
            )
        )

    return record


def aggregate_llm_provider_metrics(
    db: Session,
    *,
    provider_name: str,
    model_name: str,
    window_minutes: int,
    minimum_requests: int,
    error_rate_alert_threshold: float,
    timeout_rate_alert_threshold: float,
    now: datetime | None = None,
) -> LlmProviderMetrics:
    safe_provider = sanitize_llm_label(provider_name, max_length=64)
    safe_model = sanitize_llm_label(model_name, max_length=128)
    effective_now = now or datetime.now(timezone.utc)
    window_start = effective_now - timedelta(minutes=window_minutes)
    transport_error = (LlmProviderEvent.outcome == "fallback") & (
        LlmProviderEvent.error_category != "policy_rejected"
    )
    row = db.execute(
        select(
            func.count(LlmProviderEvent.id),
            func.sum(case((~transport_error, 1), else_=0)),
            func.sum(case((transport_error, 1), else_=0)),
            func.sum(LlmProviderEvent.retry_count),
            func.sum(case((LlmProviderEvent.retry_count > 0, 1), else_=0)),
            func.sum(case((LlmProviderEvent.timed_out.is_(True), 1), else_=0)),
            func.max(LlmProviderEvent.created_at),
        ).where(
            LlmProviderEvent.created_at >= window_start,
            LlmProviderEvent.provider_name == safe_provider,
            LlmProviderEvent.model_name == safe_model,
            LlmProviderEvent.attempt_count >= 1,
        )
    ).one()

    request_count = int(row[0] or 0)
    success_count = int(row[1] or 0)
    error_count = int(row[2] or 0)
    retry_count = int(row[3] or 0)
    retried_request_count = int(row[4] or 0)
    timeout_count = int(row[5] or 0)
    last_event_at = row[6]
    if last_event_at is not None:
        if last_event_at.tzinfo is None:
            last_event_at = last_event_at.replace(tzinfo=timezone.utc)
        else:
            last_event_at = last_event_at.astimezone(timezone.utc)
    denominator = request_count or 1
    error_rate = error_count / denominator
    timeout_rate = timeout_count / denominator
    alerts: list[LlmAlert] = []
    if request_count >= minimum_requests:
        if error_rate > error_rate_alert_threshold:
            alerts.append("error_rate")
        if timeout_rate > timeout_rate_alert_threshold:
            alerts.append("timeout_rate")

    if request_count < minimum_requests:
        status: LlmObservabilityStatus = "insufficient_data"
    elif alerts:
        status = "alert"
    else:
        status = "ok"

    return LlmProviderMetrics(
        window_minutes=window_minutes,
        minimum_requests=minimum_requests,
        request_count=request_count,
        success_count=success_count,
        error_count=error_count,
        retry_count=retry_count,
        retried_request_count=retried_request_count,
        timeout_count=timeout_count,
        request_rate_per_minute=request_count / window_minutes,
        success_rate=success_count / denominator,
        error_rate=error_rate,
        retry_rate=retried_request_count / denominator,
        timeout_rate=timeout_rate,
        alerts=tuple(alerts),
        status=status,
        last_event_at=last_event_at,
    )


def cleanup_llm_provider_events(
    db: Session,
    *,
    retention_days: int,
    dry_run: bool = False,
    now: datetime | None = None,
) -> LlmProviderCleanupReport:
    if retention_days <= 0:
        raise ValueError("retention_days must be greater than 0")
    started_at = datetime.now(timezone.utc)
    effective_now = now or started_at
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    else:
        effective_now = effective_now.astimezone(timezone.utc)
    cutoff_at = effective_now - timedelta(days=retention_days)
    matched_count = int(
        db.scalar(
            select(func.count(LlmProviderEvent.id)).where(
                LlmProviderEvent.created_at < cutoff_at
            )
        )
        or 0
    )
    deleted_count = 0
    if matched_count and not dry_run:
        result = db.execute(
            delete(LlmProviderEvent).where(LlmProviderEvent.created_at < cutoff_at)
        )
        deleted_count = int(getattr(result, "rowcount", 0) or 0)
        db.commit()
    remaining_count = int(db.scalar(select(func.count(LlmProviderEvent.id))) or 0)
    finished_at = datetime.now(timezone.utc)
    return LlmProviderCleanupReport(
        schema_version=1,
        ok=True,
        dry_run=dry_run,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=max(0, round((finished_at - started_at).total_seconds() * 1000)),
        retention_days=retention_days,
        cutoff_at=cutoff_at,
        matched_count=matched_count,
        deleted_count=deleted_count,
        remaining_count=remaining_count,
    )
