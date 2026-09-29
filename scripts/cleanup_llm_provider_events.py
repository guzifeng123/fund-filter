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
from app.db.session import get_sessionmaker  # noqa: E402
from app.repositories.llm_observability import cleanup_llm_provider_events  # noqa: E402


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
        description="Clean old LLM provider observability events and emit a safe aggregate report.",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=settings.llm_observability_retention_days,
        help="Keep events newer than this many days. Defaults to LLM_OBSERVABILITY_RETENTION_DAYS.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete matching rows. Without this flag the command only reports what would be deleted.",
    )
    parser.add_argument(
        "--json-report-path",
        help="Optional JSON report path. Relative paths are resolved from the repository root.",
    )
    args = parser.parse_args(argv)

    with get_sessionmaker()() as db:
        report = cleanup_llm_provider_events(
            db,
            retention_days=args.retention_days,
            dry_run=not args.apply,
        )
    payload = _jsonable_report(report)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.json_report_path:
        report_path = _resolve_report_path(args.json_report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
        print(f"Wrote LLM provider event cleanup report to {report_path}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
