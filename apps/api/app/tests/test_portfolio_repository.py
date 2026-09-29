from sqlalchemy import func, select
from sqlalchemy.orm import Session
import pytest

from app.db.models import Fund, Portfolio
from app.repositories.portfolios import (
    UnavailablePortfolioPositionsError,
    create_portfolio,
    delete_position,
    ensure_default_portfolios,
    get_portfolio,
    normalize_position_weights,
    rebalance_preview,
    upsert_position,
)
from app.schemas.portfolio import PortfolioCreateRequest, PortfolioPositionRequest


def test_default_portfolios_are_idempotent(db_session: Session) -> None:
    ensure_default_portfolios(db_session)
    ensure_default_portfolios(db_session)
    db_session.commit()

    count = db_session.scalar(
        select(func.count()).select_from(Portfolio).where(Portfolio.id.like("template_%"))
    )
    assert count == 3


def test_create_portfolio_inherits_template_ratios(db_session: Session) -> None:
    portfolio = create_portfolio(
        db_session, PortfolioCreateRequest(name="进取组合", template_key="growth")
    )

    assert portfolio.template_key == "growth"
    assert portfolio.stock_ratio == 80
    assert portfolio.bond_ratio == 20
    assert portfolio.total_weight_percent == 0
    assert portfolio.weight_warning is None


def test_positions_include_total_weight_warning_and_normalized_preview(db_session: Session) -> None:
    portfolio = create_portfolio(
        db_session, PortfolioCreateRequest(name="权重检查", template_key="balanced")
    )

    detail = upsert_position(
        db_session, portfolio.id, PortfolioPositionRequest(fund_code="000001", weight_percent=70)
    )

    assert detail is not None
    assert detail.total_weight_percent == 70
    assert detail.weight_warning is not None
    assert "70.00%" in detail.weight_warning
    assert detail.positions[0].normalized_weight_percent == 100


def test_rebalance_preview_uses_position_fund_types(db_session: Session) -> None:
    portfolio = create_portfolio(
        db_session, PortfolioCreateRequest(name="偏离检查", template_key="balanced")
    )
    upsert_position(
        db_session, portfolio.id, PortfolioPositionRequest(fund_code="000001", weight_percent=52)
    )
    upsert_position(
        db_session, portfolio.id, PortfolioPositionRequest(fund_code="000002", weight_percent=48)
    )

    preview = rebalance_preview(db_session, portfolio.id)

    assert preview is not None
    assert preview.triggered is False
    assert preview.current_stock_ratio == 52
    assert preview.current_bond_ratio == 48
    assert preview.drift_percent == 2


def test_normalize_position_weights_persists_exact_total(db_session: Session) -> None:
    detail = create_portfolio(
        db_session, PortfolioCreateRequest(name="归一化组合", template_key="balanced")
    )
    upsert_position(
        db_session, detail.id, PortfolioPositionRequest(fund_code="000001", weight_percent=60)
    )
    upsert_position(
        db_session, detail.id, PortfolioPositionRequest(fund_code="000002", weight_percent=20)
    )

    normalized = normalize_position_weights(db_session, detail.id)

    assert normalized is not None
    assert normalized.total_weight_percent == 100
    assert [position.weight_percent for position in normalized.positions] == [75, 25]
    assert normalized.weight_warning is None


def test_normalize_position_weights_rejects_empty_portfolio(db_session: Session) -> None:
    detail = create_portfolio(
        db_session, PortfolioCreateRequest(name="空组合", template_key="balanced")
    )

    with pytest.raises(ValueError, match="positive position weight"):
        normalize_position_weights(db_session, detail.id)


def test_delete_last_loaded_position_refreshes_empty_collection(
    db_session: Session,
) -> None:
    detail = create_portfolio(
        db_session,
        PortfolioCreateRequest(name="删除最后持仓", template_key="balanced"),
    )
    upsert_position(
        db_session,
        detail.id,
        PortfolioPositionRequest(fund_code="000001", weight_percent=100),
    )
    loaded = get_portfolio(db_session, detail.id)
    assert loaded is not None
    assert [position.fund_code for position in loaded.positions] == ["000001"]

    after_delete = delete_position(db_session, detail.id, "000001")

    assert after_delete is not None
    assert after_delete.position_count == 0
    assert after_delete.positions == []


def test_removed_fund_position_stays_visible_but_blocks_derived_actions(
    db_session: Session,
) -> None:
    detail = create_portfolio(
        db_session,
        PortfolioCreateRequest(name="含失效基金", template_key="balanced"),
    )
    upsert_position(
        db_session,
        detail.id,
        PortfolioPositionRequest(fund_code="000001", weight_percent=60),
    )
    upsert_position(
        db_session,
        detail.id,
        PortfolioPositionRequest(fund_code="000002", weight_percent=20),
    )
    removed_fund = db_session.get(Fund, "000001")
    assert removed_fund is not None
    removed_fund.snapshot_generation_id = "retired-test-generation"
    db_session.commit()

    stored = get_portfolio(db_session, detail.id)

    assert stored is not None
    assert stored.position_count == 2
    assert stored.unavailable_position_count == 1
    availability = {position.fund_code: position.available for position in stored.positions}
    assert availability == {"000001": False, "000002": True}
    reasons = {
        position.fund_code: position.availability_reason for position in stored.positions
    }
    assert reasons == {"000001": "removed_from_active_snapshot", "000002": "available"}
    with pytest.raises(UnavailablePortfolioPositionsError) as normalize_exc:
        normalize_position_weights(db_session, detail.id)
    assert normalize_exc.value.unavailable_fund_codes == ["000001"]
    assert normalize_exc.value.availability_reason == "removed_from_active_snapshot"
    with pytest.raises(UnavailablePortfolioPositionsError) as preview_exc:
        rebalance_preview(db_session, detail.id)
    assert preview_exc.value.unavailable_fund_codes == ["000001"]

    after_failed_actions = get_portfolio(db_session, detail.id)
    assert after_failed_actions is not None
    assert {
        position.fund_code: position.weight_percent for position in after_failed_actions.positions
    } == {"000001": 60, "000002": 20}

    after_delete = delete_position(db_session, detail.id, "000001")
    assert after_delete is not None
    assert after_delete.unavailable_position_count == 0
    assert [position.fund_code for position in after_delete.positions] == ["000002"]
