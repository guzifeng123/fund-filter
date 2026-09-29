"""Tests for the eastmoney_direct online adapter, incremental merge and health probe.

All network access is faked: the adapter's EastmoneySnapshotBuilder is replaced by
an in-test double, so these tests never touch the upstream.
"""

from datetime import date
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.data_sources import get_fund_data_source
from app.data_sources.eastmoney_direct import EastmoneyDirectFundDataSource
from app.data_sources.profiles.eastmoney_snapshot import EastmoneyRawSnapshot
from app.jobs.sync_fund_data import sync_all
from app.main import app
from app.schemas.data_source_health import DataSourceHealthReport

BASE_INFO: dict[str, Any] = {
    "FCODE": "000001",
    "SHORTNAME": "华夏成长混合",
    "FTYPE": "混合型-灵活",
    "RISKLEVEL": "4",
    "JJJL": "郑晓辉",
    "ISSBDATE": "2001-11-28 00:00:00",
    "ENDNAV": "2644299859.12",
    "RANKY": "358",
    "YSC": "2284",
}
PROFILE_HTML = (
    "<tr><th>管理费率</th><td>1.20%（每年）</td>"
    "<th>托管费率</th><td>0.20%（每年）</td></tr>"
)
MANAGER_HTML = "<tbody><tr><td>2024-12-26</td><td>至今</td><td>郑晓辉</td></tr></tbody>"

# Annual NAV points spanning ~6 years so 3y/5y annualized windows are satisfied.
BASE_ROWS = [
    {"FSRQ": "2020-07-10", "DWJZ": "1.000", "LJJZ": "2.500"},
    {"FSRQ": "2021-07-10", "DWJZ": "1.100", "LJJZ": "2.800"},
    {"FSRQ": "2022-07-10", "DWJZ": "1.200", "LJJZ": "3.000"},
    {"FSRQ": "2023-07-10", "DWJZ": "1.300", "LJJZ": "3.200"},
    {"FSRQ": "2024-07-10", "DWJZ": "1.400", "LJJZ": "3.400"},
    {"FSRQ": "2025-07-10", "DWJZ": "1.500", "LJJZ": "3.600"},
    {"FSRQ": "2026-07-10", "DWJZ": "1.600", "LJJZ": "3.800"},
]
# Incremental fetch returns the overlapping latest row plus one new row.
NEW_ROWS = [
    {"FSRQ": "2026-07-10", "DWJZ": "1.600", "LJJZ": "3.800"},
    {"FSRQ": "2026-09-29", "DWJZ": "1.700", "LJJZ": "3.900"},
]


class FakeBuilder:
    """Stand-in for EastmoneySnapshotBuilder that never performs network I/O."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, date | None]] = []
        self.health_error: Exception | None = None
        self.fail_codes: set[str] = set()

    def fetch_raw(
        self,
        code: str,
        as_of: date,
        *,
        start_date: date | None = None,
    ) -> EastmoneyRawSnapshot:
        if code in self.fail_codes:
            raise RuntimeError(f"upstream unavailable for {code}")
        self.calls.append((code, start_date))
        if start_date is None:
            rows = list(BASE_ROWS)
        else:
            rows = [row for row in BASE_ROWS + NEW_ROWS if row["FSRQ"] >= start_date.isoformat()]
        return EastmoneyRawSnapshot(
            base_info=dict(BASE_INFO),
            nav_rows=rows,
            profile_html=PROFILE_HTML,
            manager_html=MANAGER_HTML,
        )

    def _read_json(self, url: str, query: dict[str, str | int]) -> dict[str, Any]:
        if self.health_error is not None:
            raise self.health_error
        return {"Datas": dict(BASE_INFO), "ErrCode": 0}


def _make_source(tmp_path: Path, **overrides: Any) -> tuple[EastmoneyDirectFundDataSource, FakeBuilder]:
    kwargs: dict[str, Any] = {
        "fund_codes": ("000001",),
        "discovery_limit": 0,
        "enable_incremental": True,
        "cache_dir": str(tmp_path / "cache"),
        "timeout_seconds": 5,
        "min_interval_seconds": 0.0,
    }
    kwargs.update(overrides)
    source = EastmoneyDirectFundDataSource(**kwargs)
    builder = FakeBuilder()
    source._builder = builder  # type: ignore[assignment]
    return source, builder


# ------------------------------------------------------------------ fail-fast


def test_eastmoney_direct_requires_explicit_codes_or_discovery() -> None:
    with pytest.raises(ValueError, match="never silently scrape"):
        EastmoneyDirectFundDataSource(fund_codes=(), discovery_limit=0)


def test_eastmoney_direct_rejects_non_numeric_codes() -> None:
    with pytest.raises(ValueError, match="six digits"):
        EastmoneyDirectFundDataSource(fund_codes=("ABC123",), discovery_limit=0)


def test_factory_registers_eastmoney_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.config.settings.fund_eastmoney_fund_codes", ("000001",)
    )
    source = get_fund_data_source("eastmoney_direct")
    assert source.name == "eastmoney_direct"
    with pytest.raises(ValueError, match="unknown fund data source"):
        get_fund_data_source("does_not_exist")


# ------------------------------------------------------------- incremental


def test_first_run_is_full_then_second_run_is_incremental(tmp_path: Path) -> None:
    source, builder = _make_source(tmp_path)
    first = source.fetch_snapshot()
    assert len(first) == 1
    assert len(first[0].navs) == 7
    # First run: no cached history -> full pull.
    assert builder.calls[0][0] == "000001"
    assert builder.calls[0][1] is None
    assert source.last_run_report["funds"][0]["nav_fetch_mode"] == "full"

    second = source.fetch_snapshot()
    assert len(second) == 1
    # Second run: start_date anchored at the latest cached NAV (2026-07-10).
    assert builder.calls[-1][0] == "000001"
    assert builder.calls[-1][1] == date(2026, 7, 10)
    assert source.last_run_report["funds"][0]["nav_fetch_mode"] == "incremental"
    # Merged history keeps the 7 base points plus the one new point.
    assert [point.trade_date for point in second[0].navs][-2:] == ["2026-07-10", "2026-09-29"]
    assert len(second[0].navs) == 8


def test_incremental_disabled_falls_back_to_full(tmp_path: Path) -> None:
    source, builder = _make_source(tmp_path, enable_incremental=False)
    source.fetch_snapshot()
    source.fetch_snapshot()
    # Both pulls are full; start_date is None.
    assert all(start is None for _, start in builder.calls)
    assert source.last_run_report["funds"][0]["nav_fetch_mode"] == "full"


def test_unreadable_cache_falls_back_to_full(tmp_path: Path) -> None:
    source, _ = _make_source(tmp_path)
    cache_file = source._cache_path("000001")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("not-json", encoding="utf-8")

    source.fetch_snapshot()

    report = source.last_run_report["funds"][0]
    assert report["nav_fetch_mode"] == "full"
    assert report["fallback_reason"] == "no_cached_rows"


# ---------------------------------------------------------------- discovery


def test_discovery_failure_is_recorded_not_fatal(tmp_path: Path) -> None:
    def boom(_limit: int) -> list[str]:
        raise RuntimeError("akshare down")

    source, _ = _make_source(tmp_path, discovery_limit=5, discover_codes=boom)
    funds = source.fetch_snapshot()
    assert [fund.code for fund in funds] == ["000001"]
    skipped = source.last_run_report["skipped"]
    assert skipped and skipped[0]["stage"] == "discovery"
    assert "akshare down" in skipped[0]["reason"]


def test_discovered_fund_build_failure_is_skipped(tmp_path: Path) -> None:
    source, builder = _make_source(
        tmp_path, discovery_limit=5, discover_codes=lambda _n: ["999999"]
    )
    builder.fail_codes = {"999999"}
    funds = source.fetch_snapshot()

    assert [fund.code for fund in funds] == ["000001"]
    skipped = source.last_run_report["skipped"]
    assert any(entry.get("code") == "999999" and entry["stage"] == "build" for entry in skipped)


def test_explicit_fund_failure_propagates(tmp_path: Path) -> None:
    source, builder = _make_source(tmp_path)
    builder.fail_codes = {"000001"}
    with pytest.raises(RuntimeError, match="upstream unavailable"):
        source.fetch_snapshot()


# ------------------------------------------------------------------- health


def test_health_check_reports_probe_failure(tmp_path: Path) -> None:
    source, builder = _make_source(tmp_path)
    builder.health_error = RuntimeError("boom")

    report = source.health_check()

    assert isinstance(report, DataSourceHealthReport)
    assert report.overall_reachable is False
    assert report.endpoints[0].reachable is False
    assert "boom" in (report.endpoints[0].error or "")


def test_health_check_disabled_by_config(tmp_path: Path) -> None:
    source, _ = _make_source(tmp_path, health_enabled=False)
    report = source.health_check()
    assert report.enabled is False
    assert report.endpoints == []


# --------------------------------------------------------------- router / sync


class _StubSource:
    name = "eastmoney_direct"

    def health_check(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "checked_at": "2026-09-29T00:00:00+00:00",
            "overall_reachable": True,
            "enabled": True,
            "endpoints": [
                {
                    "name": "base_info",
                    "url": "https://fundmobapi.eastmoney.com/x",
                    "reachable": True,
                    "latency_ms": 12.0,
                    "error": None,
                }
            ],
            "configured_fund_codes": ["000001"],
            "discovery_enabled": False,
            "discovery_limit": 0,
            "skipped": [],
            "note": "probe",
        }


def test_health_router_returns_envelope() -> None:
    with patch(
        "app.routers.data_sources_health.get_fund_data_source",
        lambda: _StubSource(),
    ):
        response = TestClient(app).get("/api/data/sources/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["overall_reachable"] is True
    assert body["meta"]["source"] == "eastmoney_direct"


def test_sync_all_atomic_promotion_with_direct_source(
    db_session: Session,
    tmp_path: Path,
) -> None:
    source, _ = _make_source(tmp_path)
    result = sync_all(db_session, source_override=source)
    assert result["source"] == "eastmoney_direct"
    assert result["fund_count"] == 1
    assert result["nav_count"] == 7
    assert result["generation_boundary"] == "atomic_promotion"
    run_report = cast(dict[str, Any], result["source_run_report"])
    assert run_report["fund_count"] == 1
