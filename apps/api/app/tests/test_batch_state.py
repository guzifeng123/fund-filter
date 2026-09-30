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


# ----------------------------------------------------------------- sharded claim


def test_shard_assignment_is_deterministic_by_seq_mod_shards(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund(f"{i:06d}") for i in range(6)]
    decisions = {f.code: _decision(f.code, "supported") for f in records}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=3, include_short_history=False)
        rows = state._conn.execute(  # noqa: SLF001
            "SELECT code, shard, seq, batch_no FROM fund_sync_state ORDER BY seq"
        ).fetchall()
        assert [(r["code"], r["shard"], r["seq"], r["batch_no"]) for r in rows] == [
            ("000000", 0, 0, 0),
            ("000001", 1, 1, 0),
            ("000002", 2, 2, 1),  # batch_size=2: seq 2 starts batch 1
            ("000003", 0, 3, 1),
            ("000004", 1, 4, 2),
            ("000005", 2, 5, 2),
        ]


def test_sharded_claim_is_disjoint_and_covers_all_pending(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund(f"{i:06d}") for i in range(9)]
    decisions = {f.code: _decision(f.code, "supported") for f in records}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=3, include_short_history=False)
        per_shard = [state.claim_batch(10, f"w{s}", shards=3, shard=s) for s in range(3)]
        assert sum(len(codes) for codes in per_shard) == 9
        assert set(per_shard[0]).isdisjoint(per_shard[1])
        assert set(per_shard[0]).isdisjoint(per_shard[2])
        assert set(per_shard[1]).isdisjoint(per_shard[2])
        union = set(per_shard[0]) | set(per_shard[1]) | set(per_shard[2])
        assert union == {fund.code for fund in records}


def test_sharded_timeout_reclaim_stays_within_shard(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund(f"{i:06d}") for i in range(4)]
    decisions = {f.code: _decision(f.code, "supported") for f in records}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=2, include_short_history=False)
        # shard 0 worker dies while holding its pending rows.
        held = state.claim_batch(10, "w0", shards=2, shard=0)
        assert held == ["000000", "000002"]
        clock.advance(2000)  # past the 1800s claim timeout
        # shard 1 worker must not reclaim shard 0's timed-out in-flight rows.
        shard1 = state.claim_batch(10, "w1", shards=2, shard=1)
        assert set(shard1).isdisjoint(held)
        # shard 0 worker reclaims exactly its own timed-out rows.
        shard0 = state.claim_batch(10, "w2", shards=2, shard=0)
        assert set(shard0) == set(held)


def test_shard_validation_rejects_unpaired_and_out_of_range(tmp_path: Path) -> None:
    clock = FakeClock()
    records = [_fund("000001")]
    decisions = {"000001": _decision("000001", "supported")}
    with _state(tmp_path, clock) as state:
        state.build_plan(records, decisions, shards=1, include_short_history=False)
        with pytest.raises(ValueError, match="shards and shard must be provided together"):
            state.claim_batch(1, "w", shard=0)
        with pytest.raises(ValueError, match="shards and shard must be provided together"):
            state.claim_batch(1, "w", shards=2)
        with pytest.raises(ValueError, match="shard must be in"):
            state.claim_batch(1, "w", shards=2, shard=2)


# ------------------------------------------------- explicit-transaction build_plan


_REPRESENTATIVE_CODES = ("050025", "161725", "510300")


def _spread_codes(n: int) -> list[str]:
    """Deterministically spread ``n`` unique 6-digit codes across 000000..999999."""
    seen: set[str] = set(_REPRESENTATIVE_CODES)
    codes: list[str] = list(_REPRESENTATIVE_CODES)
    i = 0
    while len(codes) < n:
        c = f"{(i * 47) % 1_000_000:06d}"
        i += 1
        if c not in seen:
            seen.add(c)
            codes.append(c)
    return codes


def _route_for(code: str) -> str:
    # Buckets by code value; overridden below for the three representative codes.
    bucket = int(code) % 4
    if code == "510300":
        return "special_caliber"
    if code in ("050025", "161725"):
        return "supported"
    return ("supported", "special_caliber", "unsupported_secondary", "new_short_history")[bucket]  # noqa: E501


def _has3y_for(code: str) -> bool | None:
    return (True, False, None)[int(code) % 3]


def _big_universe(n: int = 21000) -> tuple[list[UniverseFund], dict[str, ClassifyDecision]]:
    funds = [
        UniverseFund(
            code=c,
            name=f"基金{c}",
            type_major="混合型",
            type_detail="混合型-灵活",
            has_3y=_has3y_for(c),
            scale=None,
            unit_nav=None,
            acc_nav=None,
            nav_date=date(2026, 9, 30),
        )
        for c in _spread_codes(n)
    ]
    decisions = {
        f.code: ClassifyDecision(
            route=_route_for(f.code),  # type: ignore[arg-type]
            reason=f"r:{_route_for(f.code)}",
            detail={"code": f.code},
        )
        for f in funds
    }
    return funds, decisions


def test_build_plan_large_scale_21k_routes_and_indexes_deterministic(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    records, decisions = _big_universe(21000)
    shards = 1
    batch_size = 100
    with BatchState(
        tmp_path / "state.db", now=clock, batch_size=batch_size, claim_timeout_seconds=1800
    ) as state:
        staged = state.build_plan(
            records, decisions, shards=shards, include_short_history=True
        )

        # --- totals -------------------------------------------------
        total = state._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) AS c FROM fund_sync_state"
        ).fetchone()["c"]
        assert total == 21000

        # --- expected route/status/reason counts --------------------
        expected_pending = expected_supported = expected_short = 0
        expected_skipped = expected_special = expected_secondary = 0
        for f in records:
            r = decisions[f.code].route
            if r == "supported":
                expected_pending += 1
                expected_supported += 1
            elif r == "new_short_history":
                expected_pending += 1  # include_short_history=True
                expected_short += 1
            elif r == "special_caliber":
                expected_skipped += 1
                expected_special += 1
            else:  # unsupported_secondary
                expected_skipped += 1
                expected_secondary += 1
        assert staged == expected_pending

        by_status = state.stats().by_status
        assert by_status.get("pending", 0) == expected_pending
        assert by_status.get("skipped", 0) == expected_skipped
        assert sum(by_status.values()) == 21000

        by_reason = state.stats().by_reason
        assert by_reason["r:supported"] == expected_supported
        assert by_reason["r:new_short_history"] == expected_short
        assert by_reason["r:special_caliber"] == expected_special
        assert by_reason["r:unsupported_secondary"] == expected_secondary

        # --- pending index: seq 0..N-1 contiguous, no gaps/dupes ----
        pending_rows = state._conn.execute(  # noqa: SLF001
            "SELECT code, batch_no, shard, seq FROM fund_sync_state "
            "WHERE status='pending' ORDER BY seq"
        ).fetchall()
        seqs = [r["seq"] for r in pending_rows]
        assert seqs == list(range(expected_pending))
        # shards=1 => shard always 0; batch_no = seq // batch_size
        assert all(r["shard"] == 0 for r in pending_rows)
        assert [r["batch_no"] for r in pending_rows] == [
            s // batch_size for s in seqs
        ]
        # no duplicate codes
        all_codes = state._conn.execute(  # noqa: SLF001
            "SELECT code FROM fund_sync_state"
        ).fetchall()
        assert len({r["code"] for r in all_codes}) == 21000

        # --- representative codes routed correctly ------------------
        row_510300 = state._conn.execute(  # noqa: SLF001
            "SELECT status, route FROM fund_sync_state WHERE code='510300'"
        ).fetchone()
        assert row_510300["route"] == "special_caliber"
        assert row_510300["status"] == "skipped"
        for rep in ("050025", "161725"):
            row = state._conn.execute(  # noqa: SLF001
                "SELECT status, route FROM fund_sync_state WHERE code=?", (rep,)
            ).fetchone()
            assert row["route"] == "supported"
            assert row["status"] == "pending"

        # --- has_3y three-state write --------------------------------
        for c in ("050025", "161725", "510300"):
            row = state._conn.execute(  # noqa: SLF001
                "SELECT has_3y FROM fund_sync_state WHERE code=?", (c,)
            ).fetchone()
            expected = _has3y_for(c)
            expected_db: int | None = (
                1 if expected is True else (0 if expected is False else None)
            )
            assert row["has_3y"] == expected_db


def test_build_plan_rebuild_is_idempotent_and_preserves_progress(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    records = [_fund(f"{i:06d}") for i in range(500)]
    decisions = {f.code: _decision(f.code, "supported") for f in records}
    with BatchState(
        tmp_path / "state.db", now=clock, batch_size=100, claim_timeout_seconds=1800
    ) as state:
        staged1 = state.build_plan(
            records, decisions, shards=1, include_short_history=True
        )
        assert staged1 == 500
        # Claim and transition a slice of rows to create real progress.
        claimed = state.claim_batch(50, worker_id="w1")
        assert len(claimed) == 50
        done_codes = claimed[:10]
        skipped_codes = claimed[10:20]
        failed_codes = claimed[20:30]
        for c in done_codes:
            state.mark_done(c, generation_id="gen-A", nav_points=12, fund_written=1)
        for c in skipped_codes:
            state.mark_skipped(c, reason="manual skip")
        for c in failed_codes:
            state.mark_failed(c, error="boom")
        # Capture pre-rebuild snapshots.
        def _snap(codes: list[str]) -> dict[str, tuple[str | None, int, str | None]]:
            out: dict[str, tuple[str | None, int, str | None]] = {}
            for c in codes:
                row = state._conn.execute(  # noqa: SLF001
                    "SELECT status, attempts, generation_id FROM fund_sync_state WHERE code=?",
                    (c,),
                ).fetchone()
                out[c] = (row["status"], int(row["attempts"]), row["generation_id"])
            return out

        before = _snap(done_codes + skipped_codes + failed_codes)

        # Rebuild with the identical plan.
        staged2 = state.build_plan(
            records, decisions, shards=1, include_short_history=True
        )
        assert staged2 == staged1

        total = state._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) AS c FROM fund_sync_state"
        ).fetchone()["c"]
        assert total == 500  # not doubled

        after = _snap(done_codes + skipped_codes + failed_codes)
        assert before == after  # status / attempts / generation_id preserved

        # Pending rows still get deterministic contiguous seq. The first 50
        # sorted codes were claimed (seq 0..49); the remaining 450 stay pending
        # with seq 50..499 after rebuild.
        pending_rows = state._conn.execute(  # noqa: SLF001
            "SELECT seq FROM fund_sync_state WHERE status='pending' ORDER BY seq"
        ).fetchall()
        seqs = [r["seq"] for r in pending_rows]
        assert seqs == list(range(50, 500))
        # All previously-done/skipped/failed rows are NOT pending.
        for c in done_codes + skipped_codes + failed_codes:
            row = state._conn.execute(  # noqa: SLF001
                "SELECT status FROM fund_sync_state WHERE code=?", (c,)
            ).fetchone()
            assert row["status"] != "pending"


def test_build_plan_rolls_back_on_error(tmp_path: Path) -> None:
    clock = FakeClock()
    # Records sorted: A, B, C, D. Decisions missing D -> KeyError on the last
    # iteration, after A/B/C have been INSERTed inside the transaction.
    a = _fund("000001")
    b = _fund("000002")
    c = _fund("000003")
    d = _fund("000004")
    records = [a, b, c, d]
    decisions = {
        "000001": _decision("000001", "supported"),
        "000002": _decision("000002", "supported"),
        "000003": _decision("000003", "supported"),
        # note: 000004 missing
    }
    with BatchState(
        tmp_path / "state.db", now=clock, batch_size=2, claim_timeout_seconds=1800
    ) as state:
        with pytest.raises(KeyError):
            state.build_plan(records, decisions, shards=1, include_short_history=False)
        # ROLLBACK must have removed the half-inserted A/B/C rows.
        count = state._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) AS c FROM fund_sync_state"
        ).fetchone()["c"]
        assert count == 0
        # Connection is usable again (back in autocommit).
        staged = state.build_plan(
            records[:3], decisions, shards=1, include_short_history=False
        )
        assert staged == 3
