import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.nav_quality import NavQualityWarningPayload
from app.db.models import (
    LEGACY_SNAPSHOT_GENERATION_ID,
    Fund,
    FundMetric,
    FundNav,
)
from app.db.session import Base
from app.repositories.fund_snapshots import ensure_snapshot_state
from app.repositories.funds import (
    stage_funds_batch,
    upsert_fund_detail,
    upsert_fund_metrics,
    upsert_fund_navs,
    upsert_fund_profile,
)
from app.services.sample_data import FUNDS
from app.schemas.funds import FundDetail


def _make_engine() -> Engine:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _seed(engine: Engine) -> Session:
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    ensure_snapshot_state(db)
    for fund in FUNDS:
        upsert_fund_detail(db, fund)
    db.commit()
    return db


def _per_point_stage(db: Session, funds: list[FundDetail], generation_id: str) -> list[NavQualityWarningPayload]:
    warnings: list[NavQualityWarningPayload] = []
    for fund in funds:
        upsert_fund_profile(db, fund, generation_id)
        db.flush()
        upsert_fund_metrics(db, fund, generation_id)
        warnings.extend(upsert_fund_navs(db, fund, generation_id))
    db.flush()
    return warnings


def _generation_payloads(db: Session, generation_id: str) -> dict[str, object]:
    funds = sorted(
        (
            row.code,
            row.name,
            dict(row.raw_data),
        )
        for row in db.scalars(select(Fund).where(Fund.snapshot_generation_id == generation_id))
    )
    navs = sorted(
        (
            row.fund_code,
            row.trade_date,
            row.nav,
            row.accumulated_nav,
            row.trade_date_precision,
            dict(row.raw_data),
        )
        for row in db.scalars(select(FundNav).where(FundNav.snapshot_generation_id == generation_id))
    )
    metrics = sorted(
        (
            row.fund_code,
            row.annualized_return_3y,
            row.annualized_return_5y,
            row.max_drawdown,
            row.sharpe_ratio,
            row.category_rank_percentile,
            row.manager_years,
            dict(row.raw_data),
        )
        for row in db.scalars(select(FundMetric).where(FundMetric.snapshot_generation_id == generation_id))
    )
    return {"funds": funds, "navs": navs, "metrics": metrics}


@pytest.fixture()
def candidate_funds() -> list[FundDetail]:
    candidate = [fund.model_copy(deep=True) for fund in FUNDS]
    candidate[0].name = "批量路径等价性新名称"
    candidate[0].navs[0] = candidate[0].navs[0].model_copy(update={"nav": 1.99})
    return candidate


def test_batch_and_per_point_paths_produce_identical_rows_and_warnings(
    candidate_funds: list[FundDetail],
) -> None:
    per_point_engine = _make_engine()
    batch_engine = _make_engine()
    try:
        per_point_db = _seed(per_point_engine)
        batch_db = _seed(batch_engine)

        per_point_warnings = _per_point_stage(per_point_db, candidate_funds, "generation-a")
        batch_warnings = stage_funds_batch(batch_db, candidate_funds, "generation-b", batch_size=2)

        assert sorted(warning["trade_date"] for warning in batch_warnings) == sorted(
            warning["trade_date"] for warning in per_point_warnings
        )
        assert len(batch_warnings) == len(per_point_warnings)

        per_point_state = _generation_payloads(per_point_db, "generation-a")
        batch_state = _generation_payloads(batch_db, "generation-b")
        # Rename the payloads so the generation_id embedded in raw_data matches: the
        # profile raw_data does not carry the generation id, but be defensive.
        assert per_point_state == batch_state

        for db in (per_point_db, batch_db):
            assert db.scalar(
                select(func.count()).select_from(FundNav).where(FundNav.snapshot_generation_id.like("generation-%"))
            ) == sum(len(fund.navs) for fund in candidate_funds)
    finally:
        Base.metadata.drop_all(per_point_engine)
        Base.metadata.drop_all(batch_engine)


def test_re_staging_the_same_generation_is_idempotent(
    candidate_funds: list[FundDetail],
) -> None:
    engine = _make_engine()
    try:
        db = _seed(engine)
        generation_id = "idempotent-gen"
        stage_funds_batch(db, candidate_funds, generation_id, batch_size=2)
        db.commit()
        nav_count_after_first = db.scalar(
            select(func.count()).select_from(FundNav).where(FundNav.snapshot_generation_id == generation_id)
        )
        expected_nav_count = sum(len(fund.navs) for fund in candidate_funds)
        assert nav_count_after_first == expected_nav_count

        stage_funds_batch(db, candidate_funds, generation_id, batch_size=2)
        db.commit()
        nav_count_after_second = db.scalar(
            select(func.count()).select_from(FundNav).where(FundNav.snapshot_generation_id == generation_id)
        )
        fund_count = db.scalar(
            select(func.count()).select_from(Fund).where(Fund.snapshot_generation_id == generation_id)
        )
        metric_count = db.scalar(
            select(func.count()).select_from(FundMetric).where(
                FundMetric.snapshot_generation_id == generation_id
            )
        )
        assert nav_count_after_second == expected_nav_count
        assert fund_count == len(candidate_funds)
        assert metric_count == len(candidate_funds)
    finally:
        Base.metadata.drop_all(engine)


def test_batch_path_assigns_rows_to_the_requested_generation_not_legacy(
    candidate_funds: list[FundDetail],
) -> None:
    engine = _make_engine()
    try:
        db = _seed(engine)
        stage_funds_batch(db, candidate_funds, "fresh-gen", batch_size=2)
        db.commit()
        active_funds = db.scalar(
            select(func.count()).select_from(Fund).where(Fund.snapshot_generation_id == "fresh-gen")
        )
        legacy_funds = db.scalar(
            select(func.count()).select_from(Fund).where(
                Fund.snapshot_generation_id == LEGACY_SNAPSHOT_GENERATION_ID
            )
        )
        assert active_funds == len(candidate_funds)
        # The first two sample funds were reused/mutated into fresh-gen; the rest
        # (not in the candidate) remain pinned to the legacy generation.
        assert legacy_funds == len(FUNDS) - len(candidate_funds)
    finally:
        Base.metadata.drop_all(engine)


def test_stage_funds_batch_rejects_non_positive_batch_size(
    candidate_funds: list[FundDetail],
) -> None:
    engine = _make_engine()
    try:
        db = _seed(engine)
        with pytest.raises(ValueError, match="batch_size"):
            stage_funds_batch(db, candidate_funds, "any-gen", batch_size=0)
    finally:
        Base.metadata.drop_all(engine)
