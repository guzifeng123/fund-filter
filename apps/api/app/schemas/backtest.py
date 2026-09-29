import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


YEAR_PATTERN = re.compile(r"^\d{4}$")
FUND_CODE_PATTERN = re.compile(r"^\d{6}$")


def _parse_backtest_bound(value: str) -> tuple[str, date]:
    if YEAR_PATTERN.fullmatch(value):
        return ("year", date(int(value), 1, 1))
    try:
        return ("date", date.fromisoformat(value))
    except ValueError as exc:
        raise ValueError("must be a four-digit year or ISO date (YYYY-MM-DD)") from exc


class BacktestRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    strategy_type: Literal["monthly_dca", "weekly_dca", "rebalance", "template_portfolio"]
    amount: float = Field(gt=0)
    start: str
    end: str
    fund_codes: list[str] = Field(default_factory=lambda: ["000001"], min_length=1, max_length=5)
    rebalance_threshold: float = Field(default=5, ge=0, le=100)
    template_key: Literal["conservative", "balanced", "growth"] = "balanced"

    @field_validator("start", "end")
    @classmethod
    def validate_date_bound(cls, value: str) -> str:
        normalized = value.strip()
        _parse_backtest_bound(normalized)
        return normalized

    @field_validator("fund_codes")
    @classmethod
    def validate_fund_codes(cls, value: list[str]) -> list[str]:
        normalized = [code.strip() for code in value]
        invalid = [code for code in normalized if not FUND_CODE_PATTERN.fullmatch(code)]
        if invalid:
            raise ValueError(f"fund_codes must contain six-digit codes; invalid: {invalid}")
        if len(set(normalized)) != len(normalized):
            raise ValueError("fund_codes must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_date_range(self) -> "BacktestRequest":
        start_kind, start_value = _parse_backtest_bound(self.start)
        end_kind, end_value = _parse_backtest_bound(self.end)
        if start_kind != end_kind:
            raise ValueError("start and end must use the same precision (year or ISO date)")
        if start_value > end_value:
            raise ValueError("start must not be later than end")
        return self


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
    money_weighted_return: float = 0
    time_weighted_return: float = 0
    return_calculation_method: Literal["xirr", "unavailable"] = "xirr"
    snapshot_generation_id: str | None = None
    data_warning: str | None = None
    points: list[BacktestPoint]
