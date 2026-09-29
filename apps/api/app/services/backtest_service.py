from sqlalchemy.orm import Session

from app.repositories.backtests import create_backtest_run, get_backtest_run
from app.schemas.backtest import BacktestRequest, BacktestResult


def run_backtest(db: Session, payload: BacktestRequest) -> BacktestResult:
    return create_backtest_run(db, payload)


def backtest_detail(db: Session, backtest_id: str) -> BacktestResult | None:
    return get_backtest_run(db, backtest_id)
