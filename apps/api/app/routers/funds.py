from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.funds import FundDataContext
from app.schemas.common import ApiErrorResponse, ApiResponse
from app.schemas.funds import (
    Fund,
    FundCompareRequest,
    FundDetail,
    FundFilterRequest,
    FundSortBy,
    FundType,
    NavPoint,
    RiskLevel,
    RiskProfile,
    SortOrder,
)
from app.services.fund_service import (
    compare_funds_with_context,
    filter_funds_with_context,
    get_fund_navs_with_context,
    get_fund_with_context,
    search_funds_with_context,
)

router = APIRouter()


def _envelope_from_context(
    data: Any,
    context: FundDataContext,
    *,
    pagination: dict[str, int] | None = None,
) -> dict[str, Any]:
    return envelope(
        data,
        source=context.source,
        data_updated_at=context.data_updated_at,
        pagination=pagination,
    )


@router.get("/search", response_model=ApiResponse[list[Fund]])
def search(
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fund_type: list[FundType] | None = Query(None),
    risk_level: list[RiskLevel] | None = Query(None),
    sort_by: FundSortBy = "code",
    sort_order: SortOrder = "asc",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = search_funds_with_context(
        db,
        q,
        page=page,
        page_size=page_size,
        fund_types=fund_type,
        risk_levels=risk_level,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _envelope_from_context(
        result.data,
        result.context,
        pagination={"page": page, "page_size": page_size, "total": result.total},
    )


@router.post("/filter", response_model=ApiResponse[list[Fund]])
def filter_endpoint(
    payload: FundFilterRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = filter_funds_with_context(db, payload)
    return _envelope_from_context(result.data, result.context)


@router.post("/compare", response_model=ApiResponse[list[Fund]])
def compare(
    payload: FundCompareRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = compare_funds_with_context(db, payload.codes)
    return _envelope_from_context(result.data, result.context)


@router.get(
    "/{code}",
    response_model=ApiResponse[FundDetail],
    responses={404: {"model": ApiErrorResponse}},
)
def detail(
    code: str,
    risk_profile: RiskProfile = "C3",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = get_fund_with_context(db, code, risk_profile)
    if result is None:
        raise HTTPException(
            status_code=404, detail={"code": "FUND_NOT_FOUND", "message": "未找到指定基金"}
        )
    return _envelope_from_context(result.data, result.context)


@router.get(
    "/{code}/nav",
    response_model=ApiResponse[list[NavPoint]],
    responses={400: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
def nav(
    code: str,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if start and end and start > end:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_DATE_RANGE", "message": "start 不能晚于 end"},
        )
    result = get_fund_navs_with_context(db, code, start, end)
    if result is None:
        raise HTTPException(
            status_code=404, detail={"code": "FUND_NOT_FOUND", "message": "未找到指定基金"}
        )
    return _envelope_from_context(result.data, result.context)
