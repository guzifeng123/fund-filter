"""add document chunk vector index

Revision ID: 0005_add_document_chunk_vector_index
Revises: 0004_use_pgvector_for_document_embeddings
Create Date: 2026-07-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_document_chunk_vector_index"
down_revision: str | None = "0004_use_pgvector_for_document_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_document_chunks_embedding_cosine"
EXPECTED_INDEX_DEFINITION = """
CREATE INDEX ix_document_chunks_embedding_cosine
ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 1)
"""


def _normalize_sql(value: str) -> str:
    return "".join(value.lower().split()).replace("'", "")


def _existing_index_definition(bind: sa.Connection) -> str | None:
    return bind.execute(
        sa.text(
            """
            SELECT indexdef
            FROM pg_catalog.pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'document_chunks'
              AND indexname = :index_name
            """
        ),
        {"index_name": INDEX_NAME},
    ).scalar_one_or_none()


def _ensure_expected_index_definition(bind: sa.Connection) -> bool:
    index_definition = _existing_index_definition(bind)
    if index_definition is None:
        return False
    if _normalize_sql(str(index_definition)) != _normalize_sql(EXPECTED_INDEX_DEFINITION):
        raise RuntimeError(
            "document_chunks embedding index exists with an unexpected definition; "
            "refusing to reuse or drop it automatically."
        )
    return True


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if _ensure_expected_index_definition(bind):
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        EXPECTED_INDEX_DEFINITION
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not _ensure_expected_index_definition(bind):
        return
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
