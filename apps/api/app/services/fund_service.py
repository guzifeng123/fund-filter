from sqlalchemy.orm import Session

from app.repositories import funds as fund_repository
from app.schemas.funds import (
    Fund,
    FundDetail,
    FundFilterRequest,
    FundSortBy,
    FundType,
    NavPoint,
    RiskLevel,
    RiskProfile,
    SortOrder,
)
from app.repositories.funds import FundReadResult, FundSearchResult


def search_funds(
    db: Session,
    query: str,
    page: int = 1,
    page_size: int = 20,
    fund_types: list[FundType] | None = None,
    risk_levels: list[RiskLevel] | None = None,
    sort_by: FundSortBy = "code",
    sort_order: SortOrder = "asc",
) -> tuple[list[Fund], int]:
    return fund_repository.search_funds(
        db,
        query,
        page=page,
        page_size=page_size,
        fund_types=fund_types,
        risk_levels=risk_levels,
        sort_by=sort_by,
        sort_order=sort_order,
    )


def search_funds_with_context(
    db: Session,
    query: str,
    page: int = 1,
    page_size: int = 20,
    fund_types: list[FundType] | None = None,
    risk_levels: list[RiskLevel] | None = None,
    sort_by: FundSortBy = "code",
    sort_order: SortOrder = "asc",
) -> FundSearchResult:
    return fund_repository.search_funds_with_context(
        db,
        query,
        page=page,
        page_size=page_size,
        fund_types=fund_types,
        risk_levels=risk_levels,
        sort_by=sort_by,
        sort_order=sort_order,
    )


def get_fund(
    db: Session,
    code: str,
    risk_profile: RiskProfile = "C3",
) -> FundDetail | None:
    return fund_repository.get_fund(db, code, risk_profile)


def get_fund_with_context(
    db: Session,
    code: str,
    risk_profile: RiskProfile = "C3",
) -> FundReadResult[FundDetail] | None:
    return fund_repository.get_fund_with_context(db, code, risk_profile)


def get_fund_navs(
    db: Session,
    code: str,
    start: str | None = None,
    end: str | None = None,
) -> list[NavPoint] | None:
    return fund_repository.get_fund_navs(db, code, start, end)


def get_fund_navs_with_context(
    db: Session,
    code: str,
    start: str | None = None,
    end: str | None = None,
) -> FundReadResult[list[NavPoint]] | None:
    return fund_repository.get_fund_navs_with_context(db, code, start, end)


def filter_funds(db: Session, payload: FundFilterRequest) -> list[Fund]:
    return fund_repository.filter_funds(db, payload)


def filter_funds_with_context(
    db: Session,
    payload: FundFilterRequest,
) -> FundReadResult[list[Fund]]:
    return fund_repository.filter_funds_with_context(db, payload)


def compare_funds(db: Session, codes: list[str]) -> list[Fund]:
    return fund_repository.compare_funds(db, codes)


def compare_funds_with_context(db: Session, codes: list[str]) -> FundReadResult[list[Fund]]:
    return fund_repository.compare_funds_with_context(db, codes)
