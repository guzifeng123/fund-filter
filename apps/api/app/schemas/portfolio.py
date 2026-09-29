from typing import Literal

from pydantic import BaseModel, Field

RiskProfile = Literal["C1", "C2", "C3", "C4", "C5"]
PortfolioAvailabilityReason = Literal["available", "removed_from_active_snapshot"]


class PortfolioTemplate(BaseModel):
    id: Literal["conservative", "balanced", "growth"]
    name: str
    stock_ratio: int
    bond_ratio: int
    suitable_profiles: list[RiskProfile]


class PortfolioPosition(BaseModel):
    fund_code: str
    fund_name: str
    fund_type: Literal["stock", "mixed", "bond", "money"]
    risk_level: str
    weight_percent: float
    normalized_weight_percent: float | None = None
    available: bool
    availability_reason: PortfolioAvailabilityReason


class PortfolioSummary(BaseModel):
    id: str
    name: str
    template_key: str
    stock_ratio: int
    bond_ratio: int
    position_count: int = 0
    unavailable_position_count: int = Field(ge=0)


class PortfolioDetail(PortfolioSummary):
    positions: list[PortfolioPosition]
    total_weight_percent: float = 0
    weight_warning: str | None = None


class PortfolioCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    template_key: Literal["conservative", "balanced", "growth"]


class PortfolioUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PortfolioPositionRequest(BaseModel):
    fund_code: str
    weight_percent: float = Field(ge=0, le=100)


class RebalancePreview(BaseModel):
    portfolio_id: str | None = None
    drift_percent: float
    message: str
    current_stock_ratio: float = 0
    current_bond_ratio: float = 0
    target_stock_ratio: float = 0
    target_bond_ratio: float = 0
    triggered: bool = False


class PortfolioDeleteResult(BaseModel):
    deleted: bool
