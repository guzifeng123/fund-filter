from sqlalchemy.orm import Session

from app.schemas.funds import Fund, FundFilterRequest
from app.repositories import funds as fund_repository


def search_funds(
    db: Session,
    query: str,
    page: int = 1,
    page_size: int = 20,
    fund_types: list[str] | None = None,
    risk_levels: list[str] | None = None,
    sort_by: str = "code",
    sort_order: str = "asc",
) -> tuple[list[Fund], int]:
    return fund_repository.search_funds(
        db,
        query,
        page=page,
        page_size=page_size,
        fund_types=fund_types,
        risk_levels=risk_levels,
        sort_by=sort_by,  # type: ignore[arg-type]
        sort_order=sort_order,  # type: ignore[arg-type]
    )


def get_fund(db: Session, code: str, risk_profile: str = "C3"):
    return fund_repository.get_fund(db, code, risk_profile)  # type: ignore[arg-type]


def get_fund_navs(db: Session, code: str, start=None, end=None):
    return fund_repository.get_fund_navs(db, code, start, end)


def filter_funds(db: Session, payload: FundFilterRequest) -> list[Fund]:
    return fund_repository.filter_funds(db, payload)


def compare_funds(db: Session, codes: list[str]) -> list[Fund]:
    return fund_repository.compare_funds(db, codes)
