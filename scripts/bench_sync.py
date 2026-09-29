from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.models import Fund, FundMetric, FundNav  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.repositories.fund_snapshots import (  # noqa: E402
    ensure_snapshot_state,
    lock_snapshot_state,
    promote_snapshot,
    stage_snapshot,
    validate_staged_snapshot,
)
from app.repositories.funds import (  # noqa: E402
    stage_funds_batch,
    upsert_fund_metrics,
    upsert_fund_navs,
    upsert_fund_profile,
)
from app.schemas.funds import FundDetail, NavPoint  # noqa: E402


BENCH_SOURCE = "bench_synthetic"
BENCH_EPOCH = date(2026, 9, 26)


def _new_generation_id(label: str) -> str:
    return f"bench-{label}-{uuid4().hex[:12]}"


def build_synthetic_funds(fund_count: int, nav_points: int) -> list[FundDetail]:
    funds: list[FundDetail] = []
    for fund_index in range(fund_count):
        code = f"BENCH{fund_index:06d}"
        navs: list[NavPoint] = []
        for point_index in range(nav_points):
            day = BENCH_EPOCH - timedelta(days=nav_points - point_index)
            nav_value = 1.0 + 0.001 * ((fund_index * 37 + point_index) % 500)
            navs.append(
                NavPoint(
                    trade_date=day.isoformat(),
                    nav=round(nav_value, 4),
                    accumulated_nav=round(nav_value + 0.5, 4),
                )
            )
        funds.append(
            FundDetail(
                code=code,
                name=f"Benchmark Fund {fund_index}",
                fund_type="mixed",
                risk_level="R3",
                manager_name="bench",
                inception_date="2018-01-01",
                fund_size_billion=10.0 + fund_index,
                management_fee=1.2,
                custody_fee=0.2,
                annualized_return_3y=5.0,
                annualized_return_5y=6.0,
                max_drawdown=-10.0,
                sharpe_ratio=1.0,
                category_rank_percentile=50,
                manager_years=5,
                source=BENCH_SOURCE,
                data_updated_at="2026-09-26T00:00:00+08:00",
                navs=navs,
                ai_summary="synthetic bench fund",
            )
        )
    return funds


@dataclass
class ScenarioResult:
    mode: str
    elapsed_seconds: float
    fund_rows: int
    nav_rows: int
    metric_rows: int


def _row_counts(db: Session) -> tuple[int, int, int]:
    funds = int(db.scalar(select(func.count()).select_from(Fund)) or 0)
    navs = int(db.scalar(select(func.count()).select_from(FundNav)) or 0)
    metrics = int(db.scalar(select(func.count()).select_from(FundMetric)) or 0)
    return funds, navs, metrics


def run_scenario(
    funds: list[FundDetail],
    *,
    mode: str,
    batch_size: int,
    database_path: Path,
) -> ScenarioResult:
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        ensure_snapshot_state(session)
        session.commit()
        generation_id = _new_generation_id(mode)
        state = lock_snapshot_state(session)
        nav_count = sum(len(fund.navs) for fund in funds)
        snapshot = stage_snapshot(
            session,
            generation_id=generation_id,
            source=BENCH_SOURCE,
            fund_count=len(funds),
            nav_count=nav_count,
            metric_count=len(funds),
        )
        started = perf_counter()
        if mode == "batch":
            stage_funds_batch(session, funds, generation_id, batch_size=batch_size)
        else:
            for fund in funds:
                upsert_fund_profile(session, fund, generation_id)
                session.flush()
                upsert_fund_metrics(session, fund, generation_id)
                upsert_fund_navs(session, fund, generation_id)
        validate_staged_snapshot(session, snapshot)
        promote_snapshot(session, state=state, snapshot=snapshot)
        session.commit()
        elapsed = perf_counter() - started
        fund_rows, nav_rows, metric_rows = _row_counts(session)
        return ScenarioResult(
            mode=mode,
            elapsed_seconds=round(elapsed, 4),
            fund_rows=fund_rows,
            nav_rows=nav_rows,
            metric_rows=metric_rows,
        )
    finally:
        session.close()
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark per-point vs batched fund snapshot writes.")
    parser.add_argument("--fund-count", type=int, default=200)
    parser.add_argument("--nav-points", type=int, default=1200)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--output",
        default=(ROOT / "output" / "bench" / "sync-bench.json").as_posix(),
        help="Where to write the JSON benchmark result (relative paths resolve from repo root).",
    )
    args = parser.parse_args(argv)

    bench_root = ROOT / "output" / "bench"
    bench_root.mkdir(parents=True, exist_ok=True)
    work_dir = bench_root / "work"
    work_dir.mkdir(exist_ok=True)

    funds = build_synthetic_funds(args.fund_count, args.nav_points)
    point_result = run_scenario(
        funds,
        mode="per_point",
        batch_size=args.batch_size,
        database_path=work_dir / "bench-point.db",
    )
    batch_result = run_scenario(
        funds,
        mode="batch",
        batch_size=args.batch_size,
        database_path=work_dir / "bench-batch.db",
    )
    speedup = (
        round(point_result.elapsed_seconds / batch_result.elapsed_seconds, 3)
        if batch_result.elapsed_seconds > 0
        else float("inf")
    )
    payload = {
        "schema_version": 1,
        "source": BENCH_SOURCE,
        "fund_count": args.fund_count,
        "nav_points_per_fund": args.nav_points,
        "total_nav_points": args.fund_count * args.nav_points,
        "batch_size": args.batch_size,
        "per_point": {
            "elapsed_seconds": point_result.elapsed_seconds,
            "fund_rows": point_result.fund_rows,
            "nav_rows": point_result.nav_rows,
            "metric_rows": point_result.metric_rows,
        },
        "batch": {
            "elapsed_seconds": batch_result.elapsed_seconds,
            "fund_rows": batch_result.fund_rows,
            "nav_rows": batch_result.nav_rows,
            "metric_rows": batch_result.metric_rows,
        },
        "speedup_multiple": speedup,
        "note": "All data is synthetic; no network calls. Rows equal the staged peak for one generation.",
    }
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
