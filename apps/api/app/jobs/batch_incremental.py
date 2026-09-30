"""Daily incremental selection for the D-stage batch job (D4, task 3).

After the initial full-market run, a daily job should *not* re-download every
fund's full NAV history. Instead it needs a small, deterministic target set:

* ``done_codes`` -- funds already promoted to ``done``: refresh only the latest
  NAV point(s) (reuses the B4 incremental capability), never the full history.
* ``retry_codes`` -- funds left ``failed`` (transient infrastructure errors):
  retry them once more.
* ``new_codes`` -- funds that entered ``pending`` since the last plan (newly
  listed / newly staged universe members not yet processed).

This module only *selects and counts* against the frozen checkpoint. It never
touches the network, never writes the business DB, and never mutates the
checkpoint (``mode=ro``). Re-running it against an unchanged checkpoint yields
byte-identical code lists (idempotent).
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class IncrementalPlan:
    """Deterministic target set for one daily incremental run."""

    done_codes: tuple[str, ...]
    retry_codes: tuple[str, ...]
    new_codes: tuple[str, ...]
    generated_at: float

    @property
    def estimated_requests(self) -> int:
        """Rough request budget: ~1-2 requests per targeted fund."""
        return len(self.done_codes) + len(self.retry_codes) + len(self.new_codes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "done_codes": list(self.done_codes),
            "retry_codes": list(self.retry_codes),
            "new_codes": list(self.new_codes),
            "counts": {
                "done": len(self.done_codes),
                "retry": len(self.retry_codes),
                "new": len(self.new_codes),
            },
            "estimated_requests": self.estimated_requests,
            "generated_at": self.generated_at,
        }


def _ro_codes(conn: sqlite3.Connection, status: str) -> list[str]:
    rows = conn.execute(
        "SELECT code FROM fund_sync_state WHERE status=? ORDER BY code",
        (status,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _apply_filter(
    codes: list[str],
    only: frozenset[str] | None,
) -> list[str]:
    if only is None:
        return codes
    return [c for c in codes if c in only]


def build_incremental_plan(
    state_db: str | Path,
    *,
    codes: Iterable[str] | None = None,
    limit: int | None = None,
    now: Callable[[], float] = time.time,
) -> IncrementalPlan:
    """Build the daily incremental target set from a checkpoint (read-only).

    Parameters
    ----------
    state_db:
        Checkpoint SQLite path; opened ``mode=ro``.
    codes:
        Optional allow-list: only these codes may appear in the plan. Useful for
        a manual backfill of a handful of funds.
    limit:
        Optional cap on the *combined* number of returned codes, applied after
        the deterministic ordering (done -> retry -> new, each sorted).
    now:
        Injectable clock for deterministic tests.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0")
    only = frozenset(codes) if codes is not None else None

    path = Path(state_db)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        done = _apply_filter(_ro_codes(conn, "done"), only)
        retry = _apply_filter(_ro_codes(conn, "failed"), only)
        new = _apply_filter(_ro_codes(conn, "pending"), only)
    finally:
        conn.close()

    if limit is not None:
        budget = limit
        done = done[:budget]
        budget -= len(done)
        retry = retry[: max(0, budget)]
        budget -= len(retry)
        new = new[: max(0, budget)]

    return IncrementalPlan(
        done_codes=tuple(done),
        retry_codes=tuple(retry),
        new_codes=tuple(new),
        generated_at=now(),
    )


__all__: tuple[str, ...] = ("IncrementalPlan", "build_incremental_plan")
