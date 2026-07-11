from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.session import get_db
from app.schemas.backtest import BacktestRequest
from app.services.backtest_service import backtest_detail, run_backtest

router = APIRouter()


@router.post("")
def create(payload: BacktestRequest, db: Session = Depends(get_db)):
    return envelope(run_backtest(db, payload))


@router.get("/{backtest_id}")
def detail(backtest_id: str, db: Session = Depends(get_db)):
    return envelope(backtest_detail(db, backtest_id))
