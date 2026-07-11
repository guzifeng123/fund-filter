from sqlalchemy.orm import Session

from app.repositories.funds import filter_funds, get_fund_navs, search_funds
from app.schemas.funds import FundFilterRequest


def test_search_funds_paginates_and_filters_by_keyword(db_session: Session) -> None:
    page, total = search_funds(db_session, "债", page=1, page_size=1, sort_by="code", sort_order="asc")

    assert total == 2
    assert len(page) == 1
    assert page[0].code == "000002"


def test_search_funds_sorts_by_fee_descending(db_session: Session) -> None:
    result, total = search_funds(db_session, "", page=1, page_size=10, sort_by="fee", sort_order="desc")

    assert total == 4
    assert [fund.code for fund in result][:2] == ["000001", "000003"]
    assert result[0].management_fee + result[0].custody_fee >= result[1].management_fee + result[1].custody_fee


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
            max_drawdown_lte_category_avg=True,
            sharpe_gte=0,
            fee_lte=3,
            sort_by="code",
            sort_order="asc",
        ),
    )

    assert [fund.code for fund in result] == ["000002", "000004"]
