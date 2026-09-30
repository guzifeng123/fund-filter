import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_sources.public_http_json import PublicHttpJsonFundDataSource
from app.data_sources.profiles.eastmoney_snapshot import (
    EastmoneyRawSnapshot,
    EastmoneySnapshotBuilder,
    build_fund_snapshot,
)
from app.db.models import Fund, FundNav, JobRun
from app.jobs.seed_sample_data import seed_sample_data
from app.jobs.sync_fund_data import sync_fund_navs
from app.repositories.funds import get_fund, upsert_fund_detail


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eastmoney_snapshot"


class FixturePublicHttpSource(PublicHttpJsonFundDataSource):
    def __init__(self) -> None:
        super().__init__(
            "https://fixture.example/",
            profile_name="eastmoney_snapshot_v1",
        )

    def _read_json(self, path: str) -> object:
        return json.loads((FIXTURE_DIR / path).read_text(encoding="utf-8"))


class FailingPublicHttpSource:
    name = "public_http_json"

    def fetch_snapshot(self) -> list[object]:
        raise RuntimeError("eastmoney snapshot mirror unavailable")


def raw_snapshot(profile_html: str | None = None) -> EastmoneyRawSnapshot:
    base_info = {
        "FCODE": "000001",
        "SHORTNAME": "华夏成长混合",
        "FTYPE": "混合型-灵活",
        "RISKLEVEL": "4",
        "JJJL": "郑晓辉,刘睿聪",
        "ISSBDATE": "2001-11-28 00:00:00",
        "ENDNAV": "2644299859.12",
        "RANKY": "358",
        "YSC": "2284",
    }
    nav_rows = [
        {"FSRQ": "2026-07-10", "DWJZ": "1.527", "LJJZ": "4.100"},
        {"FSRQ": "2025-07-10", "DWJZ": "1.300", "LJJZ": "3.600"},
        {"FSRQ": "2024-07-10", "DWJZ": "1.200", "LJJZ": "3.300"},
        {"FSRQ": "2023-07-10", "DWJZ": "1.100", "LJJZ": "3.000"},
        {"FSRQ": "2022-07-10", "DWJZ": "1.000", "LJJZ": "2.800"},
        {"FSRQ": "2021-07-09", "DWJZ": "0.900", "LJJZ": "2.500"},
    ]
    return EastmoneyRawSnapshot(
        base_info=base_info,
        nav_rows=nav_rows,
        profile_html=profile_html
        or (
            "<p><label>成立日期：<span>2001-12-18</span></label></p>"
            "<tr><th>管理费率</th><td>1.20%（每年）</td>"
            "<th>托管费率</th><td>0.20%（每年）</td></tr>"
        ),
        manager_html="<tbody><tr><td>2024-12-26</td><td>至今</td><td>郑晓辉 刘睿聪</td></tr></tbody>",
    )


def test_eastmoney_profile_builds_auditable_fund_snapshot() -> None:
    fund = build_fund_snapshot(raw_snapshot(), datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert fund.code == "000001"
    assert fund.fund_type == "mixed"
    assert fund.risk_level == "R4"
    # Inception must be the F10 establishment date (2001-12-18), never the
    # mobile payload's offer-start date ISSBDATE (2001-11-28).
    assert fund.inception_date == "2001-12-18"
    assert fund.fund_size_billion == 26.443
    assert fund.management_fee == 1.2
    assert fund.custody_fee == 0.2
    assert fund.annualized_return_3y > 0
    assert fund.annualized_return_5y > 0
    assert fund.max_drawdown <= 0
    assert fund.manager_years == 1
    assert fund.source == "eastmoney_snapshot"
    assert fund.provider_profile == "eastmoney_snapshot_v1"
    assert fund.upstream_provider == "eastmoney"
    assert fund.fee_summary is not None
    assert fund.fee_summary.total_fee == 1.4
    # The raw, un-collapsed eastmobile FTYPE detail is carried as a non-serialized
    # internal attribute for reconciliation; the stored 4-bucket fund_type is unchanged.
    assert fund._fund_type_raw == "混合型-灵活"
    assert fund.fund_type == "mixed"
    # Private attribute must not leak into the OpenAPI / JSON contract.
    from app.schemas.funds import FundDetail as _FundDetail

    assert "_fund_type_raw" not in _FundDetail.model_fields
    assert "_fund_type_raw" not in fund.model_dump(mode="json")
    assert fund.manager_profile is not None
    assert any(metric.key == "sharpe_ratio" and "250" in metric.explanation for metric in fund.metric_explanations)
    assert [point.trade_date for point in fund.navs] == sorted(point.trade_date for point in fund.navs)


def test_eastmoney_profile_rejects_missing_fee_instead_of_fabricating_it() -> None:
    with pytest.raises(ValueError, match="托管费率"):
        build_fund_snapshot(
            raw_snapshot("<tr><th>管理费率</th><td>1.20%（每年）</td></tr>"),
            datetime(2026, 7, 13, tzinfo=timezone.utc),
        )


def test_eastmoney_profile_rejects_missing_inception_instead_of_offer_start() -> None:
    # Both fees present but the F10 establishment date is absent: must fail
    # loudly rather than silently falling back to ISSBDATE (offer-start date).
    html = (
        "<tr><th>管理费率</th><td>1.20%（每年）</td>"
        "<th>托管费率</th><td>0.20%（每年）</td></tr>"
    )
    with pytest.raises(ValueError, match="成立日期"):
        build_fund_snapshot(
            raw_snapshot(html),
            datetime(2026, 7, 13, tzinfo=timezone.utc),
        )


def test_eastmoney_mirror_writes_profile_and_upstream_metadata(tmp_path: Path) -> None:
    generated_at = datetime(2026, 7, 13, tzinfo=timezone.utc)
    fund = build_fund_snapshot(raw_snapshot(), generated_at)

    manifest_path = EastmoneySnapshotBuilder().write_mirror(
        tmp_path,
        [fund],
        generated_at,
    )

    fund_payload = json.loads((tmp_path / "funds.json").read_text(encoding="utf-8"))["funds"][0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert fund_payload["source"] == "eastmoney_snapshot"
    assert fund_payload["provider_profile"] == "eastmoney_snapshot_v1"
    assert fund_payload["upstream_provider"] == "eastmoney"
    assert manifest["provider_profile"] == "eastmoney_snapshot_v1"
    assert manifest["upstream_provider"] == "eastmoney"


def test_eastmoney_normalized_fixture_is_readable_by_public_http_adapter() -> None:
    fund = FixturePublicHttpSource().fetch_fund_navs()[0]

    assert fund.code == "000001"
    assert fund.source == "eastmoney_snapshot"
    assert fund.provider_profile == "eastmoney_snapshot_v1"
    assert fund.upstream_provider == "eastmoney"
    assert [point.trade_date for point in fund.navs] == ["2021-05-25", "2026-07-10"]


def test_eastmoney_profile_metadata_remains_visible_after_persistence(
    db_session: Session,
) -> None:
    fund = FixturePublicHttpSource().fetch_fund_navs()[0]

    upsert_fund_detail(db_session, fund)
    db_session.commit()

    row = db_session.get(Fund, "000001")
    detail = get_fund(db_session, "000001", "C5")
    nav = db_session.scalars(
        select(FundNav).where(
            FundNav.fund_code == "000001",
            FundNav.trade_date == "2026-07-10",
        )
    ).one()
    assert row is not None and detail is not None
    assert row.source == "eastmoney_snapshot"
    assert row.raw_data["provider_profile"] == "eastmoney_snapshot_v1"
    assert row.raw_data["upstream_provider"] == "eastmoney"
    assert detail.source == "eastmoney_snapshot"
    assert detail.provider_profile == "eastmoney_snapshot_v1"
    assert detail.upstream_provider == "eastmoney"
    assert nav.raw_data["provider_profile"] == "eastmoney_snapshot_v1"


def test_failed_public_mirror_sync_preserves_old_rows(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_sample_data(db_session)
    original_fund_count = db_session.scalar(select(func.count()).select_from(Fund))
    original_nav_count = db_session.scalar(select(func.count()).select_from(FundNav))
    monkeypatch.setattr("app.jobs.sync_fund_data.get_fund_data_source", lambda _name: FailingPublicHttpSource())

    with pytest.raises(RuntimeError, match="mirror unavailable"):
        sync_fund_navs(db_session, "public_http_json")

    assert db_session.scalar(select(func.count()).select_from(Fund)) == original_fund_count
    assert db_session.scalar(select(func.count()).select_from(FundNav)) == original_nav_count
    latest_job = db_session.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(1)).one()
    assert latest_job.status == "failed"
    assert latest_job.details["error"] == "eastmoney snapshot mirror unavailable"
