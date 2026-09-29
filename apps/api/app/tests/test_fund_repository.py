from datetime import date

from sqlalchemy.orm import Session

from app.db.models import Fund, FundMetric, FundNav
from app.repositories.funds import (
    filter_funds,
    fund_inception_cutoff,
    fund_data_source_summary,
    get_fund_navs,
    search_funds,
    search_funds_with_context,
    upsert_fund_metrics,
    upsert_fund_navs,
    upsert_fund_profile,
)
from app.schemas.funds import FundFilterRequest, NavPoint
from app.services.sample_data import FUNDS


def test_fund_data_source_summary_reports_single_and_mixed_sources(db_session: Session) -> None:
    assert fund_data_source_summary(db_session) == "sample_local"

    fund = db_session.get(Fund, "000001")
    assert fund is not None
    fund.source = "public_http_json"
    db_session.commit()

    assert fund_data_source_summary(db_session) == "mixed(public_http_json,sample_local)"


def test_search_funds_paginates_and_filters_by_keyword(db_session: Session) -> None:
    page, total = search_funds(
        db_session, "债", page=1, page_size=1, sort_by="code", sort_order="asc"
    )

    assert total == 2
    assert len(page) == 1
    assert page[0].code == "000002"


def test_search_funds_with_context_uses_payload_generation_for_meta(
    db_session: Session,
) -> None:
    result = search_funds_with_context(
        db_session, "", page=1, page_size=10, sort_by="code", sort_order="asc"
    )

    assert result.context.snapshot_generation_id == "legacy-0008"
    assert result.context.source == "sample_local"
    assert result.context.data_updated_at is not None
    assert {fund.snapshot_generation_id for fund in result.data} == {"legacy-0008"}
    assert max(fund.data_updated_at for fund in result.data) == result.context.data_updated_at.isoformat()


def test_search_funds_sorts_by_fee_descending(db_session: Session) -> None:
    result, total = search_funds(
        db_session, "", page=1, page_size=10, sort_by="fee", sort_order="desc"
    )

    assert total == 4
    assert [fund.code for fund in result][:2] == ["000001", "000003"]
    assert (
        result[0].management_fee + result[0].custody_fee
        >= result[1].management_fee + result[1].custody_fee
    )


def test_get_fund_navs_returns_requested_date_window(db_session: Session) -> None:
    navs = get_fund_navs(db_session, "000001", start="2022", end="2024")

    assert navs is not None
    assert [point.trade_date for point in navs] == ["2022", "2023", "2024"]


def test_filter_funds_excludes_unmatched_risk_levels(db_session: Session) -> None:
    result = filter_funds(
        db_session,
        FundFilterRequest(
            risk_profile="C2",
            fund_types=["stock", "mixed", "bond"],
            min_years=0,
            size_range=(0, 500),
            return_rank_percentile=100,
            max_drawdown_lte_category_avg=False,
            sharpe_gte=0,
            fee_lte=3,
            sort_by="code",
            sort_order="asc",
        ),
    )

    assert [fund.code for fund in result] == ["000002", "000004"]


def test_filter_funds_uses_inception_age_with_a_leap_day_cutoff(db_session: Session) -> None:
    established_fund = db_session.get(Fund, "000001")
    young_fund = db_session.get(Fund, "000003")
    established_metric = db_session.get(FundMetric, "000001")
    young_metric = db_session.get(FundMetric, "000003")
    assert established_fund is not None and young_fund is not None
    assert established_metric is not None and young_metric is not None
    established_fund.inception_date = date(2021, 2, 28)
    young_fund.inception_date = date(2021, 3, 1)
    established_metric.manager_years = 0
    young_metric.manager_years = 99
    db_session.commit()

    cutoff = fund_inception_cutoff(date(2024, 2, 29), 3)
    result = filter_funds(
        db_session,
        FundFilterRequest(
            risk_profile="C5",
            fund_types=["mixed", "stock"],
            min_years=3,
            size_range=(0, 500),
            return_rank_percentile=100,
            max_drawdown_lte_category_avg=False,
            sharpe_gte=0,
            fee_lte=3,
            sort_by="code",
            sort_order="asc",
        ),
        as_of_date=date(2024, 2, 29),
    )

    assert cutoff == date(2021, 2, 28)
    assert [fund.code for fund in result] == ["000001"]


def test_filter_funds_applies_signed_category_drawdown_average_only_when_enabled(
    db_session: Session,
) -> None:
    payload = FundFilterRequest(
        risk_profile="C5",
        fund_types=["bond"],
        min_years=0,
        size_range=(0, 500),
        return_rank_percentile=100,
        max_drawdown_lte_category_avg=False,
        sharpe_gte=0,
        fee_lte=3,
        sort_by="code",
        sort_order="asc",
    )

    unfiltered = filter_funds(db_session, payload, as_of_date=date(2026, 7, 13))
    filtered = filter_funds(
        db_session,
        payload.model_copy(update={"max_drawdown_lte_category_avg": True}),
        as_of_date=date(2026, 7, 13),
    )

    assert [fund.code for fund in unfiltered] == ["000002", "000004"]
    assert [fund.code for fund in filtered] == ["000004"]


def test_filter_funds_combines_keyword_risk_and_every_applied_criterion(
    db_session: Session,
) -> None:
    payload = FundFilterRequest(
        keyword="  000002  ",
        risk_profile="C2",
        fund_types=["bond"],
        min_years=3,
        size_range=(80, 90),
        return_rank_percentile=22,
        max_drawdown_lte_category_avg=False,
        sharpe_gte=1.6,
        fee_lte=0.8,
        sort_by="fee",
        sort_order="asc",
    )

    result = filter_funds(db_session, payload, as_of_date=date(2026, 7, 13))
    assert [fund.code for fund in result] == ["000002"]

    excluding_updates: dict[str, dict[str, object]] = {
        "keyword": {"keyword": "000003"},
        "risk_profile": {"risk_profile": "C1"},
        "fund_types": {"fund_types": ["stock"]},
        "min_years": {"min_years": 10},
        "size_range": {"size_range": (0, 80)},
        "return_rank_percentile": {"return_rank_percentile": 21},
        "max_drawdown_lte_category_avg": {"max_drawdown_lte_category_avg": True},
        "sharpe_gte": {"sharpe_gte": 1.63},
        "fee_lte": {"fee_lte": 0.74},
    }
    for criterion, update in excluding_updates.items():
        filtered = filter_funds(
            db_session,
            payload.model_copy(update=update),
            as_of_date=date(2026, 7, 13),
        )
        assert filtered == [], f"criterion was not applied: {criterion}"

    sorted_result = filter_funds(
        db_session,
        FundFilterRequest(
            keyword="债",
            risk_profile="C2",
            fund_types=["bond"],
            min_years=0,
            size_range=(0, 500),
            return_rank_percentile=100,
            max_drawdown_lte_category_avg=False,
            sharpe_gte=0,
            fee_lte=3,
            sort_by="fee",
            sort_order="desc",
        ),
        as_of_date=date(2026, 7, 13),
    )
    assert [fund.code for fund in sorted_result] == ["000002", "000004"]


def test_profile_upsert_does_not_overwrite_metrics_or_navs(db_session: Session) -> None:
    existing_metric = db_session.get(FundMetric, "000001")
    existing_nav = db_session.query(FundNav).filter_by(fund_code="000001", trade_date="2021").one()
    assert existing_metric is not None
    original_return = existing_metric.annualized_return_3y
    original_nav = existing_nav.nav
    snapshot = FUNDS[0].model_copy(deep=True)
    snapshot.name = "仅更新资料名称"
    snapshot.annualized_return_3y = 999
    snapshot.navs[0].nav = 999

    upsert_fund_profile(db_session, snapshot)
    db_session.flush()

    updated_fund = db_session.get(Fund, "000001")
    updated_metric = db_session.get(FundMetric, "000001")
    assert updated_fund is not None and updated_metric is not None
    assert updated_fund.name == "仅更新资料名称"
    assert updated_metric.annualized_return_3y == original_return
    assert (
        db_session.query(FundNav).filter_by(fund_code="000001", trade_date="2021").one().nav
        == original_nav
    )


def test_nav_upsert_does_not_overwrite_profile_or_metrics(db_session: Session) -> None:
    row = db_session.get(Fund, "000001")
    metric = db_session.get(FundMetric, "000001")
    assert row is not None and metric is not None
    original_name = row.name
    original_return = metric.annualized_return_3y
    snapshot = FUNDS[0].model_copy(deep=True)
    snapshot.name = "不应覆盖资料"
    snapshot.annualized_return_3y = 999
    snapshot.navs = [NavPoint(trade_date="2021", nav=8.8, accumulated_nav=9.9)]

    upsert_fund_navs(db_session, snapshot)
    db_session.flush()

    updated_fund = db_session.get(Fund, "000001")
    updated_metric = db_session.get(FundMetric, "000001")
    assert updated_fund is not None and updated_metric is not None
    assert updated_fund.name == original_name
    assert updated_metric.annualized_return_3y == original_return
    updated_nav = db_session.query(FundNav).filter_by(fund_code="000001", trade_date="2021").one()
    assert (updated_nav.nav, updated_nav.accumulated_nav) == (8.8, 9.9)


def test_metrics_upsert_does_not_overwrite_profile_or_navs(db_session: Session) -> None:
    row = db_session.get(Fund, "000001")
    existing_nav = db_session.query(FundNav).filter_by(fund_code="000001", trade_date="2021").one()
    assert row is not None
    original_name = row.name
    original_nav = existing_nav.nav
    snapshot = FUNDS[0].model_copy(deep=True)
    snapshot.name = "不应覆盖资料"
    snapshot.annualized_return_3y = 12.345
    snapshot.navs[0].nav = 999

    upsert_fund_metrics(db_session, snapshot)
    db_session.flush()

    updated_fund = db_session.get(Fund, "000001")
    updated_metric = db_session.get(FundMetric, "000001")
    assert updated_fund is not None and updated_metric is not None
    assert updated_fund.name == original_name
    assert updated_metric.annualized_return_3y == 12.345
    assert (
        db_session.query(FundNav).filter_by(fund_code="000001", trade_date="2021").one().nav
        == original_nav
    )
