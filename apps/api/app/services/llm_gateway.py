from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.compliance import AI_DISCLAIMER
from app.core.config import settings
from app.db.models import BacktestRun, Fund
from app.repositories.rag import retrieve_document_chunks
from app.schemas.ai import ChatRequest, ChatResponse

BLOCKED_INTENTS = ["买入", "卖出", "必须", "短线", "预测收益", "保证收益", "目标价", "抄底", "逃顶"]


@dataclass
class LLMGateway:
    provider: str
    model: str

    def chat(self, db: Session, payload: ChatRequest) -> ChatResponse:
        blocked = [word for word in BLOCKED_INTENTS if word in payload.message]
        data_date = self._latest_data_date(db)
        if blocked:
            return ChatResponse(
                conclusion="这个问题涉及预测或交易指令，我不能给出买卖建议。",
                evidence=["合规边界禁止预测收益、短线买卖点和强交易指令。"],
                references=[],
                risk="可以改问基金指标含义、历史回撤来源、组合风险暴露或回测历史局限。",
                data_date=data_date,
                disclaimer=AI_DISCLAIMER,
                unable_to_answer=True,
            )

        fund_code = str(payload.context.get("fund_code") or "")
        fund = db.get(Fund, fund_code) if fund_code else None
        if fund is not None and fund.metrics is not None:
            return ChatResponse(
                conclusion=(
                    f"{fund.name} 的历史表现需要同时看收益、回撤、夏普和费用。"
                    f"当前样本中 3 年年化为 {fund.metrics.annualized_return_3y:.2f}%，"
                    f"最大回撤为 {fund.metrics.max_drawdown:.2f}%。"
                ),
                evidence=[
                    f"基金代码：{fund.code}",
                    f"风险等级：{fund.risk_level}",
                    f"夏普比率：{fund.metrics.sharpe_ratio:.2f}",
                    f"费用合计：{fund.management_fee + fund.custody_fee:.2f}%",
                ],
                references=[f"funds:{fund.code}", f"fund_metrics:{fund.code}"],
                risk="历史指标只能说明样本区间内的风险收益特征，不能外推为未来表现。",
                data_date=fund.data_updated_at.date().isoformat(),
                disclaimer=AI_DISCLAIMER,
            )

        backtest_id = str(payload.context.get("backtest_id") or "")
        backtest = db.get(BacktestRun, backtest_id) if backtest_id else None
        if backtest is not None:
            result = backtest.result_snapshot
            points = result.get("points") or []
            return ChatResponse(
                conclusion=(
                    "这次回测只能解释历史区间内的策略表现。"
                    f"样本结果显示年化收益 {backtest.annualized_return:.2f}%，"
                    f"最大回撤 {backtest.max_drawdown:.2f}%，波动率 {backtest.volatility:.2f}%。"
                ),
                evidence=[
                    f"回测 ID：{backtest.id}",
                    f"策略类型：{backtest.strategy_type}",
                    f"投入金额：{result.get('total_invested', 0):.2f}",
                    f"期末市值：{result.get('final_value', 0):.2f}",
                    f"曲线点数：{len(points)}",
                ],
                references=[f"backtest_runs:{backtest.id}", "fund_navs"],
                risk="历史表现不预示未来收益；当前结果受样本净值频率、标的选择和区间起止日期影响，不应作为交易指令。",
                data_date=backtest.created_at.date().isoformat(),
                disclaimer=AI_DISCLAIMER,
            )

        fund_count = db.scalar(select(func.count()).select_from(Fund)) or 0
        if fund_count == 0:
            return ChatResponse(
                conclusion="当前数据库没有可引用的基金数据，暂时无法完成分析。",
                evidence=["fund_count=0"],
                references=[],
                risk="请先完成数据同步或导入基金样本后再提问。",
                data_date=data_date,
                disclaimer=AI_DISCLAIMER,
                unable_to_answer=True,
            )

        retrieved_chunks = retrieve_document_chunks(db, payload.message, limit=3)
        if retrieved_chunks:
            return ChatResponse(
                conclusion="我检索到相关投教文档，可以基于这些材料解释问题，但不会给出收益预测或交易指令。",
                evidence=[chunk.content for chunk in retrieved_chunks],
                references=[
                    f"document_chunks:{chunk.chunk_id}:{chunk.document_title}:{chunk.source_uri}"
                    for chunk in retrieved_chunks
                ],
                risk="投教文档只能帮助理解概念和风险边界，不能替代个人风险测评、基金合同或专业适当性判断。",
                data_date=data_date,
                disclaimer=AI_DISCLAIMER,
            )

        return ChatResponse(
            conclusion="可以从历史收益、最大回撤、波动率、夏普比率、费用和风险等级六个维度解释基金或组合。",
            evidence=[
                f"当前可用基金数量：{fund_count}",
                f"数据源：{settings.fund_data_source}",
                f"模型通道：{self.provider}/{self.model}",
                f"用户问题：{payload.message}",
            ],
            references=["funds", "fund_metrics", "fund_navs"],
            risk="回答仅用于投教和历史数据解释，不提供收益预测或交易指令。",
            data_date=data_date,
            disclaimer=AI_DISCLAIMER,
        )

    def _latest_data_date(self, db: Session) -> str:
        latest = db.scalar(select(func.max(Fund.data_updated_at)))
        if latest is None:
            return datetime.now(timezone.utc).date().isoformat()
        return latest.date().isoformat()


def get_llm_gateway() -> LLMGateway:
    return LLMGateway(provider=settings.llm_provider, model=settings.llm_model)
