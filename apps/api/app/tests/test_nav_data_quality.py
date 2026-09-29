from math import inf, nan

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.nav_quality import NavDataQualityError
from app.db.models import FundNav, JobRun
from app.jobs import sync_fund_data
from app.repositories.funds import upsert_fund_navs
from app.schemas.funds import FundDetail, NavPoint
from app.services.sample_data import FUNDS


def real_fund_with_navs(navs: list[NavPoint]) -> FundDetail:
    payload = FUNDS[0].model_dump()
    payload.update(
        {
            "source": "csv_local",
            "provider_profile": None,
            "upstream_provider": None,
            "navs": [point.model_dump() for point in navs],
        }
    )
    return FundDetail.model_validate(payload)


@pytest.mark.parametrize(
    ("trade_date", "nav", "accumulated_nav"),
    (
        ("2026/07/10", 1.0, 1.0),
        ("2026-02-30", 1.0, 1.0),
        ("2026-07-10", 0.0, 1.0),
        ("2026-07-10", -1.0, 1.0),
        ("2026-07-10", nan, 1.0),
        ("2026-07-10", 1.0, inf),
    ),
)
def test_nav_point_rejects_noncanonical_dates_and_invalid_numbers(
    trade_date: str,
    nav: float,
    accumulated_nav: float,
) -> None:
    with pytest.raises(ValidationError):
        NavPoint(
            trade_date=trade_date,
            nav=nav,
            accumulated_nav=accumulated_nav,
        )


def test_nav_schema_keeps_only_canonical_day_or_legacy_year_dates() -> None:
    legacy_point = NavPoint(trade_date="2026", nav=1.0, accumulated_nav=1.0)
    sample_payload = FUNDS[0].model_dump()
    sample_payload["navs"] = [legacy_point.model_dump()]

    sample = FundDetail.model_validate(sample_payload)

    assert sample.navs[0].trade_date == "2026"


def test_repository_records_quality_warnings_and_trade_date_precision(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_nav_value_max", 10.0)
    monkeypatch.setattr(settings, "fund_accumulated_nav_value_max", 20.0)
    monkeypatch.setattr(settings, "fund_nav_reject_anomalies", False)
    fund = real_fund_with_navs([NavPoint(trade_date="2026-07-10", nav=11.0, accumulated_nav=21.0)])

    warnings = upsert_fund_navs(db_session, fund)
    db_session.commit()

    row = db_session.scalar(
        select(FundNav).where(
            FundNav.fund_code == fund.code,
            FundNav.trade_date == "2026-07-10",
        )
    )
    assert row is not None
    assert row.trade_date_precision == "day"
    assert {warning["field"] for warning in warnings} == {"nav", "accumulated_nav"}
    stored_warnings = row.raw_data["quality_warnings"]
    assert isinstance(stored_warnings, list)
    assert len(stored_warnings) == 2


def test_sync_job_propagates_quality_warnings(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_nav_value_max", 10.0)
    monkeypatch.setattr(settings, "fund_accumulated_nav_value_max", 1000.0)
    monkeypatch.setattr(settings, "fund_nav_reject_anomalies", False)
    fund = real_fund_with_navs([NavPoint(trade_date="2026-07-10", nav=11.0, accumulated_nav=11.0)])

    class StubSource:
        name = "quality_stub"

        @staticmethod
        def fetch_snapshot() -> list[FundDetail]:
            return [fund]

    monkeypatch.setattr(sync_fund_data, "get_fund_data_source", lambda _: StubSource())

    details = sync_fund_data.sync_fund_navs(db_session, "quality_stub")

    assert details["quality_warning_count"] == 1
    stored_warnings = details["quality_warnings"]
    assert isinstance(stored_warnings, list)
    first_warning = stored_warnings[0]
    assert isinstance(first_warning, dict)
    assert first_warning["code"] == "nav_outside_configured_range"
    assert details["quality_warnings_truncated"] is False
    job = db_session.scalar(
        select(JobRun).where(JobRun.name == "sync_fund_navs").order_by(JobRun.id.desc())
    )
    assert job is not None
    assert job.status == "success"
    assert job.details["quality_warning_count"] == 1


def test_reject_mode_fails_before_anomalous_nav_is_written(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "fund_nav_value_max", 10.0)
    monkeypatch.setattr(settings, "fund_nav_reject_anomalies", True)
    fund = real_fund_with_navs([NavPoint(trade_date="2026-07-10", nav=11.0, accumulated_nav=11.0)])

    with pytest.raises(NavDataQualityError, match="FUND_NAV_REJECT_ANOMALIES"):
        upsert_fund_navs(db_session, fund)

    assert (
        db_session.scalar(
            select(FundNav).where(
                FundNav.fund_code == fund.code,
                FundNav.trade_date == "2026-07-10",
            )
        )
        is None
    )


def test_sample_year_precision_remains_available_for_legacy_backtests(
    db_session: Session,
) -> None:
    row = db_session.scalar(
        select(FundNav).where(
            FundNav.fund_code == "000001",
            FundNav.trade_date == "2026",
        )
    )

    assert row is not None
    assert row.trade_date_precision == "year"


def test_nav_quality_settings_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUND_NAV_VALUE_MIN", "0.1")
    monkeypatch.setenv("FUND_NAV_VALUE_MAX", "12")
    monkeypatch.setenv("FUND_ACCUMULATED_NAV_VALUE_MIN", "0.2")
    monkeypatch.setenv("FUND_ACCUMULATED_NAV_VALUE_MAX", "34")
    monkeypatch.setenv("FUND_NAV_REJECT_ANOMALIES", "true")

    loaded = Settings()

    assert loaded.fund_nav_value_min == 0.1
    assert loaded.fund_nav_value_max == 12
    assert loaded.fund_accumulated_nav_value_min == 0.2
    assert loaded.fund_accumulated_nav_value_max == 34
    assert loaded.fund_nav_reject_anomalies is True


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    (
        ("FUND_NAV_VALUE_MIN", "nan", "FUND_NAV_VALUE_MIN"),
        ("FUND_NAV_VALUE_MAX", "0", "FUND_NAV_VALUE_MAX"),
        ("FUND_NAV_REJECT_ANOMALIES", "yes", "must be true or false"),
    ),
)
def test_nav_quality_settings_reject_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=message):
        Settings()
