from fastapi.testclient import TestClient
from datetime import datetime, timezone
import time

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.compliance import is_risk_matched
from app.core.config import settings
from app.db.models import AiMessage, AiThread, BacktestRun, Fund, FundMetric, FundNav, JobRun, RiskAssessment
from app.db.session import get_db
from app.jobs.seed_sample_data import seed_sample_data
from app.jobs.sync_fund_data import calculate_metrics, sync_fund_navs, sync_fund_profiles, sync_risk_levels
from app.jobs.scheduler import start_scheduler
from app.main import app
from app.repositories.data_status import get_data_status
from app.routers.data import get_data_status_reader
from app.repositories.funds import compare_funds
from app.schemas.funds import FundFilterRequest
from app.schemas.backtest import BacktestRequest
from app.services.backtest_service import run_backtest
from app.services.fund_service import filter_funds
from app.schemas.portfolio import PortfolioCreateRequest, PortfolioPositionRequest
from app.services.portfolio_service import create as create_portfolio
from app.services.portfolio_service import rebalance_preview


def make_client(db_session: Session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_data_status_reader] = lambda: lambda: get_data_status(db_session)
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_risk_profile_matching() -> None:
    assert is_risk_matched("C3", "R3")
    assert not is_risk_matched("C3", "R4")


def test_filter_excludes_over_risk_funds(db_session: Session) -> None:
    result = filter_funds(
        db_session,
        FundFilterRequest(
            risk_profile="C2",
            fund_types=["mixed", "bond", "stock"],
            min_years=3,
            size_range=(10, 100),
            return_rank_percentile=30,
            max_drawdown_lte_category_avg=True,
            sharpe_gte=1.2,
            fee_lte=1.5,
        )
    )
    assert all(fund.risk_level in {"R1", "R2"} for fund in result)


def test_filter_reads_database_not_sample_constants(db_session: Session) -> None:
    fund = db_session.get(Fund, "000002")
    assert fund is not None
    metric = db_session.get(FundMetric, "000002")
    assert metric is not None
    fund.risk_level = "R4"
    metric.sharpe_ratio = 9.9
    db_session.commit()

    result = filter_funds(
        db_session,
        FundFilterRequest(
            risk_profile="C2",
            fund_types=["bond"],
            min_years=3,
            size_range=(10, 100),
            return_rank_percentile=30,
            max_drawdown_lte_category_avg=True,
            sharpe_gte=1.2,
            fee_lte=1.5,
        ),
    )
    assert all(fund.code != "000002" for fund in result)


def test_compare_limits_to_five_codes(db_session: Session) -> None:
    result = compare_funds(db_session, ["000004", "000003", "000002", "000001", "missing", "ignored"])
    assert [fund.code for fund in result] == ["000004", "000003", "000002", "000001"]


def test_data_status_counts_seeded_rows(db_session: Session) -> None:
    db_session.add(JobRun(name="seed_sample_data", status="success", details={}))
    db_session.commit()

    status = get_data_status(db_session)

    assert status.db_connected
    assert status.fund_count == db_session.scalar(select(func.count()).select_from(Fund))
    assert status.nav_count == db_session.scalar(select(func.count()).select_from(FundNav))
    assert status.freshness_status == "fresh"
    assert status.stale_after_days == 7
    assert status.last_job is not None
    assert status.last_job.name == "seed_sample_data"


def test_seed_sample_data_is_idempotent(db_session: Session) -> None:
    seed_sample_data(db_session)
    seed_sample_data(db_session)

    assert db_session.scalar(select(func.count()).select_from(Fund)) == 4
    assert db_session.scalar(select(func.count()).select_from(FundNav)) == 24
    assert db_session.scalar(select(func.count()).select_from(FundMetric)) == 4
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 4


def test_sample_data_source_sync_jobs_are_idempotent_and_record_job_runs(db_session: Session) -> None:
    db_session.execute(delete(FundNav))
    db_session.execute(delete(FundMetric))
    db_session.execute(delete(Fund))
    db_session.commit()

    sync_fund_profiles(db_session, "sample_local")
    sync_fund_profiles(db_session, "sample_local")
    sync_fund_navs(db_session, "sample_local")
    calculate_metrics(db_session, "sample_local")
    sync_risk_levels(db_session, "sample_local")

    assert db_session.scalar(select(func.count()).select_from(Fund)) == 4
    assert db_session.scalar(select(func.count()).select_from(FundNav)) == 24
    assert db_session.scalar(select(func.count()).select_from(FundMetric)) == 4
    job_names = [row.name for row in db_session.scalars(select(JobRun).order_by(JobRun.id)).all()]
    assert job_names == [
        "sync_fund_profiles",
        "sync_fund_profiles",
        "sync_fund_navs",
        "calculate_metrics",
        "sync_risk_levels",
    ]
    assert all(row.status == "success" for row in db_session.scalars(select(JobRun)).all())


def test_manual_sync_api_runs_selected_task_and_scheduler_defaults_off(db_session: Session) -> None:
    assert start_scheduler() is None
    try:
        client = make_client(db_session)
        response = client.post("/api/data/sync", params={"task": "profiles"})
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert body["data"]["task"] == "profiles"
    assert body["data"]["result"]["fund_count"] == 4
    latest_job = db_session.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(1)).first()
    assert latest_job is not None
    assert latest_job.name == "sync_fund_profiles"
    assert latest_job.status == "success"


def test_fund_filter_api_route_uses_database(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.post(
            "/api/funds/filter",
            json={
                "risk_profile": "C2",
                "fund_types": ["mixed", "bond", "stock"],
                "min_years": 3,
                "size_range": [10, 100],
                "return_rank_percentile": 30,
                "max_drawdown_lte_category_avg": True,
                "sharpe_gte": 1.2,
                "fee_lte": 1.5,
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert "data" in response.json()
    assert all(item["risk_level"] in {"R1", "R2"} for item in response.json()["data"])


def test_data_status_api_envelope(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.get("/api/data/status")
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert body["data"]["db_connected"] is True
    assert body["data"]["fund_count"] == 4
    assert body["data"]["freshness_status"] == "fresh"
    assert "meta" in body


def test_data_status_api_degrades_when_database_is_unavailable() -> None:
    def unavailable_reader():
        raise SQLAlchemyError("database unavailable")

    app.dependency_overrides[get_data_status_reader] = lambda: unavailable_reader
    try:
        client = TestClient(app)
        response = client.get("/api/data/status")
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert body["data"] == {
        "db_connected": False,
        "fund_count": 0,
        "nav_count": 0,
        "latest_data_updated_at": None,
        "freshness_status": "empty",
        "stale_after_days": 7,
        "last_job": None,
    }
    assert "meta" in body


def test_data_status_api_abandons_a_slow_database_check(monkeypatch) -> None:
    def slow_reader():
        time.sleep(0.3)
        raise SQLAlchemyError("late database failure")

    monkeypatch.setattr(settings, "data_status_timeout_seconds", 0.05)
    app.dependency_overrides[get_data_status_reader] = lambda: slow_reader
    started_at = time.perf_counter()
    try:
        response = TestClient(app).get("/api/data/status")
    finally:
        clear_overrides()
    elapsed = time.perf_counter() - started_at

    assert response.status_code == 200
    assert response.json()["data"]["db_connected"] is False
    assert elapsed < 0.2


def test_data_status_reports_empty_failed_and_stale_states(db_session: Session) -> None:
    db_session.execute(delete(FundNav))
    db_session.commit()
    assert get_data_status(db_session).freshness_status == "empty"

    for fund in db_session.scalars(select(Fund)).all():
        fund.data_updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db_session.add(
            FundNav(
                fund_code=fund.code,
                trade_date="2020",
                nav=1.0,
                accumulated_nav=1.0,
                raw_data={},
            )
        )
    db_session.commit()
    assert get_data_status(db_session).freshness_status == "stale"

    db_session.add(
        JobRun(
            name="sync_fund_navs",
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            details={"error": "source timeout"},
        )
    )
    db_session.commit()
    status = get_data_status(db_session)
    assert status.freshness_status == "failed"
    assert status.last_job is not None
    assert status.last_job.error_detail == "source timeout"


def test_recent_job_runs_api_exposes_status_and_error_detail(db_session: Session) -> None:
    db_session.add(
        JobRun(
            name="sync_fund_profiles",
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            details={"error": "bad upstream payload"},
        )
    )
    db_session.commit()

    try:
        client = make_client(db_session)
        response = client.get("/api/data/jobs/recent", params={"limit": 1})
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert body["data"][0]["name"] == "sync_fund_profiles"
    assert body["data"][0]["status"] == "failed"
    assert body["data"][0]["error_detail"] == "bad upstream payload"


def test_search_api_supports_pagination_filters_and_sort(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.get(
            "/api/funds/search",
            params=[
                ("page", "1"),
                ("page_size", "1"),
                ("fund_type", "mixed"),
                ("risk_level", "R3"),
                ("sort_by", "annualized_return_3y"),
                ("sort_order", "desc"),
            ],
        )
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert len(body["data"]) == 1
    assert body["data"][0]["fund_type"] == "mixed"
    assert body["data"][0]["risk_level"] == "R3"
    assert body["meta"]["pagination"] == {"page": 1, "page_size": 1, "total": 1}
    assert body["meta"]["data_updated_at"] == "2026-07-08T20:30:00"


def test_fund_filter_api_supports_sorting(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.post(
            "/api/funds/filter",
            json={
                "risk_profile": "C5",
                "fund_types": ["mixed", "bond", "stock"],
                "min_years": 0,
                "size_range": [0, 500],
                "return_rank_percentile": 100,
                "max_drawdown_lte_category_avg": True,
                "sharpe_gte": 0,
                "fee_lte": 3,
                "sort_by": "sharpe_ratio",
                "sort_order": "desc",
            },
        )
    finally:
        clear_overrides()

    body = response.json()
    sharpes = [item["sharpe_ratio"] for item in body["data"]]
    assert response.status_code == 200
    assert sharpes == sorted(sharpes, reverse=True)


def test_fund_detail_api_returns_database_fund(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.get("/api/funds/000001", params={"risk_profile": "C2"})
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert body["data"]["code"] == "000001"
    assert body["data"]["navs"]
    assert body["data"]["fee_summary"]["total_fee"] == 1.4
    assert body["data"]["manager_profile"]["name"] == "陈安"
    assert {metric["key"] for metric in body["data"]["metric_explanations"]} == {
        "annualized_return_3y",
        "max_drawdown",
        "sharpe_ratio",
        "fee",
    }
    assert body["data"]["risk_match"] == {
        "user_risk_profile": "C2",
        "fund_risk_level": "R3",
        "matched": False,
        "message": "该基金风险等级 R3 超过当前 C2 承受能力，不应进入推荐结果。",
    }
    assert body["meta"]["data_updated_at"] == "2026-07-08T20:30:00"


def test_fund_nav_api_supports_date_range(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.get(
            "/api/funds/000001/nav",
            params={"start": "2023", "end": "2025"},
        )
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert [point["trade_date"] for point in body["data"]] == ["2023", "2024", "2025"]


def test_fund_compare_api_preserves_existing_code_order(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.post(
            "/api/funds/compare",
            json={"codes": ["000004", "000002", "missing"]},
        )
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert [item["code"] for item in body["data"]] == ["000004", "000002"]


def test_api_errors_use_uniform_envelope(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        missing_response = client.get("/api/funds/not-found")
        validation_response = client.get("/api/funds/search", params={"page": "0"})
    finally:
        clear_overrides()

    assert missing_response.status_code == 404
    assert missing_response.json()["error"] == {
        "code": "FUND_NOT_FOUND",
        "message": "未找到指定基金",
        "detail": None,
    }
    assert "meta" in missing_response.json()

    assert validation_response.status_code == 422
    assert validation_response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(validation_response.json()["error"]["detail"], list)


def test_risk_assessment_questions_submit_and_latest_are_persistent(db_session: Session) -> None:
    answers = [
        {"question_id": "horizon", "score": 3},
        {"question_id": "drawdown_tolerance", "score": 3},
        {"question_id": "income_stability", "score": 3},
        {"question_id": "investment_experience", "score": 3},
        {"question_id": "liquidity_need", "score": 3},
        {"question_id": "goal_priority", "score": 3},
    ]
    try:
        client = make_client(db_session)
        questions_response = client.get("/api/risk-assessments/questions")
        submit_response = client.post("/api/risk-assessments", json={"answers": answers})
        latest_response = client.get("/api/risk-assessments/latest")
        dashboard_response = client.get("/api/dashboard")
    finally:
        clear_overrides()

    assert questions_response.status_code == 200
    assert len(questions_response.json()["data"]) == 6

    submitted = submit_response.json()["data"]
    assert submit_response.status_code == 200
    assert submitted["risk_profile"] == "C3"
    assert submitted["score"] == 18
    assert submitted["is_expired"] is False
    assert db_session.scalar(select(func.count()).select_from(RiskAssessment)) == 1

    latest = latest_response.json()["data"]
    assert latest["risk_profile"] == "C3"
    assert latest["effective_to"] > latest["effective_from"]
    assert dashboard_response.json()["data"]["risk_profile"] == "C3"


def test_risk_assessment_rejects_incomplete_answers(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.post(
            "/api/risk-assessments",
            json={"answers": [{"question_id": "horizon", "score": 3}]},
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_portfolio_crud_positions_and_rebalance_preview_use_database(db_session: Session) -> None:
    portfolio = create_portfolio(
        db_session,
        PortfolioCreateRequest(name="我的稳健组合", template_key="balanced"),
    )
    assert portfolio.name == "我的稳健组合"
    assert portfolio.positions == []

    try:
        client = make_client(db_session)
        rename_response = client.patch(f"/api/portfolios/{portfolio.id}", json={"name": "长期稳健组合"})
        position_response = client.put(
            f"/api/portfolios/{portfolio.id}/positions",
            json={"fund_code": "000001", "weight_percent": 70},
        )
        preview_response = client.post(f"/api/portfolios/{portfolio.id}/rebalance-preview")
        remove_response = client.delete(f"/api/portfolios/{portfolio.id}/positions/000001")
    finally:
        clear_overrides()

    assert rename_response.status_code == 200
    assert rename_response.json()["data"]["name"] == "长期稳健组合"

    assert position_response.status_code == 200
    assert position_response.json()["data"]["positions"][0]["fund_code"] == "000001"
    assert position_response.json()["data"]["total_weight_percent"] == 70
    assert "70.00%" in position_response.json()["data"]["weight_warning"]
    assert position_response.json()["data"]["positions"][0]["normalized_weight_percent"] == 100

    preview = preview_response.json()["data"]
    assert preview_response.status_code == 200
    assert preview["current_stock_ratio"] == 70
    assert preview["target_stock_ratio"] == 50
    assert preview["drift_percent"] == 50
    assert preview["triggered"] is True
    assert "可考虑" in preview["message"]
    assert "强制交易指令" in preview["message"]

    assert remove_response.status_code == 200
    assert remove_response.json()["data"]["positions"] == []


def test_portfolio_templates_api_returns_suitable_risk_profiles(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        response = client.get("/api/portfolios/templates")
    finally:
        clear_overrides()

    body = response.json()
    assert response.status_code == 200
    assert [item["id"] for item in body["data"]] == ["conservative", "balanced", "growth"]
    assert body["data"][0]["suitable_profiles"] == ["C1", "C2"]
    assert body["data"][1]["suitable_profiles"] == ["C2", "C3"]
    assert body["data"][2]["suitable_profiles"] == ["C4", "C5"]
    assert "meta" in body


def test_rebalance_preview_does_not_trigger_below_threshold(db_session: Session) -> None:
    portfolio = create_portfolio(
        db_session,
        PortfolioCreateRequest(name="低偏离组合", template_key="balanced"),
    )
    db_session.commit()
    from app.repositories.portfolios import upsert_position

    upsert_position(db_session, portfolio.id, PortfolioPositionRequest(fund_code="000001", weight_percent=52))
    upsert_position(db_session, portfolio.id, PortfolioPositionRequest(fund_code="000002", weight_percent=48))

    preview = rebalance_preview(db_session, portfolio.id)
    assert preview is not None
    assert preview.triggered is False
    assert preview.drift_percent == 2
    assert "可继续观察" in preview.message


def test_backtest_uses_fund_navs_and_persists_result(db_session: Session) -> None:
    result = run_backtest(
        db_session,
        BacktestRequest(
            strategy_type="monthly_dca",
            fund_codes=["000001", "000002"],
            amount=1000,
            start="2021",
            end="2026",
        ),
    )

    assert len(result.points) == 6
    assert result.total_invested == 6000
    assert result.final_value > result.total_invested
    assert result.points[0].portfolio == 1000
    assert result.data_warning is not None
    assert db_session.get(BacktestRun, result.id) is not None


def test_template_portfolio_backtest_uses_template_allocation(db_session: Session) -> None:
    result = run_backtest(
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

    assert len(result.points) == 6
    assert result.strategy_type == "template_portfolio"
    assert result.total_invested == 6000
    assert result.points[0].portfolio == 1000
    assert result.final_value > result.total_invested
    assert result.data_warning is not None
    assert "组合模板回测" in result.data_warning
    persisted = db_session.get(BacktestRun, result.id)
    assert persisted is not None
    assert persisted.request_payload["template_key"] == "balanced"


def test_backtest_handles_missing_navs_without_crashing(db_session: Session) -> None:
    result = run_backtest(
        db_session,
        BacktestRequest(
            strategy_type="monthly_dca",
            fund_codes=["000001"],
            amount=1000,
            start="2030",
            end="2031",
        ),
    )

    assert result.points == []
    assert result.final_value == 0
    assert result.data_warning == "数据不足，无法生成有效回测结果。"


def test_ai_chat_uses_gateway_context_and_guardrails(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        fund_response = client.post(
            "/api/ai/chat",
            json={"message": "解释这只基金的回撤", "context": {"fund_code": "000001"}},
        )
        blocked_response = client.post(
            "/api/ai/chat",
            json={"message": "这只基金明天必须买入吗", "context": {"fund_code": "000001"}},
        )
    finally:
        clear_overrides()

    fund_body = fund_response.json()["data"]
    assert fund_response.status_code == 200
    assert fund_body["thread_id"] is not None
    assert fund_body["unable_to_answer"] is False
    assert "funds:000001" in fund_body["references"]
    assert fund_body["data_date"] == "2026-07-08"
    assert db_session.scalar(select(func.count()).select_from(AiThread)) == 2
    assert db_session.scalar(select(func.count()).select_from(AiMessage)) == 4

    blocked_body = blocked_response.json()["data"]
    assert blocked_response.status_code == 200
    assert blocked_body["unable_to_answer"] is True
    assert "不能给出买卖建议" in blocked_body["conclusion"]


def test_ai_chat_explains_backtest_result_with_historical_limits(db_session: Session) -> None:
    backtest = run_backtest(
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

    try:
        client = make_client(db_session)
        response = client.post(
            "/api/ai/chat",
            json={"message": "解释这次回测结果", "context": {"backtest_id": backtest.id}},
        )
    finally:
        clear_overrides()

    body = response.json()["data"]
    assert response.status_code == 200
    assert body["unable_to_answer"] is False
    assert f"backtest_runs:{backtest.id}" in body["references"]
    assert "历史表现不预示未来收益" in body["risk"]
    assert "交易指令" in body["risk"]
    assert any("曲线点数" in item for item in body["evidence"])


def test_ai_threads_and_streaming_response_are_persistent(db_session: Session) -> None:
    try:
        client = make_client(db_session)
        chat_response = client.post("/api/ai/chat", json={"message": "解释基金指标", "context": {"fund_code": "000001"}})
        thread_id = chat_response.json()["data"]["thread_id"]
        threads_response = client.get("/api/ai/threads")
        thread_response = client.get(f"/api/ai/threads/{thread_id}")
        with client.stream("POST", "/api/ai/chat/stream", json={"thread_id": thread_id, "message": "继续解释", "context": {"fund_code": "000001"}}) as stream_response:
            stream_text = "".join(stream_response.iter_text())
    finally:
        clear_overrides()

    assert threads_response.status_code == 200
    assert threads_response.json()["data"][0]["id"] == thread_id
    assert thread_response.status_code == 200
    assert len(thread_response.json()["data"]["messages"]) == 2
    assert "data:" in stream_text
    assert '"done": true' in stream_text
    assert db_session.scalar(select(func.count()).select_from(AiMessage)) == 4


def test_ai_chat_reports_insufficient_data(db_session: Session) -> None:
    db_session.execute(delete(FundNav))
    db_session.execute(delete(FundMetric))
    db_session.execute(delete(Fund))
    db_session.commit()

    try:
        client = make_client(db_session)
        response = client.post("/api/ai/chat", json={"message": "解释基金指标", "context": {}})
    finally:
        clear_overrides()

    body = response.json()["data"]
    assert response.status_code == 200
    assert body["unable_to_answer"] is True
    assert "fund_count=0" in body["evidence"]
