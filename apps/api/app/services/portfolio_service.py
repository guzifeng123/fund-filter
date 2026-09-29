from sqlalchemy.orm import Session

from app.repositories import portfolios as portfolio_repository
from app.repositories.portfolios import get_portfolio, list_portfolios, list_templates
from app.schemas.portfolio import (
    PortfolioCreateRequest,
    PortfolioDetail,
    PortfolioPositionRequest,
    PortfolioSummary,
    PortfolioTemplate,
    PortfolioUpdateRequest,
    RebalancePreview,
)


def templates() -> list[PortfolioTemplate]:
    return list_templates()


def portfolios(db: Session) -> list[PortfolioSummary]:
    return list_portfolios(db)


def create(db: Session, payload: PortfolioCreateRequest) -> PortfolioDetail:
    return portfolio_repository.create_portfolio(db, payload)


def portfolio_detail(db: Session, portfolio_id: str) -> PortfolioDetail | None:
    return get_portfolio(db, portfolio_id)


def update(db: Session, portfolio_id: str, payload: PortfolioUpdateRequest) -> PortfolioDetail | None:
    return portfolio_repository.update_portfolio(db, portfolio_id, payload)


def delete(db: Session, portfolio_id: str) -> bool:
    return portfolio_repository.delete_portfolio(db, portfolio_id)


def save_position(db: Session, portfolio_id: str, payload: PortfolioPositionRequest) -> PortfolioDetail | None:
    return portfolio_repository.upsert_position(db, portfolio_id, payload)


def remove_position(db: Session, portfolio_id: str, fund_code: str) -> PortfolioDetail | None:
    return portfolio_repository.delete_position(db, portfolio_id, fund_code)


def normalize_positions(db: Session, portfolio_id: str) -> PortfolioDetail | None:
    return portfolio_repository.normalize_position_weights(db, portfolio_id)


def rebalance_preview(db: Session, portfolio_id: str) -> RebalancePreview | None:
    return portfolio_repository.rebalance_preview(db, portfolio_id)
