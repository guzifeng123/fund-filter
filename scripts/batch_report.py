#!/usr/bin/env python3
"""Rolling batch progress reporter (D4, task 1).

Reads the D0 checkpoint SQLite database in read-only mode and renders the
rolling progress report produced by :func:`app.jobs.batch_report.aggregate_report`.

Examples
--------
Single-shot console summary::

    python scripts/batch_report.py --job-id full-2026w40

Emit the rolling JSON path only (for piping)::

    python scripts/batch_report.py --job-id full-2026w40 --json

Poll every 30s for up to an hour while the runner works::

    python scripts/batch_report.py --job-id full-2026w40 --watch 30 --watch-seconds 3600
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.core.config import settings  # noqa: E402
from app.jobs.batch_report import aggregate_report, render_console  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-db",
        default=str(settings.fund_batch_state_db),
        help=f"checkpoint SQLite path (default: {settings.fund_batch_state_db})",
    )
    parser.add_argument(
        "--job-id",
        required=True,
        help="logical job label; output is report-<job-id>.json",
    )
    parser.add_argument(
        "--started-at",
        type=float,
        default=None,
        help="epoch seconds when the job started, for rate/ETA (default: n/a)",
    )
    parser.add_argument(
        "--watch",
        type=float,
        default=None,
        help="poll interval in seconds; omit for a single shot",
    )
    parser.add_argument(
        "--watch-seconds",
        type=float,
        default=3600.0,
        help="maximum wall-clock time to keep watching (default: 3600s)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print only the written JSON file path (single-shot)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    started_at = args.started_at
    started_at = started_at if started_at is not None else time.time() if args.watch else None

    if args.json:
        report = aggregate_report(
            args.state_db,
            job_id=args.job_id,
            started_at=started_at,
        )
        print(report["report_path"])
        return 0

    if args.watch is None:
        report = aggregate_report(
            args.state_db,
            job_id=args.job_id,
            started_at=started_at,
        )
        print(render_console(report))
        return 0

    deadline = time.time() + args.watch_seconds
    while True:
        report = aggregate_report(
            args.state_db,
            job_id=args.job_id,
            started_at=started_at,
        )
        # Clear-screen is deliberately avoided: logs must stay scrollable.
        print(render_console(report))
        print("-" * 60)
        if time.time() >= deadline:
            break
        time.sleep(max(0.0, args.watch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
