from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import RiskAssessment, StoredRiskAnswer, StoredRiskAssessmentAnswers
from app.schemas.risk_assessment import (
    RiskAnswer,
    RiskAssessmentResult,
    RiskProfile,
    RiskQuestion,
    RiskQuestionOption,
)

VALID_DAYS = 365
EXPIRES_SOON_DAYS = 30


def _options(*values: tuple[int, str]) -> list[RiskQuestionOption]:
    return [RiskQuestionOption(score=score, label=label) for score, label in values]


RISK_QUESTIONS: list[RiskQuestion] = [
    RiskQuestion(
        id="horizon",
        title="这笔资金预计多久不会用于日常支出？",
        options=_options(
            (1, "3 个月以内"),
            (2, "3-12 个月"),
            (3, "1-3 年"),
            (4, "3-5 年"),
            (5, "5 年以上"),
        ),
    ),
    RiskQuestion(
        id="drawdown_tolerance",
        title="如果组合短期下跌，你能接受的最大波动大约是？",
        options=_options(
            (1, "几乎不能亏损"),
            (2, "5% 以内"),
            (3, "10% 以内"),
            (4, "20% 以内"),
            (5, "20% 以上也可承受"),
        ),
    ),
    RiskQuestion(
        id="income_stability",
        title="你的收入稳定性如何？",
        options=_options(
            (1, "不稳定且现金流紧张"),
            (2, "略有波动"),
            (3, "基本稳定"),
            (4, "稳定且有结余"),
            (5, "非常稳定且结余充足"),
        ),
    ),
    RiskQuestion(
        id="investment_experience",
        title="你对基金和净值波动的熟悉程度是？",
        options=_options(
            (1, "刚开始了解"),
            (2, "买过低风险产品"),
            (3, "买过债基或混合基金"),
            (4, "经历过权益基金波动"),
            (5, "长期管理多类资产"),
        ),
    ),
    RiskQuestion(
        id="liquidity_need",
        title="这笔资金对流动性的要求是？",
        options=_options(
            (1, "随时可能使用"),
            (2, "半年内可能使用"),
            (3, "保留部分即可"),
            (4, "大部分可长期安排"),
            (5, "基本无短期流动性要求"),
        ),
    ),
    RiskQuestion(
        id="goal_priority",
        title="你更看重哪类目标？",
        options=_options(
            (1, "本金稳定"),
            (2, "小幅增值"),
            (3, "稳健增长"),
            (4, "提升长期收益"),
            (5, "接受波动争取更高长期收益"),
        ),
    ),
]


def score_to_profile(score: int) -> RiskProfile:
    if score <= 9:
        return "C1"
    if score <= 14:
        return "C2"
    if score <= 19:
        return "C3"
    if score <= 24:
        return "C4"
    return "C5"


def profile_explanation(profile: RiskProfile) -> str:
    return {
        "C1": "保守型，优先关注本金稳定和高流动性。",
        "C2": "谨慎型，可接受小幅波动，适合以低风险资产为主。",
        "C3": "稳健型，可接受适度波动，适合均衡配置。",
        "C4": "积极型，可承受较大波动，适合提高权益暴露前充分评估。",
        "C5": "进取型，可承受高波动，仍需控制单一资产集中度。",
    }[profile]


def _result(row: RiskAssessment) -> RiskAssessmentResult:
    assessed_at = row.assessed_at
    if assessed_at.tzinfo is None:
        assessed_at = assessed_at.replace(tzinfo=timezone.utc)
    effective_to = assessed_at + timedelta(days=VALID_DAYS)
    now = datetime.now(timezone.utc)
    profile: RiskProfile = row.risk_profile
    score = int(row.answers.get("score", 0))
    return RiskAssessmentResult(
        risk_profile=profile,
        score=score,
        effective_from=assessed_at.date().isoformat(),
        effective_to=effective_to.date().isoformat(),
        expires_soon=now <= effective_to <= now + timedelta(days=EXPIRES_SOON_DAYS),
        is_expired=effective_to < now,
        explanation=profile_explanation(profile),
    )


def list_questions() -> list[RiskQuestion]:
    return RISK_QUESTIONS


def latest_assessment(db: Session, user_id: str = "local-user") -> RiskAssessmentResult | None:
    row = db.scalars(
        select(RiskAssessment)
        .where(RiskAssessment.user_id == user_id)
        .order_by(desc(RiskAssessment.assessed_at), desc(RiskAssessment.id))
        .limit(1)
    ).first()
    return _result(row) if row else None


def submit_assessment(
    db: Session,
    answers: list[RiskAnswer],
    user_id: str = "local-user",
) -> RiskAssessmentResult:
    valid_question_ids = {question.id for question in RISK_QUESTIONS}
    answer_ids = {answer.question_id for answer in answers}
    if answer_ids != valid_question_ids:
        missing = sorted(valid_question_ids - answer_ids)
        extra = sorted(answer_ids - valid_question_ids)
        raise ValueError(f"invalid question ids; missing={missing}; extra={extra}")

    score = sum(answer.score for answer in answers)
    profile = score_to_profile(score)
    stored_answers: StoredRiskAssessmentAnswers = {
        "score": score,
        "items": [
            StoredRiskAnswer(question_id=answer.question_id, score=answer.score)
            for answer in answers
        ],
    }
    row = RiskAssessment(
        user_id=user_id,
        risk_profile=profile,
        answers=stored_answers,
        assessed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _result(row)
