import json
import logging
import math
import random
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPMessage
from email.utils import parsedate_to_datetime
from typing import Any, IO
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.compliance import AI_DISCLAIMER
from app.core.config import settings
from app.db.models import BacktestRun, Fund
from app.repositories.fund_snapshots import active_snapshot_generation_expression
from app.repositories.llm_observability import (
    EventRecorder,
    LlmErrorCategory,
    LlmProviderEventData,
    LlmProviderOutcome,
    make_llm_event_recorder,
    sanitize_llm_label,
)
from app.repositories.rag import retrieve_document_chunks
from app.schemas.ai import ChatRequest, ChatResponse

BLOCKED_INTENTS = ["买入", "卖出", "必须", "短线", "预测收益", "保证收益", "目标价", "抄底", "逃顶"]
BLOCKED_OUTPUT_PATTERNS = (
    (
        "strong_trade_instruction",
        re.compile(r"(?:必须|立即|马上|应当|应该|建议)\s*(?:买入|卖出|加仓|减仓|清仓)"),
    ),
    (
        "deterministic_future_prediction",
        re.compile(
            r"(?:未来|明天|下周|下月)\S{0,12}(?:必然|一定|将会)\S{0,8}(?:上涨|下跌|收益|盈利)"
        ),
    ),
    (
        "market_timing_signal",
        re.compile(r"(?:买入点|卖出点|抄底|逃顶|目标价|短线信号)"),
    ),
    (
        "return_guarantee",
        re.compile(r"(?:保证|确保|承诺|必然|一定)\S{0,8}(?:收益|盈利|赚钱|回报)"),
    ),
)
SAFE_OUTPUT_REJECTION_REASONS = frozenset(reason for reason, _pattern in BLOCKED_OUTPUT_PATTERNS)
logger = logging.getLogger(__name__)
MAX_RETRY_DELAY_SECONDS = 2.0
MAX_RETRY_JITTER_SECONDS = 0.25
ALLOWED_LLM_BASE_URL_SCHEMES = {"http", "https"}


SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[\w.\-]+"), r"\1=[REDACTED]"),
    (re.compile(r"[\w.\-]+@[\w.\-]+\.\w+"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[REDACTED_PHONE]"),
    (re.compile(r"\b\d{15,19}\b"), "[REDACTED_NUMBER]"),
]


@dataclass
class LLMGateway:
    provider: str
    model: str

    def chat(self, db: Session, payload: ChatRequest) -> ChatResponse:
        blocked = [word for word in BLOCKED_INTENTS if word in payload.message]
        generation_id = active_snapshot_generation_expression()
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
        fund = (
            db.scalar(
                select(Fund)
                .where(
                    Fund.code == fund_code,
                    Fund.snapshot_generation_id == generation_id,
                )
                .options(joinedload(Fund.metrics))
            )
            if fund_code
            else None
        )
        if (
            fund is not None
            and fund.metrics is not None
            and fund.metrics.snapshot_generation_id == fund.snapshot_generation_id
        ):
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

        fund_count = (
            db.scalar(
                select(func.count())
                .select_from(Fund)
                .where(Fund.snapshot_generation_id == generation_id)
            )
            or 0
        )
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
            provider_conclusion = self._provider_conclusion(
                db=db,
                message=payload.message,
                evidence=[chunk.content for chunk in retrieved_chunks],
                data_date=data_date,
            )
            return ChatResponse(
                conclusion=provider_conclusion
                or "我检索到相关投教文档，可以基于这些材料解释问题，但不会给出收益预测或交易指令。",
                evidence=[chunk.content for chunk in retrieved_chunks],
                references=[
                    f"document_chunks:{chunk.chunk_id}:{chunk.document_title}:{chunk.source_uri}"
                    for chunk in retrieved_chunks
                ],
                risk="投教文档只能帮助理解概念和风险边界，不能替代个人风险测评、基金合同或专业适当性判断。",
                data_date=data_date,
                disclaimer=AI_DISCLAIMER,
            )

        provider_conclusion = self._provider_conclusion(
            db=db,
            message=payload.message,
            evidence=[
                f"当前可用基金数量：{fund_count}",
                f"数据源：{settings.fund_data_source}",
            ],
            data_date=data_date,
        )
        return ChatResponse(
            conclusion=provider_conclusion
            or "可以从历史收益、最大回撤、波动率、夏普比率、费用和风险等级六个维度解释基金或组合。",
            evidence=[
                f"当前可用基金数量：{fund_count}",
                f"数据源：{settings.fund_data_source}",
                "模型通道："
                f"{sanitize_llm_label(self.provider, max_length=64)}/"
                f"{sanitize_llm_label(self.model, max_length=128)}",
                f"用户问题：{payload.message}",
            ],
            references=["funds", "fund_metrics", "fund_navs"],
            risk="回答仅用于投教和历史数据解释，不提供收益预测或交易指令。",
            data_date=data_date,
            disclaimer=AI_DISCLAIMER,
        )

    def _latest_data_date(self, db: Session) -> str:
        generation_id = active_snapshot_generation_expression()
        latest = db.scalar(
            select(func.max(Fund.data_updated_at)).where(
                Fund.snapshot_generation_id == generation_id
            )
        )
        if latest is None:
            return datetime.now(timezone.utc).date().isoformat()
        return latest.date().isoformat()

    def _provider_conclusion(
        self,
        *,
        db: Session,
        message: str,
        evidence: list[str],
        data_date: str,
    ) -> str | None:
        if self.provider == "mock":
            return None
        client = LLMProviderClient(
            provider=self.provider,
            model=self.model,
            event_recorder=make_llm_event_recorder(db),
        )
        conclusion = client.generate_conclusion(
            message=message,
            evidence=evidence,
            data_date=data_date,
            output_rejection_reason=find_blocked_provider_output,
        )
        blocked_reason = find_blocked_provider_output(conclusion or "")
        if blocked_reason:
            logger.warning(
                "llm_provider_output_rejected",
                extra={
                    "provider": sanitize_llm_label(self.provider, max_length=64),
                    "model": sanitize_llm_label(self.model, max_length=128),
                    "reason": safe_output_rejection_reason(blocked_reason),
                },
            )
            return None
        return conclusion


@dataclass
class LLMProviderClient:
    provider: str
    model: str
    event_recorder: EventRecorder | None = None

    def generate_conclusion(
        self,
        *,
        message: str,
        evidence: list[str],
        data_date: str,
        output_rejection_reason: Callable[[str], str | None] | None = None,
    ) -> str | None:
        started_at = time.perf_counter()
        provider = self.provider.strip()
        model = self.model.strip()
        api_key = settings.llm_api_key.strip()
        base_url = settings.llm_base_url.strip()
        if not all((provider, model, api_key, base_url)):
            self._record_event(
                outcome="fallback",
                attempt_count=0,
                started_at=started_at,
                timed_out=False,
                error_category="config_missing",
            )
            return None

        prompt = (
            "你是基金投教助手。只能基于给定依据解释历史数据和概念；"
            "不得预测收益、不得给出买入卖出或短线择时指令。"
            f"\n数据日期：{data_date}"
            f"\n用户问题：{redact_sensitive_text(message)}"
            f"\n依据：{json.dumps([redact_sensitive_text(item) for item in evidence], ensure_ascii=False)}"
            "\n请用不超过120字中文回答，并保留风险提示。"
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "遵守中国基金投教合规边界，只做解释，不做建议。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            endpoint = llm_chat_completions_endpoint(base_url)
        except ValueError:
            self._record_event(
                outcome="fallback",
                attempt_count=0,
                started_at=started_at,
                timed_out=False,
                error_category="config_missing",
            )
            return None

        attempt_count = 0
        timed_out = False
        last_error_category: LlmErrorCategory | None = None
        for attempt in range(settings.llm_max_retries + 1):
            attempt_count = attempt + 1
            try:
                request = Request(
                    endpoint,
                    data=body,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with open_llm_provider_request(request, timeout=settings.llm_timeout_seconds) as response:
                    response_payload = json.loads(_read_provider_response_body(response).decode("utf-8"))
                raw_content = response_payload["choices"][0]["message"]["content"]
                if not isinstance(raw_content, str):
                    raise ValueError("provider content must be a string")
                stripped_content = raw_content.strip()
                if not stripped_content:
                    raise ValueError("provider content must not be blank")
                content = redact_sensitive_text(stripped_content)
                if len(content) > settings.llm_max_output_chars:
                    raise ValueError("provider content exceeds maximum output length")
            except Exception as exc:
                last_error_category = classify_provider_error(exc)
                timed_out = timed_out or last_error_category == "timeout"
                if attempt >= settings.llm_max_retries or not is_retryable_provider_error(
                    last_error_category
                ):
                    self._record_event(
                        outcome="fallback",
                        attempt_count=attempt_count,
                        started_at=started_at,
                        timed_out=timed_out,
                        error_category=last_error_category,
                    )
                    return None
                time.sleep(provider_retry_delay_seconds(exc, attempt=attempt))
                continue

            try:
                rejection_reason = (
                    output_rejection_reason(content)
                    if output_rejection_reason is not None
                    else None
                )
            except Exception:
                logger.warning(
                    "llm_provider_policy_callback_failed",
                    extra={
                        "provider": sanitize_llm_label(self.provider, max_length=64),
                        "model": sanitize_llm_label(self.model, max_length=128),
                    },
                )
                self._record_event(
                    outcome="fallback",
                    attempt_count=attempt_count,
                    started_at=started_at,
                    timed_out=timed_out,
                    error_category="policy_rejected",
                )
                return None
            if rejection_reason is not None:
                logger.warning(
                    "llm_provider_output_rejected",
                    extra={
                        "provider": sanitize_llm_label(self.provider, max_length=64),
                        "model": sanitize_llm_label(self.model, max_length=128),
                        "reason": safe_output_rejection_reason(rejection_reason),
                    },
                )
                self._record_event(
                    outcome="fallback",
                    attempt_count=attempt_count,
                    started_at=started_at,
                    timed_out=timed_out,
                    error_category="policy_rejected",
                )
                return None
            self._record_event(
                outcome="success",
                attempt_count=attempt_count,
                started_at=started_at,
                timed_out=timed_out,
                error_category=last_error_category,
            )
            return content
        return None

    def _record_event(
        self,
        *,
        outcome: LlmProviderOutcome,
        attempt_count: int,
        started_at: float,
        timed_out: bool,
        error_category: LlmErrorCategory | None,
    ) -> None:
        if not settings.llm_audit_enabled:
            return
        safe_provider = sanitize_llm_label(self.provider, max_length=64)
        safe_model = sanitize_llm_label(self.model, max_length=128)
        retry_count = max(0, attempt_count - 1)
        latency_ms = max(0, round((time.perf_counter() - started_at) * 1000))
        event = LlmProviderEventData(
            provider_name=safe_provider,
            model_name=safe_model,
            outcome=outcome,
            attempt_count=attempt_count,
            retry_count=retry_count,
            latency_ms=latency_ms,
            timed_out=timed_out,
            error_category=error_category,
        )
        if self.event_recorder is not None:
            try:
                self.event_recorder(event)
            except Exception:
                return


def classify_provider_error(exc: Exception) -> LlmErrorCategory:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, HTTPError):
        if exc.code in {408, 504}:
            return "timeout"
        if exc.code == 429:
            return "rate_limited"
        if 400 <= exc.code < 500:
            return "http_client"
        if 500 <= exc.code < 600:
            return "http_server"
        return "provider_error"
    if isinstance(exc, URLError):
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return "timeout"
        return "network"
    if isinstance(exc, (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError)):
        return "invalid_response"
    if isinstance(exc, OSError):
        return "network"
    return "provider_error"


def is_retryable_provider_error(category: LlmErrorCategory) -> bool:
    return category in {"timeout", "network", "rate_limited", "http_server"}


def _read_provider_response_body(response: Any) -> bytes:
    limit = settings.llm_max_response_bytes
    body = response.read(limit + 1)
    if not isinstance(body, bytes):
        raise ValueError("provider response body must be bytes")
    if len(body) > limit:
        raise ValueError("provider response body exceeds maximum size")
    return body


def llm_chat_completions_endpoint(base_url: str) -> str:
    normalized = _validated_llm_base_url(base_url)
    return normalized.rstrip("/") + "/chat/completions"


def _validated_llm_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme.lower() not in ALLOWED_LLM_BASE_URL_SCHEMES or not parsed.hostname:
        raise ValueError("LLM_BASE_URL must be an absolute http(s) URL with a host")
    if parsed.username or parsed.password:
        raise ValueError("LLM_BASE_URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("LLM_BASE_URL must not include query or fragment")
    if parsed.path.rstrip("/").endswith("/chat/completions"):
        raise ValueError("LLM_BASE_URL must be a service base URL, not a chat completions endpoint")
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    port = "" if parsed.port is None else f":{parsed.port}"
    path = parsed.path.rstrip("/")
    return f"{scheme}://{host}{port}{path}"


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    port = parsed.port
    default_port = (parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)
    port_suffix = "" if port is None or default_port else f":{port}"
    host = parsed.hostname.lower() if parsed.hostname else ""
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}{port_suffix}"


class SameOriginRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        if _origin(req.full_url) != _origin(newurl):
            raise URLError("cross-origin provider redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_llm_provider_request(request: Request, *, timeout: int) -> Any:
    return build_opener(SameOriginRedirectHandler).open(request, timeout=timeout)


def provider_retry_delay_seconds(exc: Exception, *, attempt: int) -> float:
    default_delay = min(float(2**attempt), MAX_RETRY_DELAY_SECONDS)
    retry_after_delay = _retry_after_delay_seconds(exc)
    base_delay = default_delay if retry_after_delay is None else min(retry_after_delay, MAX_RETRY_DELAY_SECONDS)
    jitter_limit = min(MAX_RETRY_JITTER_SECONDS, max(0.0, MAX_RETRY_DELAY_SECONDS - base_delay))
    if jitter_limit <= 0:
        return base_delay
    return min(base_delay + random.uniform(0.0, jitter_limit), MAX_RETRY_DELAY_SECONDS)


def _retry_after_delay_seconds(exc: Exception) -> float | None:
    if not isinstance(exc, HTTPError) or exc.headers is None or exc.code not in {429, 503}:
        return None
    retry_after = exc.headers.get("Retry-After")
    if retry_after is None:
        return None
    try:
        parsed_delay = float(retry_after)
    except ValueError:
        pass
    else:
        if math.isfinite(parsed_delay) and parsed_delay >= 0:
            return parsed_delay
    try:
        parsed_at = parsedate_to_datetime(retry_after)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed_at.tzinfo is None:
        parsed_at = parsed_at.replace(tzinfo=timezone.utc)
    else:
        parsed_at = parsed_at.astimezone(timezone.utc)
    delay = (parsed_at - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delay)


def redact_sensitive_text(value: str) -> str:
    redacted = value
    for pattern, replacement in SENSITIVE_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def find_blocked_provider_output(value: str) -> str | None:
    for reason, pattern in BLOCKED_OUTPUT_PATTERNS:
        if pattern.search(value):
            return reason
    return None


def safe_output_rejection_reason(value: object) -> str:
    if isinstance(value, str) and value in SAFE_OUTPUT_REJECTION_REASONS:
        return value
    return "policy_rejected"


def get_llm_gateway() -> LLMGateway:
    return LLMGateway(
        provider=settings.llm_provider.strip(),
        model=settings.llm_model.strip(),
    )
