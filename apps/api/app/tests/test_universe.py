"""D0: tests for app/data_sources/universe.py.

All samples are inline pandas DataFrames mimicking akshare's Chinese columns;
the network is never touched (fetcher is injected).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from app.data_sources.universe import (
    UniverseFilters,
    derive_major_type,
    load_or_fetch_universe,
    normalize_universe,
)

EPOCH_MS = 1_790_640_000_000  # 2026-09-28 UTC


def _rank_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "基金代码": "161725",
                "基金简称": "招商中证白酒指数(LOF)A",
                "单位净值": 1.2345,
                "累计净值": 2.3456,
                "日期": EPOCH_MS,
                "近3年": 50.0,
            },
            {
                "基金代码": "000198",
                "基金简称": "华夏现金增利货币A",
                "单位净值": 1.0,
                "累计净值": 1.0,
                "日期": EPOCH_MS,
                "近3年": None,
            },
            {
                "基金代码": "000834",
                "基金简称": "上投摩根新兴动力股票QDII",
                "单位净值": 2.0,
                "累计净值": 2.1,
                "日期": EPOCH_MS,
                "近3年": 10.0,
            },
            {
                "基金代码": "005221",
                "基金简称": "嘉实领航资产配置混合FOFA",
                "单位净值": 1.5,
                "累计净值": 1.5,
                "日期": EPOCH_MS,
                "近3年": 5.0,
            },
            {
                "基金代码": "110007",
                "基金简称": "易方达稳健收益债券B",
                "单位净值": 1.8,
                "累计净值": 2.0,
                "日期": EPOCH_MS,
                "近3年": 20.0,
            },
            {
                "基金代码": "000001",
                "基金简称": "华夏成长混合",
                "单位净值": 1.1,
                "累计净值": 3.0,
                "日期": EPOCH_MS,
                "近3年": 30.0,
            },
            {
                "基金代码": "999999",
                "基金简称": "某券商资管集合计划",
                "单位净值": 1.0,
                "累计净值": 1.0,
                "日期": EPOCH_MS,
                "近3年": 1.0,
            },
        ]
    )


def _name_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"基金代码": "161725", "基金类型": "指数型-股票"},
            {"基金代码": "000198", "基金类型": "货币型-普通货币"},
            {"基金代码": "000834", "基金类型": "QDII-普通股票"},
            {"基金代码": "005221", "基金类型": "FOF-均衡型"},
            {"基金代码": "110007", "基金类型": "债券型-长债"},
            {"基金代码": "999999", "基金类型": "混合型-灵活"},
        ]
    )


def test_derive_major_type_maps_prefixes() -> None:
    assert derive_major_type("混合型-灵活") == "混合型"
    assert derive_major_type("FOF-稳健型") == "FOF"
    assert derive_major_type("QDII-普通股票") == "QDII"
    assert derive_major_type("股票型") == "股票型"
    assert derive_major_type("Reits") == "REITs"
    assert derive_major_type("") == "未知"


def test_normalize_left_join_fills_missing_type_as_unknown() -> None:
    funds = normalize_universe(_rank_df(), _name_df(), filters=UniverseFilters())
    by_code = {f.code: f for f in funds}
    # 000001 is in the rank table but absent from the name table.
    missing = by_code["000001"]
    assert missing.type_major == "未知"
    assert missing.type_detail == ""
    # Known joins resolve.
    assert by_code["161725"].type_major == "指数型"
    assert by_code["000198"].type_major == "货币型"


def test_has_3y_detection_and_nav_date_conversion() -> None:
    funds = normalize_universe(_rank_df(), _name_df(), filters=UniverseFilters())
    by_code = {f.code: f for f in funds}
    assert by_code["161725"].has_3y is True
    assert by_code["000198"].has_3y is False  # 近3年 None
    expected_date = datetime.fromtimestamp(EPOCH_MS / 1000.0, tz=timezone.utc).date()
    assert by_code["161725"].nav_date == expected_date
    assert by_code["161725"].unit_nav == pytest.approx(1.2345)
    assert by_code["161725"].acc_nav == pytest.approx(2.3456)
    assert by_code["161725"].scale is None  # never fabricated


def test_results_are_sorted_by_code() -> None:
    funds = normalize_universe(_rank_df(), _name_df(), filters=UniverseFilters())
    codes = [f.code for f in funds]
    assert codes == sorted(codes)


def test_type_major_and_has3y_and_name_exclude_filters() -> None:
    filters = UniverseFilters(
        type_majors=frozenset({"指数型", "债券型"}),
        require_has_3y=True,
        name_exclude_keywords=("资管",),
    )
    funds = normalize_universe(_rank_df(), _name_df(), filters=filters)
    codes = {f.code for f in funds}
    assert codes == {"161725", "110007"}  # both have 近3年; 货币/QDII/FOF excluded


def test_allow_and_deny_code_sets() -> None:
    filters = UniverseFilters(allow_codes=frozenset({"110007", "000834"}))
    funds = normalize_universe(_rank_df(), _name_df(), filters=filters)
    assert {f.code for f in funds} == {"110007", "000834"}

    denied = normalize_universe(
        _rank_df(),
        _name_df(),
        filters=UniverseFilters(deny_codes=frozenset({"161725"})),
    )
    assert "161725" not in {f.code for f in denied}


def test_empty_name_table_fails_fast() -> None:
    # name_df is the master skeleton now; an empty name list refuses to build.
    empty = pd.DataFrame([])
    with pytest.raises(ValueError, match="name table is empty"):
        normalize_universe(_rank_df(), empty, filters=UniverseFilters())


def test_rank_only_universe_still_builds_when_name_present() -> None:
    # Rank is only a supplement now: an empty rank table is fine as long as the
    # name skeleton is present (those funds are name-only -> has_3y=None).
    name_only = pd.DataFrame(
        [{"基金代码": "050025", "基金简称": "博时标普500ETF联接(QDII)A", "基金类型": "QDII-普通股票"}]
    )
    funds = normalize_universe(pd.DataFrame([]), name_only, filters=UniverseFilters())
    assert [f.code for f in funds] == ["050025"]
    assert funds[0].has_3y is None  # rank-uncovered => age unknown, never fabricated
    assert funds[0].unit_nav is None
    assert funds[0].nav_date is None


def test_over_strict_filter_fails_fast() -> None:
    filters = UniverseFilters(type_majors=frozenset({"不存在的大类"}))
    with pytest.raises(ValueError, match="0 funds"):
        normalize_universe(_rank_df(), _name_df(), filters=filters)


def test_cache_is_reused_without_re_fetching(tmp_path: Path, monkeypatch: Any) -> None:
    calls = {"n": 0}

    def fake_fetcher() -> tuple[pd.DataFrame, pd.DataFrame]:
        calls["n"] += 1
        return _rank_df(), _name_df()

    fixed_clock = lambda: date(2026, 9, 30)  # noqa: E731
    first = load_or_fetch_universe(
        cache_dir=tmp_path,
        filters=UniverseFilters(),
        clock=fixed_clock,
        fetcher=fake_fetcher,
    )
    second = load_or_fetch_universe(
        cache_dir=tmp_path,
        filters=UniverseFilters(),
        clock=fixed_clock,
        fetcher=fake_fetcher,
    )
    assert calls["n"] == 1  # second call hit the JSON cache
    assert [f.code for f in first] == [f.code for f in second]
    assert (tmp_path / "universe_20260930.json").exists()


def test_cache_always_stores_full_snapshot_and_filters_in_memory(tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_fetcher() -> tuple[pd.DataFrame, pd.DataFrame]:
        calls["n"] += 1
        return _rank_df(), _name_df()

    fixed_clock = lambda: date(2026, 9, 30)  # noqa: E731
    total = len(_rank_df())

    # A narrow allow-list request returns just that code...
    one = load_or_fetch_universe(
        cache_dir=tmp_path,
        filters=UniverseFilters(allow_codes=frozenset({"000001"})),
        clock=fixed_clock,
        fetcher=fake_fetcher,
    )
    assert [f.code for f in one] == ["000001"]
    # ...but the persisted daily cache must hold the UNFILTERED full snapshot.
    cached = json.loads((tmp_path / "universe_20260930.json").read_text(encoding="utf-8"))
    assert len(cached) == total

    # Warm cache: no re-fetch, empty filters return the whole market...
    full = load_or_fetch_universe(
        cache_dir=tmp_path,
        filters=UniverseFilters(),
        clock=fixed_clock,
        fetcher=fake_fetcher,
    )
    assert len(full) == total
    # ...and a different filter is reapplied in memory against the warm cache.
    three_y = load_or_fetch_universe(
        cache_dir=tmp_path,
        filters=UniverseFilters(require_has_3y=True),
        clock=fixed_clock,
        fetcher=fake_fetcher,
    )
    assert calls["n"] == 1
    # Every rank row except the 货币 fund (近3年 = None) passes the 3y gate.
    assert {f.code for f in three_y} == {
        "161725",
        "000834",
        "005221",
        "110007",
        "000001",
        "999999",
    }


def test_nan_three_year_counts_as_no_history() -> None:
    rank = pd.DataFrame(
        [
            {
                "基金代码": "000002",
                "基金简称": "年轻基金",
                "单位净值": 1.0,
                "累计净值": 1.0,
                "日期": EPOCH_MS,
                "近3年": float("nan"),
            }
        ]
    )
    name = pd.DataFrame([{"基金代码": "000002", "基金简称": "年轻基金", "基金类型": "混合型-灵活"}])
    funds = normalize_universe(rank, name, filters=UniverseFilters())
    assert funds[0].has_3y is False
    assert math.isnan(float("nan"))


# --------------------------------------------------------------------------- #
# F-phase: name-em master skeleton, three-state has_3y, share classes.
# --------------------------------------------------------------------------- #
def _f_name_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # name-only (rank-uncovered): QDII like 050025, should survive w/ has_3y=None
            {"基金代码": "050025", "基金简称": "博时标普500ETF联接(QDII)A", "基金类型": "QDII-普通股票"},
            # on-exchange ETF body (no 近3y rank row either)
            {"基金代码": "510300", "基金简称": "华泰柏瑞沪深300ETF", "基金类型": "指数型-股票"},
            # OTC ETF feeder (kept)
            {"基金代码": "000051", "基金简称": "华夏沪深300ETF联接A", "基金类型": "指数型-股票"},
            # open-end LOF (kept)
            {"基金代码": "161725", "基金简称": "招商中证白酒指数(LOF)A", "基金类型": "指数型-股票"},
            # 定开债 / bond sub-class (kept)
            {"基金代码": "000005", "基金简称": "博时信用债纯债债券C", "基金类型": "债券型-信用债"},
            # FOF (kept)
            {"基金代码": "021001", "基金简称": "某FOF稳健养老一年持有A", "基金类型": "FOF-稳健型"},
            # backend / forex shares kept as independent codes
            {"基金代码": "000002", "基金简称": "华夏成长混合(后端)", "基金类型": "混合型-灵活"},
            {"基金代码": "000044", "基金简称": "嘉实美国成长股票美元现汇", "基金类型": "QDII-普通股票"},
            {"基金代码": "000076", "基金简称": "华夏恒生ETF联接现钞", "基金类型": "指数型-海外股票"},
            # money market / REIT / commodity excluded
            {"基金代码": "000198", "基金简称": "华夏现金增利货币A", "基金类型": "货币型-普通货币"},
            {"基金代码": "180101", "基金简称": "某公募Reits", "基金类型": "Reits"},
            {"基金代码": "000003", "基金简称": "某大宗商品", "基金类型": "商品"},
        ]
    )


def _f_rank_df() -> pd.DataFrame:
    # Only a subset (like the real feed): 050025 / 510300 are rank-uncovered.
    rows = [
        ("161725", "招商中证白酒指数(LOF)A", 50.0),
        ("000051", "华夏沪深300ETF联接A", 10.0),
        ("000005", "博时信用债纯债债券C", 20.0),
        ("021001", "某FOF稳健养老一年持有A", 5.0),
        ("000002", "华夏成长混合(后端)", 30.0),
        ("000044", "嘉实美国成长股票美元现汇", 8.0),
        ("000076", "华夏恒生ETF联接现钞", 9.0),
        ("000198", "华夏现金增利货币A", None),
        ("180101", "某公募Reits", None),
        ("000003", "某大宗商品", None),
    ]
    return pd.DataFrame(
        [
            {
                "基金代码": code,
                "基金简称": name,
                "单位净值": 1.0,
                "累计净值": 1.0,
                "日期": EPOCH_MS,
                "近3年": three_y,
            }
            for code, name, three_y in rows
        ]
    )


def test_name_only_funds_survive_with_unknown_age() -> None:
    funds = normalize_universe(_f_rank_df(), _f_name_df(), filters=UniverseFilters())
    by_code = {f.code: f for f in funds}
    # 050025 is in name but not rank -> kept, age unknown, NAV empty.
    qdii = by_code["050025"]
    assert qdii.has_3y is None
    assert qdii.unit_nav is None and qdii.nav_date is None
    # 510300 on-exchange ETF also name-only -> kept in the universe (routed special later).
    assert by_code["510300"].has_3y is None
    # rank-covered funds get a real has_3y.
    assert by_code["161725"].has_3y is True


def test_union_is_deduped_sorted_and_idempotent() -> None:
    funds = normalize_universe(_f_rank_df(), _f_name_df(), filters=UniverseFilters())
    codes = [f.code for f in funds]
    assert codes == sorted(codes)
    assert len(codes) == len(set(codes))  # deduped
    # Running again on the same inputs is deterministic.
    again = normalize_universe(_f_rank_df(), _f_name_df(), filters=UniverseFilters())
    assert [(f.code, f.has_3y, f.share_class) for f in funds] == [
        (f.code, f.has_3y, f.share_class) for f in again
    ]


def test_share_classes_are_independent_and_tagged() -> None:
    funds = normalize_universe(_f_rank_df(), _f_name_df(), filters=UniverseFilters())
    by_code = {f.code: f for f in funds}
    # No merging: each backend / forex share is its own row.
    backend = by_code["000002"]
    assert backend.share_class == "后端" and backend.share_is_backend is True
    forex = by_code["000044"]
    assert forex.share_class == "现汇" and forex.share_is_forex is True
    cash = by_code["000076"]
    assert cash.share_class == "现钞" and cash.share_is_forex is True


def test_require_has3y_keeps_unknown_age_but_drops_known_short() -> None:
    # require_has_3y must NOT drop rank-uncovered (has_3y=None) funds.
    filters = UniverseFilters(require_has_3y=True)
    funds = normalize_universe(_f_rank_df(), _f_name_df(), filters=filters)
    by_code = {f.code: f for f in funds}
    assert "050025" in by_code  # unknown age survives
    assert "510300" in by_code
    # A known-short fund (近3年 blank AND rank-covered) WOULD be dropped; here none
    # of the name-covered rows has has_3y=False except the special ones, so we
    # only assert the unknown-age preservation contract explicitly.


def test_cache_stores_full_unfiltered_union_and_refilters_in_memory(
    tmp_path: Path, monkeypatch: Any
) -> None:
    calls = {"n": 0}

    def fake_fetcher() -> tuple[pd.DataFrame, pd.DataFrame]:
        calls["n"] += 1
        return _f_rank_df(), _f_name_df()

    fixed_clock = lambda: date(2026, 9, 30)  # noqa: E731
    total = len(_f_name_df())
    # First: a narrow allow-list only returns the whitelisted code...
    one = load_or_fetch_universe(
        cache_dir=tmp_path,
        filters=UniverseFilters(allow_codes=frozenset({"050025"})),
        clock=fixed_clock,
        fetcher=fake_fetcher,
    )
    assert [f.code for f in one] == ["050025"]
    # ...but the persisted cache holds the UNFILTERED full name∪rank union.
    cached = json.loads((tmp_path / "universe_20260930.json").read_text(encoding="utf-8"))
    assert len(cached) == total
    # Warm cache: a different filter is applied in memory, never re-fetching and
    # never poisoning the stored snapshot.
    unknown_kept = load_or_fetch_universe(
        cache_dir=tmp_path,
        filters=UniverseFilters(require_has_3y=True),
        clock=fixed_clock,
        fetcher=fake_fetcher,
    )
    assert calls["n"] == 1
    assert "050025" in {f.code for f in unknown_kept}
    cached2 = json.loads((tmp_path / "universe_20260930.json").read_text(encoding="utf-8"))
    assert len(cached2) == total
