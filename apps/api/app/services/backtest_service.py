from sqlalchemy.orm import Session

from app.repositories.backtests import create_backtest_run, get_backtest_run
from app.schemas.backtest import BacktestRequest, BacktestResult


def run_backtest(db: Session, payload: BacktestRequest) -> BacktestResult:
    return create_backtest_run(db, payload)


def backtest_detail(db: Session, backtest_id: str) -> BacktestResult:
    result = get_backtest_run(db, backtest_id)
    if result is not None:
        return result
    return BacktestResult(
        id=backtest_id,
        strategy_type="monthly_dca",
        annualized_return=0,
        max_drawdown=0,
        volatility=0,
        sharpe_ratio=0,
        total_invested=0,
        final_value=0,
        data_warning="未找到指定回测结果。",
        points=[],
    )
