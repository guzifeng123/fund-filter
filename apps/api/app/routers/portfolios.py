from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.session import get_db
from app.schemas.portfolio import PortfolioCreateRequest, PortfolioPositionRequest, PortfolioUpdateRequest
from app.services.portfolio_service import (
    create,
    delete,
    portfolio_detail,
    portfolios,
    rebalance_preview,
    remove_position,
    save_position,
    templates,
    update,
)

router = APIRouter()


@router.get("/templates")
def portfolio_templates():
    return envelope(templates())


@router.get("")
def list_portfolios(db: Session = Depends(get_db)):
    return envelope(portfolios(db))


@router.post("")
def create_portfolio(payload: PortfolioCreateRequest, db: Session = Depends(get_db)):
    try:
        return envelope(create(db, payload))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PORTFOLIO_TEMPLATE", "message": "未知组合模板", "detail": str(exc)},
        ) from exc


@router.get("/{portfolio_id}")
def detail(portfolio_id: str, db: Session = Depends(get_db)):
    portfolio = portfolio_detail(db, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"})
    return envelope(portfolio)


@router.patch("/{portfolio_id}")
def update_portfolio(portfolio_id: str, payload: PortfolioUpdateRequest, db: Session = Depends(get_db)):
    portfolio = update(db, portfolio_id, payload)
    if portfolio is None:
        raise HTTPException(status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"})
    return envelope(portfolio)


@router.delete("/{portfolio_id}")
def delete_portfolio(portfolio_id: str, db: Session = Depends(get_db)):
    if not delete(db, portfolio_id):
        raise HTTPException(status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"})
    return envelope({"deleted": True})


@router.put("/{portfolio_id}/positions")
def upsert_position(portfolio_id: str, payload: PortfolioPositionRequest, db: Session = Depends(get_db)):
    try:
        portfolio = save_position(db, portfolio_id, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": "未找到指定基金", "detail": str(exc)},
        ) from exc
    if portfolio is None:
        raise HTTPException(status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"})
    return envelope(portfolio)


@router.delete("/{portfolio_id}/positions/{fund_code}")
def delete_position(portfolio_id: str, fund_code: str, db: Session = Depends(get_db)):
    portfolio = remove_position(db, portfolio_id, fund_code)
    if portfolio is None:
        raise HTTPException(status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"})
    return envelope(portfolio)


@router.post("/{portfolio_id}/rebalance-preview")
def preview(portfolio_id: str, db: Session = Depends(get_db)):
    preview_result = rebalance_preview(db, portfolio_id)
    if preview_result is None:
        raise HTTPException(status_code=404, detail={"code": "PORTFOLIO_NOT_FOUND", "message": "未找到指定组合"})
    return envelope(preview_result)
