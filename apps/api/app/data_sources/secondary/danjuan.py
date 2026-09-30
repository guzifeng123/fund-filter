"""Danjuan (蛋卷基金) secondary reconciliation source.

Read-only cross-check feed over the public, login-free ``danjuanfunds.com``
djapi endpoints. Only a User-Agent header is sent; requests are throttled to a
shared minimum interval and retried conservatively on 429/5xx with exponential
backoff. No field is fabricated: missing upstream values map to ``None`` and a
failed probe reports ``reachable=False`` rather than a success.

Endpoint reference (all public, no login):
* ``GET /djapi/fund/{code}``             -> base profile incl. fund_rates
* ``GET /djapi/fund/detail/{code}``      -> detail (withdraw_rate lives here)
* ``GET /djapi/fund/nav/history/{code}?page=N&size=M`` -> NAV history (date desc)

Important upstream quirk: danjuan's mixed-type funds expose ``value`` equal to
``nav`` (unit NAV) — there is no accumulated/复权 NAV in this feed, so
``ReconcilableNavPoint.accumulated_nav`` is always emitted as ``None`` and
``value`` must never be mistaken for the accumulated NAV.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable

import requests

from app.core.config import settings
from app.core.reconciliation import ReconcilableNavPoint, ReconcilableProfile
from app.data_sources.secondary.base import SourceHealth

BASE_URL = "https://danjuanfunds.com/djapi/fund"
PROBE_CODE = "000001"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Conservatively few retries: one extra attempt per transient status class.
MAX_RETRIES = 2
# Large pages keep the secondary pull cheap while still covering the primary's
# multi-year NAV window: the online Eastmoney builder fetches roughly 5 years
# (~1.25k trading points). danjuanfunds accepts size=500, which reaches a 5y
# window in about 3 pages instead of 60+ small requests.
DEFAULT_NAV_PAGE_SIZE = 500
# Hard safety cap so an unbounded historical pull can never run away when no
# ``since`` bound is supplied (the gate always passes ``since`` = the earliest
# primary NAV date, so a normal ~5y check stops after ~3 pages). 8 x 500 = 4000
# points (~16 trading years) is a generous ceiling; a fund older than that with
# no ``since`` is intentionally left for the engine's coverage gate to reject
# rather than triggering an unbounded crawl.
DEFAULT_MAX_NAV_PAGES = 8
USER_AGENT = "fund-filter-reconciliation/0.1 (+secondary cross-check feed)"


class DanjuanUpstreamError(RuntimeError):
    """Raised when the danjuan feed returns an unusable response."""


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_date(value: Any) -> date | None:
    text = _opt_str(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _split_managers(value: Any) -> list[str]:
    text = _opt_str(value)
    if text is None:
        return []
    return text.split()


class DanjuanSource:
    """Secondary reconciliation source backed by danjuanfunds public djapi."""

    source_name = "danjuan"

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        min_interval_seconds: float | None = None,
        nav_page_size: int = DEFAULT_NAV_PAGE_SIZE,
        max_nav_pages: int = DEFAULT_MAX_NAV_PAGES,
        probe_code: str = PROBE_CODE,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.fund_reconcile_secondary_timeout_seconds
        )
        self.min_interval_seconds = (
            min_interval_seconds
            if min_interval_seconds is not None
            else settings.fund_reconcile_secondary_min_interval_seconds
        )
        self.nav_page_size = nav_page_size
        self.max_nav_pages = max(1, max_nav_pages)
        self.probe_code = probe_code
        self._sleep = sleep
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    # -- transport (overridden in tests) -------------------------------------
    def _raw_get(self, url: str) -> requests.Response:
        return self._session.get(url, timeout=self.timeout_seconds)

    def _respect_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.min_interval_seconds:
            self._sleep(self.min_interval_seconds - elapsed)

    def _request_json(self, url: str) -> dict[str, Any]:
        attempt = 0
        while True:
            self._respect_interval()
            response = self._raw_get(url)
            self._last_request_at = time.monotonic()
            status = response.status_code
            if status in RETRY_STATUSES and attempt < MAX_RETRIES:
                attempt += 1
                self._sleep(0.5 * (2 ** (attempt - 1)))
                continue
            if status >= 400:
                raise DanjuanUpstreamError(f"danjuan GET {url} returned HTTP {status}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise DanjuanUpstreamError(f"danjuan GET {url} returned non-JSON body") from exc
            if not isinstance(payload, dict):
                raise DanjuanUpstreamError(f"danjuan GET {url} returned a non-object JSON body")
            return payload

    # -- public protocol ------------------------------------------------------
    def health_check(self) -> SourceHealth:
        start = time.monotonic()
        try:
            self._request_json(f"{BASE_URL}/{self.probe_code}")
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return SourceHealth(reachable=False, latency_ms=None, error=f"{type(exc).__name__}: {exc}")
        latency_ms = (time.monotonic() - start) * 1000
        return SourceHealth(reachable=True, latency_ms=round(latency_ms, 2), error=None)

    def fetch_profile(self, code: str) -> ReconcilableProfile:
        normalized = _normalize_code(code)
        body = self._request_json(f"{BASE_URL}/{normalized}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise DanjuanUpstreamError(f"danjuan profile for {normalized} is missing data")
        return ReconcilableProfile(
            source=self.source_name,
            code=str(data.get("fd_code") or normalized),
            name=_opt_str(data.get("fd_name")),
            full_name=_opt_str(data.get("fd_full_name")),
            found_date=_opt_date(data.get("found_date")),
            company=_opt_str(data.get("keeper_name")),
            custodian=_opt_str(data.get("trup_name")),
            managers=_split_managers(data.get("manager_name")),
            fund_type_raw=_opt_str(data.get("type_desc")),
            benchmark=_opt_str(data.get("performance_bench_mark")),
            scale_text=_opt_str(data.get("totshare")),
            rates=self._extract_rates(normalized, data),
        )

    def fetch_navs(self, code: str, since: date | None = None) -> list[ReconcilableNavPoint]:
        normalized = _normalize_code(code)
        points: list[ReconcilableNavPoint] = []
        page = 1
        while page <= self.max_nav_pages:
            url = (
                f"{BASE_URL}/nav/history/{normalized}"
                f"?page={page}&size={self.nav_page_size}"
            )
            body = self._request_json(url)
            data = body.get("data")
            if not isinstance(data, dict):
                raise DanjuanUpstreamError(f"danjuan nav history for {normalized} is missing data")
            items = data.get("items")
            if not isinstance(items, list):
                raise DanjuanUpstreamError(f"danjuan nav history for {normalized} has no items")

            stopped_at_since = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                trade_date = _opt_date(item.get("date"))
                if trade_date is None:
                    continue
                if since is not None and trade_date < since:
                    # items are newest-first; everything further back is older.
                    stopped_at_since = True
                    break
                unit_nav = _opt_float(item.get("nav"))
                if unit_nav is None:
                    continue
                points.append(
                    ReconcilableNavPoint(
                        date=trade_date,
                        unit_nav=unit_nav,
                        # Danjuan mixed-type funds expose value == nav; there is NO
                        # accumulated NAV here — never map `value` onto this field.
                        accumulated_nav=None,
                        daily_change_pct=_opt_float(item.get("percentage")),
                        source=self.source_name,
                    )
                )
            if stopped_at_since:
                break

            current_page = _opt_int(data.get("current_page"))
            total_pages = _opt_int(data.get("total_pages"))
            if not items:
                break
            if current_page is not None and total_pages is not None and current_page >= total_pages:
                break
            page += 1
        return points

    # -- internals ------------------------------------------------------------
    def _extract_rates(self, code: str, base_data: dict[str, Any]) -> dict[str, float | None]:
        base_rates = base_data.get("fund_rates")
        rates: dict[str, float | None] = {
            "purchase": None,
            "redeem": None,
            "subscribe": None,
        }
        if isinstance(base_rates, dict):
            rates["purchase"] = _opt_float(base_rates.get("declare_rate"))
            rates["subscribe"] = _opt_float(base_rates.get("subscribe_rate"))
            rates["redeem"] = _opt_float(base_rates.get("withdraw_rate"))
        if rates["redeem"] is None:
            # withdraw_rate is only published on the detail endpoint; fetch it
            # best-effort. On any upstream failure we leave redeem=None rather
            # than fabricating a fee.
            try:
                detail_body = self._request_json(f"{BASE_URL}/detail/{code}")
            except (requests.RequestException, DanjuanUpstreamError):
                return rates
            detail_data = detail_body.get("data")
            detail_rates = detail_data.get("fund_rates") if isinstance(detail_data, dict) else None
            if isinstance(detail_rates, dict):
                rates["redeem"] = _opt_float(detail_rates.get("withdraw_rate"))
        return rates


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_code(code: str) -> str:
    normalized = code.strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError(f"fund code must be six digits: {code!r}")
    return normalized
