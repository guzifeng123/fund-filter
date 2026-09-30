"""G-stage offline fixture tests for the ordinary-QDII mobile FTYPE mapping gap.

No network: every case feeds a canned :class:`EastmoneyRawSnapshot` through
``build_fund_snapshot`` / ``_normalize_fund_type``. Covers the 7 ordinary QDII
subclasses, the dict-insertion-order traps, the special-caliber commodity/REIT
backstop, the fail-closed raise on unknown FTYPEs, and the ``_fund_type_raw``
audit attribute.
"""
from datetime import datetime, timezone

import pytest

from app.data_sources.profiles.eastmoney_snapshot import (
    FUND_TYPE_PREFIXES,
    EastmoneyRawSnapshot,
    _normalize_fund_type,
    build_fund_snapshot,
)
from app.schemas.funds import FundDetail


def _raw_snapshot(ftype: str, *, code: str = "000044", name: str = "测试QDII") -> EastmoneyRawSnapshot:
    base_info = {
        "FCODE": code,
        "SHORTNAME": name,
        "FTYPE": ftype,
        "RISKLEVEL": "4",
        "JJJL": "张三,李四",
        "ISSBDATE": "2010-01-01 00:00:00",
        "ENDNAV": "1000000000.00",
        "RANKY": "100",
        "YSC": "500",
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
        profile_html=(
            "<p><label>成立日期：<span>2010-06-30</span></label></p>"
            "<tr><th>管理费率</th><td>1.20%（每年）</td>"
            "<th>托管费率</th><td>0.20%（每年）</td></tr>"
        ),
        manager_html="<tbody><tr><td>2020-01-01</td><td>至今</td><td>张三 李四</td></tr></tbody>",
    )


# The 7 ordinary QDII subclasses observed on the live mobile endpoint, mapped to
# their storage bucket. Evidence (eastmoney FTYPE vs danjuan type_desc, both ->
# reconciliation "qdii") lives under output/g-qdii/evidence_type_mapping.json.
@pytest.mark.parametrize(
    ("ftype", "expected_bucket"),
    [
        ("QDII-混合偏股", "mixed"),
        ("QDII-普通股票", "stock"),
        ("QDII-纯债", "bond"),
        ("QDII-混合灵活", "mixed"),
        ("QDII-混合债", "bond"),
        ("QDII-混合平衡", "mixed"),
        ("QDII-FOF", "mixed"),
    ],
)
def test_ordinary_qdii_ftype_maps_to_expected_bucket(ftype: str, expected_bucket: str) -> None:
    assert _normalize_fund_type(ftype) == expected_bucket


def test_qdii_fof_not_stolen_by_generic_qdii_catch_all() -> None:
    # Ordering trap: the explicit "QDII-FOF" key must win over the bare "QDII"
    # catch-all, otherwise FOF would still land in mixed -- same bucket here, but
    # the assertion pins the intended explicit-first behaviour.
    keys = list(FUND_TYPE_PREFIXES)
    assert keys.index("QDII-FOF") < keys.index("QDII")
    assert _normalize_fund_type("QDII-FOF") == "mixed"


def test_qdii_mixed_bond_not_stolen_into_mixed() -> None:
    # Ordering trap: "QDII-混合债" must NOT match a broad "QDII-混合" key (we
    # deliberately ship none) and must land in ``bond``, not ``mixed``.
    assert "QDII-混合" not in FUND_TYPE_PREFIXES
    assert _normalize_fund_type("QDII-混合债") == "bond"


def test_generic_qdii_catch_all_does_not_default_to_stock() -> None:
    # Requirement: unmapped QDII must not silently become equity; balanced mixed.
    assert _normalize_fund_type("QDII") == "mixed"
    assert _normalize_fund_type("QDII-某未预见海外子类") == "mixed"


@pytest.mark.parametrize("special", ["QDII-商品", "QDII-REITs", "QDII-REIT"])
def test_qdii_commodity_and_reits_rejected_before_catch_all(special: str) -> None:
    # Special caliber never collapses into an ordinary bucket even if it reaches
    # the builder (normally fund_classifier intercepts these upstream).
    with pytest.raises(ValueError, match="special caliber"):
        _normalize_fund_type(special)


@pytest.mark.parametrize("unknown", ["另类投资型", "期货型", "REITs", "商品型", "混合"])
def test_unknown_ftype_still_fails_closed(unknown: str) -> None:
    # Fail-closed: an unrecognized major must raise, never silently become stock.
    with pytest.raises(ValueError, match="unsupported eastmoney fund type"):
        _normalize_fund_type(unknown)


@pytest.mark.parametrize(
    ("ftype", "expected_bucket"),
    [
        ("QDII-混合偏股", "mixed"),
        ("QDII-普通股票", "stock"),
        ("QDII-纯债", "bond"),
        ("QDII-混合灵活", "mixed"),
        ("QDII-混合债", "bond"),
        ("QDII-混合平衡", "mixed"),
        ("QDII-FOF", "mixed"),
    ],
)
def test_build_layer_accepts_ordinary_qdii_without_raising(ftype: str, expected_bucket: str) -> None:
    # The builder used to raise "unsupported eastmoney fund type" for every QDII
    # FTYPE before reaching reconciliation; these must now produce a FundDetail.
    fund = build_fund_snapshot(_raw_snapshot(ftype), datetime(2026, 7, 13, tzinfo=timezone.utc))
    assert isinstance(fund, FundDetail)
    assert fund.fund_type == expected_bucket
    # The raw mobile FTYPE is preserved verbatim as an audit attribute.
    assert fund._fund_type_raw == ftype
    # Private attr must not leak into the JSON / OpenAPI contract.
    assert "_fund_type_raw" not in FundDetail.model_fields
    assert "_fund_type_raw" not in fund.model_dump(mode="json")


@pytest.mark.parametrize("special", ["QDII-商品", "QDII-REITs"])
def test_build_layer_still_rejects_special_caliber_ftype(special: str) -> None:
    with pytest.raises(ValueError, match="unsupported eastmoney fund type"):
        build_fund_snapshot(_raw_snapshot(special), datetime(2026, 7, 13, tzinfo=timezone.utc))
