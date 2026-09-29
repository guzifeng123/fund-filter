from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.nav_dates import normalize_nav_trade_date

RiskLevel = Literal["R1", "R2", "R3", "R4", "R5"]
RiskProfile = Literal["C1", "C2", "C3", "C4", "C5"]
FundType = Literal["stock", "mixed", "bond", "money"]
FundSortBy = Literal[
    "code",
    "annualized_return_3y",
    "annualized_return_5y",
    "max_drawdown",
    "sharpe_ratio",
    "fee",
    "size",
]
SortOrder = Literal["asc", "desc"]


class NavPoint(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    trade_date: str = Field(
        pattern=r"^(?:[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})$",
        description=(
            "Canonical YYYY-MM-DD for real NAVs; YYYY is reserved for legacy sample points."
        ),
    )
    nav: float = Field(gt=0)
    accumulated_nav: float = Field(gt=0)

    @field_validator("trade_date", mode="before")
    @classmethod
    def normalize_trade_date(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("trade_date must be a string")
        normalized, _ = normalize_nav_trade_date(value)
        return normalized


class FeeSummary(BaseModel):
    management_fee: float
    custody_fee: float
    total_fee: float
    explanation: str


class ManagerProfile(BaseModel):
    name: str
    years: int
    inception_date: str
    explanation: str


class MetricExplanation(BaseModel):
    key: str
    label: str
    value: str
    explanation: str


class RiskMatchResult(BaseModel):
    user_risk_profile: RiskProfile
    fund_risk_level: RiskLevel
    matched: bool
    message: str


class Fund(BaseModel):
    code: str
    name: str
    fund_type: FundType
    risk_level: RiskLevel
    manager_name: str
    inception_date: str
    fund_size_billion: float
    management_fee: float
    custody_fee: float
    annualized_return_3y: float
    annualized_return_5y: float
    max_drawdown: float
    sharpe_ratio: float
    category_rank_percentile: float
    manager_years: int
    source: str
    provider_profile: str | None = None
    upstream_provider: str | None = None
    data_updated_at: str
    snapshot_generation_id: str | None = None


class FundDetail(Fund):
    navs: list[NavPoint]
    ai_summary: str
    fee_summary: FeeSummary | None = None
    manager_profile: ManagerProfile | None = None
    metric_explanations: list[MetricExplanation] = Field(default_factory=list)
    risk_match: RiskMatchResult | None = None


class FundFilterRequest(BaseModel):
    keyword: str | None = Field(
        default=None,
        max_length=100,
        description="Optional fund code/name keyword applied together with every filter criterion.",
    )
    risk_profile: RiskProfile
    fund_types: list[FundType]
    min_years: int = Field(
        ge=0,
        description="Minimum completed years since the fund inception_date.",
    )
    size_range: tuple[float, float]
    return_rank_percentile: float = Field(ge=0, le=100)
    max_drawdown_lte_category_avg: bool = Field(
        description=(
            "When true, keep funds whose signed max_drawdown is greater than or equal to "
            "the average for the same fund_type (a smaller loss magnitude)."
        )
    )
    sharpe_gte: float
    fee_lte: float
    sort_by: FundSortBy = "annualized_return_3y"
    sort_order: SortOrder = "desc"


class FundCompareRequest(BaseModel):
    codes: list[str] = Field(min_length=2, max_length=5)
