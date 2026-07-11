from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk
from app.repositories.rag import chunk_text, ingest_document, retrieve_document_chunks
from app.schemas.ai import ChatRequest
from app.services.llm_gateway import LLMGateway


def test_chunk_text_splits_long_documents() -> None:
    chunks = chunk_text("第一段风险说明。\n\n第二段" + "很长" * 400, max_chars=120)

    assert len(chunks) > 1
    assert chunks[0] == "第一段风险说明。"


def test_ingest_document_replaces_chunks_idempotently(db_session: Session) -> None:
    document = ingest_document(
        db_session,
        title="风险投教",
        source_uri="local://risk-education",
        content="风险承受能力用于判断产品风险等级是否匹配。\n\n" + "历史收益不代表未来收益。" * 120,
    )
    db_session.commit()
    first_chunk_count = len(document.chunks)

    updated = ingest_document(
        db_session,
        title="风险投教",
        source_uri="local://risk-education",
        content="风险承受能力用于判断产品风险等级是否匹配。",
    )
    db_session.commit()

    assert updated.id == document.id
    assert db_session.scalar(select(Document).where(Document.source_uri == "local://risk-education")) is not None
    assert db_session.query(DocumentChunk).filter_by(document_id=document.id).count() == 1
    assert first_chunk_count > 1


def test_retrieve_document_chunks_returns_references(db_session: Session) -> None:
    document = ingest_document(
        db_session,
        title="回撤解释",
        source_uri="local://drawdown",
        content="最大回撤表示历史区间从高点到低点的最大跌幅，适合衡量波动冲击。",
    )
    db_session.commit()

    results = retrieve_document_chunks(db_session, "最大回撤是什么意思", limit=1)

    assert len(results) == 1
    assert results[0].document_id == document.id
    assert results[0].document_title == "回撤解释"
    assert "最大回撤" in results[0].content


def test_llm_gateway_uses_rag_documents_for_general_questions(db_session: Session) -> None:
    ingest_document(
        db_session,
        title="夏普比率投教",
        source_uri="local://sharpe",
        content="夏普比率衡量单位波动对应的历史超额收益，应结合回撤和费用一起理解。",
    )
    db_session.commit()

    response = LLMGateway(provider="mock", model="mock").chat(
        db_session,
        ChatRequest(message="夏普比率应该怎么理解？", context={}),
    )

    assert response.unable_to_answer is False
    assert "投教文档" in response.conclusion
    assert any("夏普比率" in item for item in response.evidence)
    assert response.references[0].startswith("document_chunks:")
