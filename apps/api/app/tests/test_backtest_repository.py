from sqlalchemy.orm import Session

from app.repositories.backtests import calculate_backtest_result, create_backtest_run, get_backtest_run
from app.schemas.backtest import BacktestRequest


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
    assert result.data_warning == "当前 sample 数据为年度净值点，定投频率会按可用净值点近似执行。"


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
    assert loaded.points == created.points
