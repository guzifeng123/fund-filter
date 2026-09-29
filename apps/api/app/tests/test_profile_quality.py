import pytest

from app.core.config import settings
from app.core.profile_quality import assess_profile_quality
from app.schemas.funds import FundDetail, NavPoint
from app.services.sample_data import FUNDS


def profile_fund(**overrides: object) -> FundDetail:
    payload = FUNDS[0].model_dump()
    payload.update(overrides)
    payload["navs"] = [
        NavPoint(trade_date="2025-01-02", nav=1.0, accumulated_nav=1.0).model_dump(),
        NavPoint(trade_date="2026-01-02", nav=1.1, accumulated_nav=1.1).model_dump(),
    ]
    return FundDetail.model_validate(payload)


def test_reasonable_profile_is_clean() -> None:
    report = assess_profile_quality([profile_fund()], source_name="csv_local")

    assert report.errors == ()
    assert {i.code for i in report.warnings} == set()


def test_management_fee_out_of_range_is_warning() -> None:
    report = assess_profile_quality(
        [profile_fund(management_fee=5.0)], source_name="csv_local"
    )

    assert "profile_management_fee_out_of_range" in {i.code for i in report.warnings}


def test_custody_fee_out_of_range_is_warning() -> None:
    report = assess_profile_quality(
        [profile_fund(custody_fee=2.0)], source_name="csv_local"
    )

    assert "profile_custody_fee_out_of_range" in {i.code for i in report.warnings}


def test_negative_size_is_warning() -> None:
    report = assess_profile_quality(
        [profile_fund(fund_size_billion=-1.0)], source_name="csv_local"
    )

    assert "profile_fund_size_negative" in {i.code for i in report.warnings}


def test_manager_years_exceeding_fund_age_is_warning() -> None:
    # inception 2018 -> fund age ~8 years at latest nav 2026; tenure 20 impossible.
    report = assess_profile_quality(
        [profile_fund(manager_years=20)], source_name="csv_local"
    )

    assert "profile_manager_years_exceed_fund_age" in {i.code for i in report.warnings}


def test_3y_return_claim_against_short_history_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_profile_min_history_years_for_3y", 3)
    fund = profile_fund(annualized_return_3y=8.0)  # navs span only ~1 year

    report = assess_profile_quality([fund], source_name="csv_local")

    assert "profile_3y_return_claim_unsupported_by_history" in {
        i.code for i in report.warnings
    }


def test_fee_override_relaxes_the_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "fund_profile_quality_overrides",
        {"csv_local": {"management_fee_max": 10.0}},
    )
    report = assess_profile_quality(
        [profile_fund(management_fee=5.0)], source_name="csv_local"
    )

    assert "profile_management_fee_out_of_range" not in {i.code for i in report.warnings}
