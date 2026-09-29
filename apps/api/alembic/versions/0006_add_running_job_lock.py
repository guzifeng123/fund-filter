"""add running job lock

Revision ID: 0006_add_running_job_lock
Revises: 0005_add_document_chunk_vector_index
Create Date: 2026-07-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_running_job_lock"
down_revision: str | None = "0005_add_document_chunk_vector_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_RUNNING_JOB_DETAILS = (
    """{"error":"running job was marked failed by migration before adding unique running-job lock","""
    """"migration_revision":"0006_add_running_job_lock","""
    """"migration_action":"terminate_legacy_running_job","previous_status":"running"}"""
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE job_runs "
            "SET status = 'failed', "
            "finished_at = CURRENT_TIMESTAMP, "
            f"details = '{LEGACY_RUNNING_JOB_DETAILS}' "
            "WHERE status = 'running'"
        )
    )
    op.create_index(
        "uq_job_runs_running_name",
        "job_runs",
        ["name"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
        sqlite_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_job_runs_running_name", table_name="job_runs")
