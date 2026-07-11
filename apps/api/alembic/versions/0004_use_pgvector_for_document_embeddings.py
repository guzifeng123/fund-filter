"""use pgvector for document embeddings

Revision ID: 0004_use_pgvector_for_document_embeddings
Revises: 0003_create_rag_documents
Create Date: 2026-07-10 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_use_pgvector_for_document_embeddings"
down_revision: str | None = "0003_create_rag_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        ALTER TABLE document_chunks
        ALTER COLUMN embedding TYPE vector(16)
        USING embedding::text::vector
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        """
        ALTER TABLE document_chunks
        ALTER COLUMN embedding TYPE jsonb
        USING embedding::text::jsonb
        """
    )
