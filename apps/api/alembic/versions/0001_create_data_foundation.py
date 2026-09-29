"""create data foundation

Revision ID: 0001_create_data_foundation
Revises:
Create Date: 2026-07-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_create_data_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def json_type() -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "funds",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("fund_type", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("manager_name", sa.String(length=100), nullable=False),
        sa.Column("inception_date", sa.Date(), nullable=False),
        sa.Column("fund_size_billion", sa.Float(), nullable=False),
        sa.Column("management_fee", sa.Float(), nullable=False),
        sa.Column("custody_fee", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("data_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=False),
        sa.Column("raw_data", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index(op.f("ix_funds_fund_type"), "funds", ["fund_type"], unique=False)
    op.create_index(op.f("ix_funds_name"), "funds", ["name"], unique=False)
    op.create_index(op.f("ix_funds_risk_level"), "funds", ["risk_level"], unique=False)
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_type", sa.String(length=64), nullable=False),
        sa.Column("request_payload", json_type(), nullable=False),
        sa.Column("result_snapshot", json_type(), nullable=False),
        sa.Column("annualized_return", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("volatility", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_backtest_runs_user_id"), "backtest_runs", ["user_id"], unique=False)
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", json_type(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_runs_name"), "job_runs", ["name"], unique=False)
    op.create_index(op.f("ix_job_runs_status"), "job_runs", ["status"], unique=False)
    op.create_table(
        "portfolios",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("stock_ratio", sa.Integer(), nullable=False),
        sa.Column("bond_ratio", sa.Integer(), nullable=False),
        sa.Column("config", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_portfolios_user_id"), "portfolios", ["user_id"], unique=False)
    op.create_table(
        "risk_assessments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("risk_profile", sa.String(length=8), nullable=False),
        sa.Column("answers", json_type(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_risk_assessments_user_id"), "risk_assessments", ["user_id"], unique=False)
    op.create_table(
        "fund_metrics",
        sa.Column("fund_code", sa.String(length=32), nullable=False),
        sa.Column("annualized_return_3y", sa.Float(), nullable=False),
        sa.Column("annualized_return_5y", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("sharpe_ratio", sa.Float(), nullable=False),
        sa.Column("category_rank_percentile", sa.Float(), nullable=False),
        sa.Column("manager_years", sa.Integer(), nullable=False),
        sa.Column("raw_data", json_type(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fund_code"], ["funds.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("fund_code"),
    )
    op.create_table(
        "fund_navs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fund_code", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.String(length=32), nullable=False),
        sa.Column("nav", sa.Float(), nullable=False),
        sa.Column("accumulated_nav", sa.Float(), nullable=False),
        sa.Column("raw_data", json_type(), nullable=False),
        sa.ForeignKeyConstraint(["fund_code"], ["funds.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_code", "trade_date", name="uq_fund_navs_fund_code_trade_date"),
    )
    op.create_index(op.f("ix_fund_navs_fund_code"), "fund_navs", ["fund_code"], unique=False)
    op.create_index(op.f("ix_fund_navs_trade_date"), "fund_navs", ["trade_date"], unique=False)
    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("fund_code", sa.String(length=32), nullable=False),
        sa.Column("weight_percent", sa.Float(), nullable=False),
        sa.Column("metadata", json_type(), nullable=False),
        sa.ForeignKeyConstraint(["fund_code"], ["funds.code"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portfolio_id", "fund_code", name="uq_portfolio_positions_portfolio_fund"),
    )


def downgrade() -> None:
    op.drop_table("portfolio_positions")
    op.drop_index(op.f("ix_fund_navs_trade_date"), table_name="fund_navs")
    op.drop_index(op.f("ix_fund_navs_fund_code"), table_name="fund_navs")
    op.drop_table("fund_navs")
    op.drop_table("fund_metrics")
    op.drop_index(op.f("ix_risk_assessments_user_id"), table_name="risk_assessments")
    op.drop_table("risk_assessments")
    op.drop_index(op.f("ix_portfolios_user_id"), table_name="portfolios")
    op.drop_table("portfolios")
    op.drop_index(op.f("ix_job_runs_status"), table_name="job_runs")
    op.drop_index(op.f("ix_job_runs_name"), table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index(op.f("ix_backtest_runs_user_id"), table_name="backtest_runs")
    op.drop_table("backtest_runs")
    op.drop_index(op.f("ix_funds_risk_level"), table_name="funds")
    op.drop_index(op.f("ix_funds_name"), table_name="funds")
    op.drop_index(op.f("ix_funds_fund_type"), table_name="funds")
    op.drop_table("funds")
