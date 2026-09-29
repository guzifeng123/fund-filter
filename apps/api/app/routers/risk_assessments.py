from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.risk_assessments import latest_assessment, list_questions, submit_assessment
from app.schemas.common import ApiErrorResponse, ApiResponse
from app.schemas.risk_assessment import (
    RiskAssessmentResult,
    RiskAssessmentSubmission,
    RiskQuestion,
)

router = APIRouter()


@router.get("/questions", response_model=ApiResponse[list[RiskQuestion]])
def questions() -> dict[str, Any]:
    return envelope(list_questions())


@router.get("/latest", response_model=ApiResponse[RiskAssessmentResult | None])
def latest(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = latest_assessment(db)
    return envelope(result)


@router.post(
    "",
    response_model=ApiResponse[RiskAssessmentResult],
    responses={400: {"model": ApiErrorResponse}},
)
def submit(payload: RiskAssessmentSubmission, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return envelope(submit_assessment(db, payload.answers))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_RISK_ANSWERS", "message": "风险测评答案不完整", "detail": str(exc)},
        ) from exc
