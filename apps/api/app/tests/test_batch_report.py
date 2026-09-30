"""D4: tests for app/jobs/batch_report.py (rolling progress report).

Seeds a D0 BatchState by hand (public build_plan + mark_*, plus direct inserts
for statuses the public state machine cannot reach in one hop) and asserts the
D2 result vocabulary, rate/ETA edge cases, atomic rolling writes, read-only
safety, and shard/generation aggregation.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.jobs.batch_report import aggregate_report
from app.jobs.batch_incremental import build_incremental_plan
from app.jobs.batch_state import BatchState


class Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _row(
    code: str,
    *,
    status: str,
    route: str = "supported",
    reason: str | None = None,
    fund_type: str = "混合型",
    fund_written: int = 0,
    generation_id: str | None = None,
    batch_no: int | None = None,
    shard: int | None = None,
    seq: int | None = None,
    attempts: int = 0,
    last_error: str | None = None,
    updated_at: float = 1_000_000.0,
) -> dict[str, object]:
    return {
        "code": code,
        "route": route,
        "fund_type": fund_type,
        "has_3y": 1,
        "name": f"基金{code}",
        "status": status,
        "reason": reason,
        "generation_id": generation_id,
        "batch_no": batch_no,
        "shard": shard,
        "seq": seq,
        "attempts": attempts,
        "last_error": last_error,
        "nav_points": 100,
        "fund_written": fund_written,
        "first_seen_at": 1_000_000.0,
        "updated_at": updated_at,
        "done_at": updated_at if status == "done" else None,
    }


def _seed(db_path: Path, rows: list[dict[str, object]], clock: Clock) -> BatchState:
    state = BatchState(db_path, now=clock, batch_size=50, claim_timeout_seconds=1800)
    cols = (
        "code,route,fund_type,has_3y,name,status,reason,generation_id,batch_no,"
        "shard,seq,attempts,last_error,nav_points,fund_written,first_seen_at,"
        "updated_at,done_at"
    )
    for row in rows:
        state._conn.execute(  # noqa: SLF001 - seed arbitrary checkpoint rows
            f"INSERT INTO fund_sync_state ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["code"], row["route"], row["fund_type"], row["has_3y"],
                row["name"], row["status"], row["reason"], row["generation_id"],
                row["batch_no"], row["shard"], row["seq"], row["attempts"],
                row["last_error"], row["nav_points"], row["fund_written"],
                row["first_seen_at"], row["updated_at"], row["done_at"],
            ),
        )
    state.close()
    return state


def _count_rows(db_path: Path) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM fund_sync_state").fetchone()[0])
    finally:
        conn.close()


def test_all_result_buckets_are_classified(tmp_path: Path) -> None:
    clock = Clock()
    rows = [
        _row("000001", status="done", reason="eligible_open_end", fund_written=1,
             generation_id="gen-a", batch_no=0, shard=0, seq=0),
        _row("000002", status="done", reason="short_history_included", fund_written=1,
             generation_id="gen-a", batch_no=0, shard=1, seq=1),
        _row("000003", status="skipped", reason="danjuan_not_listed"),
        _row("000004", status="skipped", reason="special_caliber"),
        _row("000005", status="skipped", reason="unknown_type"),
        _row("000006", status="skipped", reason="history_lt_3y"),
        _row("000007", status="skipped", reason="quality_failed"),
        _row("000008", status="failed", reason=None, attempts=2,
             last_error="transient 503"),
        _row("000009", status="skipped", reason="reconciliation_mismatch"),
        _row("000010", status="pending"),
        _row("000011", status="in_flight"),
        _row("000012", status="skipped", reason="totally_unknown_reason"),
    ]
    db = tmp_path / "state.db"
    _seed(db, rows, clock)

    report = aggregate_report(db, job_id="j1", started_at=clock.now,
                              now=clock, report_dir=tmp_path / "reports")
    t = report["totals"]
    assert t["total"] == 12
    assert t["processed"] == 10  # done(2)+skipped(7)+failed(1)
    assert t["pending"] == 1
    assert t["in_flight"] == 1
    assert t["verified"] == 2
    assert t["short_history_included"] == 1
    assert t["skipped_secondary"] == 1
    assert t["skipped_special"] == 3
    assert t["skipped_quality"] == 1
    assert t["failed_retryable"] == 1
    assert t["failed_terminal_reconciliation"] == 1
    assert t["failed"] == 2
    assert t["pending_retry"] == 1
    assert t["other"] == 1
    assert report["other_reasons"] == ["totally_unknown_reason"]
    # failures sample exposes the retryable one with attempts/last_error.
    assert report["failures_sample"][0]["code"] == "000008"
    assert report["failures_sample"][0]["attempts"] == 2


def test_unknown_reason_and_done_unwritten_land_in_other(tmp_path: Path) -> None:
    clock = Clock()
    rows = [
        # done but not written -> other (never silently dropped).
        _row("000001", status="done", reason="eligible_open_end", fund_written=0),
        _row("000002", status="skipped", reason="mystery"),
    ]
    db = tmp_path / "state.db"
    _seed(db, rows, clock)
    report = aggregate_report(db, job_id="j", report_dir=tmp_path / "r")
    t = report["totals"]
    assert t["verified"] == 0
    assert t["other"] == 2
    assert "mystery" in report["other_reasons"]


def test_rate_and_eta_edge_cases(tmp_path: Path) -> None:
    clock = Clock()
    rows = [_row("000001", status="done", fund_written=1, generation_id="g")]
    db = tmp_path / "state.db"
    _seed(db, rows, clock)

    # No started_at -> rate/eta are null, never divide by zero.
    r0 = aggregate_report(db, job_id="j", now=clock, report_dir=tmp_path / "r")
    assert r0["rate_per_minute"] is None
    assert r0["eta_seconds"] is None

    # Zero elapsed at start -> null even though one row is processed.
    r1 = aggregate_report(db, job_id="j", started_at=clock.now,
                         now=clock, report_dir=tmp_path / "r")
    assert r1["rate_per_minute"] is None
    assert r1["eta_seconds"] is None

    # Advance 60s with 1 processed, 0 remaining -> rate known, eta 0/None.
    clock.advance(60)
    r2 = aggregate_report(db, job_id="j", started_at=1_000_000.0,
                          now=clock, report_dir=tmp_path / "r")
    assert r2["rate_per_minute"] == 1.0
    assert r2["eta_seconds"] == 0.0


def test_rate_eta_with_remaining_work(tmp_path: Path) -> None:
    clock = Clock()
    rows = [
        _row("000001", status="done", fund_written=1),
        _row("000002", status="pending"),
        _row("000003", status="pending"),
    ]
    db = tmp_path / "state.db"
    _seed(db, rows, clock)
    clock.advance(30)  # 1 processed in 30s -> 2/min
    report = aggregate_report(db, job_id="j", started_at=1_000_000.0,
                              now=clock, report_dir=tmp_path / "r")
    assert report["rate_per_minute"] == 2.0
    # 2 remaining / 2 per minute -> 60s.
    assert report["eta_seconds"] == 60.0


def test_rolling_json_is_atomic_and_overwritten(tmp_path: Path) -> None:
    clock = Clock()
    db = tmp_path / "state.db"
    _seed(db, [_row("000001", status="pending")], clock)
    out = tmp_path / "reports"

    first = aggregate_report(db, job_id="roll", now=clock, report_dir=out)
    path = Path(first["report_path"])
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["totals"]["total"] == 1

    # Add a done row and re-aggregate: same path overwritten, no tmp left.
    state = BatchState(db, now=clock)
    state._conn.execute(  # noqa: SLF001
        "INSERT INTO fund_sync_state "
        "(code,route,fund_type,has_3y,name,status,reason,first_seen_at,updated_at,done_at)"
        " VALUES ('000002','supported','混合型',1,'x','done',?, ?, ?, ?)",
        ("eligible_open_end", clock.now, clock.now, clock.now),
    )
    state.close()
    aggregate_report(db, job_id="roll", now=clock, report_dir=out)
    assert json.loads(path.read_text(encoding="utf-8"))["totals"]["total"] == 2
    leftovers = list(out.glob(".*.tmp"))
    assert leftovers == []


def test_ro_connection_does_not_mutate_checkpoint(tmp_path: Path) -> None:
    clock = Clock()
    db = tmp_path / "state.db"
    rows = [
        _row("000001", status="done", fund_written=1, generation_id="g"),
        _row("000002", status="pending"),
    ]
    _seed(db, rows, clock)
    before = _count_rows(db)
    aggregate_report(db, job_id="j", now=clock, report_dir=tmp_path / "r")
    aggregate_report(db, job_id="j", now=clock, report_dir=tmp_path / "r")
    assert _count_rows(db) == before


def test_shard_and_generation_aggregation(tmp_path: Path) -> None:
    clock = Clock()
    rows = [
        _row("000001", status="done", fund_written=1, generation_id="gen-1",
             batch_no=0, shard=0, seq=0),
        _row("000002", status="done", fund_written=1, generation_id="gen-1",
             batch_no=0, shard=1, seq=1),
        _row("000003", status="pending", batch_no=1, shard=0, seq=2),
        _row("000004", status="failed", batch_no=1, shard=1, seq=3, attempts=1),
    ]
    db = tmp_path / "state.db"
    _seed(db, rows, clock)
    report = aggregate_report(db, job_id="j", now=clock, report_dir=tmp_path / "r")

    shards = {s["shard"]: s for s in report["shards"]}
    assert shards[0]["total"] == 2
    assert shards[0]["done"] == 1
    assert shards[1]["done"] == 1
    assert shards[1]["failed"] == 1

    batches = {b["batch_no"]: b for b in report["batches"]}
    assert batches[0]["done"] == 2
    assert batches[1]["pending"] == 1
    assert batches[1]["failed"] == 1

    assert report["generations"] == [{"generation_id": "gen-1", "done": 2, "verified": 2}]


def test_incremental_plan_selects_done_retry_new_and_is_idempotent(tmp_path: Path) -> None:
    clock = Clock()
    rows = [
        _row("000001", status="done", fund_written=1),
        _row("000002", status="done", fund_written=1),
        _row("000003", status="failed", attempts=1, last_error="boom"),
        _row("000004", status="pending"),
        _row("000005", status="in_flight"),  # excluded: being processed
        _row("000006", status="skipped", reason="special_caliber"),  # excluded
    ]
    db = tmp_path / "state.db"
    _seed(db, rows, clock)

    plan1 = build_incremental_plan(db, now=lambda: 123.0)
    assert plan1.done_codes == ("000001", "000002")
    assert plan1.retry_codes == ("000003",)
    assert plan1.new_codes == ("000004",)
    assert plan1.estimated_requests == 4

    # Idempotent: same checkpoint -> identical tuples.
    plan2 = build_incremental_plan(db, now=lambda: 456.0)
    assert plan1.done_codes == plan2.done_codes
    assert plan1.retry_codes == plan2.retry_codes
    assert plan1.new_codes == plan2.new_codes


def test_incremental_plan_codes_filter_and_limit(tmp_path: Path) -> None:
    clock = Clock()
    rows = [
        _row(f"{i:06d}", status="done", fund_written=1) for i in range(5)
    ] + [
        _row("900001", status="failed"),
        _row("900002", status="pending"),
    ]
    db = tmp_path / "state.db"
    _seed(db, rows, clock)

    only = ("000001", "000003", "900001")
    plan = build_incremental_plan(db, codes=only, now=lambda: 0.0)
    assert plan.done_codes == ("000001", "000003")
    assert plan.retry_codes == ("900001",)
    assert plan.new_codes == ()

    capped = build_incremental_plan(db, limit=2, now=lambda: 0.0)
    assert len(capped.done_codes) == 2
    assert capped.retry_codes == ()
    assert capped.new_codes == ()
    assert capped.estimated_requests == 2


def test_incremental_plan_is_read_only(tmp_path: Path) -> None:
    clock = Clock()
    db = tmp_path / "state.db"
    _seed(db, [_row("000001", status="done", fund_written=1)], clock)
    before = _count_rows(db)
    build_incremental_plan(db, now=lambda: 0.0)
    assert _count_rows(db) == before
