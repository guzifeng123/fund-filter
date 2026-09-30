"""Independent SQLite checkpoint for the D-stage sharded batch job (D0, 5).

This module owns the *batch progress* database. It is deliberately separate from
the Alembic-managed business database: it uses the stdlib ``sqlite3`` module,
creates ``output/batch/state.db`` (gitignored), and never touches the ORM, the
business tables, or the Alembic revision chain.

Contract for D1-D4 (do not loosen):

* **Generation granularity** -- one snapshot generation per batch. The runner
  pulls / cross-checks / quality-adjudicates each fund, then stages the whole
  "passed set" and promotes it atomically under a single ``generation_id``.
  Funds that do not pass are never promoted into that generation; they are
  checkpointed as ``skipped`` / ``failed``. ``generation.details`` records
  job_id / batch_no / shard / passed-skipped-failed counts and the code lists.
* **Rate limiting** -- per-domain minimum interval (eastmoney / danjuan / sina,
  default 0.5s, independent knobs); default workers=1 (hard cap 3); 429/5xx/
  timeouts back off 2/4/8s (capped) with at most 3 retries; deterministic
  failures (404 / not-for-sale / quality fail / cross-check mismatch) are NOT
  retried.
* **Resume** -- after a restart, ``pending`` and timed-out ``in_flight`` rows are
  claimed again automatically; no manual intervention.

Status state machine:

::

    pending --claim--> in_flight --mark_done--> done
                       in_flight --mark_skipped--> skipped
                       in_flight --mark_failed--> failed --retry_failed--> pending
    timed-out in_flight --(claim)--> pending (reclaimed, attempts++)
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from app.core.config import settings
from app.core.fund_classifier import ClassifyDecision
from app.data_sources.universe import UniverseFund

STATUSES = ("pending", "in_flight", "done", "skipped", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fund_sync_state (
    code TEXT PRIMARY KEY,
    route TEXT NOT NULL,
    fund_type TEXT NOT NULL,
    -- F-phase: three-state age evidence. 1 = known >=3y, 0 = known <3y,
    -- NULL = rank-uncovered (age unknown, deferred to the runner's inception check).
    has_3y INTEGER,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('pending','in_flight','done','skipped','failed')),
    reason TEXT,
    generation_id TEXT,
    batch_no INTEGER,
    shard INTEGER,
    seq INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    nav_points INTEGER,
    fund_written INTEGER,
    first_seen_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    done_at REAL
);
CREATE INDEX IF NOT EXISTS idx_fund_sync_state_status ON fund_sync_state(status);
CREATE INDEX IF NOT EXISTS idx_fund_sync_state_batch ON fund_sync_state(batch_no, shard, seq);
CREATE TABLE IF NOT EXISTS batch_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class BatchStats:
    """Aggregate counters plus throughput inputs for the runner."""

    total: int
    by_status: dict[str, int]
    by_reason: dict[str, int]
    by_fund_type: dict[str, int]

    @property
    def pending(self) -> int:
        return self.by_status.get("pending", 0)

    @property
    def in_flight(self) -> int:
        return self.by_status.get("in_flight", 0)

    @property
    def done(self) -> int:
        return self.by_status.get("done", 0)

    @property
    def skipped(self) -> int:
        return self.by_status.get("skipped", 0)

    @property
    def failed(self) -> int:
        return self.by_status.get("failed", 0)


class BatchState:
    """Transactional checkpoint over a single SQLite connection."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        conn: sqlite3.Connection | None = None,
        now: Callable[[], float] = time.time,
        batch_size: int | None = None,
        claim_timeout_seconds: float | None = None,
    ) -> None:
        self._now = now
        self.batch_size = (
            batch_size if batch_size is not None else settings.fund_batch_size
        )
        self.claim_timeout_seconds = (
            claim_timeout_seconds
            if claim_timeout_seconds is not None
            else settings.fund_batch_claim_timeout_seconds
        )
        if conn is not None:
            self._owns_conn = False
            self._conn = conn
        else:
            path = Path(
                db_path if db_path is not None else settings.fund_batch_state_db
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            # isolation_level=None => autocommit; we drive BEGIN IMMEDIATE ourselves.
            self._owns_conn = True
            self._conn = sqlite3.connect(str(path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO batch_meta(key, value) VALUES ('schema_version', '1')"
        )

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()

    def __enter__(self) -> "BatchState":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ plan
    def build_plan(
        self,
        records: Iterable[UniverseFund],
        decisions: dict[str, ClassifyDecision],
        *,
        shards: int,
        include_short_history: bool,
    ) -> int:
        """Upsert the universe + decisions, deterministically assigning shards.

        Returns the number of funds staged as ``pending`` (eligible to process).
        Idempotent: re-running does not create duplicate rows and does not reset
        already-``done``/``skipped``/``failed`` progress or attempt counters.
        """
        if shards < 1:
            raise ValueError("shards must be >= 1")
        now = self._now()
        pending_index = 0
        staged = 0
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            for fund in sorted(records, key=lambda item: item.code):
                decision = decisions[fund.code]
                if decision.route == "supported":
                    status = "pending"
                elif decision.route == "new_short_history" and include_short_history:
                    status = "pending"
                else:
                    status = "skipped"

                if status == "pending":
                    batch_no = pending_index // self.batch_size
                    shard = pending_index % shards
                    seq = pending_index
                    pending_index += 1
                    staged += 1
                else:
                    batch_no = None
                    shard = None
                    seq = None

                self._conn.execute(
                    """
                    INSERT INTO fund_sync_state
                      (code, route, fund_type, has_3y, name, status, reason,
                       batch_no, shard, seq, attempts, first_seen_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                      route=excluded.route,
                      fund_type=excluded.fund_type,
                      has_3y=excluded.has_3y,
                      name=excluded.name,
                      reason=excluded.reason,
                      batch_no=excluded.batch_no,
                      shard=excluded.shard,
                      seq=excluded.seq,
                      updated_at=excluded.updated_at
                    """,
                    (
                        fund.code,
                        decision.route,
                        fund.type_major,
                        1 if fund.has_3y is True else (0 if fund.has_3y is False else None),
                        fund.name,
                        status,
                        decision.reason,
                        batch_no,
                        shard,
                        seq,
                        now,
                        now,
                    ),
                )
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.commit()
        return staged

    # ---------------------------------------------------- coalesced job meta
    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM batch_meta WHERE key=?", (key,)
        ).fetchone()
        return None if row is None else str(row[0])

    def put_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO batch_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def delete_meta(self, key: str) -> None:
        self._conn.execute("DELETE FROM batch_meta WHERE key=?", (key,))

    def get_coalesced_generation(self, job_id: str) -> str | None:
        """Return the in-flight coalesced generation for a job, if resuming one."""
        return self.get_meta(f"coalesce_gen:{job_id}")

    def set_coalesced_generation(self, job_id: str, generation_id: str) -> None:
        self.put_meta(f"coalesce_gen:{job_id}", generation_id)

    def clear_coalesced_generation(self, job_id: str) -> None:
        self.delete_meta(f"coalesce_gen:{job_id}")

    def terminal_skipped(self, limit: int = 200) -> list[tuple[str, str | None]]:
        rows = self._conn.execute(
            "SELECT code, reason FROM fund_sync_state "
            "WHERE status='skipped' ORDER BY code LIMIT ?",
            (limit,),
        ).fetchall()
        return [(str(r["code"]), r["reason"]) for r in rows]

    def terminal_failed(self, limit: int = 200) -> list[tuple[str, str | None]]:
        rows = self._conn.execute(
            "SELECT code, last_error FROM fund_sync_state "
            "WHERE status='failed' ORDER BY code LIMIT ?",
            (limit,),
        ).fetchall()
        return [(str(r["code"]), r["last_error"]) for r in rows]

    # ------------------------------------------------------------------ claim
    def claim_batch(
        self,
        batch_size: int,
        worker_id: str,
        *,
        shards: int | None = None,
        shard: int | None = None,
    ) -> list[str]:
        """Atomically claim up to ``batch_size`` pending codes for ``worker_id``.

        Timed-out ``in_flight`` rows are reclaimed first (attempts++), then the
        next pending batch is marked ``in_flight`` in one immediate transaction.

        Sharded claim (D1): when both ``shards`` and ``shard`` are supplied, only
        rows :meth:`build_plan` assigned to that shard are claimed, and the
        timeout reclamation is scoped to the same shard so workers never reclaim or
        steal another shard's in-flight rows. Calling with exactly one of the two,
        or a ``shard`` outside ``[0, shards)``, raises. With neither argument the
        behaviour is identical to the unsharded D0 contract.
        """
        if (shard is None) != (shards is None):
            raise ValueError("shards and shard must be provided together")
        shard_clause = ""
        shard_params: list[int] = []
        if shard is not None:
            assert shards is not None  # narrowed by the paired check above
            if shards < 1:
                raise ValueError("shards must be >= 1")
            if not 0 <= shard < shards:
                raise ValueError(f"shard must be in [0, {shards}); got {shard}")
            shard_clause = " AND shard = ?"
            shard_params = [shard]

        now = self._now()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                f"""
                UPDATE fund_sync_state
                   SET status='pending',
                       last_error=?
                 WHERE status='in_flight' AND updated_at < ?{shard_clause}
                """,
                (
                    f"reclaimed after timeout (worker={worker_id})",
                    now - self.claim_timeout_seconds,
                    *shard_params,
                ),
            )
            rows = self._conn.execute(
                f"""
                SELECT code FROM fund_sync_state
                 WHERE status='pending'{shard_clause}
                 ORDER BY batch_no, shard, seq
                 LIMIT ?
                """,
                (*shard_params, batch_size),
            ).fetchall()
            codes = [str(row[0]) for row in rows]
            if codes:
                markers = ",".join("?" for _ in codes)
                self._conn.execute(
                    f"""
                    UPDATE fund_sync_state
                       SET status='in_flight', attempts=attempts+1,
                           updated_at=?, last_error=NULL
                     WHERE code IN ({markers})
                    """,
                    (now, *codes),
                )
            self._conn.commit()
            return codes
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------- transitions
    def mark_done(
        self,
        code: str,
        *,
        generation_id: str,
        nav_points: int = 0,
        fund_written: int = 0,
    ) -> None:
        now = self._now()
        cursor = self._conn.execute(
            """
            UPDATE fund_sync_state
               SET status='done', generation_id=?, nav_points=?, fund_written=?,
                   updated_at=?, done_at=?
             WHERE code=? AND status='in_flight'
            """,
            (generation_id, nav_points, fund_written, now, now, code),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"illegal transition: {code!r} not in_flight")

    def mark_skipped(self, code: str, reason: str) -> None:
        now = self._now()
        cursor = self._conn.execute(
            """
            UPDATE fund_sync_state
               SET status='skipped', reason=?, updated_at=?
             WHERE code=? AND status IN ('pending','in_flight')
            """,
            (reason, now, code),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"illegal transition: {code!r} not pending/in_flight")

    def mark_failed(self, code: str, error: str, *, retryable: bool = True) -> None:
        now = self._now()
        cursor = self._conn.execute(
            """
            UPDATE fund_sync_state
               SET status='failed', last_error=?, updated_at=?
             WHERE code=? AND status='in_flight'
            """,
            (error, now, code),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"illegal transition: {code!r} not in_flight")

    def retry_failed(self) -> int:
        """Reset all ``failed`` rows back to ``pending`` for re-processing."""
        now = self._now()
        cursor = self._conn.execute(
            """
            UPDATE fund_sync_state
               SET status='pending', last_error=NULL, updated_at=?
             WHERE status='failed'
            """,
            (now,),
        )
        return int(cursor.rowcount)

    # ------------------------------------------------------------------ stats
    def stats(self) -> BatchStats:
        def _group(column: str) -> dict[str, int]:
            rows = self._conn.execute(
                f"SELECT {column} AS k, COUNT(*) AS c FROM fund_sync_state GROUP BY {column}"
            ).fetchall()
            return {str(row["k"]): int(row["c"]) for row in rows}

        by_status = _group("status")
        total = sum(by_status.values())
        return BatchStats(
            total=total,
            by_status=by_status,
            by_reason=_group("reason"),
            by_fund_type=_group("fund_type"),
        )
