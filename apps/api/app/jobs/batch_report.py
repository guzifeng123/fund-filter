"""Rolling progress report for the D-stage sharded batch job (D4, task 1).

This module is the *read-only observability* half of the batch checkpoint. It
never mutates ``fund_sync_state``: it opens the checkpoint SQLite database in
``mode=ro``, aggregates the frozen D0 columns, classifies each row into the D2
result vocabulary, and atomically rewrites a single rolling JSON file per job::

    output/batch/report-<job_id>.json   (tmp + os.replace, overwritten every batch)

The D2 runner only has to call :func:`aggregate_report` once at the end of every
batch; tests instead seed a :class:`~app.jobs.batch_state.BatchState` by hand
(``build_plan`` + ``mark_*``) and then assert on the returned dict / file.

Result buckets are the D2 contract verbatim (do not rename):

* ``verified``            -- ``status=done`` AND ``fund_written=1``.
* ``skipped_secondary``   -- ``status=skipped`` AND reason ∈ {danjuan_not_listed}.
* ``skipped_special``    -- ``status=skipped`` AND reason ∈
                            {special_caliber, unknown_type, history_lt_3y}.
* ``skipped_quality``     -- ``status=skipped`` AND reason = quality_failed.
* ``failed``             -- ``status=failed`` (retryable transient) PLUS
                            ``status=skipped`` AND reason = reconciliation_mismatch
                            (terminal, non-retryable). Split into
                            ``failed_retryable`` / ``failed_terminal``.
* ``short_history_included`` -- done funds pulled in by
                            ``FUND_BATCH_INCLUDE_SHORT_HISTORY`` (reason =
                            short_history_included).
* ``other``              -- anything not cleanly bucketed (unknown skipped reason,
                            done-but-unwritten); raw reasons are listed, never
                            dropped.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings

# --- D2 result vocabulary (frozen, verbatim) -------------------------------
SKIPPED_SECONDARY_REASONS: frozenset[str] = frozenset({"danjuan_not_listed"})
SKIPPED_SPECIAL_REASONS: frozenset[str] = frozenset(
    {"special_caliber", "unknown_type", "history_lt_3y"}
)
SKIPPED_QUALITY_REASONS: frozenset[str] = frozenset({"quality_failed"})
TERMINAL_RECONCILIATION_REASON: str = "reconciliation_mismatch"
SHORT_HISTORY_INCLUDED_REASON: str = "short_history_included"

_KNOWN_SKIPPED_REASONS: frozenset[str] = (
    SKIPPED_SECONDARY_REASONS
    | SKIPPED_SPECIAL_REASONS
    | SKIPPED_QUALITY_REASONS
    | {TERMINAL_RECONCILIATION_REASON}
)

_MAX_FAILURE_SAMPLE = 20


def _ro_connect(state_db: str | Path) -> sqlite3.Connection:
    """Open the checkpoint read-only (mode=ro) -- never writes to the DB."""
    path = Path(state_db)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _count_group(conn: sqlite3.Connection, column: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column} AS k, COUNT(*) AS c FROM fund_sync_state GROUP BY {column}"
    ).fetchall()
    return {str(row["k"]): int(row["c"]) for row in rows}


def _bucket_counts(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status IN ('done','skipped','failed') THEN 1 ELSE 0 END)
            AS processed,
          SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
          SUM(CASE WHEN status='in_flight' THEN 1 ELSE 0 END) AS in_flight,
          SUM(CASE WHEN status='done' AND fund_written=1 THEN 1 ELSE 0 END)
            AS verified,
          SUM(CASE WHEN status='done' AND reason=? THEN 1 ELSE 0 END)
            AS short_history_included,
          SUM(CASE WHEN status='skipped' AND reason IN
              ('danjuan_not_listed') THEN 1 ELSE 0 END) AS skipped_secondary,
          SUM(CASE WHEN status='skipped' AND reason IN
              ('special_caliber','unknown_type','history_lt_3y') THEN 1 ELSE 0 END)
            AS skipped_special,
          SUM(CASE WHEN status='skipped' AND reason='quality_failed' THEN 1 ELSE 0 END)
            AS skipped_quality,
          SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_retryable,
          SUM(CASE WHEN status='skipped' AND reason='reconciliation_mismatch'
              THEN 1 ELSE 0 END) AS failed_terminal,
          SUM(CASE WHEN status='done' AND
              (fund_written IS NULL OR fund_written=0) THEN 1 ELSE 0 END)
            AS other_done_unwritten,
          SUM(CASE WHEN status='skipped' AND reason IS NOT NULL AND reason NOT IN
              ('danjuan_not_listed','special_caliber','unknown_type',
               'history_lt_3y','quality_failed','reconciliation_mismatch')
              THEN 1 ELSE 0 END) AS other_skipped
        FROM fund_sync_state
        """,
        (SHORT_HISTORY_INCLUDED_REASON,),
    ).fetchone()
    assert row is not None
    return {
        "total": int(row["total"] or 0),
        "processed": int(row["processed"] or 0),
        "pending": int(row["pending"] or 0),
        "in_flight": int(row["in_flight"] or 0),
        "verified": int(row["verified"] or 0),
        "short_history_included": int(row["short_history_included"] or 0),
        "skipped_secondary": int(row["skipped_secondary"] or 0),
        "skipped_special": int(row["skipped_special"] or 0),
        "skipped_quality": int(row["skipped_quality"] or 0),
        "failed_retryable": int(row["failed_retryable"] or 0),
        "failed_terminal": int(row["failed_terminal"] or 0),
        "other_done_unwritten": int(row["other_done_unwritten"] or 0),
        "other_skipped": int(row["other_skipped"] or 0),
    }


def _unknown_reasons(conn: sqlite3.Connection) -> list[str]:
    placeholders = ",".join("?" for _ in sorted(_KNOWN_SKIPPED_REASONS))
    rows = conn.execute(
        f"""
        SELECT DISTINCT reason AS r FROM fund_sync_state
         WHERE status='skipped' AND reason IS NOT NULL
           AND reason NOT IN ({placeholders})
         ORDER BY reason
        """,
        tuple(sorted(_KNOWN_SKIPPED_REASONS)),
    ).fetchall()
    return [str(row["r"]) for row in rows]


def _shard_progress(conn: sqlite3.Connection) -> list[dict[str, int]]:
    rows = conn.execute(
        """
        SELECT
          shard AS shard,
          COUNT(*) AS total,
          SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
          SUM(CASE WHEN status='in_flight' THEN 1 ELSE 0 END) AS in_flight,
          SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done,
          SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped,
          SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
        FROM fund_sync_state
        WHERE shard IS NOT NULL
        GROUP BY shard
        ORDER BY shard
        """
    ).fetchall()
    return [
        {
            "shard": int(row["shard"]),
            "total": int(row["total"]),
            "pending": int(row["pending"] or 0),
            "in_flight": int(row["in_flight"] or 0),
            "done": int(row["done"] or 0),
            "skipped": int(row["skipped"] or 0),
            "failed": int(row["failed"] or 0),
        }
        for row in rows
    ]


def _batches(conn: sqlite3.Connection) -> list[dict[str, int]]:
    rows = conn.execute(
        """
        SELECT
          batch_no AS batch_no,
          COUNT(*) AS total,
          SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
          SUM(CASE WHEN status='in_flight' THEN 1 ELSE 0 END) AS in_flight,
          SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done,
          SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped,
          SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
        FROM fund_sync_state
        WHERE batch_no IS NOT NULL
        GROUP BY batch_no
        ORDER BY batch_no
        """
    ).fetchall()
    return [
        {
            "batch_no": int(row["batch_no"]),
            "total": int(row["total"]),
            "pending": int(row["pending"] or 0),
            "in_flight": int(row["in_flight"] or 0),
            "done": int(row["done"] or 0),
            "skipped": int(row["skipped"] or 0),
            "failed": int(row["failed"] or 0),
        }
        for row in rows
    ]


def _generations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          generation_id AS generation_id,
          COUNT(*) AS done,
          SUM(CASE WHEN fund_written=1 THEN 1 ELSE 0 END) AS verified
        FROM fund_sync_state
        WHERE generation_id IS NOT NULL
        GROUP BY generation_id
        ORDER BY generation_id
        """
    ).fetchall()
    return [
        {
            "generation_id": str(row["generation_id"]),
            "done": int(row["done"]),
            "verified": int(row["verified"] or 0),
        }
        for row in rows
    ]


def _failure_sample(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT code AS code, attempts AS attempts, last_error AS last_error
          FROM fund_sync_state
         WHERE status='failed'
         ORDER BY attempts DESC, code
         LIMIT ?
        """,
        (_MAX_FAILURE_SAMPLE,),
    ).fetchall()
    return [
        {
            "code": str(row["code"]),
            "attempts": int(row["attempts"] or 0),
            "last_error": str(row["last_error"]) if row["last_error"] is not None else None,
        }
        for row in rows
    ]


def _throughput(
    processed: int,
    remaining: int,
    *,
    started_at: float | None,
    now_ts: float,
) -> tuple[float | None, float | None]:
    """Return (rate_per_minute, eta_seconds); None on any zero/undefined edge."""
    if started_at is None:
        return None, None
    elapsed = now_ts - started_at
    if elapsed <= 0 or processed <= 0:
        return None, None
    rate_per_minute = processed / (elapsed / 60.0)
    if rate_per_minute <= 0:
        return None, None
    eta_seconds = (remaining / rate_per_minute) * 60.0
    return rate_per_minute, eta_seconds


def aggregate_report(
    state_db: str | Path,
    *,
    job_id: str,
    started_at: float | None = None,
    now: Callable[[], float] = time.time,
    report_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Aggregate the checkpoint and atomically write the rolling JSON report.

    Parameters
    ----------
    state_db:
        Path to the checkpoint SQLite file (opened ``mode=ro``).
    job_id:
        Logical job label; the file is ``report-<job_id>.json``.
    started_at:
        Wall-clock (epoch seconds) when the job started. When omitted,
        throughput / ETA are reported as ``null`` instead of guessing.
    now:
        Injectable clock for deterministic tests.
    report_dir:
        Output directory; defaults to ``settings.fund_batch_report_dir``.
    """
    now_ts = now()
    conn = _ro_connect(state_db)
    try:
        buckets = _bucket_counts(conn)
        total = buckets["total"]
        processed = buckets["processed"]
        remaining = buckets["pending"] + buckets["in_flight"]
        failed_total = buckets["failed_retryable"] + buckets["failed_terminal"]
        other_total = buckets["other_done_unwritten"] + buckets["other_skipped"]
        rate_per_minute, eta_seconds = _throughput(
            processed, remaining, started_at=started_at, now_ts=now_ts
        )

        report: dict[str, Any] = {
            "job_id": job_id,
            "generated_at": now_ts,
            "started_at": started_at,
            "elapsed_seconds": (now_ts - started_at) if started_at is not None else None,
            "totals": {
                "total": total,
                "processed": processed,
                "pending": buckets["pending"],
                "in_flight": buckets["in_flight"],
                "verified": buckets["verified"],
                "short_history_included": buckets["short_history_included"],
                "skipped_secondary": buckets["skipped_secondary"],
                "skipped_special": buckets["skipped_special"],
                "skipped_quality": buckets["skipped_quality"],
                "failed": failed_total,
                "failed_retryable": buckets["failed_retryable"],
                "failed_terminal_reconciliation": buckets["failed_terminal"],
                "pending_retry": buckets["failed_retryable"],
                "other": other_total,
            },
            "by_status": _count_group(conn, "status"),
            "by_reason": _count_group(conn, "reason"),
            "by_fund_type": _count_group(conn, "fund_type"),
            "other_reasons": _unknown_reasons(conn),
            "rate_per_minute": rate_per_minute,
            "eta_seconds": eta_seconds,
            "shards": _shard_progress(conn),
            "batches": _batches(conn),
            "generations": _generations(conn),
            "failures_sample": _failure_sample(conn),
        }
    finally:
        conn.close()

    out_dir = Path(report_dir) if report_dir is not None else settings.fund_batch_report_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"report-{job_id}.json"
    tmp_path = out_dir / f".report-{job_id}.json.tmp"
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, report_path)  # atomic on POSIX / Windows
    report["report_path"] = str(report_path)
    return report


def render_console(report: dict[str, Any]) -> str:
    """Render a plain-text, cross-platform summary (no box-drawing deps)."""
    totals = report["totals"]
    lines: list[str] = []
    lines.append(f"batch report: {report['job_id']}")
    lines.append(
        f"  total={totals['total']}  processed={totals['processed']} "
        f"pending={totals['pending']}  in_flight={totals['in_flight']}"
    )
    lines.append(
        f"  verified={totals['verified']} "
        f"(short_history_included={totals['short_history_included']})"
    )
    lines.append(
        f"  skipped: secondary={totals['skipped_secondary']} "
        f"special={totals['skipped_special']} "
        f"quality={totals['skipped_quality']}"
    )
    lines.append(
        f"  failed: total={totals['failed']} "
        f"retryable={totals['failed_retryable']} "
        f"terminal_reconciliation={totals['failed_terminal_reconciliation']}"
        f"  pending_retry={totals['pending_retry']}"
    )
    if totals["other"]:
        lines.append(f"  other={totals['other']}  reasons={report['other_reasons']}")
    rate = report["rate_per_minute"]
    eta = report["eta_seconds"]
    if rate is None:
        lines.append("  rate=n/a  eta=n/a  (no started_at or no progress yet)")
    else:
        eta_text = f"{eta/3600:.2f}h" if eta is not None else "n/a"
        lines.append(f"  rate={rate:.2f} funds/min  eta={eta_text}")
    by_reason = report["by_reason"]
    if by_reason:
        joined = ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
        lines.append(f"  by_reason: {joined}")
    by_type = report["by_fund_type"]
    if by_type:
        joined = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
        lines.append(f"  by_fund_type: {joined}")
    return "\n".join(lines)


def report_path_for(
    job_id: str,
    *,
    report_dir: str | Path | None = None,
) -> Path:
    """Convenience: where :func:`aggregate_report` will write for a job_id."""
    out_dir = Path(report_dir) if report_dir is not None else settings.fund_batch_report_dir
    return out_dir / f"report-{job_id}.json"


__all__: tuple[str, ...] = (
    "aggregate_report",
    "render_console",
    "report_path_for",
    "SKIPPED_SECONDARY_REASONS",
    "SKIPPED_SPECIAL_REASONS",
    "SKIPPED_QUALITY_REASONS",
    "TERMINAL_RECONCILIATION_REASON",
    "SHORT_HISTORY_INCLUDED_REASON",
)
