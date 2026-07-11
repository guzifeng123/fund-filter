from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.risk_assessments import latest_assessment, list_questions, submit_assessment
from app.schemas.risk_assessment import RiskAssessmentSubmission

router = APIRouter()


@router.get("/questions")
def questions():
    return envelope(list_questions())


@router.get("/latest")
def latest(db: Session = Depends(get_db)):
    result = latest_assessment(db)
    return envelope(result)


@router.post("")
def submit(payload: RiskAssessmentSubmission, db: Session = Depends(get_db)):
    try:
        return envelope(submit_assessment(db, payload.answers))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_RISK_ANSWERS", "message": "风险测评答案不完整", "detail": str(exc)},
        ) from exc
