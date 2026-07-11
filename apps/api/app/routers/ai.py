import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.compliance import envelope
from app.db.session import get_db
from app.repositories.ai_threads import get_thread, list_threads, save_chat_turn
from app.schemas.ai import ChatRequest, ChatResponse
from app.services.llm_gateway import get_llm_gateway

router = APIRouter()


@router.post("/chat")
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    response: ChatResponse = get_llm_gateway().chat(db, payload)
    return envelope(save_chat_turn(db, payload.message, response, payload.thread_id))


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    response: ChatResponse = save_chat_turn(db, payload.message, get_llm_gateway().chat(db, payload), payload.thread_id)

    def events():
        for chunk in [response.conclusion, *response.evidence, response.risk]:
            yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True, 'response': response.model_dump()}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/threads")
def threads(db: Session = Depends(get_db)):
    return envelope(list_threads(db))


@router.get("/threads/{thread_id}")
def thread(thread_id: str, db: Session = Depends(get_db)):
    result = get_thread(db, thread_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "AI_THREAD_NOT_FOUND", "message": "未找到指定 AI 对话"})
    return envelope(result)
