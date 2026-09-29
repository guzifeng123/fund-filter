from datetime import date, datetime, timezone
from typing import Literal, TypeAlias, TypedDict

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.session import Base
from app.db.vector import VectorList

JsonType = JSONB().with_variant(JSON(), "sqlite")

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]
LEGACY_SNAPSHOT_GENERATION_ID = "legacy-0008"
StoredRiskProfile: TypeAlias = Literal["C1", "C2", "C3", "C4", "C5"]
StoredBacktestStrategy: TypeAlias = Literal[
    "monthly_dca", "weekly_dca", "rebalance", "template_portfolio"
]


class StoredBacktestRequest(TypedDict, total=False):
    strategy_type: StoredBacktestStrategy
    amount: float
    start: str
    end: str
    fund_codes: list[str]
    rebalance_threshold: float
    template_key: Literal["conservative", "balanced", "growth"]


class StoredBacktestPoint(TypedDict):
    date: str
    portfolio: float
    benchmark: float


class StoredBacktestResult(TypedDict, total=False):
    id: str
    strategy_type: StoredBacktestStrategy
    annualized_return: float
    max_drawdown: float
    volatility: float
    sharpe_ratio: float
    total_invested: float
    final_value: float
    money_weighted_return: float
    time_weighted_return: float
    return_calculation_method: Literal["xirr", "unavailable"]
    snapshot_generation_id: str | None
    data_warning: str | None
    points: list[StoredBacktestPoint]


class StoredRiskAnswer(TypedDict):
    question_id: str
    score: int


class StoredRiskAssessmentAnswers(TypedDict, total=False):
    score: int
    items: list[StoredRiskAnswer]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FundDataSnapshot(Base):
    __tablename__ = "fund_data_snapshots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('staging', 'active', 'superseded')",
            name="ck_fund_data_snapshots_status",
        ),
        CheckConstraint(
            "fund_count >= 0",
            name="ck_fund_data_snapshots_fund_count_nonnegative",
        ),
        CheckConstraint(
            "nav_count >= 0",
            name="ck_fund_data_snapshots_nav_count_nonnegative",
        ),
        CheckConstraint(
            "metric_count >= 0",
            name="ck_fund_data_snapshots_metric_count_nonnegative",
        ),
    )

    generation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    fund_count: Mapped[int] = mapped_column(Integer, nullable=False)
    nav_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FundDataSnapshotState(Base):
    __tablename__ = "fund_data_snapshot_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_fund_data_snapshot_state_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_generation_id: Mapped[str] = mapped_column(
        ForeignKey("fund_data_snapshots.generation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Fund(Base):
    __tablename__ = "funds"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fund_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    manager_name: Mapped[str] = mapped_column(String(100), nullable=False)
    inception_date: Mapped[date] = mapped_column(Date, nullable=False)
    fund_size_billion: Mapped[float] = mapped_column(Float, nullable=False)
    management_fee: Mapped[float] = mapped_column(Float, nullable=False)
    custody_fee: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="sample_local")
    data_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ai_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_data: Mapped[JsonObject] = mapped_column(JsonType, nullable=False, default=dict)
    snapshot_generation_id: Mapped[str] = mapped_column(
        ForeignKey("fund_data_snapshots.generation_id", ondelete="RESTRICT"),
        nullable=False,
        default=LEGACY_SNAPSHOT_GENERATION_ID,
        server_default=LEGACY_SNAPSHOT_GENERATION_ID,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    navs: Mapped[list["FundNav"]] = relationship(
        back_populates="fund", cascade="all, delete-orphan", order_by="FundNav.trade_date"
    )
    metrics: Mapped["FundMetric | None"] = relationship(
        back_populates="fund", cascade="all, delete-orphan", uselist=False
    )


class FundNav(Base):
    __tablename__ = "fund_navs"
    __table_args__ = (UniqueConstraint("fund_code", "trade_date", name="uq_fund_navs_fund_code_trade_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(ForeignKey("funds.code", ondelete="CASCADE"), nullable=False, index=True)
    trade_date: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trade_date_precision: Mapped[str] = mapped_column(
        String(8), nullable=False, default="unknown", server_default="unknown"
    )
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    accumulated_nav: Mapped[float] = mapped_column(Float, nullable=False)
    raw_data: Mapped[JsonObject] = mapped_column(JsonType, nullable=False, default=dict)
    snapshot_generation_id: Mapped[str] = mapped_column(
        ForeignKey("fund_data_snapshots.generation_id", ondelete="RESTRICT"),
        nullable=False,
        default=LEGACY_SNAPSHOT_GENERATION_ID,
        server_default=LEGACY_SNAPSHOT_GENERATION_ID,
        index=True,
    )

    fund: Mapped[Fund] = relationship(back_populates="navs")


class FundMetric(Base):
    __tablename__ = "fund_metrics"

    fund_code: Mapped[str] = mapped_column(ForeignKey("funds.code", ondelete="CASCADE"), primary_key=True)
    annualized_return_3y: Mapped[float] = mapped_column(Float, nullable=False)
    annualized_return_5y: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    sharpe_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    category_rank_percentile: Mapped[float] = mapped_column(Float, nullable=False)
    manager_years: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[JsonObject] = mapped_column(JsonType, nullable=False, default=dict)
    snapshot_generation_id: Mapped[str] = mapped_column(
        ForeignKey("fund_data_snapshots.generation_id", ondelete="RESTRICT"),
        nullable=False,
        default=LEGACY_SNAPSHOT_GENERATION_ID,
        server_default=LEGACY_SNAPSHOT_GENERATION_ID,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    fund: Mapped[Fund] = relationship(back_populates="metrics")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="local-user")
    risk_profile: Mapped[StoredRiskProfile] = mapped_column(String(8), nullable=False)
    answers: Mapped[StoredRiskAssessmentAnswers] = mapped_column(
        JsonType, nullable=False, default=dict
    )
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="local-user")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stock_ratio: Mapped[int] = mapped_column(Integer, nullable=False)
    bond_ratio: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[JsonObject] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    positions: Mapped[list["PortfolioPosition"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "fund_code", name="uq_portfolio_positions_portfolio_fund"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    fund_code: Mapped[str] = mapped_column(ForeignKey("funds.code", ondelete="RESTRICT"), nullable=False)
    weight_percent: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JsonType, nullable=False, default=dict
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")
    fund: Mapped[Fund] = relationship()


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="local-user")
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[StoredBacktestRequest] = mapped_column(
        JsonType, nullable=False, default=dict
    )
    result_snapshot: Mapped[StoredBacktestResult] = mapped_column(
        JsonType, nullable=False, default=dict
    )
    annualized_return: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    volatility: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index(
            "uq_job_runs_running_name",
            "name",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[JsonObject] = mapped_column(JsonType, nullable=False, default=dict)


class AiThread(Base):
    __tablename__ = "ai_threads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="local-user")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    messages: Mapped[list["AiMessage"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="AiMessage.created_at"
    )


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("ai_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[JsonObject] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    thread: Mapped[AiThread] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, default="education")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JsonType, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VectorList(16), nullable=False)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JsonType, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    document: Mapped[Document] = relationship(back_populates="chunks")


class LlmProviderEvent(Base):
    __tablename__ = "llm_provider_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success', 'fallback')",
            name="ck_llm_provider_events_outcome",
        ),
        CheckConstraint(
            "(attempt_count = 0 AND retry_count = 0) OR "
            "(attempt_count >= 1 AND retry_count >= 0 AND retry_count < attempt_count)",
            name="ck_llm_provider_events_attempt_retry",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_llm_provider_events_latency_ms",
        ),
        CheckConstraint(
            "error_category IS NULL OR error_category IN "
            "('config_missing', 'timeout', 'network', 'rate_limited', 'http_client', "
            "'http_server', 'invalid_response', 'policy_rejected', 'provider_error')",
            name="ck_llm_provider_events_error_category",
        ),
        CheckConstraint(
            "outcome != 'fallback' OR error_category IS NOT NULL",
            name="ck_llm_provider_events_fallback_category",
        ),
        CheckConstraint(
            "(attempt_count = 0 AND outcome = 'fallback' "
            "AND error_category = 'config_missing') OR "
            "(attempt_count >= 1 AND "
            "(error_category IS NULL OR error_category != 'config_missing'))",
            name="ck_llm_provider_events_config_missing_attempt",
        ),
        CheckConstraint(
            "length(provider_name) BETWEEN 1 AND 64 "
            "AND provider_name NOT LIKE '%:%' AND provider_name NOT LIKE '%/%' "
            "AND provider_name NOT LIKE '%@%' AND provider_name NOT LIKE '%?%' "
            "AND provider_name NOT LIKE '%#%' AND provider_name NOT LIKE '%=%' "
            "AND provider_name NOT LIKE '% %'",
            name="ck_llm_provider_events_provider_name_safe",
        ),
        CheckConstraint(
            "length(model_name) BETWEEN 1 AND 128 "
            "AND model_name NOT LIKE '%:%' AND model_name NOT LIKE '%/%' "
            "AND model_name NOT LIKE '%@%' AND model_name NOT LIKE '%?%' "
            "AND model_name NOT LIKE '%#%' AND model_name NOT LIKE '%=%' "
            "AND model_name NOT LIKE '% %'",
            name="ck_llm_provider_events_model_name_safe",
        ),
        Index(
            "ix_llm_provider_events_provider_model_created_at",
            "provider_name",
            "model_name",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
