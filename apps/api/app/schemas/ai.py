from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    thread_id: str | None = None
    message: str
    context: dict[str, Any] = {}


class ChatResponse(BaseModel):
    thread_id: str | None = None
    conclusion: str
    evidence: list[str]
    references: list[str] = []
    risk: str
    data_date: str
    disclaimer: str
    unable_to_answer: bool = False


class AiMessageSchema(BaseModel):
    id: int
    role: str
    content: str
    created_at: str
    payload: dict[str, Any]


class AiThreadSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class AiThreadDetail(AiThreadSummary):
    messages: list[AiMessageSchema]
