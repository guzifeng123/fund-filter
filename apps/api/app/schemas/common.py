from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiMeta(BaseModel):
    source: str
    data_updated_at: str
    disclaimer: str
    pagination: dict[str, int] | None = None


class ApiResponse(BaseModel, Generic[T]):
    data: T
    meta: ApiMeta


class ApiError(BaseModel):
    code: str
    message: str
    detail: Any | None = None


class ApiErrorResponse(BaseModel):
    error: ApiError
    meta: ApiMeta
