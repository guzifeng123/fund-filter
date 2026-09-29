import json
from typing import Any

from sqlalchemy.engine import Dialect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import TypeCompiler
from sqlalchemy.types import TypeDecorator, TypeEngine, UserDefinedType


class PgVector(UserDefinedType[str]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dimensions})"


@compiles(PgVector, "sqlite")
def _compile_pg_vector_sqlite(
    type_: PgVector, compiler: TypeCompiler, **kw: Any
) -> str:
    return "JSON"


@compiles(PgVector, "postgresql")
def _compile_pg_vector_postgresql(
    type_: PgVector, compiler: TypeCompiler, **kw: Any
) -> str:
    return f"vector({type_.dimensions})"


class VectorList(TypeDecorator[list[float]]):
    impl = PgVector
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        super().__init__(dimensions)

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[str]:
        return dialect.type_descriptor(PgVector(self.dimensions))

    def process_bind_param(
        self, value: list[float] | None, dialect: Dialect
    ) -> str | None:
        if value is None:
            return None
        if len(value) != self.dimensions:
            raise ValueError(f"expected vector with {self.dimensions} dimensions, got {len(value)}")
        if dialect.name == "postgresql":
            return "[" + ",".join(str(float(item)) for item in value) + "]"
        return json.dumps([float(item) for item in value])

    def process_result_value(
        self, value: Any, dialect: Dialect
    ) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(item) for item in value]
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned.startswith("[") and cleaned.endswith("]"):
                return [float(item) for item in json.loads(cleaned)]
        return [float(item) for item in value]
