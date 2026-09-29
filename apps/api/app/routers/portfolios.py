from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.portfolios import UnavailablePortfolioPositionsError
from app.schemas.common import ApiErrorResponse, ApiResponse
from app.schemas.portfolio import (
    PortfolioCreateRequest,
    PortfolioDeleteResult,
    PortfolioDetail,
    PortfolioPositionRequest,
    PortfolioSummary,
    PortfolioTemplate,
    PortfolioUpdateRequest,
    RebalancePreview,
)
from app.services.portfolio_service import (
    create,
    delete,
    normalize_positions,
    portfolio_detail,
    portfolios,
    rebalance_preview,
    remove_position,
    save_position,
    templates,
    update,
)

router = APIRouter()


def _unavailable_positions_error_detail(
    exc: UnavailablePortfolioPositionsError,
) -> dict[str, Any]:
    return {
        "availability_reason": exc.availability_reason,
        "unavailable_fund_codes": exc.unavailable_fund_codes,
    }


@router.get("/templates", response_model=ApiResponse[list[PortfolioTemplate]])
def portfolio_templates() -> dict[str, Any]:
    return envelope(templates())


@router.get("", response_model=ApiResponse[list[PortfolioSummary]])
def list_portfolios(db: Session = Depends(get_db)) -> dict[str, Any]:
    return envelope(portfolios(db))


@router.post(
    "",
    response_model=ApiResponse[PortfolioDetail],
    responses={400: {"model": ApiErrorResponse}},
)
def create_portfolio(
    payload: PortfolioCreateRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    try:
        return envelope(create(db, payload))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_PORTFOLIO_TEMPLATE",
                "message": "未知组合模板",
                "detail": str(exc),
            },
        ) from exc


@router.get(
    "/{portfolio_id}",
    response_model=ApiResponse[PortfolioDetail],
    responses={404: {"model": ApiErrorResponse}},
)
def detail(portfolio_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    portfolio = portfolio_detail(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"}
        )
    return envelope(portfolio)


@router.patch(
    "/{portfolio_id}",
    response_model=ApiResponse[PortfolioDetail],
    responses={404: {"model": ApiErrorResponse}},
)
def update_portfolio(
    portfolio_id: str,
    payload: PortfolioUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    portfolio = update(db, portfolio_id, payload)
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"}
        )
    return envelope(portfolio)


@router.delete(
    "/{portfolio_id}",
    response_model=ApiResponse[PortfolioDeleteResult],
    responses={404: {"model": ApiErrorResponse}},
)
def delete_portfolio(portfolio_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not delete(db, portfolio_id):
        raise HTTPException(
            status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"}
        )
    return envelope({"deleted": True})


@router.put(
    "/{portfolio_id}/positions",
    response_model=ApiResponse[PortfolioDetail],
    responses={404: {"model": ApiErrorResponse}},
)
def upsert_position(
    portfolio_id: str,
    payload: PortfolioPositionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        portfolio = save_position(db, portfolio_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": "未找到指定基金", "detail": str(exc)},
        ) from exc
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"}
        )
    return envelope(portfolio)


@router.delete(
    "/{portfolio_id}/positions/{fund_code}",
    response_model=ApiResponse[PortfolioDetail],
    responses={404: {"model": ApiErrorResponse}},
)
def delete_position(
    portfolio_id: str,
    fund_code: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    portfolio = remove_position(db, portfolio_id, fund_code)
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"}
        )
    return envelope(portfolio)


@router.post(
    "/{portfolio_id}/positions/normalize",
    response_model=ApiResponse[PortfolioDetail],
    responses={
        400: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
    },
)
def normalize_position_weights(
    portfolio_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        portfolio = normalize_positions(db, portfolio_id)
    except UnavailablePortfolioPositionsError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PORTFOLIO_HAS_UNAVAILABLE_POSITIONS",
                "message": "组合包含当前不可用的基金持仓",
                "detail": _unavailable_positions_error_detail(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_PORTFOLIO_WEIGHTS",
                "message": "持仓权重无法归一化",
                "detail": str(exc),
            },
        ) from exc
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"}
        )
    return envelope(portfolio)


@router.post(
    "/{portfolio_id}/rebalance-preview",
    response_model=ApiResponse[RebalancePreview],
    responses={409: {"model": ApiErrorResponse}, 404: {"model": ApiErrorResponse}},
)
def preview(portfolio_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        preview_result = rebalance_preview(db, portfolio_id)
    except UnavailablePortfolioPositionsError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PORTFOLIO_HAS_UNAVAILABLE_POSITIONS",
                "message": "组合包含当前不可用的基金持仓",
                "detail": _unavailable_positions_error_detail(exc),
            },
        ) from exc
    if preview_result is None:
        raise HTTPException(
            status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"}
        )
    return envelope(preview_result)
