#!/usr/bin/env python3
"""D2 batch sync CLI: drive the sharded checkpoint over the full-market universe.

This is the thin operator wrapper around :mod:`app.jobs.batch_runner`. It wires
the real (network) pieces -- the eastmoney per-code primary pull, the danjuan /
sina secondary cross-check feeds, and the per-domain throttle -- onto the
dependency-injected, fully-testable runner.

Examples::

    # Gray release: fetch + reconcile + quality-adjudicate, write nothing.
    python scripts/batch_sync.py --dry-run --limit 50

    # Real run, resuming pending + timed-out in_flight automatically.
    python scripts/batch_sync.py

    # Re-run only the previously failed codes.
    python scripts/batch_sync.py --retry

The checkpoint lives in its own SQLite DB (default ``output/batch/state.db``);
the business DB defaults to ``settings.database_url`` (SQLite for local runs).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = WORKSPACE_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.reconciliation_service import ReconciliationService  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.jobs.batch_runner import BatchRunner  # noqa: E402
from app.jobs.batch_state import BatchState  # noqa: E402
from app.jobs.batch_throttle import BatchThrottle  # noqa: E402


class ThrottledSecondary:
    """Route a secondary source's HTTP calls through the batch per-domain throttle."""

    def __init__(self, inner: object, throttle: BatchThrottle, domain: str) -> None:
        self._inner = inner
        self._throttle = throttle
        self._domain = domain
        self.source_name = getattr(inner, "source_name", domain)

    def fetch_profile(self, code: str) -> object:
        return self._throttle.run(self._domain, lambda: self._inner.fetch_profile(code))

    def fetch_navs(self, code: str, *, since: object = None) -> object:
        return self._throttle.run(
            self._domain, lambda: self._inner.fetch_navs(code, since=since)
        )

    def fetch_quotes(self, codes: list[str]) -> object:
        return self._throttle.run(self._domain, lambda: self._inner.fetch_quotes(codes))


class EastmoneyPerCodeFetcher:
    """Per-code primary pull: reuse the builder's fetch_raw -> FundDetail mapping."""

    name = "eastmoney_snapshot"

    def __init__(self, builder: object) -> None:
        self._builder = builder

    def fetch_fund(self, code: str, *, as_of: object, start_date: object) -> object:
        from app.data_sources.profiles.eastmoney_snapshot import build_fund_snapshot

        raw = self._builder.fetch_raw(code, as_of, start_date=start_date)
        return build_fund_snapshot(raw, as_of and _utc_now())


def _utc_now() -> object:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _build_throttle() -> BatchThrottle:
    return BatchThrottle(
        limits={
            "eastmoney": settings.fund_batch_min_interval_eastmoney,
            "danjuan": settings.fund_batch_min_interval_danjuan,
            "sina": settings.fund_batch_min_interval_sina,
        },
        max_retries=settings.fund_batch_max_retries,
        backoff_base_seconds=settings.fund_batch_backoff_base_seconds,
        backoff_cap_seconds=settings.fund_batch_backoff_cap_seconds,
    )


def _build_reconciliation(throttle: BatchThrottle, fetcher: object) -> ReconciliationService | None:
    if not settings.fund_reconcile_enabled:
        return None
    import importlib

    try:
        danjuan_module = importlib.import_module("app.data_sources.secondary.danjuan")
        sina_module = importlib.import_module("app.data_sources.secondary.sina")
        danjuan = getattr(danjuan_module, "DanjuanSource")(
            timeout_seconds=settings.fund_reconcile_secondary_timeout_seconds,
            min_interval_seconds=settings.fund_reconcile_secondary_min_interval_seconds,
        )
        sina = getattr(sina_module, "SinaSource")(
            timeout_seconds=settings.fund_reconcile_secondary_timeout_seconds,
            min_interval_seconds=settings.fund_reconcile_secondary_min_interval_seconds,
            batch=settings.fund_reconcile_sina_batch,
        )
    except ImportError as exc:
        print(f"reconciliation secondary clients unavailable; gate skipped: {exc}")
        return None
    return ReconciliationService(
        fetcher,
        ThrottledSecondary(danjuan, throttle, "danjuan"),
        ThrottledSecondary(sina, throttle, "sina"),
        settings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D2 sharded batch fund sync runner")
    parser.add_argument("--dry-run", action="store_true", help="fetch+reconcile+quality, write nothing")
    parser.add_argument("--limit", type=int, default=None, help="cap total claimed codes")
    parser.add_argument("--shards", type=int, default=None, help="total shards (D1)")
    parser.add_argument("--shard", type=int, default=None, help="this shard index (D1)")
    parser.add_argument("--resume", action="store_true", help="explicit: continue pending/timeout-in_flight (default)")
    parser.add_argument("--codes", nargs="*", default=None, help="restrict to these codes")
    parser.add_argument("--workers", type=int, default=None, help="parallel workers (default 1, hard cap 3)")
    parser.add_argument("--retry", action="store_true", help="reset failed rows to pending before running")
    parser.add_argument("--job-id", type=str, default="batch-sync")
    parser.add_argument("--state-db", type=Path, default=None, help="override checkpoint SQLite path")
    parser.add_argument("--max-batches", type=int, default=None, help="optional cap on batches processed")
    args = parser.parse_args(argv)

    workers = args.workers if args.workers is not None else settings.fund_batch_workers
    if workers > 3:
        print(f"--workers={workers} exceeds hard cap 3; clamping to 3", file=sys.stderr)
        workers = 3
    if workers > 1:
        print(
            f"warning: workers={workers} requested; D2 runs a single worker by default. "
            "Parallel claim is a later phase; this process stays sequential."
        )

    throttle = _build_throttle()
    fetcher = EastmoneyPerCodeFetcher(_build_builder())
    reconciliation = _build_reconciliation(throttle, fetcher)

    state = BatchState(args.state_db)
    try:
        if args.retry:
            reset = state.retry_failed()
            print(f"reset {reset} failed row(s) back to pending")
        db = get_sessionmaker()()
        runner = BatchRunner(
            db,
            state,
            fetcher=fetcher,
            reconciliation=reconciliation,
            throttle=throttle,
            job_id=args.job_id,
            shards=args.shards,
            shard=args.shard,
        )
        summary = runner.run(
            batch_size=settings.fund_batch_size,
            max_batches=args.max_batches,
            dry_run=args.dry_run,
        )
        print(
            f"batches={summary.batches} claimed={summary.claimed} "
            f"passed={summary.passed} skipped={summary.skipped} failed={summary.failed} "
            f"generations={len(summary.generations)} dry_run={args.dry_run}"
        )
        for report in summary.reports:
            print(f"  batch {report.codes}: success_rate={report.success_rate:.2f}")
        db.close()
    finally:
        state.close()
    return 0


def _build_builder() -> object:
    from app.data_sources.profiles.eastmoney_snapshot import EastmoneySnapshotBuilder

    return EastmoneySnapshotBuilder(
        settings.fund_eastmoney_timeout_seconds,
        settings.fund_batch_min_interval_eastmoney,
    )


if __name__ == "__main__":
    raise SystemExit(main())
