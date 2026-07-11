from datetime import datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.session import Base
from app.db.vector import VectorList

JsonType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Fund(Base):
    __tablename__ = "funds"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fund_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    manager_name: Mapped[str] = mapped_column(String(100), nullable=False)
    inception_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    fund_size_billion: Mapped[float] = mapped_column(Float, nullable=False)
    management_fee: Mapped[float] = mapped_column(Float, nullable=False)
    custody_fee: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="sample_local")
    data_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ai_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_data: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
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
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    accumulated_nav: Mapped[float] = mapped_column(Float, nullable=False)
    raw_data: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)

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
    raw_data: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    fund: Mapped[Fund] = relationship(back_populates="metrics")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="local-user")
    risk_profile: Mapped[str] = mapped_column(String(8), nullable=False)
    answers: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="local-user")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stock_ratio: Mapped[int] = mapped_column(Integer, nullable=False)
    bond_ratio: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
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
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")
    fund: Mapped[Fund] = relationship()


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="local-user")
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    result_snapshot: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    annualized_return: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    volatility: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)


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
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    thread: Mapped[AiThread] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, default="education")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
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
    metadata_: Mapped[dict] = mapped_column("metadata", JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    document: Mapped[Document] = relationship(back_populates="chunks")
