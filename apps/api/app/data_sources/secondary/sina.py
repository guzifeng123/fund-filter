"""Sina (新浪基金) secondary reconciliation source.

Read-only cross-check feed over Sina's public realtime quote endpoint
``https://hq.sinajs.cn/list=of{code}``. Two hard requirements of this endpoint:

* it only answers with the mandatory header ``Referer: https://finance.sina.com.cn/``;
* the body is encoded in **GBK**, not UTF-8.

Each line looks like::

    var hq_str_of000001="名称,单位净值,累计净值,前收/估算,日涨幅%,YYYY-MM-DD";

This feed returns only the *latest* quote per fund (there is no historical
series), so ``fetch_navs`` adapts to exactly one :class:`ReconcilableNavPoint`.
Unlike danjuan, Sina *does* publish an accumulated (累计) NAV, which is mapped
straight onto ``accumulated_nav``. Per-code failures (missing line, empty
fields, malformed numbers, encoding errors) mark only that code unavailable
rather than fabricating a whole success.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

import requests

from app.core.config import settings
from app.core.reconciliation import ReconcilableNavPoint, ReconcilableProfile
from app.data_sources.secondary.base import SourceHealth

QUOTE_URL = "https://hq.sinajs.cn/list={symbols}"
REFERER = "https://finance.sina.com.cn/"
PROBE_CODE = "000001"
DEFAULT_BATCH_SIZE = 40
USER_AGENT = "fund-filter-reconciliation/0.1 (+secondary cross-check feed)"
_LINE = re.compile(r'var hq_str_of(\d{6})="([^"]*)";')


class SinaUpstreamError(RuntimeError):
    """Raised when the sina feed cannot be read or decoded."""


@dataclass(frozen=True)
class SinaQuote:
    name: str
    unit_nav: float
    accumulated_nav: float
    daily_change_pct: float | None
    trade_date: date


def _opt_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _opt_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class SinaSource:
    """Secondary reconciliation source backed by Sina fund quotes."""

    source_name = "sina"

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        min_interval_seconds: float | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch: bool = True,
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
        self.batch_size = max(1, batch_size)
        # FUND_RECONCILE_SINA_BATCH: batch=True groups codes into one list= request
        # of up to batch_size; batch=False sends one request per code (chunk size 1).
        self.batch = batch
        self._chunk_size = self.batch_size if batch else 1
        self.probe_code = probe_code
        self._sleep = sleep
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": USER_AGENT, "Referer": REFERER}
        )

    # -- transport (overridden in tests) --------------------------------------
    def _raw_get_text(self, url: str) -> str:
        response = self._session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        # Sina serves GBK; decoding as UTF-8 would raise on CJK fund names.
        return response.content.decode("gbk", errors="replace")

    def _respect_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.min_interval_seconds:
            self._sleep(self.min_interval_seconds - elapsed)

    def _get_text(self, url: str) -> str:
        self._respect_interval()
        text = self._raw_get_text(url)
        self._last_request_at = time.monotonic()
        return text

    # -- public protocol ------------------------------------------------------
    def health_check(self) -> SourceHealth:
        start = time.monotonic()
        try:
            quotes = self.fetch_quotes([self.probe_code])
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return SourceHealth(reachable=False, latency_ms=None, error=f"{type(exc).__name__}: {exc}")
        if self.probe_code not in quotes:
            return SourceHealth(
                reachable=False,
                latency_ms=None,
                error=f"probe code {self.probe_code} missing from sina response",
            )
        latency_ms = (time.monotonic() - start) * 1000
        return SourceHealth(reachable=True, latency_ms=round(latency_ms, 2), error=None)

    def fetch_quotes(self, codes: list[str]) -> dict[str, SinaQuote]:
        """Fetch the latest quote for every requested code.

        Codes that are absent from the response, have empty/malformed fields, or
        fail to parse are simply omitted from the returned dict — the caller can
        tell "unavailable" from "present" by membership.
        """
        normalized = [_normalize_code(code) for code in codes]
        result: dict[str, SinaQuote] = {}
        for chunk in _chunks(normalized, self._chunk_size):
            symbols = ",".join(f"of{code}" for code in chunk)
            url = QUOTE_URL.format(symbols=symbols)
            text = self._get_text(url)
            parsed = _parse_quote_text(text)
            result.update(parsed)
        return {code: quote for code, quote in result.items() if code in set(normalized)}

    def fetch_profile(self, code: str) -> ReconcilableProfile:
        normalized = _normalize_code(code)
        quotes = self.fetch_quotes([normalized])
        quote = quotes.get(normalized)
        if quote is None:
            raise SinaUpstreamError(f"sina has no quote for {normalized}")
        # Sina only exposes the short display name; everything else stays empty/None
        # so this profile serves as a name-only third-party cross-check.
        return ReconcilableProfile(
            source=self.source_name,
            code=normalized,
            name=quote.name,
            full_name=None,
            found_date=None,
            company=None,
            custodian=None,
            managers=[],
            fund_type_raw=None,
            benchmark=None,
            scale_text=None,
            rates=None,
        )

    def fetch_navs(self, code: str, since: date | None = None) -> list[ReconcilableNavPoint]:
        # Sina quotes are point-in-time only; `since` is accepted for protocol
        # compatibility but cannot filter a (non-existent) history.
        del since
        normalized = _normalize_code(code)
        quotes = self.fetch_quotes([normalized])
        quote = quotes.get(normalized)
        if quote is None:
            raise SinaUpstreamError(f"sina has no quote for {normalized}")
        return [
            ReconcilableNavPoint(
                date=quote.trade_date,
                unit_nav=quote.unit_nav,
                accumulated_nav=quote.accumulated_nav,
                daily_change_pct=quote.daily_change_pct,
                source=self.source_name,
            )
        ]


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_quote_text(text: str) -> dict[str, SinaQuote]:
    parsed: dict[str, SinaQuote] = {}
    for match in _LINE.finditer(text):
        code = match.group(1)
        raw = match.group(2)
        quote = _parse_quote_line(raw)
        if quote is not None:
            parsed[code] = quote
    return parsed


def _parse_quote_line(raw: str) -> SinaQuote | None:
    fields = raw.split(",")
    # Expected: name, unit_nav, accumulated_nav, prev/estimate, pct, date
    if len(fields) < 6:
        return None
    name = fields[0].strip()
    unit_nav = _opt_float(fields[1].strip())
    accumulated_nav = _opt_float(fields[2].strip())
    pct = _opt_float(fields[4].strip())
    trade_date = _opt_date(fields[5].strip())
    if not name or unit_nav is None or accumulated_nav is None or trade_date is None:
        # Any essential field empty/unparseable -> this code is unavailable.
        return None
    return SinaQuote(
        name=name,
        unit_nav=unit_nav,
        accumulated_nav=accumulated_nav,
        daily_change_pct=pct,
        trade_date=trade_date,
    )


def _normalize_code(code: str) -> str:
    normalized = code.strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError(f"fund code must be six digits: {code!r}")
    return normalized
