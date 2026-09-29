from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import BacktestRun, FundNav
from app.db.session import get_db
from app.main import app


def test_backtest_api_uses_first_available_daily_nav_per_month(
    db_session: Session,
) -> None:
    db_session.execute(delete(FundNav).where(FundNav.fund_code == "000001"))
    db_session.add_all(
        FundNav(
            fund_code="000001",
            trade_date=trade_date,
            nav=nav,
            accumulated_nav=nav,
            raw_data={},
        )
        for trade_date, nav in (
            ("2026-01-06", 1.0),
            ("2026-01-20", 2.0),
            ("2026-02-03", 4.0),
        )
    )
    db_session.commit()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/backtests",
            json={
                "strategy_type": "monthly_dca",
                "fund_codes": ["000001"],
                "amount": 1000,
                "start": "2026-01-01",
                "end": "2026-02-28",
            },
        )
    finally:
        app.dependency_overrides.clear()

    body = response.json()["data"]
    assert response.status_code == 200
    assert body["total_invested"] == 2000
    assert [point["portfolio"] for point in body["points"]] == [1000, 2000, 5000]
    assert body["money_weighted_return"] == body["annualized_return"]
    assert body["time_weighted_return"] > 0
    assert body["return_calculation_method"] == "xirr"
    assert body["snapshot_generation_id"] == "legacy-0008"
    assert body["data_warning"] is None
    assert db_session.get(BacktestRun, body["id"]) is not None
