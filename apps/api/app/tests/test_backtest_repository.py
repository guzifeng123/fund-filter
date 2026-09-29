import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import FundNav
from app.repositories.backtests import (
    _annualized_return,
    _annualized_time_weighted_return,
    _contribution_dates,
    _xirr,
    calculate_backtest_result,
    create_backtest_run,
    get_backtest_run,
)
from app.schemas.backtest import BacktestPoint, BacktestRequest


@pytest.mark.parametrize(
    "overrides",
    (
        {"amount": 0},
        {"amount": float("nan")},
        {"start": "2027", "end": "2026"},
        {"start": "2021", "end": "2026-12-31"},
        {"start": "2026/01/01", "end": "2026/12/31"},
        {"fund_codes": ["000001", "000001"]},
        {"fund_codes": ["abc"]},
    ),
)
def test_backtest_request_rejects_invalid_amount_dates_and_codes(
    overrides: dict[str, object],
) -> None:
    payload = {
        "strategy_type": "monthly_dca",
        "amount": 1000,
        "start": "2021",
        "end": "2026",
        "fund_codes": ["000001"],
        **overrides,
    }

    with pytest.raises(ValidationError):
        BacktestRequest.model_validate(payload)


def test_backtest_request_normalizes_fund_code_whitespace() -> None:
    payload = BacktestRequest(
        strategy_type="monthly_dca",
        amount=1000,
        start="2021-01-01",
        end="2026-12-31",
        fund_codes=[" 000001 "],
    )

    assert payload.fund_codes == ["000001"]


def replace_navs(db_session: Session, fund_code: str, trade_dates: list[str]) -> None:
    replace_nav_points(
        db_session,
        fund_code,
        [(trade_date, 1.0) for trade_date in trade_dates],
    )


def replace_nav_points(
    db_session: Session,
    fund_code: str,
    nav_points: list[tuple[str, float]],
) -> None:
    db_session.execute(delete(FundNav).where(FundNav.fund_code == fund_code))
    db_session.add_all(
        FundNav(
            fund_code=fund_code,
            trade_date=trade_date,
            nav=nav,
            accumulated_nav=nav,
            raw_data={},
        )
        for trade_date, nav in nav_points
    )
    db_session.commit()


@pytest.mark.parametrize(
    ("strategy_type", "trade_dates", "expected"),
    (
        (
            "monthly_dca",
            ["2026-01-05", "2026-01-15", "2026-02-03"],
            {"2026-01-05", "2026-02-03"},
        ),
        (
            "weekly_dca",
            ["2025-12-29", "2026-01-02", "2026-01-05"],
            {"2025-12-29", "2026-01-05"},
        ),
    ),
)
def test_contribution_dates_select_first_available_nav_per_calendar_period(
    strategy_type: str,
    trade_dates: list[str],
    expected: set[str],
) -> None:
    selected, uses_yearly_approximation = _contribution_dates(trade_dates, strategy_type)

    assert selected == expected
    assert uses_yearly_approximation is False


def test_contribution_dates_keep_year_only_sample_points_with_explicit_mode() -> None:
    selected, uses_yearly_approximation = _contribution_dates(
        ["2021", "2023", "2026"],
        "monthly_dca",
    )

    assert selected == {"2021", "2023", "2026"}
    assert uses_yearly_approximation is True


def test_annualized_return_uses_actual_first_and_last_date_span() -> None:
    trade_dates = ["2026-01-02", "2026-04-01", "2026-07-02"]
    elapsed_days = 181
    expected = round(((1210 / 1000) ** (365.2425 / elapsed_days) - 1) * 100, 2)

    assert _annualized_return(1210, 1000, trade_dates) == expected


def test_annualized_return_interprets_year_labels_as_january_first() -> None:
    elapsed_days = 1826
    expected = round(((1610.51 / 1000) ** (365.2425 / elapsed_days) - 1) * 100, 2)

    assert _annualized_return(1610.51, 1000, ["2021", "2026"]) == expected


def test_xirr_calculates_money_weighted_annual_return() -> None:
    result = _xirr(
        [
            ("2026-01-01", -1000),
            ("2026-07-01", -1000),
            ("2027-01-01", 2200),
        ]
    )

    assert result == 13.45


def test_time_weighted_return_removes_external_flows_before_annualizing() -> None:
    points = [
        BacktestPoint(date="2026-01-01", portfolio=1000, benchmark=1000),
        BacktestPoint(date="2027-01-01", portfolio=2200, benchmark=2000),
    ]
    external_flows = [1000.0, 1000.0]

    assert _annualized_time_weighted_return(points, external_flows) == 20.01


def test_monthly_dca_invests_once_per_calendar_month_with_daily_navs(
    db_session: Session,
) -> None:
    replace_nav_points(
        db_session,
        "000001",
        [
            ("2026-01-05", 1.0),
            ("2026-01-15", 2.0),
            ("2026-02-02", 4.0),
            ("2026-02-20", 8.0),
        ],
    )

    result = calculate_backtest_result(
        db_session,
        BacktestRequest(
            strategy_type="monthly_dca",
            fund_codes=["000001"],
            amount=1000,
            start="2026-01-01",
            end="2026-02-28",
        ),
    )

    assert len(result.points) == 4
    assert result.total_invested == 2000
    assert [point.portfolio for point in result.points] == [1000, 2000, 5000, 10000]
    assert result.final_value == 10000
    assert result.annualized_return == result.money_weighted_return
    assert result.time_weighted_return > 0
    assert result.return_calculation_method == "xirr"
    assert result.snapshot_generation_id == "legacy-0008"
    assert result.points[-1].benchmark == 10000
    assert result.data_warning is None


def test_weekly_dca_invests_once_per_iso_week_with_daily_navs(db_session: Session) -> None:
    replace_nav_points(
        db_session,
        "000001",
        [
            ("2025-12-29", 1.0),
            ("2026-01-02", 2.0),
            ("2026-01-05", 4.0),
        ],
    )

    result = calculate_backtest_result(
        db_session,
        BacktestRequest(
            strategy_type="weekly_dca",
            fund_codes=["000001"],
            amount=1000,
            start="2025-12-29",
            end="2026-01-31",
        ),
    )

    assert result.total_invested == 2000
    assert [point.portfolio for point in result.points] == [1000, 2000, 5000]
    assert result.final_value == 5000
    assert result.points[-1].benchmark == 5000
    assert result.data_warning is None
    assert result.return_calculation_method == "xirr"


def test_year_precision_request_includes_daily_navs_from_the_whole_end_year(
    db_session: Session,
) -> None:
    replace_nav_points(
        db_session,
        "000001",
        [("2026-01-05", 1.0), ("2026-12-31", 2.0)],
    )

    result = calculate_backtest_result(
        db_session,
        BacktestRequest(
            strategy_type="monthly_dca",
            fund_codes=["000001"],
            amount=1000,
            start="2026",
            end="2026",
        ),
    )

    assert [point.date for point in result.points] == ["2026-01-05", "2026-12-31"]
    assert result.total_invested == 2000
    assert result.data_warning is None


def test_real_daily_navs_take_precedence_over_legacy_year_rows(
    db_session: Session,
) -> None:
    replace_nav_points(
        db_session,
        "000001",
        [
            ("2025", 0.5),
            ("2025-12-30", 1.0),
            ("2026", 0.6),
            ("2026-01-02", 2.0),
        ],
    )

    result = calculate_backtest_result(
        db_session,
        BacktestRequest(
            strategy_type="weekly_dca",
            fund_codes=["000001"],
            amount=1000,
            start="2025",
            end="2026",
        ),
    )

    assert [point.date for point in result.points] == ["2025-12-30", "2026-01-02"]
    assert result.total_invested == 1000
    assert result.data_warning is None


def test_rebalance_strategy_uses_the_same_one_time_cash_flow_for_benchmark(
    db_session: Session,
) -> None:
    replace_navs(
        db_session,
        "000001",
        ["2026-01-05", "2026-01-06", "2026-01-07"],
    )

    result = calculate_backtest_result(
        db_session,
        BacktestRequest(
            strategy_type="rebalance",
            fund_codes=["000001"],
            amount=1000,
            start="2026-01-01",
            end="2026-01-31",
        ),
    )

    assert result.total_invested == 1000
    assert result.final_value == 1000
    assert result.points[-1].benchmark == 1000


def test_calculate_monthly_dca_from_nav_points(db_session: Session) -> None:
    result = calculate_backtest_result(
        db_session,
        BacktestRequest(
            strategy_type="monthly_dca",
            fund_codes=["000001", "000002"],
            amount=1000,
            start="2021",
            end="2026",
        ),
        run_id="bt_test",
    )

    assert result.id == "bt_test"
    assert len(result.points) == 6
    assert result.total_invested == 6000
    assert result.points[0].portfolio == 1000
    assert result.final_value > result.total_invested
    assert result.data_warning == (
        "当前 sample 数据仅含年度净值点；回测按每个可用年份投入一次，"
        "年化按首末年份各自 1 月 1 日之间的实际日历跨度近似计算。"
    )


def test_calculate_backtest_handles_missing_nav_window(db_session: Session) -> None:
    result = calculate_backtest_result(
        db_session,
        BacktestRequest(
            strategy_type="monthly_dca",
            fund_codes=["000001"],
            amount=1000,
            start="2030",
            end="2031",
        ),
    )

    assert result.points == []
    assert result.final_value == 0
    assert result.return_calculation_method == "unavailable"
    assert result.data_warning == "数据不足，无法生成有效回测结果。"


def test_template_portfolio_uses_template_allocation_warning(db_session: Session) -> None:
    result = calculate_backtest_result(
        db_session,
        BacktestRequest(
            strategy_type="template_portfolio",
            template_key="balanced",
            fund_codes=["000001", "000002"],
            amount=1000,
            start="2021",
            end="2026",
        ),
    )

    assert result.strategy_type == "template_portfolio"
    assert result.total_invested == 6000
    assert result.data_warning is not None
    assert "组合模板回测按模板股债比例分配投入" in result.data_warning
    assert "历史学习" in result.data_warning


def test_create_and_get_backtest_run_round_trip(db_session: Session) -> None:
    created = create_backtest_run(
        db_session,
        BacktestRequest(
            strategy_type="rebalance",
            fund_codes=["000001", "000002"],
            amount=1000,
            start="2021",
            end="2026",
            rebalance_threshold=5,
        ),
    )

    loaded = get_backtest_run(db_session, created.id)

    assert loaded is not None
    assert loaded.id == created.id
    assert loaded.strategy_type == "rebalance"
    assert loaded.money_weighted_return == created.money_weighted_return
    assert loaded.time_weighted_return == created.time_weighted_return
    assert loaded.return_calculation_method == "xirr"
    assert loaded.snapshot_generation_id == created.snapshot_generation_id == "legacy-0008"
    assert loaded.points == created.points
