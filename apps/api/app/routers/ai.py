import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.compliance import envelope, meta
from app.db.session import get_db
from app.repositories.ai_threads import get_thread, list_threads, save_chat_turn
from app.repositories.funds import fund_data_source_summary, latest_fund_data_updated_at
from app.schemas.ai import AiThreadDetail, AiThreadSummary, ChatRequest, ChatResponse
from app.schemas.common import ApiErrorResponse, ApiResponse
from app.services.llm_gateway import get_llm_gateway

router = APIRouter()


@router.post("/chat", response_model=ApiResponse[ChatResponse])
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    response: ChatResponse = get_llm_gateway().chat(db, payload)
    return envelope(
        save_chat_turn(db, payload.message, response, payload.thread_id),
        source=fund_data_source_summary(db),
        data_updated_at=latest_fund_data_updated_at(db),
    )


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-sent chat chunks followed by the final structured response.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    response: ChatResponse = save_chat_turn(db, payload.message, get_llm_gateway().chat(db, payload), payload.thread_id)
    response_meta = meta(
        source=fund_data_source_summary(db),
        data_updated_at=latest_fund_data_updated_at(db),
    )

    def events() -> Iterator[str]:
        for chunk in [response.conclusion, *response.evidence, response.risk]:
            yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True, 'response': response.model_dump(), 'meta': response_meta}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/threads", response_model=ApiResponse[list[AiThreadSummary]])
def threads(db: Session = Depends(get_db)) -> dict[str, Any]:
    return envelope(list_threads(db), source="database")


@router.get(
    "/threads/{thread_id}",
    response_model=ApiResponse[AiThreadDetail],
    responses={404: {"model": ApiErrorResponse}},
)
def thread(thread_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = get_thread(db, thread_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "AI_THREAD_NOT_FOUND", "message": "未找到指定 AI 对话"})
    return envelope(result, source="database")
