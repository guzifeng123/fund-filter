import json
from typing import Any

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import TypeDecorator, UserDefinedType


class PgVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dimensions})"


@compiles(PgVector, "sqlite")
def _compile_pg_vector_sqlite(type_: PgVector, compiler, **kw: Any) -> str:
    return "JSON"


@compiles(PgVector, "postgresql")
def _compile_pg_vector_postgresql(type_: PgVector, compiler, **kw: Any) -> str:
    return f"vector({type_.dimensions})"


class VectorList(TypeDecorator[list[float]]):
    impl = PgVector
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        super().__init__(dimensions)

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(PgVector(self.dimensions))

    def process_bind_param(self, value: list[float] | None, dialect) -> str | None:
        if value is None:
            return None
        if len(value) != self.dimensions:
            raise ValueError(f"expected vector with {self.dimensions} dimensions, got {len(value)}")
        if dialect.name == "postgresql":
            return "[" + ",".join(str(float(item)) for item in value) + "]"
        return json.dumps([float(item) for item in value])

    def process_result_value(self, value: Any, dialect) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(item) for item in value]
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned.startswith("[") and cleaned.endswith("]"):
                return [float(item) for item in json.loads(cleaned)]
        return [float(item) for item in value]
