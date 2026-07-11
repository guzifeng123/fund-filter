from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Fund, FundMetric, FundNav
from app.repositories.backtests import create_backtest_run
from app.schemas.ai import ChatRequest
from app.schemas.backtest import BacktestRequest
from app.services.llm_gateway import LLMGateway


def test_gateway_explains_fund_context(db_session: Session) -> None:
    response = LLMGateway(provider="mock", model="test").chat(
        db_session,
        ChatRequest(message="解释基金指标", context={"fund_code": "000001"}),
    )

    assert response.unable_to_answer is False
    assert "funds:000001" in response.references
    assert any("夏普比率" in item for item in response.evidence)
    assert "不构成投资建议" in response.disclaimer


def test_gateway_blocks_directive_trading_language(db_session: Session) -> None:
    response = LLMGateway(provider="mock", model="test").chat(
        db_session,
        ChatRequest(message="这只基金明天必须买入吗", context={"fund_code": "000001"}),
    )

    assert response.unable_to_answer is True
    assert response.references == []
    assert "不能给出买卖建议" in response.conclusion
    assert "强交易指令" in response.evidence[0]


def test_gateway_explains_backtest_context_with_history_limits(db_session: Session) -> None:
    backtest = create_backtest_run(
        db_session,
        BacktestRequest(
            strategy_type="template_portfolio",
            template_key="balanced",
            fund_codes=["000001", "000002"],
            amount=1000,
            start="2021",
            end="2026",
        ),
    )

    response = LLMGateway(provider="mock", model="test").chat(
        db_session,
        ChatRequest(message="解释这次回测", context={"backtest_id": backtest.id}),
    )

    assert response.unable_to_answer is False
    assert f"backtest_runs:{backtest.id}" in response.references
    assert "历史表现不预示未来收益" in response.risk
    assert any("曲线点数" in item for item in response.evidence)


def test_gateway_reports_insufficient_data(db_session: Session) -> None:
    db_session.execute(delete(FundNav))
    db_session.execute(delete(FundMetric))
    db_session.execute(delete(Fund))
    db_session.commit()

    response = LLMGateway(provider="mock", model="test").chat(
        db_session,
        ChatRequest(message="解释基金指标", context={}),
    )

    assert response.unable_to_answer is True
    assert response.evidence == ["fund_count=0"]
    assert "数据同步" in response.risk
