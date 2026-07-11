from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.funds import latest_fund_data_updated_at
from app.schemas.funds import FundCompareRequest, FundFilterRequest, FundSortBy, FundType, RiskLevel, RiskProfile, SortOrder
from app.services.fund_service import compare_funds, filter_funds, get_fund, get_fund_navs, search_funds

router = APIRouter()


@router.get("/search")
def search(
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fund_type: list[FundType] | None = Query(None),
    risk_level: list[RiskLevel] | None = Query(None),
    sort_by: FundSortBy = "code",
    sort_order: SortOrder = "asc",
    db: Session = Depends(get_db),
):
    funds, total = search_funds(db, q, page, page_size, fund_type, risk_level, sort_by, sort_order)
    return envelope(
        funds,
        data_updated_at=latest_fund_data_updated_at(db),
        pagination={"page": page, "page_size": page_size, "total": total},
    )


@router.post("/filter")
def filter_endpoint(payload: FundFilterRequest, db: Session = Depends(get_db)):
    return envelope(filter_funds(db, payload), data_updated_at=latest_fund_data_updated_at(db))


@router.post("/compare")
def compare(payload: FundCompareRequest, db: Session = Depends(get_db)):
    return envelope(compare_funds(db, payload.codes), data_updated_at=latest_fund_data_updated_at(db))


@router.get("/{code}")
def detail(code: str, risk_profile: RiskProfile = "C3", db: Session = Depends(get_db)):
    fund = get_fund(db, code, risk_profile)
    if fund is None:
        raise HTTPException(status_code=404, detail={"code": "FUND_NOT_FOUND", "message": "未找到指定基金"})
    return envelope(fund, data_updated_at=latest_fund_data_updated_at(db))


@router.get("/{code}/nav")
def nav(code: str, start: str | None = None, end: str | None = None, db: Session = Depends(get_db)):
    if start and end and start > end:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_DATE_RANGE", "message": "start 不能晚于 end"},
        )
    navs = get_fund_navs(db, code, start, end)
    if navs is None:
        raise HTTPException(status_code=404, detail={"code": "FUND_NOT_FOUND", "message": "未找到指定基金"})
    return envelope(navs, data_updated_at=latest_fund_data_updated_at(db))
