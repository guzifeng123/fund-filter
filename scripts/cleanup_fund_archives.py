from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.core.config import settings  # noqa: E402
from app.repositories.fund_archives import (  # noqa: E402
    prune_fund_archives,
    resolve_archive_root,
)


def _jsonable_report(report: object) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in asdict(report).items():
        payload[key] = value.isoformat() if isinstance(value, datetime) else value
    return payload


def _resolve_report_path(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prune old fund snapshot generation archives and emit a safe report.",
    )
    parser.add_argument(
        "--archive-dir",
        default=settings.fund_archive_dir.as_posix(),
        help="Archive root directory. Defaults to FUND_ARCHIVE_DIR.",
    )
    parser.add_argument(
        "--keep-generations",
        type=int,
        default=settings.fund_archive_keep_generations,
        help=(
            "Keep the newest N archive generations. 0 (the default) keeps every "
            "archive and deletes nothing."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete matching archive directories. Without this flag the command only "
        "reports what would be deleted.",
    )
    parser.add_argument(
        "--json-report-path",
        help="Optional JSON report path. Relative paths are resolved from the repository root.",
    )
    args = parser.parse_args(argv)

    archive_root = resolve_archive_root(Path(args.archive_dir))
    report = prune_fund_archives(
        archive_root,
        keep_generations=args.keep_generations,
        dry_run=not args.apply,
    )
    payload = _jsonable_report(report)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.json_report_path:
        report_path = _resolve_report_path(args.json_report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
        print(f"Wrote fund archive cleanup report to {report_path}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
