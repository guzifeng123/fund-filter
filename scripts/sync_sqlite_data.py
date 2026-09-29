"""Pull audited public fund snapshots into the local SQLite business database."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = WORKSPACE_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.data_sources.profiles.eastmoney_snapshot import EastmoneySnapshotBuilder  # noqa: E402
from app.jobs.sync_fund_data import sync_all  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402


class SnapshotSource:
    name = "eastmoney_snapshot"

    def __init__(self, funds):
        self._funds = funds

    def fetch_snapshot(self):
        return self._funds

    def fetch_fund_profiles(self):
        return self._funds

    def fetch_fund_navs(self):
        return self._funds

    def fetch_risk_levels(self):
        return {fund.code: fund.risk_level for fund in self._funds}


def _discover_fund_codes(limit: int) -> list[str]:
    """Discover current open-fund codes through AKShare's public universe."""
    import akshare as ak

    # Ranking data is a better candidate pool than newly launched funds in
    # the daily universe because the snapshot requires 3/5-year history.
    frame = ak.fund_open_fund_rank_em()
    codes = frame["基金代码"].astype(str).str.zfill(6).drop_duplicates().tolist()
    return codes[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull EastMoney fund snapshots into SQLite.")
    parser.add_argument("--fund-code", action="append", dest="fund_codes")
    parser.add_argument("--discover", action="store_true", help="discover current open-fund codes via AKShare")
    parser.add_argument("--limit", type=int, default=10, help="number of successful discovered snapshots (default: 10)")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--min-interval-seconds", type=float, default=0.5)
    parser.add_argument("--json-report", type=Path, default=WORKSPACE_ROOT / "output" / "sqlite-sync.json")
    args = parser.parse_args()
    if args.fund_codes and args.discover:
        parser.error("use --fund-code or --discover, not both")
    # With no explicit code, use the live AKShare ranking universe so a plain
    # invocation never silently produces a one-fund database.
    fund_codes = args.fund_codes or _discover_fund_codes(max(args.limit * 10, 20))

    # The default settings URL is the repository SQLite file. Respect an
    # explicit DATABASE_URL so operators can point the same command elsewhere.
    builder = EastmoneySnapshotBuilder(args.timeout_seconds, args.min_interval_seconds)
    funds = []
    skipped: list[dict[str, str]] = []
    generated_at = datetime.now(timezone.utc)
    target_count = args.limit if not args.fund_codes else len(fund_codes)
    for code in fund_codes:
        if len(funds) >= target_count:
            break
        try:
            funds.extend(builder.build([code], generated_at))
        except Exception as exc:
            skipped.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(0.05)
    if not funds:
        raise RuntimeError(f"no fund snapshot could be built; skipped={skipped[:5]}")
    db = get_sessionmaker()()
    try:
        result = sync_all(db, source_override=SnapshotSource(funds))
    finally:
        db.close()

    payload = {"ok": True, "database_url": os.getenv("DATABASE_URL", "default sqlite"), "requested_fund_codes": fund_codes, "skipped": skipped, "result": result}
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
