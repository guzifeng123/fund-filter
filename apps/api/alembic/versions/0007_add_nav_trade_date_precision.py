"""classify NAV trade-date precision without rewriting legacy values

Revision ID: 0007_add_nav_trade_date_precision
Revises: 0006_add_running_job_lock
Create Date: 2026-07-13 00:00:00.000000
"""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import context, op

revision: str = "0007_add_nav_trade_date_precision"
down_revision: str | None = "0006_add_running_job_lock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
BACKFILL_BATCH_SIZE = 1_000


def _has_precision_column(bind: sa.Connection) -> bool:
    return any(
        column["name"] == "trade_date_precision"
        for column in sa.inspect(bind).get_columns("fund_navs")
    )


def _classify_trade_date(raw_value: object) -> str:
    value = str(raw_value)
    if len(value) == 4 and value.isdigit():
        try:
            date(int(value), 1, 1)
        except ValueError:
            return "unknown"
        return "year"
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return "unknown"
    return "day" if parsed.isoformat() == value else "unknown"


def _offline_backfill_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return (
            "UPDATE fund_navs SET trade_date_precision = CASE "
            "WHEN trade_date ~ '^[0-9]{4}$' THEN 'year' "
            "WHEN trade_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN 'day' "
            "ELSE 'unknown' END "
            "WHERE trade_date_precision = 'unknown'"
        )
    return (
        "UPDATE fund_navs SET trade_date_precision = CASE "
        "WHEN trade_date GLOB '[0-9][0-9][0-9][0-9]' THEN 'year' "
        "WHEN trade_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN 'day' "
        "ELSE 'unknown' END "
        "WHERE trade_date_precision = 'unknown'"
    )


def _backfill_trade_date_precision(bind: sa.Connection) -> None:
    fund_navs = sa.table(
        "fund_navs",
        sa.column("id", sa.Integer()),
        sa.column("trade_date", sa.String()),
        sa.column("trade_date_precision", sa.String()),
    )
    result = bind.execute(
        sa.select(fund_navs.c.id, fund_navs.c.trade_date)
        .where(fund_navs.c.trade_date_precision == "unknown")
        .order_by(fund_navs.c.id)
    )
    while True:
        rows = result.fetchmany(BACKFILL_BATCH_SIZE)
        if not rows:
            break
        ids_by_precision: dict[str, list[int]] = {"day": [], "year": []}
        for row in rows:
            precision = _classify_trade_date(row[1])
            if precision in ids_by_precision:
                ids_by_precision[precision].append(int(row[0]))
        for precision, row_ids in ids_by_precision.items():
            if row_ids:
                bind.execute(
                    sa.update(fund_navs)
                    .where(fund_navs.c.id.in_(row_ids))
                    .values(trade_date_precision=precision)
                )


def upgrade() -> None:
    bind = op.get_bind()
    if context.is_offline_mode():
        op.add_column(
            "fund_navs",
            sa.Column(
                "trade_date_precision",
                sa.String(length=8),
                nullable=False,
                server_default=sa.text("'unknown'"),
            ),
        )
        op.execute(_offline_backfill_sql(bind.dialect.name))
        return

    if not _has_precision_column(bind):
        op.add_column(
            "fund_navs",
            sa.Column(
                "trade_date_precision",
                sa.String(length=8),
                nullable=False,
                server_default=sa.text("'unknown'"),
            ),
        )

    _backfill_trade_date_precision(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if context.is_offline_mode():
        op.drop_column("fund_navs", "trade_date_precision")
        return
    if not _has_precision_column(bind):
        return
    with op.batch_alter_table("fund_navs") as batch_op:
        batch_op.drop_column("trade_date_precision")
