import importlib.util
from pathlib import Path
from collections.abc import Callable
from typing import Protocol, cast

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Dialect


MIGRATION_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
postgresql_dialect = cast(Callable[[], Dialect], postgresql.dialect)


class RagDocumentMigration(Protocol):
    def json_type(self) -> sa.types.TypeEngine[object]: ...


def _load_migration(filename: str) -> RagDocumentMigration:
    spec = importlib.util.spec_from_file_location(
        f"test_{filename.removesuffix('.py')}",
        MIGRATION_DIR / filename,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(RagDocumentMigration, module)


def test_0003_keeps_embedding_as_json_until_pgvector_revision() -> None:
    migration = _load_migration("0003_create_rag_documents.py")

    json_type = migration.json_type()

    assert json_type.compile(dialect=postgresql_dialect()) == "JSONB"
    assert json_type.compile(dialect=sqlite.dialect()) == "JSON"


def test_0004_is_the_pgvector_conversion_boundary() -> None:
    source = (MIGRATION_DIR / "0004_use_pgvector_for_document_embeddings.py").read_text(
        encoding="utf-8"
    )

    assert "ALTER COLUMN embedding TYPE vector(16)" in source
    assert "ALTER COLUMN embedding TYPE jsonb" in source
