"""Tests for the secondary reconciliation sources (danjuan + sina).

All HTTP is stubbed at the transport layer (``_raw_get`` / ``_raw_get_text``) so
the suite never touches the network. Real recorded fixtures from
``fixtures/reconciliation/`` drive the field-mapping assertions.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import requests

from app.data_sources.secondary.danjuan import DanjuanSource
from app.data_sources.secondary.sina import (
    SinaSource,
    _parse_quote_line,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reconciliation"


def _load_recorded_body(name: str) -> dict[str, Any]:
    """A recorded fixture is {"url": ..., "body": <real api json>}; return body."""
    record: dict[str, Any] = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    body: dict[str, Any] = record["body"]
    return body


class _FakeResponse(requests.Response):
    def __init__(self, status_code: int, payload: Any = None) -> None:
        super().__init__()
        self.status_code = status_code
        self._payload = payload

    def json(self, **_kwargs: object) -> Any:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeDanjuan(DanjuanSource):
    """Routes GETs to recorded fixtures / canned nav pages."""

    def __init__(
        self,
        *,
        nav_pages: dict[tuple[str, int], dict[str, Any]] | None = None,
        status_script: list[int] | None = None,
        min_interval_seconds: float = 0.0,
        nav_page_size: int = 20,
    ) -> None:
        self.nav_pages = nav_pages or {}
        self.status_script = list(status_script or [])
        self.requested_urls: list[str] = []
        self.sleeps: list[float] = []
        super().__init__(
            timeout_seconds=1,
            min_interval_seconds=min_interval_seconds,
            nav_page_size=nav_page_size,
            sleep=self._record_sleep,
        )

    def _record_sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def _raw_get(self, url: str) -> requests.Response:
        self.requested_urls.append(url)
        if self.status_script:
            status = self.status_script.pop(0)
            return _FakeResponse(status, {"data": {"items": []}} if status < 400 else None)
        if "/detail/" in url:
            return _FakeResponse(200, _load_recorded_body("danjuan_detail_000001.json"))
        nav = re.search(r"/nav/history/(\d{6})\?page=(\d+)&", url)
        if nav:
            key = (nav.group(1), int(nav.group(2)))
            return _FakeResponse(200, self.nav_pages[key])
        base = re.search(r"/fund/(\d{6})$", url)
        if base:
            return _FakeResponse(200, _load_recorded_body(f"danjuan_base_{base.group(1)}.json"))
        return _FakeResponse(404, {"data": None})


def _nav_page(body: dict[str, Any], *, current_page: int, total_pages: int) -> dict[str, Any]:
    cloned: dict[str, Any] = json.loads(json.dumps(body))
    cloned["data"]["current_page"] = current_page
    cloned["data"]["total_pages"] = total_pages
    return cloned


# --------------------------------------------------------------------------- #
# danjuan: profile field mapping
# --------------------------------------------------------------------------- #
def test_danjuan_profile_field_mapping_including_detail_redeem() -> None:
    source = FakeDanjuan()

    profile = source.fetch_profile("000001")

    assert profile.source == "danjuan"
    assert profile.code == "000001"
    assert profile.name == "华夏成长混合"
    assert profile.full_name == "华夏成长证券投资基金"
    assert profile.found_date == date(2001, 12, 18)
    assert profile.company == "华夏基金管理有限公司"
    assert profile.custodian == "中国建设银行股份有限公司"
    assert profile.managers == ["刘睿聪", "郑晓辉"]
    assert profile.fund_type_raw == "混合型-偏股"
    assert profile.benchmark == "中证800成长指数收益率*70%+中债-综合全价（总值）指数收益率*30%"
    assert profile.scale_text == "39.38亿"
    # purchase/subscribe come from base.fund_rates; redeem only from detail.
    assert profile.rates is not None
    assert profile.rates["purchase"] == pytest.approx(1.5)
    assert profile.rates["subscribe"] == pytest.approx(0.0)
    assert profile.rates["redeem"] == pytest.approx(1.5)
    # detail endpoint must have been hit to obtain withdraw_rate.
    assert any("/detail/000001" in url for url in source.requested_urls)


def test_danjuan_profile_002910_base_fields() -> None:
    source = FakeDanjuan()

    profile = source.fetch_profile("002910")

    assert profile.code == "002910"
    assert profile.name == "易方达供给改革混合"
    assert profile.company == "易方达基金管理有限公司"
    assert profile.custodian == "中国银行股份有限公司"
    assert profile.managers == ["杨宗昌"]
    assert profile.fund_type_raw == "混合型-灵活配置"
    assert profile.scale_text == "140.76亿"
    assert profile.found_date == date(2017, 1, 25)
    assert profile.rates is not None
    assert profile.rates["purchase"] == pytest.approx(1.5)
    assert profile.rates["subscribe"] == pytest.approx(1.2)


# --------------------------------------------------------------------------- #
# danjuan: nav history pagination / since / accumulated_nav invariant
# --------------------------------------------------------------------------- #
def test_danjuan_nav_history_single_page_maps_unit_nav_and_never_value() -> None:
    page1 = _nav_page(
        _load_recorded_body("danjuan_nav_history_000001_p1.json"),
        current_page=1,
        total_pages=1,
    )
    source = FakeDanjuan(nav_pages={("000001", 1): page1})

    points = source.fetch_navs("000001")

    assert len(points) == 10
    newest = points[0]
    assert newest.date == date(2026, 9, 29)
    assert newest.unit_nav == pytest.approx(1.2460)
    assert newest.daily_change_pct == pytest.approx(0.16)
    # The critical invariant: danjuan `value == nav`, never the accumulated NAV.
    for point in points:
        assert point.accumulated_nav is None


def test_danjuan_nav_history_two_page_pagination() -> None:
    page1 = _nav_page(
        _load_recorded_body("danjuan_nav_history_002910_p1.json"),
        current_page=1,
        total_pages=2,
    )
    page2 = {
        "data": {
            "items": [
                {"date": "2026-09-21", "nav": "8.2200", "percentage": "0.10", "value": "8.2200"},
                {"date": "2026-09-18", "nav": "8.2000", "percentage": "-0.02", "value": "8.2000"},
            ],
            "current_page": 2,
            "size": 5,
            "total_items": 7,
            "total_pages": 2,
        },
        "result_code": 0,
    }
    source = FakeDanjuan(nav_pages={("002910", 1): page1, ("002910", 2): page2})

    points = source.fetch_navs("002910")

    assert len(points) == 7  # 5 on page 1 + 2 on page 2
    assert points[-1].date == date(2026, 9, 18)
    assert points[-1].unit_nav == pytest.approx(8.2000)
    assert any("page=2" in url for url in source.requested_urls)


def test_danjuan_nav_history_since_stops_at_first_older_item() -> None:
    page1 = _nav_page(
        _load_recorded_body("danjuan_nav_history_000001_p1.json"),
        current_page=1,
        total_pages=601,
    )
    source = FakeDanjuan(nav_pages={("000001", 1): page1})

    points = source.fetch_navs("000001", since=date(2026, 9, 22))

    # Items >= 2026-09-22 kept; 2026-09-21 and older stop the walk immediately.
    assert [p.date for p in points] == [
        date(2026, 9, 29),
        date(2026, 9, 28),
        date(2026, 9, 24),
        date(2026, 9, 23),
        date(2026, 9, 22),
    ]
    # Only one page requested even though total_pages=601: the since boundary ends it.
    assert len(source.requested_urls) == 1


def test_danjuan_nav_history_since_none_respects_hard_page_cap() -> None:
    # Simulate a never-ending feed: every page reports current_page < total_pages.
    endless_page = {
        "data": {
            "items": [
                {"date": "2026-09-29", "nav": "1.2", "percentage": "0.1", "value": "1.2"},
            ],
            "current_page": 1,
            "size": 1,
            "total_items": 100_000,
            "total_pages": 100_000,
        },
        "result_code": 0,
    }
    pages = {( "000001", p): _nav_page(
        json.loads(json.dumps(endless_page)), current_page=p, total_pages=100_000
    ) for p in range(1, 21)}
    source = FakeDanjuan(nav_pages=pages, nav_page_size=1)

    points = source.fetch_navs("000001", since=None)

    # Bounded by max_nav_pages (default 20) — never an unbounded pull.
    assert len(points) == 20
    assert len([u for u in source.requested_urls if "nav/history" in u]) == 20


# --------------------------------------------------------------------------- #
# danjuan: rate limit / retry / health
# --------------------------------------------------------------------------- #
def test_danjuan_respects_min_interval_sleep() -> None:
    source = FakeDanjuan(min_interval_seconds=0.05)

    # Two throttled requests: the second must sleep to honour the minimum gap.
    source._request_json("https://danjuanfunds.com/djapi/fund/000001")
    source._request_json("https://danjuanfunds.com/djapi/fund/000001")

    assert len(source.sleeps) >= 1
    assert source.sleeps[-1] > 0


def test_danjuan_retries_429_5xx_then_succeeds() -> None:
    source = FakeDanjuan(status_script=[500, 503, 200])

    points = source.fetch_navs("000001")

    # 3 attempts total (2 retries); the final 200 returns an empty items list.
    assert points == []
    assert len(source.requested_urls) == 3
    assert source.sleeps  # backoff sleeps happened


def test_danjuan_health_reports_unreachable_on_connection_error() -> None:
    source = FakeDanjuan()

    def _boom(url: str) -> requests.Response:
        raise requests.ConnectionError("boom")

    source._raw_get = _boom  # type: ignore[method-assign]

    health = source.health_check()

    assert health.reachable is False
    assert health.error
    assert "boom" in health.error


def test_danjuan_health_ok_on_success() -> None:
    source = FakeDanjuan()

    health = source.health_check()

    assert health.reachable is True
    assert health.error is None
    assert health.latency_ms is not None


# --------------------------------------------------------------------------- #
# sina: batch GBK quotes
# --------------------------------------------------------------------------- #
class FakeSina(SinaSource):
    def __init__(self, body: str, *, batch: bool = True, batch_size: int = 40) -> None:
        self._body = body
        self.requested_urls: list[str] = []
        super().__init__(
            timeout_seconds=1,
            min_interval_seconds=0.0,
            batch=batch,
            batch_size=batch_size,
            sleep=lambda s: None,
        )

    def _raw_get_text(self, url: str) -> str:
        self.requested_urls.append(url)
        return self._body


def _sina_source() -> FakeSina:
    # The recorded snapshot is a normalized UTF-8 text fixture; on the wire Sina
    # answers GBK. Either way the parser consumes a decoded str, so hand it the
    # decoded fixture body.
    body = (FIXTURE_DIR / "sina_quotes_of000001_of002910.txt").read_text(encoding="utf-8")
    return FakeSina(body)


def test_sina_batch_parses_both_funds_with_accumulated_nav() -> None:
    source = _sina_source()

    quotes = source.fetch_quotes(["000001", "002910"])

    assert set(quotes) == {"000001", "002910"}
    one = quotes["000001"]
    assert one.name == "华夏成长混合A"
    assert one.unit_nav == pytest.approx(1.246)
    assert one.accumulated_nav == pytest.approx(3.819)
    assert one.daily_change_pct == pytest.approx(0.16)
    assert one.trade_date == date(2026, 9, 29)
    two = quotes["002910"]
    assert two.unit_nav == pytest.approx(7.8755)
    # 002910 accumulated NAV == unit NAV (no dividend history).
    assert two.accumulated_nav == pytest.approx(7.8755)


def test_sina_batch_groups_codes_into_one_request() -> None:
    source = _sina_source()

    source.fetch_quotes(["000001", "002910"])

    # Both codes share a single list= request when batching is on.
    assert len(source.requested_urls) == 1
    assert "of000001,of002910" in source.requested_urls[0]


def test_sina_batch_off_sends_one_request_per_code() -> None:
    body = (FIXTURE_DIR / "sina_quotes_of000001_of002910.txt").read_text(encoding="utf-8")
    source = FakeSina(body, batch=False)

    quotes = source.fetch_quotes(["000001", "002910"])

    # batch=False: N codes -> N separate requests (chunk size 1).
    assert len(quotes) == 2
    assert len(source.requested_urls) == 2
    assert all(url.count("of") == 1 for url in source.requested_urls)


def test_sina_fetch_navs_returns_single_point_with_accumulated_nav() -> None:
    source = _sina_source()

    points = source.fetch_navs("000001")

    assert len(points) == 1
    point = points[0]
    assert point.unit_nav == pytest.approx(1.246)
    assert point.accumulated_nav == pytest.approx(3.819)
    assert point.daily_change_pct == pytest.approx(0.16)
    assert point.date == date(2026, 9, 29)


def test_sina_fetch_profile_name_only() -> None:
    source = _sina_source()

    profile = source.fetch_profile("000001")

    assert profile.source == "sina"
    assert profile.code == "000001"
    assert profile.name == "华夏成长混合A"
    # Everything else stays empty/None for a name-only cross-check.
    assert profile.full_name is None
    assert profile.company is None
    assert profile.managers == []


def test_sina_missing_code_line_is_absent_not_fabricated() -> None:
    source = FakeSina('var hq_str_of000001="华夏成长混合A,1.246,3.819,1.244,0.16,2026-09-29";')

    quotes = source.fetch_quotes(["000001", "002910"])

    assert "000001" in quotes
    assert "002910" not in quotes  # missing line -> unavailable, not fabricated


@pytest.mark.parametrize(
    "raw",
    [
        "名称,,3.819,1.244,0.16,2026-09-29",   # empty unit nav
        "名称,1.246,,1.244,0.16,2026-09-29",     # empty accumulated nav
        "名称,1.246,3.819,1.244,0.16",            # missing date (too few fields)
        "名称,abc,3.819,1.244,0.16,2026-09-29",   # non-numeric unit nav
    ],
)
def test_sina_malformed_line_marks_code_unavailable(raw: str) -> None:
    assert _parse_quote_line(raw) is None


def test_sina_health_reports_unreachable_on_error() -> None:
    source = _sina_source()

    def _boom(url: str) -> str:
        raise requests.ConnectionError("down")

    source._raw_get_text = _boom  # type: ignore[method-assign]

    health = source.health_check()

    assert health.reachable is False
    assert "down" in (health.error or "")
