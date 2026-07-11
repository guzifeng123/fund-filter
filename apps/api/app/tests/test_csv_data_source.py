from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_sources import get_fund_data_source
from app.data_sources.csv_local import CsvLocalFundDataSource, preflight_csv_local
from app.db.models import Fund, FundNav
from app.jobs.sync_fund_data import sync_fund_navs


def write_csv_fixture(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "funds.csv").write_text(
        "\n".join(
            [
                "code,name,fund_type,risk_level,manager_name,inception_date,fund_size_billion,management_fee,custody_fee,annualized_return_3y,annualized_return_5y,max_drawdown,sharpe_ratio,category_rank_percentile,manager_years,data_updated_at,ai_summary",
                "900001,CSV 稳健混合,mixed,R3,林一,2020-01-01,12.5,1.0,0.2,6.2,7.1,-12.3,1.21,20,5,2026-07-09T10:00:00+08:00,CSV 导入样本",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (data_dir / "navs.csv").write_text(
        "\n".join(
            [
                "fund_code,trade_date,nav,accumulated_nav",
                "900001,2024-01-02,1.1,1.1",
                "900001,2023-01-02,1.0,1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_csv_local_data_source_reads_funds_and_navs(tmp_path: Path) -> None:
    write_csv_fixture(tmp_path)

    source = CsvLocalFundDataSource(tmp_path)
    funds = source.fetch_fund_profiles()

    assert len(funds) == 1
    assert funds[0].code == "900001"
    assert funds[0].source == "csv_local"
    assert [point.trade_date for point in funds[0].navs] == ["2023-01-02", "2024-01-02"]
    assert source.fetch_risk_levels() == {"900001": "R3"}


def test_csv_local_can_be_selected_by_name() -> None:
    source = get_fund_data_source("csv_local")

    assert source.name == "csv_local"


def test_csv_local_sync_writes_database(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    write_csv_fixture(tmp_path)
    monkeypatch.setenv("FUND_CSV_DIR", str(tmp_path))
    import app.core.config as config
    import app.data_sources.csv_local as csv_local

    config.settings.fund_csv_dir = str(tmp_path)
    csv_local.settings.fund_csv_dir = str(tmp_path)

    result = sync_fund_navs(db_session, "csv_local")

    assert result == {"source": "csv_local", "fund_count": 1, "nav_count": 2}
    assert db_session.get(Fund, "900001") is not None
    assert db_session.scalar(select(func.count()).select_from(FundNav).where(FundNav.fund_code == "900001")) == 2


def test_csv_local_reports_missing_required_columns(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "funds.csv").write_text("code,name\n900001,缺字段\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required CSV columns"):
        CsvLocalFundDataSource(tmp_path).fetch_fund_profiles()


def test_csv_local_reports_invalid_numeric_field_with_line_number(tmp_path: Path) -> None:
    write_csv_fixture(tmp_path)
    funds_path = tmp_path / "funds.csv"
    funds_path.write_text(
        funds_path.read_text(encoding="utf-8").replace(",12.5,", ",not-a-number,"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"funds\.csv:2: invalid numeric CSV field fund_size_billion=not-a-number"):
        CsvLocalFundDataSource(tmp_path).fetch_fund_profiles()


def test_csv_local_preflight_reports_counts(tmp_path: Path) -> None:
    write_csv_fixture(tmp_path)

    report = preflight_csv_local(tmp_path)

    assert report["ok"] is True
    assert report["fund_count"] == 1
    assert report["nav_count"] == 2
    assert report["errors"] == []


def test_csv_local_preflight_reports_errors(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "funds.csv").write_text("code,name\n900001,缺字段\n", encoding="utf-8")

    report = preflight_csv_local(tmp_path)

    assert report["ok"] is False
    assert report["fund_count"] == 0
    assert "missing required CSV columns" in report["errors"][0]


def test_csv_local_preflight_reports_unknown_nav_fund_codes(tmp_path: Path) -> None:
    write_csv_fixture(tmp_path)
    with (tmp_path / "navs.csv").open("a", encoding="utf-8") as file:
        file.write("missing-code,2024-01-02,1.0,1.0\n")

    report = preflight_csv_local(tmp_path)

    assert report["ok"] is False
    assert report["fund_count"] == 1
    assert report["nav_count"] == 3
    assert "unknown fund codes: missing-code" in report["errors"][0]


def test_csv_local_rejects_duplicate_fund_codes_with_both_line_numbers(tmp_path: Path) -> None:
    write_csv_fixture(tmp_path)
    funds_path = tmp_path / "funds.csv"
    duplicate_row = funds_path.read_text(encoding="utf-8").splitlines()[1]
    with funds_path.open("a", encoding="utf-8") as file:
        file.write(f"{duplicate_row}\n")

    with pytest.raises(ValueError, match=r"funds\.csv:3: duplicate fund code 900001; first seen at line 2"):
        CsvLocalFundDataSource(tmp_path).fetch_fund_profiles()

    report = preflight_csv_local(tmp_path)
    assert report["ok"] is False
    assert len(report["errors"]) == 1
    assert "duplicate fund code 900001" in report["errors"][0]


def test_csv_local_rejects_duplicate_nav_keys_with_both_line_numbers(tmp_path: Path) -> None:
    write_csv_fixture(tmp_path)
    with (tmp_path / "navs.csv").open("a", encoding="utf-8") as file:
        file.write("900001,2024-01-02,1.2,1.2\n")

    with pytest.raises(ValueError, match=r"navs\.csv:4: duplicate NAV key 900001/2024-01-02; first seen at line 2"):
        CsvLocalFundDataSource(tmp_path).fetch_fund_profiles()

    report = preflight_csv_local(tmp_path)
    assert report["ok"] is False
    assert len(report["errors"]) == 1
    assert "duplicate NAV key 900001/2024-01-02" in report["errors"][0]


def test_csv_local_trims_fields_before_cross_file_and_unique_key_checks(tmp_path: Path) -> None:
    write_csv_fixture(tmp_path)
    funds_path = tmp_path / "funds.csv"
    funds_path.write_text(
        funds_path.read_text(encoding="utf-8").replace("900001,CSV", " 900001 , CSV"),
        encoding="utf-8",
    )
    navs_path = tmp_path / "navs.csv"
    navs_path.write_text(
        navs_path.read_text(encoding="utf-8").replace("900001,", " 900001 ,"),
        encoding="utf-8",
    )

    funds = CsvLocalFundDataSource(tmp_path).fetch_fund_profiles()

    assert funds[0].code == "900001"
    assert funds[0].name == "CSV 稳健混合"
    assert len(funds[0].navs) == 2
    assert preflight_csv_local(tmp_path)["ok"] is True


@pytest.mark.parametrize(
    ("filename", "old_value", "new_value", "expected"),
    [
        ("funds.csv", "2020-01-01", "2020-02-30", "invalid ISO date field inception_date=2020-02-30"),
        (
            "funds.csv",
            "2026-07-09T10:00:00+08:00",
            "not-a-datetime",
            "invalid ISO datetime field data_updated_at=not-a-datetime",
        ),
        (
            "funds.csv",
            "2026-07-09T10:00:00+08:00",
            "2026-07-09T10:00:00",
            "ISO datetime field data_updated_at must include a timezone offset",
        ),
        ("navs.csv", "2024-01-02", "2024-02-30", "invalid ISO date field trade_date=2024-02-30"),
    ],
)
def test_csv_local_rejects_invalid_iso_dates(
    tmp_path: Path,
    filename: str,
    old_value: str,
    new_value: str,
    expected: str,
) -> None:
    write_csv_fixture(tmp_path)
    path = tmp_path / filename
    path.write_text(path.read_text(encoding="utf-8").replace(old_value, new_value), encoding="utf-8")

    report = preflight_csv_local(tmp_path)

    assert report["ok"] is False
    assert any(expected in error for error in report["errors"])


@pytest.mark.parametrize(
    ("filename", "old_value", "new_value", "expected"),
    [
        ("funds.csv", ",12.5,", ",-1,", "fund_size_billion must be >= 0"),
        ("funds.csv", ",1.0,0.2,", ",101,0.2,", "management_fee must be between 0 and 100"),
        ("funds.csv", ",1.21,20,5,", ",1.21,101,5,", "category_rank_percentile must be between 0 and 100"),
        ("funds.csv", ",20,5,", ",20,5.5,", "manager_years must be a non-negative integer"),
        ("funds.csv", ",-12.3,", ",1.0,", "max_drawdown must be between -100 and 0"),
        ("navs.csv", ",1.1,1.1", ",0,1.1", "nav must be > 0"),
        ("navs.csv", ",1.1,1.1", ",1.1,NaN", "non-finite numeric CSV field accumulated_nav=NaN"),
    ],
)
def test_csv_local_rejects_out_of_range_numeric_values(
    tmp_path: Path,
    filename: str,
    old_value: str,
    new_value: str,
    expected: str,
) -> None:
    write_csv_fixture(tmp_path)
    path = tmp_path / filename
    path.write_text(path.read_text(encoding="utf-8").replace(old_value, new_value, 1), encoding="utf-8")

    report = preflight_csv_local(tmp_path)

    assert report["ok"] is False
    assert any(expected in error for error in report["errors"])
