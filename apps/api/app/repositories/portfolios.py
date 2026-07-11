from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Fund, Portfolio, PortfolioPosition
from app.schemas.portfolio import (
    PortfolioCreateRequest,
    PortfolioDetail,
    PortfolioPosition as PortfolioPositionSchema,
    PortfolioPositionRequest,
    PortfolioSummary,
    PortfolioTemplate,
    PortfolioUpdateRequest,
    RebalancePreview,
)

TEMPLATES = [
    PortfolioTemplate(id="conservative", name="保守型", stock_ratio=20, bond_ratio=80, suitable_profiles=["C1", "C2"]),
    PortfolioTemplate(id="balanced", name="稳健型", stock_ratio=50, bond_ratio=50, suitable_profiles=["C2", "C3"]),
    PortfolioTemplate(id="growth", name="进取型", stock_ratio=80, bond_ratio=20, suitable_profiles=["C4", "C5"]),
]


def list_templates() -> list[PortfolioTemplate]:
    return TEMPLATES


def _template_by_id(template_key: str) -> PortfolioTemplate | None:
    return next((template for template in TEMPLATES if template.id == template_key), None)


def ensure_default_portfolios(db: Session) -> None:
    for template in TEMPLATES:
        portfolio_id = f"template_{template.id}"
        row = db.get(Portfolio, portfolio_id)
        if row is None:
            db.add(
                Portfolio(
                    id=portfolio_id,
                    user_id="local-user",
                    name=f"{template.name}闲钱组合",
                    template_key=template.id,
                    stock_ratio=template.stock_ratio,
                    bond_ratio=template.bond_ratio,
                    config={"suitable_profiles": template.suitable_profiles},
                )
            )


def _to_summary(row: Portfolio) -> PortfolioSummary:
    return PortfolioSummary(
        id=row.id,
        name=row.name,
        template_key=row.template_key,
        stock_ratio=row.stock_ratio,
        bond_ratio=row.bond_ratio,
        position_count=len(row.positions),
    )


def _to_position(row: PortfolioPosition, total_weight: float) -> PortfolioPositionSchema:
    fund = row.fund
    normalized_weight = round(row.weight_percent / total_weight * 100, 2) if total_weight > 0 else None
    return PortfolioPositionSchema(
        fund_code=row.fund_code,
        fund_name=fund.name,
        fund_type=fund.fund_type,  # type: ignore[arg-type]
        risk_level=fund.risk_level,
        weight_percent=row.weight_percent,
        normalized_weight_percent=normalized_weight,
    )


def _weight_warning(total_weight: float) -> str | None:
    if total_weight == 0:
        return None
    if abs(total_weight - 100) <= 0.01:
        return None
    return f"当前持仓权重合计为 {total_weight:.2f}%，可参考归一化比例检查配置。"


def _to_detail(row: Portfolio) -> PortfolioDetail:
    summary = _to_summary(row)
    total_weight = round(sum(position.weight_percent for position in row.positions), 2)
    return PortfolioDetail(
        **summary.model_dump(),
        positions=[_to_position(position, total_weight) for position in row.positions],
        total_weight_percent=total_weight,
        weight_warning=_weight_warning(total_weight),
    )


def list_portfolios(db: Session) -> list[PortfolioSummary]:
    rows = db.scalars(select(Portfolio).options(joinedload(Portfolio.positions)).order_by(Portfolio.id)).unique().all()
    return [_to_summary(row) for row in rows]


def create_portfolio(db: Session, payload: PortfolioCreateRequest, user_id: str = "local-user") -> PortfolioDetail:
    template = _template_by_id(payload.template_key)
    if template is None:
        raise ValueError("unknown template")
    row = Portfolio(
        id=f"portfolio_{uuid4().hex[:12]}",
        user_id=user_id,
        name=payload.name,
        template_key=template.id,
        stock_ratio=template.stock_ratio,
        bond_ratio=template.bond_ratio,
        config={"suitable_profiles": template.suitable_profiles},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_detail(row)


def get_portfolio(db: Session, portfolio_id: str) -> PortfolioDetail | None:
    row = db.scalars(
        select(Portfolio)
        .where(Portfolio.id == portfolio_id)
        .options(joinedload(Portfolio.positions).joinedload(PortfolioPosition.fund))
    ).unique().first()
    if row is None:
        return None
    return _to_detail(row)


def update_portfolio(db: Session, portfolio_id: str, payload: PortfolioUpdateRequest) -> PortfolioDetail | None:
    row = db.get(Portfolio, portfolio_id)
    if row is None:
        return None
    row.name = payload.name
    db.commit()
    return get_portfolio(db, portfolio_id)


def delete_portfolio(db: Session, portfolio_id: str) -> bool:
    row = db.get(Portfolio, portfolio_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def upsert_position(db: Session, portfolio_id: str, payload: PortfolioPositionRequest) -> PortfolioDetail | None:
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio is None:
        return None
    if db.get(Fund, payload.fund_code) is None:
        raise ValueError("fund not found")
    row = db.scalars(
        select(PortfolioPosition).where(
            PortfolioPosition.portfolio_id == portfolio_id,
            PortfolioPosition.fund_code == payload.fund_code,
        )
    ).first()
    if row is None:
        row = PortfolioPosition(portfolio_id=portfolio_id, fund_code=payload.fund_code, metadata_={})
        db.add(row)
    row.weight_percent = payload.weight_percent
    db.commit()
    return get_portfolio(db, portfolio_id)


def delete_position(db: Session, portfolio_id: str, fund_code: str) -> PortfolioDetail | None:
    if db.get(Portfolio, portfolio_id) is None:
        return None
    row = db.scalars(
        select(PortfolioPosition).where(
            PortfolioPosition.portfolio_id == portfolio_id,
            PortfolioPosition.fund_code == fund_code,
        )
    ).first()
    if row is not None:
        db.delete(row)
        db.commit()
    return get_portfolio(db, portfolio_id)


def rebalance_preview(db: Session, portfolio_id: str) -> RebalancePreview | None:
    row = db.scalars(
        select(Portfolio)
        .where(Portfolio.id == portfolio_id)
        .options(joinedload(Portfolio.positions).joinedload(PortfolioPosition.fund))
    ).unique().first()
    if row is None:
        return None
    stock_weight = 0.0
    bond_weight = 0.0
    for position in row.positions:
        if position.fund.fund_type in {"stock", "mixed"}:
            stock_weight += position.weight_percent
        else:
            bond_weight += position.weight_percent
    drift = max(abs(stock_weight - row.stock_ratio), abs(bond_weight - row.bond_ratio))
    triggered = drift > 5
    message = (
        "可考虑用于恢复目标比例，非强制交易指令。"
        if triggered
        else "当前偏离未超过 5%，可继续观察，非交易指令。"
    )
    return RebalancePreview(
        portfolio_id=row.id,
        drift_percent=round(drift, 2),
        message=message,
        current_stock_ratio=round(stock_weight, 2),
        current_bond_ratio=round(bond_weight, 2),
        target_stock_ratio=row.stock_ratio,
        target_bond_ratio=row.bond_ratio,
        triggered=triggered,
    )
