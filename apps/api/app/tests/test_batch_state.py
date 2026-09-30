"""D0: tests for app/jobs/batch_state.py (independent SQLite checkpoint)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.core.fund_classifier import ClassifyDecision
from app.data_sources.universe import UniverseFund
from app.jobs.batch_state import BatchState


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _fund(code: str, *, major: str = "混合型", has_3y: bool = True) -> UniverseFund:
    return UniverseFund(
        code=code,
        name=f"基金{code}",
        type_major=major,
        type_detail=f"{major}-灵活",
        has_3y=has_3y,
        scale=None,
        unit_nav=None,
        acc_nav=None,
        nav_date=date(2026, 9, 30),
    )


def _decision(code: str, route: str, reason: str = "x") -> ClassifyDecision:
    return ClassifyDecision(route=route, reason=reason, detail={"code": code})  # type: ignore[arg-type]


def _state(tmp_path: Path, clock: FakeClock) -> BatchState:
    return BatchState(
        tmp_path / "state.db", now=clock, batch_size=2, claim_timeout_seconds=1800
    )


def test_build_plan_stages_supported_pending_and_shards_deterministically(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    records = [_fund(f"{i:06d}") for i in range(5)]  # 000000..000004
    decisions = {f.code: _decision(f.code, "supported") for f in records}
    with _state(tmp_path, clock) as state:
        staged = state.build_plan(records, decisions, shards=2, include_short_history=False)
        assert staged == 5
        rows = state._conn.execute(  # noqa: SLF001 - test internals directly
            "SELECT code, batch_no, shard, seq, status FROM fund_sync_state ORDER BY seq"
        ).fetchall()
        # batch_size=2: codes 0,1 -> batch 0; 2,3 -> batch 1; 4 -> batch 2.
        # shard = seq % 2.
        assert [(r["code"], r["batch_no"], r["shard"], r["seq"]) for r in rows] == [
            ("000000", 0, 0, 0),
            ("000001", 0, 1, 1),
            ("000002", 1, 0, 2),
            ("000003", 1, 1, 3),
            ("000004", 2, 0, 4),
        ]
        assert all(r["status"] == "pending" for r in rows)


def test_skipped_routes_do_not_enter_pending(tmp_path: Path) -> None:
    clock = FakeClock()
    supported = _fund("000001")
    special = _fund("000002", major="货币型")
    records = [supported, special]
    decisions = {
        "000001": _decision("000001", "supported"),
        "000002": _decision("000002", "special_caliber", "money_market"),
    }
    with _state(tmp_path, clock) as state:
        staged = state.build_plan(records, decisions, shards=1, include_short_history=False)
        assert staged == 1
        row = state._conn.execute(  # noqa: SLF001
            "SELECT status, reason FROM fund_sync_state WHERE code='000002'"
        ).fetchone()
        assert row["status"] == "skipped"
        assert row["reason"] == "money_market"


def test_claim_batches_do_not_overlap_between_workers(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund(f"{i:06d}") for i in range(5)]
    decisions = {f.code: _decision(f.code, "supported") for f in records}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=1, include_short_history=False)
        first = state.claim_batch(2, worker_id="w1")
        second = state.claim_batch(2, worker_id="w2")
        third = state.claim_batch(2, worker_id="w1")
        assert len(first) == 2
        assert len(second) == 2
        assert len(third) == 1
        assert set(first).isdisjoint(second)
        assert set(first).isdisjoint(third)
        assert set(second).isdisjoint(third)


def test_in_flight_timeout_is_reclaimed(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund("000001")]
    decisions = {"000001": _decision("000001", "supported")}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=1, include_short_history=False)
        claimed = state.claim_batch(1, worker_id="w1")
        assert claimed == ["000001"]
        # Worker dies without marking. Advance past the 1800s claim timeout.
        clock.advance(2000)
        reclaimed = state.claim_batch(1, worker_id="w2")
        assert reclaimed == ["000001"]
        row = state._conn.execute(  # noqa: SLF001
            "SELECT attempts FROM fund_sync_state WHERE code='000001'"
        ).fetchone()
        assert row["attempts"] == 2  # initial claim + reclaim


def test_mark_transitions_and_illegal_rejected(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund("000001")]
    decisions = {"000001": _decision("000001", "supported")}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=1, include_short_history=False)
        state.claim_batch(1, worker_id="w1")
        # Cannot mark_done from pending (it's in_flight now) -> ok.
        state.mark_done("000001", generation_id="gen-1", nav_points=10, fund_written=1)
        row = state._conn.execute(  # noqa: SLF001
            "SELECT status, generation_id, nav_points, done_at FROM fund_sync_state WHERE code='000001'"
        ).fetchone()
        assert row["status"] == "done"
        assert row["generation_id"] == "gen-1"
        assert row["nav_points"] == 10
        assert row["done_at"] is not None
        # Illegal: cannot mark a done row as failed.
        with pytest.raises(ValueError, match="not in_flight"):
            state.mark_failed("000001", "boom")


def test_mark_failed_then_retry_failed_resets_to_pending(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund("000001"), _fund("000002")]
    decisions = {f.code: _decision(f.code, "supported") for f in records}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=1, include_short_history=False)
        state.claim_batch(2, worker_id="w1")
        state.mark_failed("000001", "transient 503")
        assert state.retry_failed() == 1
        row = state._conn.execute(  # noqa: SLF001
            "SELECT status FROM fund_sync_state WHERE code='000001'"
        ).fetchone()
        assert row["status"] == "pending"


def test_repeated_build_plan_is_idempotent(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund("000001")]
    decisions = {"000001": _decision("000001", "supported")}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=1, include_short_history=False)
        state.claim_batch(1, worker_id="w1")
        state.mark_done("000001", generation_id="gen-1")
        # Rebuild the identical plan: must not duplicate rows or reset done.
        state.build_plan(records, decisions, shards=1, include_short_history=False)
        count = state._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) AS c FROM fund_sync_state"
        ).fetchone()["c"]
        assert count == 1
        row = state._conn.execute(  # noqa: SLF001
            "SELECT status FROM fund_sync_state WHERE code='000001'"
        ).fetchone()
        assert row["status"] == "done"


def test_stats_aggregates(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund("000001"), _fund("000002"), _fund("000003", major="货币型")]
    decisions = {
        "000001": _decision("000001", "supported"),
        "000002": _decision("000002", "supported"),
        "000003": _decision("000003", "special_caliber", "money_market"),
    }
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=1, include_short_history=False)
        state.claim_batch(1, worker_id="w1")  # claims 000001
        state.mark_done("000001", generation_id="g1")
        stats = state.stats()
        assert stats.total == 3
        assert stats.done == 1
        assert stats.pending == 1  # 000002
        assert stats.skipped == 1  # 000003
        assert stats.by_fund_type["混合型"] == 2
