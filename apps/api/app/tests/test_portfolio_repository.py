from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Portfolio
from app.repositories.portfolios import (
    create_portfolio,
    ensure_default_portfolios,
    rebalance_preview,
    upsert_position,
)
from app.schemas.portfolio import PortfolioCreateRequest, PortfolioPositionRequest


def test_default_portfolios_are_idempotent(db_session: Session) -> None:
    ensure_default_portfolios(db_session)
    ensure_default_portfolios(db_session)
    db_session.commit()

    count = db_session.scalar(select(func.count()).select_from(Portfolio).where(Portfolio.id.like("template_%")))
    assert count == 3


def test_create_portfolio_inherits_template_ratios(db_session: Session) -> None:
    portfolio = create_portfolio(db_session, PortfolioCreateRequest(name="进取组合", template_key="growth"))

    assert portfolio.template_key == "growth"
    assert portfolio.stock_ratio == 80
    assert portfolio.bond_ratio == 20
    assert portfolio.total_weight_percent == 0
    assert portfolio.weight_warning is None


def test_positions_include_total_weight_warning_and_normalized_preview(db_session: Session) -> None:
    portfolio = create_portfolio(db_session, PortfolioCreateRequest(name="权重检查", template_key="balanced"))

    detail = upsert_position(db_session, portfolio.id, PortfolioPositionRequest(fund_code="000001", weight_percent=70))

    assert detail is not None
    assert detail.total_weight_percent == 70
    assert detail.weight_warning is not None
    assert "70.00%" in detail.weight_warning
    assert detail.positions[0].normalized_weight_percent == 100


def test_rebalance_preview_uses_position_fund_types(db_session: Session) -> None:
    portfolio = create_portfolio(db_session, PortfolioCreateRequest(name="偏离检查", template_key="balanced"))
    upsert_position(db_session, portfolio.id, PortfolioPositionRequest(fund_code="000001", weight_percent=52))
    upsert_position(db_session, portfolio.id, PortfolioPositionRequest(fund_code="000002", weight_percent=48))

    preview = rebalance_preview(db_session, portfolio.id)

    assert preview is not None
    assert preview.triggered is False
    assert preview.current_stock_ratio == 52
    assert preview.current_bond_ratio == 48
    assert preview.drift_percent == 2
