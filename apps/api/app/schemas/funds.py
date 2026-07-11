from typing import Literal

from pydantic import BaseModel, Field

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
    trade_date: str
    nav: float
    accumulated_nav: float


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
    data_updated_at: str


class FundDetail(Fund):
    navs: list[NavPoint]
    ai_summary: str
    fee_summary: FeeSummary | None = None
    manager_profile: ManagerProfile | None = None
    metric_explanations: list[MetricExplanation] = Field(default_factory=list)
    risk_match: RiskMatchResult | None = None


class FundFilterRequest(BaseModel):
    risk_profile: RiskProfile
    fund_types: list[FundType]
    min_years: int = Field(ge=0)
    size_range: tuple[float, float]
    return_rank_percentile: float = Field(ge=0, le=100)
    max_drawdown_lte_category_avg: bool
    sharpe_gte: float
    fee_lte: float
    sort_by: FundSortBy = "annualized_return_3y"
    sort_order: SortOrder = "desc"


class FundCompareRequest(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=5)
