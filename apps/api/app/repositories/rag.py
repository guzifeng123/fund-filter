from dataclasses import dataclass
import hashlib
import math
import re
from uuid import uuid5, NAMESPACE_URL

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Document, DocumentChunk

EMBEDDING_DIMENSIONS = 16


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: str
    document_title: str
    source_uri: str
    chunk_id: int
    chunk_index: int
    content: str
    score: float


def chunk_text(content: str, max_chars: int = 600) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", content) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [content.strip()]:
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(paragraph[index : index + max_chars] for index in range(0, len(paragraph), max_chars))
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def embed_text(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    buckets = [0.0 for _ in range(dimensions)]
    for token in re.findall(r"[\w\u4e00-\u9fff]+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = digest[0] % dimensions
        buckets[bucket] += 1.0 + digest[1] / 255
    norm = math.sqrt(sum(value * value for value in buckets))
    if norm == 0:
        return buckets
    return [round(value / norm, 8) for value in buckets]


def ingest_document(
    db: Session,
    *,
    title: str,
    source_uri: str,
    content: str,
    document_type: str = "education",
    metadata: dict | None = None,
) -> Document:
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("document content cannot be empty")
    content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    document_id = str(uuid5(NAMESPACE_URL, source_uri))
    document = db.get(Document, document_id)
    if document is None:
        document = Document(id=document_id, source_uri=source_uri)
        db.add(document)
    document.title = title
    document.document_type = document_type
    document.content_hash = content_hash
    document.metadata_ = metadata or {}
    if document.id:
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
        db.flush()
    document.chunks = []
    for index, chunk in enumerate(chunk_text(normalized_content)):
        document.chunks.append(
            DocumentChunk(
                chunk_index=index,
                content=chunk,
                embedding=embed_text(chunk),
                metadata_={"content_hash": content_hash},
            )
        )
    db.flush()
    return document


def retrieve_document_chunks(db: Session, query: str, limit: int = 3) -> list[RetrievedChunk]:
    query_embedding = embed_text(query)
    rows = db.scalars(
        select(DocumentChunk).options(selectinload(DocumentChunk.document)).order_by(DocumentChunk.id)
    ).all()
    scored: list[RetrievedChunk] = []
    for row in rows:
        score = _cosine_similarity(query_embedding, row.embedding)
        lexical_overlap = _lexical_overlap(query, row.content)
        score += lexical_overlap * 0.05
        scored.append(
            RetrievedChunk(
                document_id=row.document_id,
                document_title=row.document.title,
                source_uri=row.document.source_uri,
                chunk_id=row.id,
                chunk_index=row.chunk_index,
                content=row.content,
                score=round(score, 6),
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:limit]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))


def _lexical_overlap(query: str, content: str) -> int:
    query_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
    content_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", content.lower()))
    return len(query_terms & content_terms)
