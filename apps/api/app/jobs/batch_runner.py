"""D2 background batch runner: claim -> per-fund pipeline -> one atomic generation.

This is the orchestration that drives the independent :class:`~app.jobs.batch_state.BatchState`
checkpoint over the Alembic-managed business database. It reuses the exact write
primitives the single-shot atomic snapshot job uses
(:func:`~app.repositories.fund_snapshots.lock_snapshot_state` ->
:func:`~app.repositories.fund_snapshots.stage_snapshot` ->
:func:`~app.repositories.funds.stage_funds_batch` ->
:func:`~app.repositories.fund_snapshots.validate_staged_snapshot` ->
:func:`~app.repositories.fund_snapshots.promote_snapshot`) without touching
``sync_fund_data.task()``.

Per-batch contract (D0, do not loosen):

* One batch = one claimed set = one promoted ``generation_id``. The funds that
  pass quality + reconciliation are staged together and promoted atomically;
  funds that do not pass are never staged into that generation.
* Per-fund isolation: a bad/absent/transient fund never sinks its batch.
* Checkpoint reasons (D4 reporting depends on these literal strings):
  - passed            -> ``mark_done(generation_id, nav_points, fund_written=1)``
  - danjuan not listed / 404 / 暂不销售
                      -> ``mark_skipped("danjuan_not_listed")``
  - B2 quality error  -> ``mark_skipped("quality_failed")``
  - cross-check mismatch (unit/accumulated NAV critical)
                      -> ``mark_skipped("reconciliation_mismatch")``
  - transient exhausted -> ``mark_failed(retryable=True)``
* ``--dry-run`` fetches + reconciles + quality-adjudicates but never stages,
  promotes, or writes the business database (and never mutates the checkpoint).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import logging
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import nav_series_quality as series_q
from app.core import profile_quality as profile_q
from app.core.config import Settings, settings
from app.core.reconciliation_service import IsolatedReconciliation, ReconciliationService
from app.db.models import Fund, FundDataSnapshot, FundNav, JobRun, JsonObject, JsonValue
from app.jobs.batch_state import BatchState
from app.jobs.batch_throttle import (
    BatchThrottle,
    DeterministicReject,
    TransientUpstreamError,
    is_deterministic_message,
)
from app.repositories.fund_snapshots import (
    ensure_snapshot_state,
    lock_snapshot_state,
    promote_snapshot,
    refresh_snapshot_metadata,
    stage_snapshot,
    validate_staged_snapshot,
)
from app.repositories.funds import stage_funds_batch
from app.repositories.portfolios import ensure_default_portfolios
from app.schemas.funds import FundDetail

logger = logging.getLogger(__name__)

#: Skip-reason literals the runner writes to the checkpoint (D4 report contract).
REASON_DANJUAN_NOT_LISTED = "danjuan_not_listed"
REASON_QUALITY_FAILED = "quality_failed"
REASON_RECONCILIATION_MISMATCH = "reconciliation_mismatch"
#: F-phase: precise >=3y check moved down from plan time to here. A fund whose
#: primary-source inception_date is younger than 3y (and short history is off)
#: is skipped here -- never staged, never promoted into a generation.
REASON_INSUFFICIENT_HISTORY = "insufficient_history"

#: Cap the code lists embedded in the per-generation details envelope, mirroring
#: the existing DETAIL_FUND_LIMIT / NAV_WARNING_DETAIL_LIMIT truncation style.
_DETAIL_CODE_LIMIT = 200


class PrimaryFundFetcher(Protocol):
    """Per-code primary pull. The eastmoney adapter supplies this in production;
    tests hand in a fake so no HTTP / akshare is ever touched."""

    name: str

    def fetch_fund(
        self, code: str, *, as_of: date, start_date: date | None
    ) -> FundDetail:
        """Build the :class:`FundDetail` for ``code``.

        ``start_date`` is the latest NAV date already staged for the fund (the
        incremental lower bound, B4): the real adapter only fetches pages newer
        than it, merging against its local history cache.
        """
        ...


class _ShardAwareClaim(Protocol):
    """The D1 claim_batch signature (added later on the integration branch).

    Casting to this lets the shard-forwarding branch type-check against the D1
    kwargs while remaining legal on the current 3-arg signature, where the
    branch is never taken at runtime.
    """

    def __call__(
        self,
        batch_size: int,
        worker_id: str,
        *,
        shards: int | None = ...,
        shard: int | None = ...,
    ) -> list[str]: ...


# --------------------------------------------------------------------------- #
# Per-fund outcomes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Outcome:
    code: str
    kind: str  # "passed" | "skipped" | "failed"
    fund: FundDetail | None = None
    reason: str | None = None
    error: str | None = None
    retryable: bool = False

    @classmethod
    def passed(cls, code: str, fund: FundDetail) -> "_Outcome":
        return cls(code=code, kind="passed", fund=fund)

    @classmethod
    def skipped(cls, code: str, reason: str) -> "_Outcome":
        return cls(code=code, kind="skipped", reason=reason)

    @classmethod
    def failed(cls, code: str, error: str, *, retryable: bool) -> "_Outcome":
        return cls(code=code, kind="failed", error=error, retryable=retryable)


@dataclass(frozen=True)
class BatchReport:
    """One processed batch (used by dry-run and the run summary)."""

    codes: tuple[str, ...]
    outcomes: tuple[_Outcome, ...]
    generation_id: str | None

    @property
    def passed_codes(self) -> list[str]:
        return [o.code for o in self.outcomes if o.kind == "passed"]

    @property
    def success_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(1 for o in self.outcomes if o.kind == "passed") / len(self.outcomes)


@dataclass
class RunSummary:
    batches: int = 0
    claimed: int = 0
    passed: int = 0
    skipped: int = 0
    failed: int = 0
    generations: list[str] = field(default_factory=list)
    reports: list[BatchReport] = field(default_factory=list)


def _new_generation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"snapshot-{stamp}-{uuid4().hex[:12]}"


class BatchRunner:
    """Claim batches from the checkpoint and promote the passed set per batch."""

    def __init__(
        self,
        db: Session,
        state: BatchState,
        *,
        fetcher: PrimaryFundFetcher,
        reconciliation: ReconciliationService | None,
        throttle: BatchThrottle,
        settings_: Settings = settings,
        job_id: str = "batch-sync",
        worker_id: str = "worker-1",
        as_of: date | None = None,
        shards: int | None = None,
        shard: int | None = None,
    ) -> None:
        self._db = db
        self._state = state
        self._fetcher = fetcher
        self._reconciliation = reconciliation
        self._throttle = throttle
        self._settings = settings_
        self.job_id = job_id
        self._worker_id = worker_id
        self._as_of = as_of or datetime.now(timezone.utc).date()
        self._shards = shards
        self._shard = shard
        self._source_name = fetcher.name
        # D1 forward-compat: claim_batch currently takes (batch_size, worker_id).
        # If a later D1 revision adds shards/shard kwargs, forward them; until
        # then shard filtering is applied by the D1 merge and we just record it.
        self._claim_supports_shards = "shards" in inspect.signature(
            state.claim_batch
        ).parameters
        if (shards is not None or shard is not None) and not self._claim_supports_shards:
            logger.info(
                "claim_batch does not yet accept shards/shard (D1); "
                "shards=%s shard=%s recorded but not forwarded at claim time",
                shards,
                shard,
            )

    # ------------------------------------------------------------------ claim
    def _claim(self, batch_size: int) -> list[str]:
        # D1 forward-compat: forward shards/shard only once claim_batch accepts
        # them. getattr yields Any, so binding it to the shard-aware Protocol
        # needs no cast: passes whether or not D1's shard kwargs exist at
        # type-check time, while the runtime inspect probe selects this branch
        # only when claim_batch actually accepts shards/shard.
        if self._claim_supports_shards:
            shard_claim: _ShardAwareClaim = getattr(self._state, "claim_batch")
            return list(
                shard_claim(batch_size, self._worker_id, shards=self._shards, shard=self._shard)
            )
        return list(self._state.claim_batch(batch_size, self._worker_id))

    # ------------------------------------------------------------ per-fund DB
    def _latest_nav_trade_date(self, code: str) -> date | None:
        raw = self._db.scalar(
            select(func.max(FundNav.trade_date)).where(FundNav.fund_code == code)
        )
        if not isinstance(raw, str) or len(raw) != 10:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    # ------------------------------------------------------------- per-fund
    def _min_inception_date(self) -> date:
        """Earliest inception_date that still counts as ">=3y" at ``self._as_of``."""
        as_of = self._as_of
        try:
            return date(as_of.year - 3, as_of.month, as_of.day)
        except ValueError:  # Feb 29 -> clamp to Feb 28 of three years prior
            return date(as_of.year - 3, as_of.month, 28)

    def _has_min_history(self, fund: FundDetail) -> bool:
        """True when the fund's inception_date is not younger than 3y.

        ``inception_date`` is an ISO ``YYYY-MM-DD`` string set by the builder
        from the F10 成立日期. A fund qualifies once its inception_date is on or
        before the three-year cutoff relative to ``self._as_of``.
        """
        try:
            inception = date.fromisoformat(fund.inception_date)
        except ValueError:
            # An unparseable inception date is a structural data reject, not an
            # age decision: let it fall through to the B2 quality gate below.
            logger.warning("unparseable inception_date=%r for %s", fund.inception_date, fund.code)
            return True
        return inception <= self._min_inception_date()

    def _process_one(self, code: str) -> _Outcome:
        start_date = self._latest_nav_trade_date(code)
        try:
            fund = self._throttle.run(
                "eastmoney",
                lambda: self._fetcher.fetch_fund(
                    code, as_of=self._as_of, start_date=start_date
                ),
            )
        except DeterministicReject as exc:
            return _Outcome.skipped(code, exc.reason)
        except TransientUpstreamError as exc:
            return _Outcome.failed(code, str(exc), retryable=True)
        except ValueError as exc:
            # Primary build/parse produced an unusable fund: deterministic data reject.
            logger.info("primary build rejected %s: %s", code, exc)
            return _Outcome.skipped(code, REASON_QUALITY_FAILED)

        # F-phase: precise ">=3y" hard check, moved down from plan time. We only
        # learn the real inception_date once the primary source is fetched. When
        # short-history inclusion is off, a fund younger than 3y is skipped here
        # (never staged, never promoted into a generation); the switch on lets it
        # through, aligned with the short_history_included caliber.
        if not self._settings.fund_batch_include_short_history and not self._has_min_history(fund):
            logger.info("fund %s inception_date=%s younger than 3y; skipping", code, fund.inception_date)
            return _Outcome.skipped(code, REASON_INSUFFICIENT_HISTORY)

        # B2 per-fund structural quality gate.
        series_report = series_q.assess_nav_series_quality([fund], source_name=self._source_name)
        profile_report = profile_q.assess_profile_quality([fund], source_name=self._source_name)
        if series_report.errors or profile_report.errors:
            return _Outcome.skipped(code, REASON_QUALITY_FAILED)

        # C1/C3 per-fund isolated cross-check.
        if self._reconciliation is not None:
            result = self._reconciliation.reconcile_one_fund_isolated(fund)
            verdict = self._classify_reconciliation(code, result)
            if verdict is not None:
                return verdict
        return _Outcome.passed(code, fund)

    def _classify_reconciliation(
        self, code: str, result: IsolatedReconciliation
    ) -> _Outcome | None:
        status = result.report.status
        if status == "mismatch":
            return _Outcome.skipped(code, REASON_RECONCILIATION_MISMATCH)
        if status == "source_unavailable" or not result.danjuan_available:
            if is_deterministic_message(result.danjuan_error):
                return _Outcome.skipped(code, REASON_DANJUAN_NOT_LISTED)
            return _Outcome.failed(
                code,
                result.danjuan_error or "danjuan required source unavailable",
                retryable=True,
            )
        # "verified" / "unverified" are promotable (the strict whole-snapshot
        # gate only blocks mismatch / source_unavailable).
        return None

    # ------------------------------------------------------------- promotion
    def _promote_batch(
        self,
        passed: list[FundDetail],
        *,
        job_id: str,
        batch_no: int | None,
        reports: list[BatchReport],
    ) -> str:
        generation_id = _new_generation_id()
        state = lock_snapshot_state(self._db)
        nav_count = sum(len(f.navs) for f in passed)
        snapshot = stage_snapshot(
            self._db,
            generation_id=generation_id,
            source=self._source_name,
            fund_count=len(passed),
            nav_count=nav_count,
            metric_count=len(passed),
        )
        stage_funds_batch(
            self._db, passed, generation_id, batch_size=self._settings.fund_write_batch_size
        )
        ensure_default_portfolios(self._db)
        validate_staged_snapshot(self._db, snapshot)
        promote_snapshot(self._db, state=state, snapshot=snapshot)
        self._record_generation_details(
            generation_id=generation_id,
            job_id=job_id,
            batch_no=batch_no,
            passed=passed,
            reports=reports,
        )
        self._db.commit()
        return generation_id

    def _record_generation_details(
        self,
        *,
        generation_id: str,
        job_id: str,
        batch_no: int | None,
        passed: list[FundDetail],
        reports: list[BatchReport],
    ) -> None:
        skipped = [(o.code, o.reason) for r in reports for o in r.outcomes if o.kind == "skipped"]
        failed = [(o.code, o.error) for r in reports for o in r.outcomes if o.kind == "failed"]
        passed_codes: list[JsonValue] = [code for code in (f.code for f in passed[:_DETAIL_CODE_LIMIT])]
        skipped_rows: list[JsonValue] = [
            {"code": c, "reason": r} for c, r in skipped[:_DETAIL_CODE_LIMIT]
        ]
        failed_rows: list[JsonValue] = [
            {"code": c, "error": e} for c, e in failed[:_DETAIL_CODE_LIMIT]
        ]
        details: JsonObject = {
            "source": self._source_name,
            "runner": "batch_runner",
            "job_id": job_id,
            "batch_no": batch_no,
            "shard": self._shard,
            "shard_workers": self._settings.fund_batch_workers,
            "snapshot_generation_id": generation_id,
            "passed_count": len(passed),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "passed_codes": passed_codes,
            "passed_codes_truncated": len(passed) > _DETAIL_CODE_LIMIT,
            "skipped": skipped_rows,
            "failed": failed_rows,
        }
        job = JobRun(
            name=f"batch_sync:{job_id}",
            status="success",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            details=details,
        )
        self._db.add(job)
        self._db.flush()

    # -------------------------------------------- coalesced full-market model
    # A full-market job spans hundreds of batches. Promoting one generation per
    # batch would move the single active-generation pointer to each batch in turn,
    # so after the run only the last batch's funds would be visible. In coalesced
    # mode the whole job accumulates into ONE staging generation that is published
    # exactly once, after every batch is processed; an operator pause
    # (``--max-batches``) or a crash leaves it staging and ``--resume`` reattaches.
    def _resume_coalesced_generation(self) -> str | None:
        """Recover an unfinished coalesced generation id at the start of a run."""
        generation_id = self._state.get_coalesced_generation(self.job_id)
        if generation_id is None:
            return None
        if self._db.get(FundDataSnapshot, generation_id) is None:
            raise RuntimeError(
                f"checkpoint references coalesced generation {generation_id!r} for "
                f"job {self.job_id!r} that is absent from the business database; "
                "refusing to create a parallel generation"
            )
        return generation_id

    def _stage_into_coalesced(
        self, generation_id: str | None, passed: list[FundDetail]
    ) -> str:
        """Create the job generation once, then accumulate this batch into it.

        The generation stays ``staging`` (invisible; reads only see the active
        generation) until :meth:`_finalize_coalesced`. Each batch commits as it
        lands, so a crash loses only the in-flight batch, whose codes are reclaimed
        and re-staged idempotently on resume.
        """
        if generation_id is None:
            generation_id = _new_generation_id()
            # Empty-DB first run: ensure the singleton state row and a legacy
            # baseline exist before opening a coalesced staging generation (the
            # per-batch path gets this implicitly via lock_snapshot_state).
            ensure_snapshot_state(self._db)
            stage_snapshot(
                self._db,
                generation_id=generation_id,
                source=self._source_name,
                fund_count=0,
                nav_count=0,
                metric_count=0,
            )
            ensure_default_portfolios(self._db)
            # Persist the staging generation FIRST ...
            self._db.commit()
            # ... then point the checkpoint at it, so a meta pointer can never
            # reference a generation row that does not exist in the business DB.
            self._state.set_coalesced_generation(self.job_id, generation_id)
        stage_funds_batch(
            self._db,
            passed,
            generation_id,
            batch_size=self._settings.fund_write_batch_size,
        )
        self._db.commit()
        return generation_id

    def _finalize_coalesced(self, generation_id: str) -> None:
        """Recount, validate and publish the single coalesced generation once."""
        snapshot = refresh_snapshot_metadata(
            self._db,
            generation_id=generation_id,
            fallback_source=self._source_name,
        )
        # A failed validation must leave the previous active generation serving.
        validate_staged_snapshot(self._db, snapshot)
        lock = lock_snapshot_state(self._db)
        promote_snapshot(self._db, state=lock, snapshot=snapshot)
        self._record_coalesced_job_details(snapshot)
        self._db.commit()
        self._state.clear_coalesced_generation(self.job_id)

    def _record_coalesced_job_details(self, snapshot: FundDataSnapshot) -> None:
        """Record one job-level JobRun. Counts are authoritative across resumed
        processes: the generation's own recounted row counts plus the checkpoint's
        terminal-state stats (a resumed process only re-handles its own batches)."""
        stats = self._state.stats()
        skipped_rows: list[JsonValue] = [
            {"code": c, "reason": r} for c, r in self._state.terminal_skipped(_DETAIL_CODE_LIMIT)
        ]
        failed_rows: list[JsonValue] = [
            {"code": c, "error": e} for c, e in self._state.terminal_failed(_DETAIL_CODE_LIMIT)
        ]
        passed_codes: list[JsonValue] = list(
            self._db.scalars(
                select(Fund.code)
                .where(Fund.snapshot_generation_id == snapshot.generation_id)
                .order_by(Fund.code)
                .limit(_DETAIL_CODE_LIMIT)
            ).all()
        )
        details: JsonObject = {
            "source": self._source_name,
            "runner": "batch_runner",
            "job_id": self.job_id,
            "coalesced": True,
            "shard": self._shard,
            "shard_workers": self._settings.fund_batch_workers,
            "snapshot_generation_id": snapshot.generation_id,
            "passed_count": snapshot.fund_count,
            "nav_count": snapshot.nav_count,
            "metric_count": snapshot.metric_count,
            "skipped_count": stats.by_status.get("skipped", 0),
            "failed_count": stats.by_status.get("failed", 0),
            "pending_count": stats.by_status.get("pending", 0),
            "in_flight_count": stats.by_status.get("in_flight", 0),
            "passed_codes": passed_codes,
            "passed_codes_truncated": snapshot.fund_count > _DETAIL_CODE_LIMIT,
            "skipped": skipped_rows,
            "failed": failed_rows,
        }
        now = datetime.now(timezone.utc)
        self._db.add(
            JobRun(
                name=f"batch_sync:{self.job_id}",
                status="success",
                started_at=now,
                finished_at=now,
                details=details,
            )
        )
        self._db.flush()

    # ------------------------------------------------------------------ loop
    def run(
        self,
        *,
        batch_size: int | None = None,
        max_batches: int | None = None,
        dry_run: bool = False,
        coalesce: bool | None = None,
    ) -> RunSummary:
        size = batch_size or self._settings.fund_batch_size
        coalesce = (
            self._settings.fund_batch_coalesce_generation
            if coalesce is None
            else coalesce
        )
        summary = RunSummary()
        batch_no = 0
        # Coalesced jobs publish a single generation for the whole run; on resume
        # we reattach to the unfinished staging generation via checkpoint meta.
        coalesced_gen: str | None = None
        if coalesce and not dry_run:
            coalesced_gen = self._resume_coalesced_generation()
        exhausted = False
        while True:
            if max_batches is not None and batch_no >= max_batches:
                # Operator-paused (gray release): keep the staging generation and
                # do NOT publish; --resume with the same job_id keeps accumulating.
                break
            codes = self._claim(size)
            if not codes:
                exhausted = True
                break
            outcomes = [self._process_one(code) for code in codes]
            passed_funds = [o.fund for o in outcomes if o.kind == "passed" and o.fund is not None]
            full_report = BatchReport(
                codes=tuple(codes), outcomes=tuple(outcomes), generation_id=None
            )

            generation_id: str | None = None
            if not dry_run and passed_funds:
                try:
                    if coalesce:
                        coalesced_gen = self._stage_into_coalesced(
                            coalesced_gen, passed_funds
                        )
                        generation_id = coalesced_gen
                    else:
                        generation_id = self._promote_batch(
                            passed_funds,
                            job_id=self.job_id,
                            batch_no=batch_no,
                            reports=[full_report],
                        )
                except Exception:
                    self._db.rollback()
                    logger.exception(
                        "batch %d staging/promotion failed; %d codes stay in_flight",
                        batch_no,
                        len(codes),
                    )
                    raise

            # Checkpoint transitions happen AFTER the business DB write commits so
            # a crash leaves codes in_flight (reclaimed on restart), never falsely
            # done. In coalesced mode the generation is still staging here.
            if not dry_run:
                for outcome in outcomes:
                    if outcome.kind == "passed" and outcome.fund is not None:
                        assert generation_id is not None
                        self._state.mark_done(
                            outcome.code,
                            generation_id=generation_id,
                            nav_points=len(outcome.fund.navs),
                            fund_written=1,
                        )
                    elif outcome.kind == "skipped":
                        self._state.mark_skipped(outcome.code, outcome.reason or "")
                    else:
                        self._state.mark_failed(
                            outcome.code, outcome.error or "", retryable=outcome.retryable
                        )

            summary.batches += 1
            summary.claimed += len(codes)
            summary.passed += len(passed_funds)
            summary.skipped += sum(1 for o in outcomes if o.kind == "skipped")
            summary.failed += sum(1 for o in outcomes if o.kind == "failed")
            if not coalesce and generation_id is not None:
                summary.generations.append(generation_id)
            # Strip the full FundDetail payloads before retaining a report, so a
            # 354-batch full-market run cannot hold ~22m NAV points in memory.
            slim_outcomes = tuple(
                _Outcome(
                    code=o.code,
                    kind=o.kind,
                    fund=None,
                    reason=o.reason,
                    error=o.error,
                    retryable=o.retryable,
                )
                for o in outcomes
            )
            summary.reports.append(
                BatchReport(
                    codes=tuple(codes),
                    outcomes=slim_outcomes,
                    generation_id=generation_id,
                )
            )
            batch_no += 1

        # Publish the coalesced generation only when the checkpoint is naturally
        # exhausted (no pending codes left) -- never after an operator pause.
        if coalesce and not dry_run and coalesced_gen is not None and exhausted:
            self._finalize_coalesced(coalesced_gen)
            summary.generations = [coalesced_gen]
        return summary


__all__ = [
    "BatchRunner",
    "BatchReport",
    "PrimaryFundFetcher",
    "REASON_DANJUAN_NOT_LISTED",
    "REASON_QUALITY_FAILED",
    "REASON_RECONCILIATION_MISMATCH",
    "REASON_INSUFFICIENT_HISTORY",
    "RunSummary",
]
