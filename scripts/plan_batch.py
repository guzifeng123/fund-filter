from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.core.config import settings  # noqa: E402
from app.data_sources.universe import UniverseFilters  # noqa: E402
from app.jobs.batch_planner import create_batch_plan  # noqa: E402
from app.jobs.batch_state import BatchState  # noqa: E402


def _parse_codes(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the deterministic sharded pending plan for the D-stage fund "
            "batch job. Pure planning: it loads the universe snapshot, routes every "
            "fund, and upserts the checkpoint; it never downloads NAV series."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.fund_batch_size,
        help="Pending rows per batch. Defaults to FUND_BATCH_SIZE.",
    )
    parser.add_argument(
        "--shards",
        type=int,
        default=1,
        help="Number of shards to plan across. Defaults to 1.",
    )
    parser.add_argument(
        "--shard",
        type=int,
        default=None,
        help=(
            "Echoed in the output for a later shard-scoped claim. Planning always "
            "builds the whole plan; this flag does not restrict the allocation."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Truncate the eligible set to its first N funds in code order.",
    )
    parser.add_argument(
        "--codes",
        default=None,
        help="Comma-separated allow-list of six-digit fund codes.",
    )
    parser.add_argument(
        "--include-short-history",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Include eligible classes with <3y history. Defaults to "
            "FUND_BATCH_INCLUDE_SHORT_HISTORY."
        ),
    )
    parser.add_argument(
        "--state-db",
        default=settings.fund_batch_state_db.as_posix(),
        help="Batch checkpoint SQLite path. Defaults to FUND_BATCH_STATE_DB.",
    )
    parser.add_argument(
        "--universe-cache-dir",
        default=settings.fund_batch_universe_cache_dir.as_posix(),
        help="Universe snapshot cache directory. Defaults to FUND_BATCH_UNIVERSE_CACHE_DIR.",
    )
    args = parser.parse_args(argv)

    filters = UniverseFilters(allow_codes=_parse_codes(args.codes))
    state = BatchState(
        args.state_db,
        batch_size=args.batch_size,
    )
    try:
        summary = create_batch_plan(
            state=state,
            filters=filters,
            shards=args.shards,
            include_short_history=args.include_short_history,
            limit=args.limit,
            cache_dir=args.universe_cache_dir,
        )
    finally:
        state.close()

    payload: dict[str, object] = summary.to_dict()
    payload["batch_size"] = args.batch_size
    payload["planned_shard"] = args.shard
    payload["state_db"] = str(args.state_db)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = ROOT / "output" / "batch" / f"plan-{stamp}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    print(text, end="")
    print(f"Wrote batch plan summary to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
