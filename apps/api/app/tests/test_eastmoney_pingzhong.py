"""Offline tests for the Eastmoney pingzhongdata fast NAV path.

The real bundle for 000001 is trimmed (head + inception/window/tail points) and
checked into ``app/tests/fixtures/eastmoney_pingzhong/``; every HTTP call in
these tests is intercepted by a fake ``_read_text`` transport, so no network is
touched.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.data_sources.profiles.eastmoney_pingzhong import (
    PINGZHONG_URL,
    PingzhongDataError,
    PingzhongMoneyFundError,
    parse_pingzhong_navs,
)
from app.data_sources.profiles.eastmoney_snapshot import (
    NAV_URL,
    EastmoneySnapshotBuilder,
    _merge_nav_rows,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eastmoney_pingzhong"


# ------------------------------------------------------------- pure parser tests


def test_parse_real_trimmed_bundle_extracts_inception_window_and_tail() -> None:
    js_text = (FIXTURE_DIR / "000001.js").read_text(encoding="utf-8")

    rows = parse_pingzhong_navs(js_text, "000001")

    # 11 real points: 3 inception + 5 around the 5y window edge + 3 tail.
    assert len(rows) == 11
    # x is a ms epoch at 00:00 UTC -> Asia/Shanghai date is the trade date; the
    # first point must be the fund inception date (2001-12-18), not the offer start.
    assert rows[0]["FSRQ"] == "2001-12-18"
    assert rows[0]["DWJZ"] == "1.0"
    assert rows[0]["LJJZ"] == "1.0"
    # Ascending, sorted by trade date.
    assert [r["FSRQ"] for r in rows] == sorted(r["FSRQ"] for r in rows)
    # Tail points: unit/accumulated NAVs and a percent daily return.
    assert rows[-1] == {
        "FSRQ": "2026-09-29",
        "DWJZ": "1.246",
        "LJJZ": "3.819",
        "JZZZL": "0.16",
    }
    # equityReturn is a percent number (0.16 == +0.16%), matching lsjz JZZZL unit.
    assert float(rows[-1]["JZZZL"]) == pytest.approx(0.16)


def test_parse_truncates_to_requested_window() -> None:
    js_text = (FIXTURE_DIR / "000001.js").read_text(encoding="utf-8")
    rows = parse_pingzhong_navs(js_text, "000001")
    as_of = date(2026, 9, 30)
    start = as_of - timedelta(days=5 * 366 + 45)

    window = [r for r in rows if start.isoformat() <= r["FSRQ"] <= as_of.isoformat()]

    # Only the 2021-08-12-onward window-edge points + the 3 tail points fall in the
    # 5y window; the 2001 inception points and the two days before the window edge
    # (2021-08-10/11) are excluded.
    assert [r["FSRQ"] for r in window] == [
        "2021-08-12",
        "2021-08-13",
        "2021-08-16",
        "2026-09-24",
        "2026-09-28",
        "2026-09-29",
    ]


def test_pingzhong_rows_match_lsjz_rows_overlapping_window() -> None:
    """pingzhong parsed rows must be field-for-field equivalent to lsjz rows."""
    js_text = (FIXTURE_DIR / "000001.js").read_text(encoding="utf-8")
    pz_rows = parse_pingzhong_navs(js_text, "000001")
    # Build an lsjz-style payload with the SAME values (lsjz returns strings).
    lsjz_rows = [
        {
            "FSRQ": r["FSRQ"],
            "DWJZ": r["DWJZ"],
            "LJJZ": r["LJJZ"],
            "JZZZL": r["JZZZL"],
        }
        for r in pz_rows
    ]
    # Both normalize identically through the shared NavPoint mapping.
    from app.data_sources.profiles.eastmoney_snapshot import _normalize_navs

    pz_points = _normalize_navs(list(pz_rows))
    lsjz_points = _normalize_navs(list(lsjz_rows))
    assert [p.trade_date for p in pz_points] == [p.trade_date for p in lsjz_points]
    assert [p.nav for p in pz_points] == pytest.approx([p.nav for p in lsjz_points])
    assert [p.accumulated_nav for p in pz_points] == pytest.approx(
        [p.accumulated_nav for p in lsjz_points]
    )


# ----------------------------------------------------------- fail-closed cases


def test_money_fund_shape_raises_defensive_error() -> None:
    js_text = 'var fS_name = "某某货币A";var Data_netWorthTrend=[];var Data_ACWorthTrend=[];'
    with pytest.raises(PingzhongMoneyFundError, match="货币"):
        parse_pingzhong_navs(js_text, "000198")


def test_missing_net_trend_is_fail_closed() -> None:
    js_text = 'var fS_name = "华夏成长混合";var Data_ACWorthTrend=[[1,1.0]];'
    with pytest.raises(PingzhongDataError, match="Data_netWorthTrend"):
        parse_pingzhong_navs(js_text, "000001")


def test_corrupt_truncated_array_is_fail_closed() -> None:
    js_text = (
        'var fS_name = "华夏成长混合";'
        'var Data_netWorthTrend=[{"x":1008604800000,"y":1.0,'
    )
    with pytest.raises(PingzhongDataError):
        parse_pingzhong_navs(js_text, "000001")


def test_missing_accumulated_series_is_fail_closed() -> None:
    js_text = (
        'var fS_name = "华夏成长混合";'
        'var Data_netWorthTrend=[{"x":1008604800000,"y":1.0,"equityReturn":0}];'
    )
    with pytest.raises(PingzhongDataError, match="Data_ACWorthTrend"):
        parse_pingzhong_navs(js_text, "000001")


# ------------------------------------------------------------ builder integration


class FakeHTTP:
    """Scripted stand-in for the builder's rate-limited ``_read_text`` seam."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.routes: dict[str, Any] = {}

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        for needle, response in self.routes.items():
            if needle in url:
                if callable(response):
                    return str(response(url))
                return str(response)
        raise AssertionError(f"unexpected upstream URL: {url}")


def _lsjz_payload(rows: list[dict[str, Any]]) -> str:
    return json.dumps({"Data": {"LSJZList": rows}, "TotalCount": len(rows), "ErrCode": 0})


def _build_builder(fake: FakeHTTP) -> EastmoneySnapshotBuilder:
    builder = EastmoneySnapshotBuilder(timeout_seconds=5, min_interval_seconds=0.0)
    builder._read_text = fake  # type: ignore[method-assign]
    return builder


def test_fast_path_prefers_pingzhong_and_tops_up_latest() -> None:
    fake = FakeHTTP()
    fake.routes[PINGZHONG_URL.format(code="000001")] = (
        (FIXTURE_DIR / "000001.js").read_text(encoding="utf-8")
    )
    # lsjz top-up returns the overlapping last point (fresher value) plus a newer day.
    topup_rows = [
        {"FSRQ": "2026-09-29", "DWJZ": "1.247", "LJJZ": "3.820", "JZZZL": "0.16"},
        {"FSRQ": "2026-09-30", "DWJZ": "1.255", "LJJZ": "3.830", "JZZZL": "0.64"},
    ]
    fake.routes[NAV_URL] = lambda _url: _lsjz_payload(topup_rows)
    builder = _build_builder(fake)

    rows, trace = builder._read_nav_rows("000001", date(2021, 8, 12), date(2026, 9, 30))

    assert trace == "pingzhong+lsjz_topup"
    dates = [r["FSRQ"] for r in rows]
    # No duplicate trade dates; lsjz fresher value wins on 2026-09-29; new day added.
    assert len(dates) == len(set(dates))
    by_date = {r["FSRQ"]: r for r in rows}
    assert by_date["2026-09-29"]["DWJZ"] == "1.247"  # lsjz top-up wins over bundle 1.246
    assert by_date["2026-09-30"]["DWJZ"] == "1.255"  # QDII-lag day filled by lsjz
    # Sorted ascending.
    assert dates == sorted(dates)
    # Exactly one pingzhong bundle request + one small lsjz page.
    assert sum("pingzhongdata/000001.js" in c for c in fake.calls) == 1
    assert sum(c.startswith(NAV_URL) for c in fake.calls) == 1


def test_pingzhong_unavailable_falls_back_to_paginated_lsjz() -> None:
    fake = FakeHTTP()

    def _boom(_url: str) -> str:
        raise TimeoutError("pingzhong timed out")

    fake.routes[PINGZHONG_URL.format(code="000001")] = _boom
    legacy_rows = [
        {"FSRQ": "2026-09-28", "DWJZ": "1.244", "LJJZ": "3.817"},
        {"FSRQ": "2026-09-29", "DWJZ": "1.246", "LJJZ": "3.819"},
    ]
    fake.routes[NAV_URL] = lambda _url: _lsjz_payload(legacy_rows)
    builder = _build_builder(fake)

    rows, trace = builder._read_nav_rows("000001", date(2021, 8, 12), date(2026, 9, 30))

    assert trace.startswith("pingzhong_fallback:")
    assert [r["FSRQ"] for r in rows] == ["2026-09-28", "2026-09-29"]


def test_pingzhong_corrupt_bundle_falls_back_to_lsjz() -> None:
    fake = FakeHTTP()
    fake.routes[PINGZHONG_URL.format(code="000001")] = (
        'var fS_name="华夏成长混合";var Data_netWorthTrend=[{"x":broken'
    )
    legacy_rows = [{"FSRQ": "2026-09-29", "DWJZ": "1.246", "LJJZ": "3.819"}]
    fake.routes[NAV_URL] = lambda _url: _lsjz_payload(legacy_rows)
    builder = _build_builder(fake)

    rows, trace = builder._read_nav_rows("000001", date(2021, 8, 12), date(2026, 9, 30))

    assert trace.startswith("pingzhong_fallback:")
    assert rows == legacy_rows


def test_money_fund_error_propagates_without_lsjz_fallback() -> None:
    fake = FakeHTTP()
    fake.routes[PINGZHONG_URL.format(code="000198")] = (
        'var fS_name="某某货币A";var Data_netWorthTrend=[];'
    )
    builder = _build_builder(fake)

    with pytest.raises(PingzhongMoneyFundError, match="货币"):
        builder._read_nav_rows("000198", date(2021, 8, 12), date(2026, 9, 30))
    # No lsjz fallback attempt for a money fund.
    assert not any(c.startswith(NAV_URL) for c in fake.calls)


def test_rate_limiter_sees_pingzhong_request() -> None:
    # The pingzhong bundle must go through the shared rate-limited _read_text seam
    # (so min_interval_seconds still applies per host), never around it.
    builder = EastmoneySnapshotBuilder(timeout_seconds=5, min_interval_seconds=0.0)
    seen: list[str] = []

    def fake_read_text(url: str) -> str:
        seen.append(url)
        if "pingzhongdata/000001.js" in url:
            return (FIXTURE_DIR / "000001.js").read_text(encoding="utf-8")
        if NAV_URL in url:
            return _lsjz_payload([])
        raise AssertionError(url)

    with patch.object(builder, "_read_text", side_effect=fake_read_text):
        builder._read_nav_rows("000001", date(2021, 8, 12), date(2026, 9, 30))

    assert any("pingzhongdata/000001.js" in url for url in seen)


def test_merge_dedups_and_sorts() -> None:
    older = [{"FSRQ": "2026-09-24", "DWJZ": "1.0", "LJJZ": "3.0"}]
    newer = [
        {"FSRQ": "2026-09-24", "DWJZ": "1.1", "LJJZ": "3.1"},  # overlap: newer wins
        {"FSRQ": "2026-09-29", "DWJZ": "1.2", "LJJZ": "3.2"},
    ]
    merged = _merge_nav_rows(older, newer)
    assert [r["FSRQ"] for r in merged] == ["2026-09-24", "2026-09-29"]
    assert merged[0]["DWJZ"] == "1.1"
