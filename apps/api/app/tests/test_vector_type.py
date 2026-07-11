import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

from app.db.vector import VectorList


def test_vector_list_compiles_to_pgvector_for_postgresql() -> None:
    column = sa.Column("embedding", VectorList(16), nullable=False)

    ddl = str(sa.schema.CreateColumn(column).compile(dialect=postgresql.dialect()))

    assert "embedding vector(16)" in ddl


def test_vector_list_uses_json_storage_for_sqlite() -> None:
    column = sa.Column("embedding", VectorList(16), nullable=False)

    ddl = str(sa.schema.CreateColumn(column).compile(dialect=sqlite.dialect()))

    assert "embedding JSON" in ddl


def test_vector_list_validates_dimensions() -> None:
    vector_type = VectorList(3)

    with pytest.raises(ValueError, match="expected vector with 3 dimensions"):
        vector_type.process_bind_param([1.0, 2.0], sqlite.dialect())
