from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.snapshot_quality import SnapshotQualityError, validate_snapshot_quality
from app.db.models import (
    LEGACY_SNAPSHOT_GENERATION_ID,
    Fund,
    FundDataSnapshot,
    FundDataSnapshotState,
    FundMetric,
    FundNav,
    JobRun,
)
from app.jobs import sync_fund_data
from app.repositories.data_status import get_data_status
from app.repositories.fund_snapshots import SNAPSHOT_STATE_ROW_ID, promote_snapshot
from app.repositories.funds import (
    get_fund,
    get_fund_navs,
    search_funds,
    upsert_fund_metrics as real_upsert_fund_metrics,
)
from app.repositories.portfolios import (
    UnavailablePortfolioPositionsError,
    create_portfolio,
    delete_position,
    get_portfolio,
    normalize_position_weights,
    rebalance_preview,
    upsert_position,
)
from app.schemas.funds import FundDetail
from app.schemas.portfolio import PortfolioCreateRequest, PortfolioPositionRequest
from app.services.sample_data import FUNDS


class SnapshotSourceStub:
    name = "snapshot_stub"

    def __init__(self, funds: list[FundDetail]) -> None:
        self._funds = funds
        self.fetch_count = 0

    def fetch_snapshot(self) -> list[FundDetail]:
        self.fetch_count += 1
        return self._funds

    def fetch_fund_profiles(self) -> list[FundDetail]:
        raise AssertionError("atomic sync must not fetch a separate profile snapshot")

    def fetch_fund_navs(self) -> list[FundDetail]:
        raise AssertionError("atomic sync must not fetch a separate NAV snapshot")

    def fetch_risk_levels(self) -> dict[str, str]:
        raise AssertionError("atomic sync must not fetch separate risk levels")


def _install_source(
    monkeypatch: pytest.MonkeyPatch,
    source: SnapshotSourceStub,
) -> None:
    monkeypatch.setattr(
        sync_fund_data,
        "get_fund_data_source",
        lambda _source_name: source,
    )


def _snapshot_ids(db: Session) -> set[str]:
    return set(db.scalars(select(FundDataSnapshot.generation_id)).all())


def _reset_snapshot_quality_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fund_snapshot_min_fund_count", 1)
    monkeypatch.setattr(settings, "fund_snapshot_min_nav_coverage_ratio", 0.0)
    monkeypatch.setattr(settings, "fund_snapshot_max_latest_nav_age_days", 0)
    monkeypatch.setattr(settings, "fund_snapshot_max_fund_count_drop_ratio", 1.0)
    monkeypatch.setattr(settings, "fund_snapshot_quality_overrides", {})


def test_sync_all_promotes_one_complete_generation_and_hides_removed_funds(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = create_portfolio(
        db_session,
        PortfolioCreateRequest(name="跨快照保留持仓", template_key="balanced"),
    )
    removed_fund_code = FUNDS[2].code
    upsert_position(
        db_session,
        portfolio.id,
        PortfolioPositionRequest(fund_code=removed_fund_code, weight_percent=100),
    )
    candidate = [fund.model_copy(deep=True) for fund in FUNDS[:2]]
    candidate[0].name = "原子快照新名称"
    source = SnapshotSourceStub(candidate)
    _install_source(monkeypatch, source)

    details = sync_fund_data.sync_all(db_session, source.name)

    generation_id = str(details["snapshot_generation_id"])
    assert source.fetch_count == 1
    assert details["generation_boundary"] == "atomic_promotion"
    assert details["previous_snapshot_generation_id"] == LEGACY_SNAPSHOT_GENERATION_ID
    state = db_session.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert state is not None
    assert state.active_generation_id == generation_id
    snapshots = {
        row.generation_id: row for row in db_session.scalars(select(FundDataSnapshot)).all()
    }
    assert snapshots[LEGACY_SNAPSHOT_GENERATION_ID].status == "superseded"
    assert snapshots[generation_id].status == "active"

    expected_nav_count = sum(len(fund.navs) for fund in candidate)
    assert db_session.scalar(
        select(func.count()).select_from(Fund).where(Fund.snapshot_generation_id == generation_id)
    ) == len(candidate)
    assert db_session.scalar(
        select(func.count())
        .select_from(FundMetric)
        .where(FundMetric.snapshot_generation_id == generation_id)
    ) == len(candidate)
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(FundNav)
            .where(FundNav.snapshot_generation_id == generation_id)
        )
        == expected_nav_count
    )

    stale_fund = db_session.get(Fund, FUNDS[2].code)
    assert stale_fund is not None
    assert stale_fund.snapshot_generation_id == LEGACY_SNAPSHOT_GENERATION_ID
    visible, total = search_funds(db_session, "", page_size=20)
    assert total == 2
    assert [fund.code for fund in visible] == [fund.code for fund in candidate]
    assert get_fund(db_session, removed_fund_code) is None
    assert get_fund_navs(db_session, removed_fund_code) is None

    stored_portfolio = get_portfolio(db_session, portfolio.id)
    assert stored_portfolio is not None
    assert stored_portfolio.unavailable_position_count == 1
    assert stored_portfolio.positions[0].fund_code == removed_fund_code
    assert stored_portfolio.positions[0].available is False
    assert stored_portfolio.positions[0].availability_reason == "removed_from_active_snapshot"
    with pytest.raises(UnavailablePortfolioPositionsError) as normalize_exc:
        normalize_position_weights(db_session, portfolio.id)
    assert normalize_exc.value.unavailable_fund_codes == [removed_fund_code]
    with pytest.raises(UnavailablePortfolioPositionsError) as preview_exc:
        rebalance_preview(db_session, portfolio.id)
    assert preview_exc.value.unavailable_fund_codes == [removed_fund_code]
    with pytest.raises(ValueError, match="fund not found"):
        upsert_position(
            db_session,
            portfolio.id,
            PortfolioPositionRequest(fund_code=removed_fund_code, weight_percent=50),
        )
    after_delete = delete_position(db_session, portfolio.id, removed_fund_code)
    assert after_delete is not None
    assert after_delete.positions == []

    active_fund = get_fund(db_session, candidate[0].code)
    assert active_fund is not None
    assert active_fund.name == "原子快照新名称"

    status = get_data_status(db_session)
    assert status.fund_count == len(candidate)
    assert status.nav_count == expected_nav_count


def test_sync_all_late_failure_rolls_back_candidate_and_promotion(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successful = sync_fund_data.sync_all(db_session, "sample_local")
    active_generation_id = str(successful["snapshot_generation_id"])
    snapshot_ids_before = _snapshot_ids(db_session)
    original_name = get_fund(db_session, FUNDS[0].code)
    assert original_name is not None
    original_name_value = original_name.name

    candidate = [fund.model_copy(deep=True) for fund in FUNDS]
    candidate[0].name = "不得提交的候选名称"
    source = SnapshotSourceStub(candidate)
    _install_source(monkeypatch, source)
    original_promote: Callable[..., None] = promote_snapshot

    def fail_after_promotion(*args: object, **kwargs: object) -> None:
        original_promote(*args, **kwargs)
        raise RuntimeError("injected late snapshot failure")

    monkeypatch.setattr(sync_fund_data, "promote_snapshot", fail_after_promotion)

    with pytest.raises(RuntimeError, match="injected late snapshot failure"):
        sync_fund_data.sync_all(db_session, source.name)

    db_session.expire_all()
    state = db_session.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert state is not None
    assert state.active_generation_id == active_generation_id
    assert _snapshot_ids(db_session) == snapshot_ids_before
    visible = get_fund(db_session, FUNDS[0].code)
    assert visible is not None
    assert visible.name == original_name_value
    assert visible.snapshot_generation_id == active_generation_id
    latest_job = db_session.scalars(select(JobRun).order_by(JobRun.id.desc())).first()
    assert latest_job is not None
    assert latest_job.status == "failed"
    assert latest_job.details["error"] == "injected late snapshot failure"


def test_sync_all_rejects_empty_or_duplicate_snapshot_without_changing_visibility(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for candidate, message in (
        ([], "empty snapshot"),
        (
            [FUNDS[0].model_copy(deep=True), FUNDS[0].model_copy(deep=True)],
            "duplicate fund codes",
        ),
    ):
        source = SnapshotSourceStub(candidate)
        _install_source(monkeypatch, source)
        with pytest.raises(ValueError, match=message):
            sync_fund_data.sync_all(db_session, source.name)

    visible, total = search_funds(db_session, "", page_size=20)
    assert total == len(FUNDS)
    assert {fund.code for fund in visible} == {fund.code for fund in FUNDS}
    assert _snapshot_ids(db_session) == {LEGACY_SNAPSHOT_GENERATION_ID}


def test_sync_all_rejects_snapshot_below_minimum_fund_count(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_snapshot_quality_thresholds(monkeypatch)
    monkeypatch.setattr(settings, "fund_snapshot_min_fund_count", 5)
    source = SnapshotSourceStub([fund.model_copy(deep=True) for fund in FUNDS[:2]])
    _install_source(monkeypatch, source)

    with pytest.raises(SnapshotQualityError, match="fund count is below"):
        sync_fund_data.sync_all(db_session, source.name)

    visible, total = search_funds(db_session, "", page_size=20)
    assert total == len(FUNDS)
    assert {fund.code for fund in visible} == {fund.code for fund in FUNDS}
    latest_job = db_session.scalars(select(JobRun).order_by(JobRun.id.desc())).first()
    assert latest_job is not None
    assert latest_job.status == "failed"
    assert "configured minimum" in str(latest_job.details["error"])


def test_sync_all_rejects_excessive_fund_count_drop(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_snapshot_quality_thresholds(monkeypatch)
    successful = sync_fund_data.sync_all(db_session, "sample_local")
    active_generation_id = str(successful["snapshot_generation_id"])
    monkeypatch.setattr(settings, "fund_snapshot_max_fund_count_drop_ratio", 0.25)
    source = SnapshotSourceStub([fund.model_copy(deep=True) for fund in FUNDS[:2]])
    _install_source(monkeypatch, source)

    with pytest.raises(SnapshotQualityError, match="fund count drop exceeds"):
        sync_fund_data.sync_all(db_session, source.name)

    db_session.expire_all()
    state = db_session.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert state is not None
    assert state.active_generation_id == active_generation_id
    visible, total = search_funds(db_session, "", page_size=20)
    assert total == len(FUNDS)
    assert {fund.code for fund in visible} == {fund.code for fund in FUNDS}


def test_snapshot_quality_override_can_require_complete_nav_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_snapshot_quality_thresholds(monkeypatch)
    monkeypatch.setattr(
        settings,
        "fund_snapshot_quality_overrides",
        {"eastmoney_snapshot": {"min_nav_coverage_ratio": 1.0}},
    )
    funds = [fund.model_copy(deep=True) for fund in FUNDS[:2]]
    for fund in funds:
        fund.source = "eastmoney_snapshot"
    funds[1].navs = []

    with pytest.raises(SnapshotQualityError, match="NAV coverage"):
        validate_snapshot_quality(
            funds,
            source_name="public_http_json",
            previous_fund_count=0,
            today=date(2026, 7, 17),
        )


def test_snapshot_quality_rejects_stale_latest_nav_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_snapshot_quality_thresholds(monkeypatch)
    monkeypatch.setattr(settings, "fund_snapshot_max_latest_nav_age_days", 3)
    funds = [fund.model_copy(deep=True) for fund in FUNDS[:1]]
    funds[0].source = "public_http_json"
    funds[0].navs[0].trade_date = "2026-07-10"

    with pytest.raises(SnapshotQualityError, match="latest NAV date"):
        validate_snapshot_quality(
            funds,
            source_name="public_http_json",
            previous_fund_count=0,
            today=date(2026, 7, 17),
        )


def test_legacy_component_task_alias_still_promotes_a_complete_snapshot(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SnapshotSourceStub([fund.model_copy(deep=True) for fund in FUNDS])
    _install_source(monkeypatch, source)

    details = sync_fund_data.sync_fund_profiles(db_session, source.name)

    assert source.fetch_count == 1
    assert details["requested_task"] == "profiles"
    assert details["effective_scope"] == "full_snapshot"
    assert details["generation_boundary"] == "atomic_promotion"
    assert details["snapshot_generation_id"] != LEGACY_SNAPSHOT_GENERATION_ID
    state = db_session.get(FundDataSnapshotState, SNAPSHOT_STATE_ROW_ID)
    assert state is not None
    assert state.active_generation_id == details["snapshot_generation_id"]


def test_staged_count_mismatch_rolls_back_without_changing_active_rows(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = [fund.model_copy(deep=True) for fund in FUNDS[:2]]
    source = SnapshotSourceStub(candidate)
    _install_source(monkeypatch, source)
    # This patch targets the per-point upsert loop; force that path so the
    # deliberate missing metric reaches validate_staged_snapshot.
    monkeypatch.setattr(settings, "fund_write_batch_enabled", False)

    def omit_one_metric(
        db: Session,
        fund: FundDetail,
        generation_id: str | None = None,
    ) -> None:
        if fund.code != candidate[-1].code:
            real_upsert_fund_metrics(db, fund, generation_id)

    monkeypatch.setattr(sync_fund_data, "upsert_fund_metrics", omit_one_metric)

    with pytest.raises(RuntimeError, match="row counts do not match"):
        sync_fund_data.sync_all(db_session, source.name)

    visible, total = search_funds(db_session, "", page_size=20)
    assert total == len(FUNDS)
    assert {fund.code for fund in visible} == {fund.code for fund in FUNDS}
    assert _snapshot_ids(db_session) == {LEGACY_SNAPSHOT_GENERATION_ID}


def test_active_pointer_is_resolved_before_each_fund_repository_read(
    db_session: Session,
) -> None:
    statements: list[tuple[str, object]] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append((statement.lower(), parameters))

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        search_funds(db_session, "", page_size=20)
        get_fund(db_session, FUNDS[0].code)
        get_fund_navs(db_session, FUNDS[0].code)
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    fund_data_statements = [
        statement
        for statement, _parameters in statements
        if "from funds" in statement or "from fund_navs" in statement
    ]
    state_statements = [
        statement
        for statement, _parameters in statements
        if "from fund_data_snapshot_state" in statement
    ]
    assert fund_data_statements
    assert len(state_statements) >= 3
    fund_data_parameters = [
        parameters
        for statement, parameters in statements
        if "from funds" in statement or "from fund_navs" in statement
    ]
    assert all("legacy-0008" in str(parameters) for parameters in fund_data_parameters)
