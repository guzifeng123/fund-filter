from datetime import date

import pytest

from app.core.config import settings
from app.core.nav_series_quality import NavSeriesQualityReport, assess_nav_series_quality
from app.schemas.funds import FundDetail, NavPoint
from app.services.sample_data import FUNDS


def fund_with_navs(
    *,
    code: str = "000111",
    fund_type: str = "mixed",
    navs: list[NavPoint],
    source: str = "csv_local",
) -> FundDetail:
    payload = FUNDS[0].model_dump()
    payload.update(
        {
            "code": code,
            "fund_type": fund_type,
            "source": source,
            "navs": [point.model_dump() for point in navs],
        }
    )
    return FundDetail.model_validate(payload)


def _codes(report: NavSeriesQualityReport) -> tuple[set[str], set[str]]:
    return (
        {issue.code for issue in report.errors},
        {issue.code for issue in report.warnings},
    )


def test_clean_day_series_has_no_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_gap_days", 0)
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2026-07-01", nav=1.00, accumulated_nav=1.00),
            NavPoint(trade_date="2026-07-02", nav=1.01, accumulated_nav=1.01),
        ]
    )

    report = assess_nav_series_quality([fund], source_name="csv_local")

    error_codes, warning_codes = _codes(report)
    assert error_codes == set()
    assert warning_codes == set()


def test_duplicate_trade_date_is_error() -> None:
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2026-07-01", nav=1.0, accumulated_nav=1.0),
            NavPoint(trade_date="2026-07-01", nav=1.01, accumulated_nav=1.01),
        ]
    )

    report = assess_nav_series_quality([fund], source_name="csv_local")

    assert "nav_series_duplicate_trade_date" in {i.code for i in report.errors}


def test_out_of_order_trade_date_is_error() -> None:
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2026-07-02", nav=1.0, accumulated_nav=1.0),
            NavPoint(trade_date="2026-07-01", nav=1.01, accumulated_nav=1.01),
        ]
    )

    report = assess_nav_series_quality([fund], source_name="csv_local")

    assert "nav_series_not_ascending" in {i.code for i in report.errors}


def test_calendar_gap_is_warning_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_gap_days", 5)
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2026-07-01", nav=1.0, accumulated_nav=1.0),
            NavPoint(trade_date="2026-07-20", nav=1.01, accumulated_nav=1.01),
        ]
    )

    report = assess_nav_series_quality(
        [fund], source_name="csv_local", today=date(2026, 7, 21)
    )

    assert "nav_series_gap_exceeded" in {i.code for i in report.warnings}
    assert report.errors == ()


def test_staleness_since_latest_nav_is_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_gap_days", 5)
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2026-07-01", nav=1.0, accumulated_nav=1.0),
            NavPoint(trade_date="2026-07-02", nav=1.01, accumulated_nav=1.01),
        ]
    )

    report = assess_nav_series_quality(
        [fund], source_name="csv_local", today=date(2026, 7, 30)
    )

    assert "nav_series_stale" in {i.code for i in report.warnings}


def test_single_day_unit_nav_jump_is_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_single_day_change", 0.5)
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2026-07-01", nav=1.0, accumulated_nav=1.0),
            NavPoint(trade_date="2026-07-02", nav=1.6, accumulated_nav=1.6),
        ]
    )

    report = assess_nav_series_quality([fund], source_name="csv_local")

    assert "nav_series_single_day_jump" in {i.code for i in report.warnings}


def test_dividend_ex_date_drop_is_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_single_day_change", 0.5)
    # Unit NAV drops 55% but accumulated NAV rides through unchanged: a dividend.
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2026-07-01", nav=2.0, accumulated_nav=2.0),
            NavPoint(trade_date="2026-07-02", nav=0.9, accumulated_nav=2.0),
        ]
    )

    report = assess_nav_series_quality([fund], source_name="csv_local")

    assert "nav_series_single_day_jump" not in {i.code for i in report.warnings}


def test_accumulated_nav_decrease_is_warning() -> None:
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2026-07-01", nav=1.0, accumulated_nav=1.10),
            NavPoint(trade_date="2026-07-02", nav=1.0, accumulated_nav=1.00),
        ]
    )

    report = assess_nav_series_quality([fund], source_name="csv_local")

    assert "accumulated_nav_not_monotonic" in {i.code for i in report.warnings}


def test_money_fund_skips_equity_jump_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_single_day_change", 0.5)
    fund = fund_with_navs(
        fund_type="money",
        navs=[
            NavPoint(trade_date="2026-07-01", nav=1.0, accumulated_nav=1.0),
            NavPoint(trade_date="2026-07-02", nav=1.6, accumulated_nav=0.5),
        ],
    )

    report = assess_nav_series_quality([fund], source_name="csv_local")

    warning_codes = {i.code for i in report.warnings}
    assert "nav_series_single_day_jump" not in warning_codes
    assert "accumulated_nav_not_monotonic" not in warning_codes


def test_legacy_year_precision_points_are_not_series_check_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_gap_days", 5)
    fund = fund_with_navs(
        navs=[
            NavPoint(trade_date="2021", nav=1.0, accumulated_nav=1.0),
            NavPoint(trade_date="2026", nav=1.4, accumulated_nav=1.4),
        ]
    )

    report = assess_nav_series_quality([fund], source_name="sample_local")

    assert report.errors == ()
    assert report.warnings == ()


def test_source_level_overrides_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_nav_series_max_single_day_change", 0.01)
    monkeypatch.setattr(
        settings,
        "fund_nav_series_quality_overrides",
        {"eastmoney_snapshot": {"max_single_day_change": 0.5}},
    )
    fund = fund_with_navs(
        source="eastmoney_snapshot",
        navs=[
            NavPoint(trade_date="2026-07-01", nav=1.0, accumulated_nav=1.0),
            NavPoint(trade_date="2026-07-02", nav=1.2, accumulated_nav=1.2),
        ],
    )

    report = assess_nav_series_quality([fund], source_name="public_http_json")

    # 20% move: rejected by global 1% threshold but allowed by the 5% override.
    assert "nav_series_single_day_jump" not in {i.code for i in report.warnings}
