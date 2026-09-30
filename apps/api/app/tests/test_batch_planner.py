"""D1: tests for app/jobs/batch_planner.py.

All samples are inline pandas DataFrames mimicking akshare's Chinese columns;
the network is never touched (fetcher injected, state.db on tmp_path).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

from app.data_sources.universe import UniverseFilters
from app.jobs.batch_planner import PlanSummary, create_batch_plan
from app.jobs.batch_state import BatchState

EPOCH_MS = 1_790_640_000_000  # 2026-09-28 UTC


def _rank_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"基金代码": "000001", "基金简称": "华夏成长混合", "单位净值": 1.1, "累计净值": 3.0, "日期": EPOCH_MS, "近3年": 30.0},
            {"基金代码": "000002", "基金简称": "华夏现金增利货币A", "单位净值": 1.0, "累计净值": 1.0, "日期": EPOCH_MS, "近3年": None},
            {"基金代码": "000003", "基金简称": "新成立短历史混合", "单位净值": 1.0, "累计净值": 1.0, "日期": EPOCH_MS, "近3年": None},
            {"基金代码": "000004", "基金简称": "某券商资管集合计划", "单位净值": 1.0, "累计净值": 1.0, "日期": EPOCH_MS, "近3年": 5.0},
            {"基金代码": "000005", "基金简称": "易方达稳健收益债券", "单位净值": 1.8, "累计净值": 2.0, "日期": EPOCH_MS, "近3年": 20.0},
            {"基金代码": "000006", "基金简称": "富国天惠混合", "单位净值": 2.1, "累计净值": 4.0, "日期": EPOCH_MS, "近3年": 15.0},
        ]
    )


def _name_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"基金代码": "000001", "基金类型": "混合型-灵活"},
            {"基金代码": "000002", "基金类型": "货币型-普通"},
            {"基金代码": "000003", "基金类型": "混合型-灵活"},
            {"基金代码": "000004", "基金类型": "混合型-灵活"},
            {"基金代码": "000005", "基金类型": "债券型-长债"},
            {"基金代码": "000006", "基金类型": "混合型-灵活"},
        ]
    )


def _fetcher() -> tuple[pd.DataFrame, pd.DataFrame]:
    return _rank_df(), _name_df()


def _plan(
    tmp_path: Path,
    *,
    shards: int = 1,
    include_short_history: bool = False,
    limit: int | None = None,
    codes: frozenset[str] | None = None,
) -> PlanSummary:
    state = BatchState(
        tmp_path / "state.db", batch_size=2, claim_timeout_seconds=1800
    )
    try:
        return create_batch_plan(
            state=state,
            filters=UniverseFilters(),
            shards=shards,
            include_short_history=include_short_history,
            limit=limit,
            codes=codes,
            cache_dir=tmp_path / "universe",
            fetcher=_fetcher,
        )
    finally:
        state.close()


def test_plan_routes_pending_and_skipped_counts(tmp_path: Path) -> None:
    payload = _plan(tmp_path, shards=2, include_short_history=False).to_dict()
    # require_has_3y=True drops 000002 (货币) and 000003 (short history).
    # 000004 (资管) survives the filter but the classifier marks it secondary.
    assert payload["total_universe"] == 4
    assert payload["pending"] == 3  # 000001, 000005, 000006
    assert payload["batches"] == 2
    assert payload["shards"] == 2
    assert payload["routes"] == {"supported": 3, "unsupported_secondary": 1}
    assert payload["skipped"] == {"broker_asset_management": 1}


def test_deterministic_shard_and_batch_numbering(tmp_path: Path) -> None:
    state = BatchState(
        tmp_path / "state.db", batch_size=2, claim_timeout_seconds=1800
    )
    try:
        create_batch_plan(
            state=state,
            filters=UniverseFilters(),
            shards=3,
            include_short_history=False,
            cache_dir=tmp_path / "u",
            fetcher=_fetcher,
        )
        rows = state._conn.execute(  # noqa: SLF001
            "SELECT code, batch_no, shard, seq FROM fund_sync_state WHERE status='pending' ORDER BY seq"
        ).fetchall()
        # pending order by code: 000001, 000005, 000006 (资管 skipped).
        assert [(r["code"], r["batch_no"], r["shard"], r["seq"]) for r in rows] == [
            ("000001", 0, 0, 0),
            ("000005", 0, 1, 1),
            ("000006", 1, 2, 2),
        ]
    finally:
        state.close()


def test_limit_truncates_eligible_after_sort(tmp_path: Path) -> None:
    payload = _plan(tmp_path, shards=2, include_short_history=False, limit=2).to_dict()
    assert payload["pending"] == 2
    assert payload["total_universe"] == 4

    state = BatchState(
        tmp_path / "state2.db", batch_size=2, claim_timeout_seconds=1800
    )
    try:
        create_batch_plan(
            state=state,
            filters=UniverseFilters(),
            shards=2,
            include_short_history=False,
            limit=2,
            cache_dir=tmp_path / "u2",
            fetcher=_fetcher,
        )
        pending_codes = [
            r["code"]
            for r in state._conn.execute(  # noqa: SLF001
                "SELECT code FROM fund_sync_state WHERE status='pending' ORDER BY seq"
            ).fetchall()
        ]
        assert pending_codes == ["000001", "000005"]
    finally:
        state.close()


def test_codes_allow_list_restricts_universe(tmp_path: Path) -> None:
    payload = _plan(
        tmp_path,
        shards=1,
        include_short_history=False,
        codes=frozenset({"000001", "000006"}),
    ).to_dict()
    assert payload["total_universe"] == 2
    assert payload["pending"] == 2


def test_short_history_switch_flips_inclusion(tmp_path: Path) -> None:
    off = _plan(tmp_path / "off", shards=1, include_short_history=False).to_dict()
    on = _plan(tmp_path / "on", shards=1, include_short_history=True).to_dict()
    # Switch on: short-history 000003 becomes supported; money-market 000002
    # flows through and is routed to special_caliber instead of pre-filtered.
    assert off["pending"] == 3
    assert on["pending"] == 4
    assert on["routes"] == {
        "supported": 4,
        "unsupported_secondary": 1,
        "special_caliber": 1,
    }


def test_repeated_plan_is_idempotent_and_keeps_progress(tmp_path: Path) -> None:
    state = BatchState(
        tmp_path / "state.db", batch_size=2, claim_timeout_seconds=1800
    )
    try:
        create_batch_plan(
            state=state,
            filters=UniverseFilters(),
            shards=2,
            include_short_history=False,
            cache_dir=tmp_path / "u",
            fetcher=_fetcher,
        )
        claimed = state.claim_batch(1, "w1", shards=2, shard=0)
        assert claimed
        state.mark_done(claimed[0], generation_id="g1")
        before = state._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) AS c FROM fund_sync_state"
        ).fetchone()["c"]
        # Rebuild the identical plan: no dup rows, done progress preserved.
        create_batch_plan(
            state=state,
            filters=UniverseFilters(),
            shards=2,
            include_short_history=False,
            cache_dir=tmp_path / "u",
            fetcher=_fetcher,
        )
        after = state._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) AS c FROM fund_sync_state"
        ).fetchone()["c"]
        assert after == before
        row = state._conn.execute(  # noqa: SLF001
            "SELECT status FROM fund_sync_state WHERE code=?", (claimed[0],)
        ).fetchone()
        assert row["status"] == "done"
    finally:
        state.close()
