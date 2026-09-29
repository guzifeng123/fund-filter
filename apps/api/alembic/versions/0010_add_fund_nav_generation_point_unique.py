"""lock per-generation (fund_code, trade_date) nav identity for idempotent writes

Revision ID: 0010_add_fund_nav_generation_point_unique
Revises: 0009_add_llm_provider_events
Create Date: 2026-09-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_add_fund_nav_generation_point_unique"
down_revision: str | None = "0009_add_llm_provider_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENERATION_POINT_INDEX = "uq_fund_navs_generation_point"


def upgrade() -> None:
    """Enforce "one nav point per (generation, fund_code, trade_date)" at the DB.

    The historical global ``uq_fund_navs_fund_code_trade_date`` already keeps a
    single physical row per (fund_code, trade_date) because this schema mutates
    rows in place between generations. This supplementary unique index makes the
    per-generation idempotency contract explicit and protects the new batched
    write path from ever staging two nav rows for the same point in one
    generation. Existing data already satisfies it (the global constraint is
    stricter), so building the index never requires a table rewrite.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("fund_navs")}
    if GENERATION_POINT_INDEX not in existing_indexes:
        op.create_index(
            GENERATION_POINT_INDEX,
            "fund_navs",
            ["snapshot_generation_id", "fund_code", "trade_date"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("fund_navs")}
    if GENERATION_POINT_INDEX in existing_indexes:
        op.drop_index(GENERATION_POINT_INDEX, table_name="fund_navs")
