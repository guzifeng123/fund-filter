import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings as config_settings
from app.db.models import Fund, FundMetric, FundNav
from app.repositories.backtests import create_backtest_run
from app.schemas.ai import ChatRequest
from app.schemas.backtest import BacktestRequest
from app.services.llm_gateway import (
    LLMGateway,
    LLMProviderClient,
    find_blocked_provider_output,
    redact_sensitive_text,
)


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


def test_gateway_redacts_sensitive_text() -> None:
    redacted = redact_sensitive_text("api_key=sk-test password=secret 13800138000 user@example.com")

    assert "sk-test" not in redacted
    assert "secret" not in redacted
    assert "13800138000" not in redacted
    assert "user@example.com" not in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_real_provider_missing_config_falls_back(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_settings, "llm_base_url", "")
    monkeypatch.setattr(config_settings, "llm_api_key", "")

    response = LLMGateway(provider="openai_compatible", model="test").chat(
        db_session,
        ChatRequest(message="解释基金指标", context={}),
    )

    assert response.unable_to_answer is False
    assert "历史收益" in response.conclusion


@pytest.mark.parametrize(
    ("unsafe_output", "reason"),
    (
        ("你必须立即买入这只基金。", "strong_trade_instruction"),
        ("这个产品保证获得稳定收益。", "return_guarantee"),
        ("当前就是最佳抄底时机。", "market_timing_signal"),
        ("明天一定会上涨并带来收益。", "deterministic_future_prediction"),
    ),
)
def test_provider_output_guardrail_detects_prohibited_content(
    unsafe_output: str,
    reason: str,
) -> None:
    assert find_blocked_provider_output(unsafe_output) == reason


def test_gateway_discards_unsafe_provider_output_and_uses_compliant_fallback(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LLMProviderClient,
        "generate_conclusion",
        lambda *_args, **_kwargs: "你必须立即买入，保证获得收益。",
    )

    response = LLMGateway(provider="openai_compatible", model="test").chat(
        db_session,
        ChatRequest(message="解释当前基金数据", context={}),
    )

    assert "必须立即买入" not in response.conclusion
    assert "保证获得收益" not in response.conclusion
    assert "历史收益" in response.conclusion
    assert "不构成投资建议" in response.disclaimer
