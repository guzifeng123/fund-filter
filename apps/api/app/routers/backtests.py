from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.funds import fund_data_context
from app.schemas.backtest import BacktestRequest, BacktestResult
from app.schemas.common import ApiErrorResponse, ApiResponse
from app.services.backtest_service import backtest_detail, run_backtest

router = APIRouter()


def _envelope_for_backtest(result: BacktestResult, db: Session) -> dict[str, Any]:
    context = fund_data_context(db, result.snapshot_generation_id)
    return envelope(
        result,
        source=context.source,
        data_updated_at=context.data_updated_at,
    )


@router.post("", response_model=ApiResponse[BacktestResult])
def create(payload: BacktestRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _envelope_for_backtest(run_backtest(db, payload), db)


@router.get(
    "/{backtest_id}",
    response_model=ApiResponse[BacktestResult],
    responses={404: {"model": ApiErrorResponse}},
)
def detail(backtest_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = backtest_detail(db, backtest_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "BACKTEST_NOT_FOUND", "message": "未找到指定回测结果"},
        )
    return _envelope_for_backtest(result, db)
