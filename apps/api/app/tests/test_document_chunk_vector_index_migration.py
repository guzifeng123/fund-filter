from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0005_add_document_chunk_vector_index.py"
)
SPEC = importlib.util.spec_from_file_location(
    "test_migration_0005_add_document_chunk_vector_index",
    MIGRATION_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class _FakeResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> str | None:
        return self._value


class _FakeBind:
    def __init__(self, index_definition: str | None) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.index_definition = index_definition
        self.executed: list[tuple[str, dict[str, str] | None]] = []

    def execute(self, statement: object, parameters: dict[str, str] | None = None) -> _FakeResult:
        self.executed.append((str(statement), parameters))
        rendered = str(statement)
        # The pg_indexes probe returns the stored indexdef; the separate
        # ``SELECT current_schema()`` probe returns the schema name to strip.
        if "pg_indexes" in rendered:
            return _FakeResult(self.index_definition)
        return _FakeResult("public")


def test_upgrade_skips_existing_matching_index(monkeypatch: pytest.MonkeyPatch) -> None:
    bind = _FakeBind(MIGRATION.EXPECTED_INDEX_DEFINITION)
    executed: list[str] = []
    monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: bind)
    monkeypatch.setattr(MIGRATION.op, "execute", lambda statement: executed.append(str(statement)))

    MIGRATION.upgrade()

    assert executed == []


def test_upgrade_creates_index_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    bind = _FakeBind(None)
    executed: list[str] = []
    monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: bind)
    monkeypatch.setattr(MIGRATION.op, "execute", lambda statement: executed.append(str(statement)))

    MIGRATION.upgrade()

    assert executed == [
        "CREATE EXTENSION IF NOT EXISTS vector",
        MIGRATION.EXPECTED_INDEX_DEFINITION,
    ]


def test_upgrade_rejects_existing_mismatched_index(monkeypatch: pytest.MonkeyPatch) -> None:
    bind = _FakeBind(
        "CREATE INDEX ix_document_chunks_embedding_cosine ON document_chunks USING btree (embedding)"
    )
    executed: list[str] = []
    monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: bind)
    monkeypatch.setattr(MIGRATION.op, "execute", lambda statement: executed.append(str(statement)))

    with pytest.raises(RuntimeError, match="unexpected definition"):
        MIGRATION.upgrade()

    assert executed == []


def test_downgrade_rejects_existing_mismatched_index(monkeypatch: pytest.MonkeyPatch) -> None:
    bind = _FakeBind(
        "CREATE INDEX ix_document_chunks_embedding_cosine ON document_chunks USING btree (embedding)"
    )
    executed: list[str] = []
    monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: bind)
    monkeypatch.setattr(MIGRATION.op, "execute", lambda statement: executed.append(str(statement)))

    with pytest.raises(RuntimeError, match="unexpected definition"):
        MIGRATION.downgrade()

    assert executed == []


# PostgreSQL 16 renders ``pg_indexes.indexdef`` with a schema-qualified table
# name and quoted ``WITH (lists='1')``. These cases lock in the normalisation
# that strips the ``current_schema()`` prefix so the fresh-PG upgrade/downgrade
# loop does not trip on the literal text difference.
PG16_INDEXDEF = (
    "CREATE INDEX ix_document_chunks_embedding_cosine "
    "ON public.document_chunks USING ivfflat (embedding vector_cosine_ops) "
    "WITH (lists='1')"
)


def test_upgrade_accepts_pg16_schema_qualified_index(monkeypatch: pytest.MonkeyPatch) -> None:
    bind = _FakeBind(PG16_INDEXDEF)
    executed: list[str] = []
    monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: bind)
    monkeypatch.setattr(MIGRATION.op, "execute", lambda statement: executed.append(str(statement)))

    MIGRATION.upgrade()

    assert executed == []


def test_downgrade_drops_pg16_schema_qualified_index(monkeypatch: pytest.MonkeyPatch) -> None:
    bind = _FakeBind(PG16_INDEXDEF)
    executed: list[str] = []
    monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: bind)
    monkeypatch.setattr(MIGRATION.op, "execute", lambda statement: executed.append(str(statement)))

    MIGRATION.downgrade()

    assert executed == [f"DROP INDEX IF EXISTS {MIGRATION.INDEX_NAME}"]


def test_pg16_schema_qualified_but_wrong_index_type_still_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind = _FakeBind(
        "CREATE INDEX ix_document_chunks_embedding_cosine "
        "ON public.document_chunks USING btree (embedding)"
    )
    executed: list[str] = []
    monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: bind)
    monkeypatch.setattr(MIGRATION.op, "execute", lambda statement: executed.append(str(statement)))

    with pytest.raises(RuntimeError, match="unexpected definition"):
        MIGRATION.upgrade()

    assert executed == []


def test_strip_schema_qualifier_only_affects_current_schema() -> None:
    actual = MIGRATION._strip_schema_qualifier(PG16_INDEXDEF, "public")
    assert "ON public.document_chunks" not in actual
    assert "ON document_chunks" in actual
    # A different schema must not be stripped (defensive: we never run into it
    # in practice because the query filters schemaname = current_schema()).
    other = MIGRATION._strip_schema_qualifier(PG16_INDEXDEF, "other_schema")
    assert other == PG16_INDEXDEF
