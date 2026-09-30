"""Online Eastmoney direct data source.

This adapter reuses :class:`EastmoneySnapshotBuilder` to pull public Eastmoney
pages on demand (never copying the builder's fetch/parse logic) and adapts it to
the transactional :class:`FundDataSource` protocol. It never writes to the
database itself; the sync job performs the atomic snapshot promotion.

Two operational modes coexist with the offline auditable mirror:

* ``eastmoney_direct`` (this adapter): low-frequency online pull, incremental NAV
  merge against a local on-disk history cache.
* ``eastmoney_snapshot_v1`` (offline mirror via ``public_http_json``): a fully
  audited static mirror built by ``scripts/build_eastmoney_mirror.py``.

Compliance boundary: only public pages are read, requests are rate-limited, no
anti-scraping controls are bypassed, and no field is fabricated. When upstream
structure changes, the capability degrades loudly instead of inventing data.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.data_sources.profiles.eastmoney_snapshot import (
    BASE_INFO_URL,
    NAV_URL,
    EastmoneyRawSnapshot,
    EastmoneySnapshotBuilder,
    build_fund_snapshot,
)
from app.data_sources.universe import (
    UniverseFilters,
    UniverseFetcher,
    default_fetcher,
    load_or_fetch_universe,
)
from app.schemas.data_source_health import DataSourceHealthReport, EndpointHealth
from app.schemas.funds import FundDetail

_SIX_DIGIT = re.compile(r"^\d{6}$")
_DEFAULT_YEARS_LOOKBACK_DAYS = 5 * 366 + 45


def _valid_codes(codes: tuple[str, ...]) -> list[str]:
    return [code for code in codes if _SIX_DIGIT.fullmatch(code)]


class EastmoneyDirectFundDataSource:
    name = "eastmoney_direct"

    def __init__(
        self,
        *,
        fund_codes: tuple[str, ...] | None = None,
        discovery_limit: int | None = None,
        enable_incremental: bool | None = None,
        cache_dir: str | None = None,
        timeout_seconds: int | None = None,
        min_interval_seconds: float | None = None,
        health_enabled: bool | None = None,
        discover_codes: Callable[[int], list[str]] | None = None,
        universe_fetcher: UniverseFetcher | None = None,
        universe_cache_dir: str | None = None,
        include_short_history: bool | None = None,
    ) -> None:
        self._configured_codes = list(
            fund_codes if fund_codes is not None else settings.fund_eastmoney_fund_codes
        )
        self._discovery_limit = (
            discovery_limit
            if discovery_limit is not None
            else settings.fund_eastmoney_discovery_limit
        )
        self._enable_incremental = (
            enable_incremental
            if enable_incremental is not None
            else settings.fund_eastmoney_enable_incremental
        )
        raw_cache_dir = (
            cache_dir if cache_dir is not None else settings.fund_eastmoney_cache_dir
        )
        self._cache_dir = Path(raw_cache_dir) if raw_cache_dir.strip() else None
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.fund_eastmoney_timeout_seconds
        )
        self._min_interval_seconds = (
            min_interval_seconds
            if min_interval_seconds is not None
            else settings.fund_eastmoney_min_interval_seconds
        )
        self._health_enabled = (
            health_enabled
            if health_enabled is not None
            else settings.fund_eastmoney_health_enabled
        )
        self._discover_codes = discover_codes
        # Full-universe discovery (discovery_limit == -1) runs through the D0
        # snapshot pipeline. The fetcher/cache are injectable so tests never touch
        # akshare/network; include_short_history gates <3y history funds.
        self._universe_fetcher = universe_fetcher
        raw_universe_cache = (
            universe_cache_dir
            if universe_cache_dir is not None
            else settings.fund_batch_universe_cache_dir.as_posix()
        )
        self._universe_cache_dir = Path(raw_universe_cache) if raw_universe_cache else None
        self._include_short_history = (
            include_short_history
            if include_short_history is not None
            else settings.fund_batch_include_short_history
        )
        self._builder = EastmoneySnapshotBuilder(
            self._timeout_seconds,
            self._min_interval_seconds,
        )
        self.last_run_report: dict[str, Any] = {}
        self._validate_config()

    # ------------------------------------------------------------------ config

    def _validate_config(self) -> None:
        invalid = [code for code in self._configured_codes if not _SIX_DIGIT.fullmatch(code)]
        if invalid:
            raise ValueError(
                "FUND_EASTMONEY_FUND_CODES entries must be six digits; got: "
                + ", ".join(invalid)
            )
        self._codes: list[str] = list(dict.fromkeys(self._configured_codes))
        # 0 = discovery disabled (fail-fast on empty codes); -1 = full D0
        # universe; >0 = limited akshare rank discovery.
        self._discovery_enabled = self._discovery_limit != 0
        if not self._codes and not self._discovery_enabled:
            raise ValueError(
                "eastmoney_direct requires FUND_EASTMONEY_FUND_CODES (explicit six-digit "
                "codes) or FUND_EASTMONEY_DISCOVERY_LIMIT != 0 (>0 or -1); it never "
                "silently scrapes the whole market"
            )

    # ------------------------------------------------------------- fund codes

    def _resolve_codes(self) -> tuple[list[str], list[dict[str, Any]]]:
        codes: list[str] = list(self._codes)
        skipped: list[dict[str, Any]] = []
        if self._discovery_enabled:
            try:
                discovered = self._discover_codes_for_limit()
            except Exception as exc:  # discovery is best-effort, never fatal
                skipped.append(
                    {
                        "stage": "discovery",
                        "code": None,
                        "reason": f"{type(exc).__name__}: {exc}",
                    }
                )
                discovered = []
            for code in discovered:
                if _SIX_DIGIT.fullmatch(code) and code not in codes:
                    codes.append(code)
        if not codes:
            raise ValueError("eastmoney_direct resolved to an empty fund set; refusing sync")
        return codes, skipped

    def _discover_codes_for_limit(self) -> list[str]:
        """Return the candidate codes depending on the configured discovery limit."""
        if self._discovery_limit == -1:
            return self._default_discover_universe_codes()
        if self._discover_codes is not None:
            return self._discover_codes(self._discovery_limit)
        return self._default_discover_codes(self._discovery_limit)

    def _default_discover_universe_codes(self) -> list[str]:
        """Full-market discovery through the D0 universe snapshot + classifier.

        Only funds the classifier routes to ``supported`` are returned. When
        ``include_short_history`` is False the universe pre-filter requires a
        近3年 metric; when True, short-history eligible classes are promoted to
        supported by the classifier instead. Special caliber (money-market,
        on-exchange ETF, REITs, commodity) and secondary/unknown shares are dropped.
        """
        # Imported lazily: fund_classifier pulls in this package's universe
        # submodule, and importing it at module load would cycle back through
        # app.data_sources.__init__ while eastmoney_direct is still loading.
        from app.core.fund_classifier import classify

        filters = UniverseFilters(require_has_3y=not self._include_short_history)
        cache_dir = self._universe_cache_dir or settings.fund_batch_universe_cache_dir
        funds = load_or_fetch_universe(
            cache_dir=cache_dir,
            filters=filters,
            fetcher=self._universe_fetcher or default_fetcher,
        )
        codes: list[str] = []
        for fund in funds:
            decision = classify(fund, include_short_history=self._include_short_history)
            if decision.route == "supported" and _SIX_DIGIT.fullmatch(fund.code):
                codes.append(fund.code)
        return codes

    def _default_discover_codes(self, limit: int) -> list[str]:
        if self._discover_codes is not None:
            return self._discover_codes(limit)
        import akshare as ak  # type: ignore[import-untyped]  # optional, lazily loaded

        rank_fn = getattr(ak, "fund_open_fund_rank_em", None)
        if rank_fn is None:
            raise RuntimeError("akshare open-fund rank endpoint is unavailable")
        frame = rank_fn(symbol="全部")
        column = "基金代码"
        if column not in getattr(frame, "columns", []):
            raise RuntimeError("akshare rank frame lacks a 基金代码 column")
        codes: list[str] = []
        for value in frame[column].astype(str):
            code = value.strip().zfill(6)
            if _SIX_DIGIT.fullmatch(code) and code not in codes:
                codes.append(code)
            if len(codes) >= limit:
                break
        return codes

    # ------------------------------------------------------------- nav cache

    def _cache_path(self, code: str) -> Path:
        assert self._cache_dir is not None
        return self._cache_dir / "navs" / f"{code}.json"

    def _read_cached_rows(self, code: str) -> list[dict[str, Any]]:
        if self._cache_dir is None:
            return []
        path = self._cache_path(code)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = payload.get("nav_rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _write_cached_rows(self, code: str, rows: list[dict[str, Any]]) -> None:
        if self._cache_dir is None:
            return
        path = self._cache_path(code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"nav_rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _merge_rows(
        existing: list[dict[str, Any]], fresh: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_date: dict[str, dict[str, Any]] = {}
        for row in [*existing, *fresh]:
            date_value = row.get("FSRQ")
            if isinstance(date_value, str) and date_value:
                by_date[date_value] = row
        return sorted(by_date.values(), key=lambda row: str(row.get("FSRQ", "")))

    # -------------------------------------------------------------- snapshot

    def _collect_funds(self, generated_at: datetime) -> list[FundDetail]:
        as_of = generated_at.date()
        codes, skipped = self._resolve_codes()
        funds: list[FundDetail] = []
        per_fund: list[dict[str, Any]] = []
        for code in codes:
            try:
                fund, report = self._build_one(code, as_of, generated_at)
            except Exception:
                if code in self._codes:
                    raise  # explicitly requested funds must not be silently dropped
                skipped.append({"stage": "build", "code": code, "reason": "upstream/invalid"})
                continue
            funds.append(fund)
            per_fund.append(report)
        self.last_run_report = {
            "mode": "online_direct",
            "incremental_enabled": self._enable_incremental and self._cache_dir is not None,
            "fund_count": len(funds),
            "skipped": skipped,
            "funds": per_fund,
        }
        return funds

    def _build_one(
        self,
        code: str,
        as_of: date,
        generated_at: datetime,
    ) -> tuple[FundDetail, dict[str, Any]]:
        cached_rows = self._read_cached_rows(code)
        incremental_start, mode, reason = self._plan_incremental(cached_rows)
        raw = self._builder.fetch_raw(code, as_of, start_date=incremental_start)
        merged_rows = self._merge_rows(cached_rows, raw.nav_rows)
        merged_raw = EastmoneyRawSnapshot(
            base_info=raw.base_info,
            nav_rows=merged_rows,
            profile_html=raw.profile_html,
            manager_html=raw.manager_html,
        )
        fund = build_fund_snapshot(merged_raw, generated_at)
        self._write_cached_rows(code, merged_rows)
        report: dict[str, Any] = {
            "code": code,
            "nav_fetch_mode": mode,
            "cached_nav_rows": len(cached_rows),
            "fetched_nav_rows": len(raw.nav_rows),
            "merged_nav_rows": len(merged_rows),
            "nav_trace": raw.nav_trace,
        }
        if reason:
            report["fallback_reason"] = reason
        return fund, report

    def _plan_incremental(
        self, cached_rows: list[dict[str, Any]]
    ) -> tuple[date | None, str, str | None]:
        if not (self._enable_incremental and self._cache_dir is not None):
            return None, "full", "incremental_disabled"
        if not cached_rows:
            return None, "full", "no_cached_rows"
        latest = max(
            (str(row["FSRQ"]) for row in cached_rows if isinstance(row.get("FSRQ"), str)),
            default="",
        )
        if not latest:
            return None, "full", "cached_rows_unusable"
        try:
            return date.fromisoformat(latest), "incremental", None
        except ValueError:
            return None, "full", "cached_latest_date_invalid"

    # ------------------------------------------------------- protocol methods

    def fetch_snapshot(self) -> list[FundDetail]:
        generated_at = datetime.now(timezone.utc)
        return self._collect_funds(generated_at)

    def fetch_fund_profiles(self) -> list[FundDetail]:
        # Eastmoney fund metrics are derived from the NAV series, so a profile
        # snapshot cannot be produced without NAV points; return the full snapshot.
        return self.fetch_snapshot()

    def fetch_fund_navs(self) -> list[FundDetail]:
        return self.fetch_snapshot()

    def fetch_risk_levels(self) -> dict[str, str]:
        return {fund.code: fund.risk_level for fund in self.fetch_fund_profiles()}

    # ----------------------------------------------------------------- health

    def health_check(self) -> DataSourceHealthReport:
        checked_at = datetime.now(timezone.utc).isoformat()
        endpoints: list[EndpointHealth] = []
        if not self._health_enabled:
            return DataSourceHealthReport(
                source=self.name,
                checked_at=checked_at,
                overall_reachable=False,
                enabled=False,
                configured_fund_codes=self._codes,
                discovery_enabled=self._discovery_enabled,
                discovery_limit=self._discovery_limit,
                note="eastmoney health check disabled by configuration",
            )
        probe_code = self._codes[0] if self._codes else ""
        reachable = False
        latency_ms: float | None = None
        error: str | None = None
        if not probe_code:
            error = "no configured fund code; cannot probe the fund-scoped endpoint"
        else:
            started = time.monotonic()
            try:
                self._builder._read_json(
                    BASE_INFO_URL,
                    {
                        "FCODE": probe_code,
                        "deviceid": "fund-analysis-health",
                        "plat": "Iphone",
                        "product": "EFund",
                        "version": "6.3.8",
                    },
                )
                latency_ms = round((time.monotonic() - started) * 1000, 2)
                reachable = True
            except Exception as exc:  # probe must never raise
                error = f"{type(exc).__name__}: {exc}"
        endpoints.append(
            EndpointHealth(
                name="base_info",
                url=BASE_INFO_URL,
                reachable=reachable,
                latency_ms=latency_ms,
                error=error,
            )
        )
        return DataSourceHealthReport(
            source=self.name,
            checked_at=checked_at,
            overall_reachable=reachable,
            enabled=True,
            endpoints=endpoints,
            configured_fund_codes=self._codes,
            discovery_enabled=self._discovery_enabled,
            discovery_limit=self._discovery_limit,
            note=f"minimal single-endpoint probe against {NAV_URL.rsplit('/', 1)[0]}",
        )
