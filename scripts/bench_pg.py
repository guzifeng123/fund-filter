from __future__ import annotations

"""D3: PostgreSQL synthetic write benchmark + SQLite control.

Fully synthetic, no network. Loads N x M fund_navs rows into a throwaway local
PostgreSQL database and compares per-point staging vs the B3 batched
``stage_funds_batch`` across a sweep of ``batch_size`` values, then reports the
optimal batch size, throughput, on-disk size and simple query latencies. A
SQLite control run gives a comparable number on the zero-config store.

The throwaway PG database is dropped on exit unless ``--keep-db`` is passed.
Output JSON (gitignored) lands at ``output/bench/pg-sync-bench.json``.
"""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import time
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

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

ADMIN_URL = "postgresql+psycopg://postgres@localhost:55432/postgres"
HOST = "localhost:55432"
BENCH_SOURCE = "bench_pg_synthetic"
BENCH_EPOCH = date(2026, 9, 30)


def _new_generation_id(label: str) -> str:
    return f"bench-{label}-{uuid4().hex[:12]}"


def build_synthetic_funds(fund_count: int, nav_points: int) -> list[FundDetail]:
    funds: list[FundDetail] = []
    for fund_index in range(fund_count):
        code = f"PGB{fund_index:06d}"
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
                name=f"PG Bench Fund {fund_index}",
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
                data_updated_at="2026-09-30T00:00:00+08:00",
                navs=navs,
                ai_summary="synthetic pg bench fund",
            )
        )
    return funds


@dataclass
class LoadResult:
    mode: str
    batch_size: int
    elapsed_seconds: float
    fund_rows: int
    nav_rows: int
    metric_rows: int

    @property
    def rows_per_second(self) -> float:
        return round(self.nav_rows / self.elapsed_seconds, 1) if self.elapsed_seconds > 0 else 0.0


def _row_counts(db: Session) -> tuple[int, int, int]:
    funds = int(db.scalar(select(func.count()).select_from(Fund)) or 0)
    navs = int(db.scalar(select(func.count()).select_from(FundNav)) or 0)
    metrics = int(db.scalar(select(func.count()).select_from(FundMetric)) or 0)
    return funds, navs, metrics


def _prepare_session(engine: Engine) -> Session:
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    ensure_snapshot_state(session)
    session.commit()
    return session


def _do_load(
    session: Session,
    funds: list[FundDetail],
    *,
    mode: str,
    batch_size: int,
) -> LoadResult:
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
    return LoadResult(
        mode=mode,
        batch_size=batch_size,
        elapsed_seconds=round(elapsed, 4),
        fund_rows=fund_rows,
        nav_rows=nav_rows,
        metric_rows=metric_rows,
    )


def _truncate_pg(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE fund_navs, fund_metrics, funds, fund_data_snapshots "
                "RESTART IDENTITY CASCADE"
            )
        )


def _pg_sizes(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        navs_bytes = int(
            connection.execute(
                text("SELECT pg_total_relation_size('fund_navs')")
            ).scalar_one()
        )
        funds_bytes = int(
            connection.execute(text("SELECT pg_total_relation_size('funds')")).scalar_one()
        )
        db_name = connection.execute(text("SELECT current_database()")).scalar_one()
        db_bytes = int(
            connection.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar_one()
        )
    return {
        "fund_navs_total_bytes": navs_bytes,
        "funds_total_bytes": funds_bytes,
        "database_bytes": db_bytes,
        "database_name": str(db_name),
    }


def _pg_query_timings(engine: Engine, fund_count: int) -> dict[str, float]:
    sample_fund = f"PGB{(fund_count // 2):06d}"
    timings: dict[str, float] = {}
    with engine.connect() as connection:
        for label, sql in (
            (
                "latest_nav_by_fund",
                "SELECT nav, accumulated_nav FROM fund_navs "
                "WHERE fund_code = :c ORDER BY trade_date DESC LIMIT 1",
            ),
            (
                "range_navs_by_fund",
                "SELECT count(*) FROM fund_navs WHERE fund_code = :c "
                "AND trade_date BETWEEN '2020-01-01' AND '2026-09-30'",
            ),
        ):
            # warmup
            connection.execute(text(sql), {"c": sample_fund})
            runs = []
            for _ in range(5):
                t0 = perf_counter()
                connection.execute(text(sql), {"c": sample_fund})
                runs.append(perf_counter() - t0)
            timings[label] = round(min(runs) * 1000, 3)  # ms, best of 5
    return timings


def _create_pg_database() -> str:
    name = f"fund_d3_bench_{uuid4().hex[:12]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()
    return f"postgresql+psycopg://postgres@{HOST}/{name}"


def _drop_pg_database(url: str) -> None:
    name = url.rsplit("/", 1)[1]
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        admin.dispose()


def run_pg(
    funds: list[FundDetail],
    batch_sizes: list[int],
    keep_db: bool,
) -> dict[str, object]:
    url = _create_pg_database()
    engine = create_engine(
        url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=0"},
    )
    pg_results: list[dict[str, object]] = []
    sizes: dict[str, int] = {}
    query_timings: dict[str, float] = {}
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(engine)

        # Per-point baseline on a fresh dataset.
        session = _prepare_session(engine)
        point = _do_load(session, funds, mode="per_point", batch_size=0)
        session.close()
        pg_results.append(_result_dict(point))

        # Batch sweep: reset the tables between sizes so each run inserts fresh.
        for size in batch_sizes:
            _truncate_pg(engine)
            session = _prepare_session(engine)
            result = _do_load(session, funds, mode="batch", batch_size=size)
            session.close()
            pg_results.append(_result_dict(result))

        sizes = _pg_sizes(engine)
        query_timings = _pg_query_timings(engine, len(funds))
    finally:
        engine.dispose()
        if keep_db:
            print(f"[bench_pg] --keep-db: leaving {url}")
        else:
            _drop_pg_database(url)

    batch_results = [r for r in pg_results if r["mode"] == "batch"]
    best = min(batch_results, key=lambda r: r["elapsed_seconds"]) if batch_results else None
    return {
        "engine": "postgresql",
        "results": pg_results,
        "best_batch_size": best["batch_size"] if best else None,
        "best_rows_per_second": best["rows_per_second"] if best else None,
        "per_point_rows_per_second": point.rows_per_second,
        "sizes_bytes": sizes,
        "query_timings_ms": query_timings,
    }


def _run_sqlite_scenario(
    funds: list[FundDetail],
    *,
    mode: str,
    batch_size: int,
    db_path: Path,
) -> LoadResult:
    if db_path.exists():
        db_path.unlink()
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    try:
        session = _prepare_session(engine)
        result = _do_load(session, funds, mode=mode, batch_size=batch_size)
        session.close()
    finally:
        engine.dispose()
    return result


def run_sqlite_control(
    funds: list[FundDetail],
    batch_size: int,
    work_dir: Path,
) -> dict[str, object]:
    point_path = work_dir / "pg-bench-sqlite-point.db"
    batch_path = work_dir / "pg-bench-sqlite-batch.db"
    point = _run_sqlite_scenario(funds, mode="per_point", batch_size=0, db_path=point_path)
    batch = _run_sqlite_scenario(
        funds, mode="batch", batch_size=batch_size, db_path=batch_path
    )
    db_bytes = point_path.stat().st_size + batch_path.stat().st_size
    return {
        "engine": "sqlite",
        "per_point": _result_dict(point),
        "batch": _result_dict(batch),
        "db_bytes_total": db_bytes,
    }


def _result_dict(result: LoadResult) -> dict[str, object]:
    return {
        "mode": result.mode,
        "batch_size": result.batch_size,
        "elapsed_seconds": result.elapsed_seconds,
        "fund_rows": result.fund_rows,
        "nav_rows": result.nav_rows,
        "metric_rows": result.metric_rows,
        "rows_per_second": result.rows_per_second,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic PG vs SQLite write benchmark.")
    parser.add_argument("--fund-count", type=int, default=800)
    parser.add_argument("--nav-points", type=int, default=1000)
    parser.add_argument(
        "--batch-sizes",
        default="25,50,100,200,500",
        help="Comma-separated batch sizes to sweep for the PG batched path.",
    )
    parser.add_argument("--sqlite-batch-size", type=int, default=100)
    parser.add_argument("--keep-db", action="store_true", help="Do not drop the temp PG db.")
    parser.add_argument(
        "--output",
        default=(ROOT / "output" / "bench" / "pg-sync-bench.json").as_posix(),
    )
    parser.add_argument("--skip-sqlite", action="store_true")
    args = parser.parse_args(argv)

    bench_root = ROOT / "output" / "bench"
    bench_root.mkdir(parents=True, exist_ok=True)
    work_dir = bench_root / "work"
    work_dir.mkdir(exist_ok=True)

    batch_sizes = [int(x) for x in args.batch_sizes.split(",") if x.strip()]
    funds = build_synthetic_funds(args.fund_count, args.nav_points)
    total_navs = args.fund_count * args.nav_points
    print(f"[bench_pg] loading {total_navs:,} nav rows "
          f"({args.fund_count} funds x {args.nav_points} points)")

    started = time.time()
    pg = run_pg(funds, batch_sizes, args.keep_db)
    payload: dict[str, object] = {
        "schema_version": 1,
        "source": BENCH_SOURCE,
        "fund_count": args.fund_count,
        "nav_points_per_fund": args.nav_points,
        "total_nav_rows": total_navs,
        "postgres": pg,
    }
    if not args.skip_sqlite:
        sqlite = run_sqlite_control(funds, args.sqlite_batch_size, work_dir)
        payload["sqlite"] = sqlite

    # --- Extrapolation to ~16M rows (13k funds x 1247 points) ----------------
    measured_rows = total_navs
    best_rps = float(pg.get("best_rows_per_second") or 0)
    sizes_bytes = pg.get("sizes_bytes") or {}
    navs_total_bytes = float(sizes_bytes.get("fund_navs_total_bytes") or 0)
    extrapolated_rows = 16_000_000
    extrapolation: dict[str, object] = {}
    if measured_rows > 0 and best_rps > 0:
        extrapolation["estimated_full_write_seconds"] = round(extrapolated_rows / best_rps, 1)
        extrapolation["estimated_full_write_minutes"] = round(extrapolated_rows / best_rps / 60, 1)
    if measured_rows > 0 and navs_total_bytes > 0:
        extrapolation["estimated_fund_navs_bytes"] = round(
            navs_total_bytes * extrapolated_rows / measured_rows
        )
        extrapolation["estimated_fund_navs_gb"] = round(
            navs_total_bytes * extrapolated_rows / measured_rows / (1024**3), 2
        )
    extrapolation["assumptions"] = (
        "Linear extrapolation from the measured synthetic load; row width and "
        "index-to-data ratio assumed constant; no autovacuum/maintenance I/O "
        "included; single-node local PostgreSQL 16 + pgvector, warm OS cache."
    )
    payload["extrapolation_to_16m_rows"] = extrapolation
    payload["wall_clock_seconds"] = round(time.time() - started, 1)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"[bench_pg] wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
