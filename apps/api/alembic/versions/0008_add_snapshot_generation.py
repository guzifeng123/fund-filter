"""add atomically promoted fund snapshot generations

Revision ID: 0008_add_snapshot_generation
Revises: 0007_add_nav_trade_date_precision
Create Date: 2026-07-13 00:00:00.000000
"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_snapshot_generation"
down_revision: str | None = "0007_add_nav_trade_date_precision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_GENERATION_ID = "legacy-0008"
STATE_ROW_ID = 1
SNAPSHOT_STATUS_INDEX = "ix_fund_data_snapshots_status"
SNAPSHOT_STATUS_CHECK = "ck_fund_data_snapshots_status"
SNAPSHOT_COUNT_CHECKS = {
    "fund_count": "ck_fund_data_snapshots_fund_count_nonnegative",
    "nav_count": "ck_fund_data_snapshots_nav_count_nonnegative",
    "metric_count": "ck_fund_data_snapshots_metric_count_nonnegative",
}
GENERATION_INDEXES = {
    "funds": "ix_funds_snapshot_generation_id",
    "fund_navs": "ix_fund_navs_snapshot_generation_id",
    "fund_metrics": "ix_fund_metrics_snapshot_generation_id",
}
GENERATION_FOREIGN_KEYS = {
    "funds": "fk_funds_snapshot_generation_id",
    "fund_navs": "fk_fund_navs_snapshot_generation_id",
    "fund_metrics": "fk_fund_metrics_snapshot_generation_id",
}


def _table_names(bind: sa.Connection) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind: sa.Connection, table_name: str) -> set[str]:
    return {str(column["name"]) for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind: sa.Connection, table_name: str) -> set[str]:
    return {str(index["name"]) for index in sa.inspect(bind).get_indexes(table_name)}


def _source_summary(bind: sa.Connection) -> str:
    rows = bind.execute(sa.text("SELECT DISTINCT source FROM funds ORDER BY source")).scalars()
    sources = [str(source).strip() for source in rows if source and str(source).strip()]
    if not sources:
        return "legacy"
    if len(sources) == 1:
        return sources[0]
    return f"mixed({len(sources)} sources)"


def _row_count(bind: sa.Connection, table_name: str) -> int:
    return int(bind.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one())


def upgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if "fund_data_snapshots" not in tables:
        op.create_table(
            "fund_data_snapshots",
            sa.Column("generation_id", sa.String(length=64), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("fund_count", sa.Integer(), nullable=False),
            sa.Column("nav_count", sa.Integer(), nullable=False),
            sa.Column("metric_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('staging', 'active', 'superseded')",
                name=SNAPSHOT_STATUS_CHECK,
            ),
            *(
                sa.CheckConstraint(f"{column_name} >= 0", name=constraint_name)
                for column_name, constraint_name in SNAPSHOT_COUNT_CHECKS.items()
            ),
            sa.PrimaryKeyConstraint("generation_id"),
        )
    if SNAPSHOT_STATUS_INDEX not in _index_names(bind, "fund_data_snapshots"):
        op.create_index(
            SNAPSHOT_STATUS_INDEX,
            "fund_data_snapshots",
            ["status"],
            unique=False,
        )

    now = datetime.now(timezone.utc)
    snapshots = sa.table(
        "fund_data_snapshots",
        sa.column("generation_id", sa.String()),
        sa.column("source", sa.String()),
        sa.column("status", sa.String()),
        sa.column("fund_count", sa.Integer()),
        sa.column("nav_count", sa.Integer()),
        sa.column("metric_count", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("promoted_at", sa.DateTime(timezone=True)),
    )
    legacy_exists = bind.execute(
        sa.select(snapshots.c.generation_id).where(
            snapshots.c.generation_id == LEGACY_GENERATION_ID
        )
    ).first()
    if legacy_exists is None:
        bind.execute(
            sa.insert(snapshots).values(
                generation_id=LEGACY_GENERATION_ID,
                source=_source_summary(bind),
                status="active",
                fund_count=_row_count(bind, "funds"),
                nav_count=_row_count(bind, "fund_navs"),
                metric_count=_row_count(bind, "fund_metrics"),
                created_at=now,
                promoted_at=now,
            )
        )

    for table_name, index_name in GENERATION_INDEXES.items():
        if "snapshot_generation_id" not in _column_names(bind, table_name):
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "snapshot_generation_id",
                        sa.String(length=64),
                        nullable=False,
                        server_default=sa.text(f"'{LEGACY_GENERATION_ID}'"),
                    )
                )
                batch_op.create_foreign_key(
                    GENERATION_FOREIGN_KEYS[table_name],
                    "fund_data_snapshots",
                    ["snapshot_generation_id"],
                    ["generation_id"],
                    ondelete="RESTRICT",
                )
        bind.execute(
            sa.text(
                f"UPDATE {table_name} SET snapshot_generation_id = :generation_id "
                "WHERE snapshot_generation_id IS NULL OR snapshot_generation_id = ''"
            ),
            {"generation_id": LEGACY_GENERATION_ID},
        )
        if index_name not in _index_names(bind, table_name):
            op.create_index(index_name, table_name, ["snapshot_generation_id"], unique=False)

    if "fund_data_snapshot_state" not in _table_names(bind):
        op.create_table(
            "fund_data_snapshot_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("active_generation_id", sa.String(length=64), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["active_generation_id"],
                ["fund_data_snapshots.generation_id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("active_generation_id"),
            sa.CheckConstraint("id = 1", name="ck_fund_data_snapshot_state_singleton"),
        )
    state = sa.table(
        "fund_data_snapshot_state",
        sa.column("id", sa.Integer()),
        sa.column("active_generation_id", sa.String()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    if bind.execute(sa.select(state.c.id).where(state.c.id == STATE_ROW_ID)).first() is None:
        bind.execute(
            sa.insert(state).values(
                id=STATE_ROW_ID,
                active_generation_id=LEGACY_GENERATION_ID,
                updated_at=now,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _table_names(bind)
    if "fund_data_snapshot_state" in tables:
        op.drop_table("fund_data_snapshot_state")

    for table_name, index_name in GENERATION_INDEXES.items():
        if table_name not in _table_names(bind):
            continue
        if index_name in _index_names(bind, table_name):
            op.drop_index(index_name, table_name=table_name)
        if "snapshot_generation_id" in _column_names(bind, table_name):
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_constraint(
                    GENERATION_FOREIGN_KEYS[table_name],
                    type_="foreignkey",
                )
                batch_op.drop_column("snapshot_generation_id")

    if "fund_data_snapshots" in _table_names(bind):
        if SNAPSHOT_STATUS_INDEX in _index_names(bind, "fund_data_snapshots"):
            op.drop_index(SNAPSHOT_STATUS_INDEX, table_name="fund_data_snapshots")
        op.drop_table("fund_data_snapshots")
