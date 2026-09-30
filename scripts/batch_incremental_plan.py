#!/usr/bin/env python3
"""Daily incremental plan printer (D4, task 3).

Reads the D0 checkpoint read-only and prints (or writes) the deterministic
daily incremental target set produced by
:func:`app.jobs.batch_incremental.build_incremental_plan`. It never downloads
anything and never writes the business DB.

Examples
--------
Print the plan as JSON to stdout::

    python scripts/batch_incremental_plan.py

Restrict to a few codes and cap the total::

    python scripts/batch_incremental_plan.py --codes 000001,000002 --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.core.config import settings  # noqa: E402
from app.jobs.batch_incremental import build_incremental_plan  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-db",
        default=str(settings.fund_batch_state_db),
        help=f"checkpoint SQLite path (default: {settings.fund_batch_state_db})",
    )
    parser.add_argument(
        "--codes",
        default=None,
        help="comma-separated allow-list of fund codes to plan",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap the combined number of returned codes",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="optional path to write the plan JSON (otherwise stdout only)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    codes = (
        tuple(c.strip() for c in args.codes.split(",") if c.strip())
        if args.codes
        else None
    )
    plan = build_incremental_plan(args.state_db, codes=codes, limit=args.limit)
    payload = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    print(payload)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
