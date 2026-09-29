import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = WORKSPACE_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.data_sources.profiles.eastmoney_snapshot import (  # noqa: E402
    PROFILE_NAME,
    EastmoneySnapshotBuilder,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an audited public_http_json Eastmoney snapshot mirror.")
    parser.add_argument("--fund-code", action="append", required=True, help="Six-digit fund code; repeat as needed.")
    parser.add_argument("--output-dir", type=Path, default=WORKSPACE_ROOT / "output" / "eastmoney-mirror")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--min-interval-seconds", type=float, default=0.5)
    args = parser.parse_args()

    generated_at = datetime.now(timezone.utc)
    builder = EastmoneySnapshotBuilder(args.timeout_seconds, args.min_interval_seconds)
    funds = builder.build(args.fund_code, generated_at)
    manifest_path = builder.write_mirror(args.output_dir.resolve(), funds, generated_at)
    print(
        json.dumps(
            {
                "ok": True,
                "provider_profile": PROFILE_NAME,
                "fund_count": len(funds),
                "nav_count": sum(len(fund.navs) for fund in funds),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
