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


def test_empty_rank_table_fails_fast() -> None:
    empty = pd.DataFrame([])
    with pytest.raises(ValueError, match="empty"):
        normalize_universe(empty, _name_df(), filters=UniverseFilters())


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
    funds = normalize_universe(rank, pd.DataFrame([]), filters=UniverseFilters())
    assert funds[0].has_3y is False
    assert math.isnan(float("nan"))
