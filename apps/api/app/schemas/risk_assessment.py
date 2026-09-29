from typing import Literal

from pydantic import BaseModel, Field, field_validator

RiskProfile = Literal["C1", "C2", "C3", "C4", "C5"]


class RiskQuestionOption(BaseModel):
    score: int = Field(ge=1, le=5)
    label: str


class RiskQuestion(BaseModel):
    id: str
    title: str
    options: list[RiskQuestionOption]


class RiskAnswer(BaseModel):
    question_id: str
    score: int = Field(ge=1, le=5)


class RiskAssessmentSubmission(BaseModel):
    answers: list[RiskAnswer] = Field(min_length=5, max_length=8)

    @field_validator("answers")
    @classmethod
    def reject_duplicate_question_ids(cls, answers: list[RiskAnswer]) -> list[RiskAnswer]:
        question_ids = [answer.question_id for answer in answers]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("answers must contain each question_id at most once")
        return answers


class RiskAssessmentResult(BaseModel):
    risk_profile: RiskProfile
    score: int
    effective_from: str
    effective_to: str
    expires_soon: bool
    is_expired: bool
    explanation: str
