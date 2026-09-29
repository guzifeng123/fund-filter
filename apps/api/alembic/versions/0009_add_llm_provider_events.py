"""add sanitized llm provider observability events

Revision ID: 0009_add_llm_provider_events
Revises: 0008_add_snapshot_generation
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_add_llm_provider_events"
down_revision: str | None = "0008_add_snapshot_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("timed_out", sa.Boolean(), nullable=False),
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('success', 'fallback')",
            name="ck_llm_provider_events_outcome",
        ),
        sa.CheckConstraint(
            "(attempt_count = 0 AND retry_count = 0) OR "
            "(attempt_count >= 1 AND retry_count >= 0 AND retry_count < attempt_count)",
            name="ck_llm_provider_events_attempt_retry",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ck_llm_provider_events_latency_ms",
        ),
        sa.CheckConstraint(
            "error_category IS NULL OR error_category IN "
            "('config_missing', 'timeout', 'network', 'rate_limited', 'http_client', "
            "'http_server', 'invalid_response', 'policy_rejected', 'provider_error')",
            name="ck_llm_provider_events_error_category",
        ),
        sa.CheckConstraint(
            "outcome != 'fallback' OR error_category IS NOT NULL",
            name="ck_llm_provider_events_fallback_category",
        ),
        sa.CheckConstraint(
            "(attempt_count = 0 AND outcome = 'fallback' "
            "AND error_category = 'config_missing') OR "
            "(attempt_count >= 1 AND "
            "(error_category IS NULL OR error_category != 'config_missing'))",
            name="ck_llm_provider_events_config_missing_attempt",
        ),
        sa.CheckConstraint(
            "length(provider_name) BETWEEN 1 AND 64 "
            "AND provider_name NOT LIKE '%:%' AND provider_name NOT LIKE '%/%' "
            "AND provider_name NOT LIKE '%@%' AND provider_name NOT LIKE '%?%' "
            "AND provider_name NOT LIKE '%#%' AND provider_name NOT LIKE '%=%' "
            "AND provider_name NOT LIKE '% %'",
            name="ck_llm_provider_events_provider_name_safe",
        ),
        sa.CheckConstraint(
            "length(model_name) BETWEEN 1 AND 128 "
            "AND model_name NOT LIKE '%:%' AND model_name NOT LIKE '%/%' "
            "AND model_name NOT LIKE '%@%' AND model_name NOT LIKE '%?%' "
            "AND model_name NOT LIKE '%#%' AND model_name NOT LIKE '%=%' "
            "AND model_name NOT LIKE '% %'",
            name="ck_llm_provider_events_model_name_safe",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_llm_provider_events_provider_model_created_at",
        "llm_provider_events",
        ["provider_name", "model_name", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_llm_provider_events_provider_model_created_at",
        table_name="llm_provider_events",
    )
    op.drop_table("llm_provider_events")
