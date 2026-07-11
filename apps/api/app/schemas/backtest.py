from typing import Literal

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    strategy_type: Literal["monthly_dca", "weekly_dca", "rebalance", "template_portfolio"]
    amount: float
    start: str
    end: str
    fund_codes: list[str] = Field(default_factory=lambda: ["000001"], min_length=1, max_length=5)
    rebalance_threshold: float = Field(default=5, ge=0, le=100)
    template_key: Literal["conservative", "balanced", "growth"] = "balanced"


class BacktestPoint(BaseModel):
    date: str
    portfolio: float
    benchmark: float


class BacktestResult(BaseModel):
    id: str
    strategy_type: Literal["monthly_dca", "weekly_dca", "rebalance", "template_portfolio"]
    annualized_return: float
    max_drawdown: float
    volatility: float
    sharpe_ratio: float
    total_invested: float
    final_value: float
    data_warning: str | None = None
    points: list[BacktestPoint]
