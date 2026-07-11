from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import AiMessage, AiThread
from app.schemas.ai import AiMessageSchema, AiThreadDetail, AiThreadSummary, ChatResponse


def _thread_summary(row: AiThread) -> AiThreadSummary:
    return AiThreadSummary(
        id=row.id,
        title=row.title,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _message_schema(row: AiMessage) -> AiMessageSchema:
    return AiMessageSchema(
        id=row.id,
        role=row.role,
        content=row.content,
        created_at=row.created_at.isoformat(),
        payload=row.payload,
    )


def ensure_thread(db: Session, message: str, thread_id: str | None = None, user_id: str = "local-user") -> AiThread:
    if thread_id:
        existing = db.get(AiThread, thread_id)
        if existing is not None:
            return existing
    title = message.strip()[:40] or "新的 AI 对话"
    row = AiThread(id=f"ai_{uuid4().hex[:12]}", user_id=user_id, title=title)
    db.add(row)
    db.flush()
    return row


def add_message(db: Session, thread_id: str, role: str, content: str, payload: dict) -> AiMessage:
    row = AiMessage(thread_id=thread_id, role=role, content=content, payload=payload)
    db.add(row)
    return row


def save_chat_turn(db: Session, message: str, response: ChatResponse, thread_id: str | None = None) -> ChatResponse:
    thread = ensure_thread(db, message, thread_id)
    add_message(db, thread.id, "user", message, {"message": message})
    response.thread_id = thread.id
    add_message(db, thread.id, "assistant", response.conclusion, response.model_dump())
    db.commit()
    return response


def list_threads(db: Session, user_id: str = "local-user") -> list[AiThreadSummary]:
    rows = db.scalars(
        select(AiThread)
        .where(AiThread.user_id == user_id)
        .order_by(desc(AiThread.updated_at), desc(AiThread.created_at))
    ).all()
    return [_thread_summary(row) for row in rows]


def get_thread(db: Session, thread_id: str) -> AiThreadDetail | None:
    row = db.scalars(
        select(AiThread).where(AiThread.id == thread_id).options(joinedload(AiThread.messages))
    ).unique().first()
    if row is None:
        return None
    summary = _thread_summary(row)
    return AiThreadDetail(**summary.model_dump(), messages=[_message_schema(message) for message in row.messages])
