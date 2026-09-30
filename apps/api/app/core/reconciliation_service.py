"""Multi-source cross-check orchestration, pre-staging write gate and report sink.

This is the *orchestration* layer (C3). It does not itself decide whether two NAV
values agree -- that lives in the pure-function engine :mod:`app.core.reconciliation`
(C1). Its jobs are:

1. For every not-yet-staged fund, pull a secondary view:
   * ``danjuan``  -- unit-NAV history (from the fund's earliest primary NAV date)
     plus a profile; it is the *required* secondary source.
   * ``sina``     -- a single latest quote used only to cross-check the accumulated
     NAV (复权口径); it is best-effort and never by itself rejects a generation.
2. Adapt the primary :class:`~app.schemas.funds.FundDetail` into C1's
   :class:`~app.core.reconciliation.SourceSnapshot` contract and run the engine.
3. Apply strict / non-strict gating:
   * strict      -- any ``mismatch`` / ``source_unavailable`` fund raises
     :class:`ReconciliationError` so the atomic transaction rolls back and the
     previous generation keeps serving.
   * non-strict  -- those funds are downgraded to ``unverified`` and recorded as
     warnings; the generation still promotes.
4. Persist a compact summary into ``job_runs.details["reconciliation"]`` and the
   full per-fund report to ``FUND_RECONCILE_REPORT_DIR/{timestamp}.json``.

The secondary HTTP clients (C2) are never imported here: this module declares a
structural :class:`ReconciliationSourceLike` protocol, the sync job assembles the
concrete classes via a function-local import, and tests hand in plain fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.core import reconciliation as engine
from app.core.config import Settings
from app.schemas.funds import FundDetail, NavPoint

logger = logging.getLogger(__name__)

RECONCILE_REPORT_SCHEMA_VERSION = 1
THRESHOLD_VERSION = "reconciliation/v1"

# Job-details envelope budget: keep per-fund rows compact and bounded so a long
# fund list never bloats the job_runs JSON (mirrors NAV_WARNING_DETAIL_LIMIT).
DETAIL_FUND_LIMIT = 200

# Statuses that block promotion in strict mode. ``unverified`` is the non-strict
# degradation bucket and never blocks; ``verified`` passes even with minor warnings.
_BLOCKING_STATUSES = {"mismatch", "source_unavailable"}

# Primary FundDetail.fund_type already carries a canonical English bucket; map it
# to a Chinese hint so C1's map_fund_type collapses primary and the (Chinese)
# danjuan type_desc into the same canonical bucket.
_PRIMARY_TYPE_HINT: dict[str, str] = {
    "stock": "股票型",
    "mixed": "混合型",
    "bond": "债券型",
    "money": "货币型",
}


class ReconciliationError(ValueError):
    """Raised when the strict reconciliation gate rejects the candidate generation.

    The exception carries a JSON-serialisable summary of every blocking fund so the
    existing ``_run_job`` failure path records an audit trail without special
    plumbing.
    """

    def __init__(self, message: str, *, summary: dict[str, Any]) -> None:
        super().__init__(message)
        self.summary = summary


@runtime_checkable
class ReconciliationSourceLike(Protocol):
    """Structural shape C2's ``ReconciliationSource`` satisfies without inheriting.

    A source only needs to implement the calls it can answer; the orchestrator
    treats a missing/unsupported call (or an exception) as "source unavailable"
    rather than crashing the whole gate.
    """

    source_name: str

    def fetch_profile(self, code: str) -> Any:
        """Return this source's view of one fund's profile, or raise on failure."""
        ...

    def fetch_navs(self, code: str, *, since: Any = None) -> Any:
        """Return this source's unit-NAV history for ``code`` (optionally since a date)."""
        ...

    def fetch_quotes(self, codes: list[str]) -> Any:
        """Return latest quotes keyed by fund code (used for accumulated NAV)."""
        ...


@dataclass(frozen=True)
class _SecondaryResult:
    """Normalised secondary views for one fund, with reachability flags."""

    danjuan_available: bool
    danjuan_nav_points: list[engine.ReconcilableNavPoint]
    danjuan_profile: engine.ReconcilableProfile | None
    danjuan_error: str | None
    sina_available: bool
    sina_acc_nav: float | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class IsolatedReconciliation:
    """Result of a per-fund isolated cross-check (D2 batch runner).

    Unlike :meth:`ReconciliationService.reconcile_snapshot`, this never raises on
    a blocking fund: it returns the single-fund report plus the danjuan
    reachability signal so the batch runner can isolate one bad/absent fund
    instead of rolling back the whole generation. ``danjuan_error`` is the
    stringified exception the required source raised (empty when it answered);
    the runner classifies it as a hard "not listed" skip vs a transient retry.
    """

    report: engine.FundReconciliationReport
    danjuan_available: bool
    danjuan_error: str | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _earliest_nav_date(fund: FundDetail) -> date | None:
    earliest: date | None = None
    for point in fund.navs:
        if len(point.trade_date) != 10:
            continue
        parsed = _parse_iso_date(point.trade_date)
        if parsed is not None and (earliest is None or parsed < earliest):
            earliest = parsed
    return earliest


def _latest_iso_nav(fund: FundDetail) -> NavPoint | None:
    dated = [p for p in fund.navs if len(p.trade_date) == 10]
    if not dated:
        return fund.navs[-1] if fund.navs else None
    dated.sort(key=lambda p: p.trade_date)
    return dated[-1]


def _unit_change_pct(points: list[NavPoint], index: int) -> float | None:
    if index <= 0:
        return None
    previous = points[index - 1].nav
    if previous <= 0:
        return None
    return round(points[index].nav / previous - 1.0, 6)


class ReconciliationService:
    """Fetches secondary views, runs the C1 engine and enforces the write gate."""

    def __init__(
        self,
        primary_source: Any,
        danjuan: ReconciliationSourceLike,
        sina: ReconciliationSourceLike,
        settings: Settings,
    ) -> None:
        self._primary = primary_source
        self._danjuan = danjuan
        self._sina = sina
        self._settings = settings
        self.last_report_path: str | None = None

    # -- primary adaptation -----------------------------------------------------

    def _primary_nav_points(self, fund: FundDetail) -> list[engine.ReconcilableNavPoint]:
        points: list[engine.ReconcilableNavPoint] = []
        for index, point in enumerate(fund.navs):
            if len(point.trade_date) != 10:
                # Legacy year-precision samples are not traded dates; the engine
                # inner-joins on real dates, so year-precision points are skipped.
                continue
            points.append(
                engine.ReconcilableNavPoint(
                    date=date.fromisoformat(point.trade_date),
                    unit_nav=point.nav,
                    accumulated_nav=point.accumulated_nav,
                    daily_change_pct=_unit_change_pct(fund.navs, index),
                    source=self._primary.name,
                )
            )
        return points

    def _primary_profile(self, fund: FundDetail) -> engine.ReconcilableProfile:
        # Prefer the upstream's raw, un-collapsed type detail (eastmoney mobile FTYPE)
        # carried as a non-serialized private attribute, so the primary and secondary
        # type text both flow through C1's map_fund_type and collapse to the same
        # canonical bucket (e.g. "指数型-海外股票" <-> "QDII-股票" -> qdii). Other
        # data sources leave the private attribute unset; fall back to the 4-bucket
        # Chinese hint derived from the stored fund_type.
        primary_type_raw = getattr(fund, "_fund_type_raw", None) or _PRIMARY_TYPE_HINT.get(
            fund.fund_type, fund.fund_type
        )
        return engine.ReconcilableProfile(
            code=fund.code,
            name=fund.name,
            full_name=None,
            found_date=_parse_iso_date(fund.inception_date),
            # The eastmoney primary adapter does NOT disclose the fund-management
            # company or the custodian bank: upstream_provider/provider_profile are
            # source labels ("eastmoney" / "eastmoney_snapshot_v1"), not company
            # names. Report them honestly as absent. C1's engine treats a major
            # field present on only one side as a skip (warning) rather than a
            # blocking mismatch, so danjuan's real keeper_name/trup_name are
            # recorded without forcing a false contradiction.
            company=None,
            custodian=None,
            managers=[fund.manager_name] if fund.manager_name else [],
            fund_type_raw=primary_type_raw,
            benchmark=None,
            scale_text=f"{fund.fund_size_billion}亿" if fund.fund_size_billion >= 0 else None,
            rates=None,
            source=self._primary.name,
        )

    # -- secondary fetching (defensive: one bad fund never sinks the gate) -------

    def _fetch_secondary(self, fund: FundDetail) -> _SecondaryResult:
        warnings: list[str] = []
        nav_points: list[engine.ReconcilableNavPoint] = []
        profile: engine.ReconcilableProfile | None = None
        danjuan_available = True
        danjuan_error: str | None = None

        since = _earliest_nav_date(fund)
        try:
            raw_navs = self._danjuan.fetch_navs(fund.code, since=since) or []
            nav_points = [
                engine.ReconcilableNavPoint(
                    date=getattr(p, "date"),
                    unit_nav=getattr(p, "unit_nav", None),
                    accumulated_nav=getattr(p, "accumulated_nav", None),
                    daily_change_pct=getattr(p, "daily_change_pct", None),
                    source=self._danjuan.source_name,
                )
                for p in raw_navs
            ]
        except Exception as exc:  # required source: flagged, never swallowed
            danjuan_available = False
            danjuan_error = str(exc)
            warnings.append(f"danjuan navs unavailable for {fund.code}: {exc}")
        else:
            try:
                fetched = self._danjuan.fetch_profile(fund.code)
                if isinstance(fetched, engine.ReconcilableProfile):
                    profile = fetched
            except Exception as exc:
                # Profile-only failure degrades the profile comparison; NAV history
                # may still be comparable. Recorded as a warning, not fatal.
                warnings.append(f"danjuan profile unavailable for {fund.code}: {exc}")

        sina_available = True
        sina_acc_nav: float | None = None
        try:
            quotes = self._sina.fetch_quotes([fund.code]) or {}
            quote: Any
            if isinstance(quotes, dict):
                quote = quotes.get(fund.code)
            elif isinstance(quotes, list) and quotes:
                quote = quotes[0]
            else:
                quote = None
            if quote is not None:
                sina_acc_nav = (
                    quote.get("accumulated_nav") if isinstance(quote, dict)
                    else getattr(quote, "accumulated_nav", None)
                )
        except Exception as exc:
            # Sina is best-effort for accumulated NAV only; missing it never blocks.
            sina_available = False
            warnings.append(f"sina quote unavailable for {fund.code}: {exc}")

        return _SecondaryResult(
            danjuan_available=danjuan_available,
            danjuan_nav_points=nav_points,
            danjuan_profile=profile,
            danjuan_error=danjuan_error,
            sina_available=sina_available,
            sina_acc_nav=sina_acc_nav,
            warnings=tuple(warnings),
        )

    # -- the gate ---------------------------------------------------------------

    def reconcile_snapshot(self, funds: list[FundDetail]) -> engine.ReconciliationSummary:
        """Cross-check a not-yet-staged snapshot and enforce the strict gate.

        Returns the C1 ``ReconciliationSummary`` on success. Raises
        :class:`ReconciliationError` in strict mode when a fund blocks promotion.
        The on-disk report is written on both the success and rejection paths.
        """
        cfg = engine.ReconcileConfig.from_settings(self._settings)
        reports: list[engine.FundReconciliationReport] = []
        for fund in funds:
            secondary = self._fetch_secondary(fund)
            reports.append(self._reconcile_one_fund(fund, secondary, cfg))

        summary = engine.build_summary(reports, cfg)

        # Persist the full report on disk *before* deciding to raise, so a strict
        # rejection still leaves an auditable record. A write failure is logged,
        # never silently treated as "pass".
        report_path = self._write_report(summary)

        self._enforce_strict(summary, report_path, cfg)
        return summary

    # -- D2: per-fund isolated gate (never rolls back the whole generation) ----

    def reconcile_one_fund_isolated(self, fund: FundDetail) -> IsolatedReconciliation:
        """Cross-check a single fetched fund without any batch-wide side effect.

        Reuses the exact same ``_fetch_secondary`` + ``_reconcile_one_fund``
        primitives as the strict whole-snapshot gate, but returns the single-fund
        report (and the danjuan reachability signal) instead of raising on the
        first blocker. The batch runner decides per fund:

        * ``report.status == "mismatch"``        -> reconciliation_mismatch skip
        * ``report.status == "source_unavailable"`` and danjuan reachable but
          hard-404 / not-listed                  -> danjuan_not_listed skip
        * ``report.status == "source_unavailable"`` for a transient danjuan outage
                                                 -> retryable failed
        * ``verified`` / ``unverified``         -> eligible to be promoted
        """
        cfg = engine.ReconcileConfig.from_settings(self._settings)
        secondary = self._fetch_secondary(fund)
        report = self._reconcile_one_fund(fund, secondary, cfg)
        return IsolatedReconciliation(
            report=report,
            danjuan_available=secondary.danjuan_available,
            danjuan_error=secondary.danjuan_error,
        )

    # -- C1 engine adapter ------------------------------------------------------

    def _reconcile_one_fund(
        self,
        fund: FundDetail,
        secondary: _SecondaryResult,
        cfg: engine.ReconcileConfig,
    ) -> engine.FundReconciliationReport:
        primary_snapshot = engine.SourceSnapshot(
            code=fund.code,
            source=self._primary.name,
            profile=self._primary_profile(fund),
            nav_points=self._primary_nav_points(fund),
            fetched_at=_utc_now(),
            reachable=True,
            error=None,
        )
        secondary_snapshot = engine.SourceSnapshot(
            code=fund.code,
            source=self._danjuan.source_name,
            profile=secondary.danjuan_profile if secondary.danjuan_available else None,
            nav_points=secondary.danjuan_nav_points if secondary.danjuan_available else [],
            fetched_at=_utc_now(),
            reachable=secondary.danjuan_available,
            error=secondary.danjuan_error,
        )

        report = engine.reconcile_fund(primary_snapshot, secondary_snapshot, cfg)

        # Sina accumulated-NAV cross-check on the latest point. Sina is not a
        # required source: when it is down we only record a warning. When it is
        # reachable but disagrees beyond tolerance it becomes a critical failure
        # (strict -> mismatch, non-strict -> unverified).
        latest = _latest_iso_nav(fund)
        extra_warnings: list[str] = list(secondary.warnings)
        if secondary.sina_available and secondary.sina_acc_nav is not None and latest is not None:
            agree = engine.numbers_match(
                latest.accumulated_nav,
                secondary.sina_acc_nav,
                cfg.acc_nav_abs_tolerance,
                0.0,
            )
            if agree is False:
                report = replace(
                    report,
                    critical_failures=[
                        *report.critical_failures,
                        (
                            f"accumulated_nav: latest accumulated NAV "
                            f"{latest.accumulated_nav} vs sina {secondary.sina_acc_nav}"
                        ),
                    ],
                )
                report = engine.adjudicate(report, cfg)
        elif not secondary.sina_available:
            extra_warnings.append(
                f"sina accumulated NAV unavailable for {fund.code}; not blocking"
            )

        # Only NOW (after the sina accumulated-NAV critical may have been added) do
        # we consider softening a literal name mismatch: the softening gate reads
        # the fully-assembled critical_failures, so a sina accumulated-NAV
        # disagreement (or any other critical) keeps the name blocking.
        report = engine.maybe_soften_name_check(report, cfg)

        report = replace(report, warnings=[*report.warnings, *extra_warnings])

        # Non-strict: degrade a required-source outage to unverified + warning.
        # (mismatch is already downgraded to unverified inside C1's adjudicate.)
        if not cfg.strict and report.status == "source_unavailable":
            report = replace(
                report,
                status="unverified",
                warnings=[*report.warnings, "strict=false: required source outage downgraded to unverified"],
            )
        return report

    # -- strict / non-strict gate ----------------------------------------------

    def _enforce_strict(
        self,
        summary: engine.ReconciliationSummary,
        report_path: str | None,
        cfg: engine.ReconcileConfig,
    ) -> None:
        if not cfg.strict:
            return
        blocking = [r for r in summary.funds if r.status in _BLOCKING_STATUSES]
        if not blocking:
            return
        lines = [
            (
                f"{r.code}: status={r.status}, critical_failures={len(r.critical_failures)}, "
                f"nav_coverage={r.nav_coverage:.4f}, nav_agreement={r.nav_agreement:.4f}"
            )
            for r in blocking
        ]
        message = (
            "strict reconciliation gate rejected the candidate snapshot for "
            f"{len(blocking)} fund(s): " + "; ".join(lines)
        )
        raise ReconciliationError(message, summary=self.summary_to_details(summary, report_path))

    # -- serialisation (owned by C3; consumed by job details + read API) --------

    def summary_to_details(
        self,
        summary: engine.ReconciliationSummary,
        report_path: str | None,
    ) -> dict[str, Any]:
        funds: list[dict[str, Any]] = []
        for report in summary.funds:
            funds.append(
                {
                    "code": report.code,
                    "status": report.status,
                    "critical": bool(report.critical_failures),
                    "nav_coverage": round(report.nav_coverage, 6),
                    "nav_agreement": round(report.nav_agreement, 6),
                    "critical_failures": len(report.critical_failures),
                    "critical_failure_details": list(report.critical_failures),
                    "nav_mismatch_points": list(report.nav_mismatch_points),
                    "warnings": len(report.warnings),
                    "field_diffs": [
                        {
                            "field": fc.field,
                            "severity": fc.severity,
                            "match": fc.match,
                            "rule": fc.rule,
                            "detail": fc.detail,
                        }
                        for fc in report.field_checks
                    ],
                    "source_values": {
                        "sources": list(report.sources),
                        "nav_total": report.nav_total,
                        "nav_matched": report.nav_matched,
                        "nav_mismatch": report.nav_mismatch,
                        "nav_missing": report.nav_missing,
                    },
                }
            )
        return {
            "overall_status": summary.overall_status,
            "threshold_version": THRESHOLD_VERSION,
            "config_version": cfg_public(summary.config),
            "sources": [self._primary.name, self._danjuan.source_name, self._sina.source_name],
            "generated_at": summary.generated_at.isoformat(),
            "fund_count": len(funds),
            "critical_failure_count": sum(1 for r in summary.funds if r.critical_failures),
            "warning_count": sum(len(r.warnings) for r in summary.funds),
            "funds": funds[:DETAIL_FUND_LIMIT],
            "funds_truncated": len(funds) > DETAIL_FUND_LIMIT,
            "report_path": report_path,
        }

    # -- report file ------------------------------------------------------------

    def _resolve_report_dir(self) -> Path:
        configured = Path(self._settings.fund_reconcile_report_dir)
        if configured.is_absolute():
            return configured
        workspace_root = Path(__file__).resolve().parents[4]
        return workspace_root / configured

    def _write_report(self, summary: engine.ReconciliationSummary) -> str | None:
        """Best-effort full-report dump. Never raises: a write failure is logged."""
        try:
            directory = self._resolve_report_dir()
            directory.mkdir(parents=True, exist_ok=True)
            stamp = summary.generated_at.strftime("%Y%m%dT%H%M%S%fZ")
            path = directory / f"reconciliation-{stamp}.json"
            payload: dict[str, Any] = {
                "schema_version": RECONCILE_REPORT_SCHEMA_VERSION,
                "threshold_version": THRESHOLD_VERSION,
                "overall_status": summary.overall_status,
                "sources": [self._primary.name, self._danjuan.source_name, self._sina.source_name],
                "generated_at": summary.generated_at.isoformat(),
                "config": cfg_public(summary.config),
                "funds": [
                    {
                        "code": r.code,
                        "display_name": r.display_name,
                        "status": r.status,
                        "sources": list(r.sources),
                        "nav_total": r.nav_total,
                        "nav_matched": r.nav_matched,
                        "nav_mismatch": r.nav_mismatch,
                        "nav_missing": r.nav_missing,
                        "nav_coverage": r.nav_coverage,
                        "nav_agreement": r.nav_agreement,
                        "critical_failures": list(r.critical_failures),
                        "nav_mismatch_points": list(r.nav_mismatch_points),
                        "warnings": list(r.warnings),
                        "field_checks": [
                            {
                                "field": fc.field,
                                "severity": fc.severity,
                                "match": fc.match,
                                "rule": fc.rule,
                                "detail": fc.detail,
                            }
                            for fc in r.field_checks
                        ],
                    }
                    for r in summary.funds
                ],
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
                + "\n",
                encoding="utf-8",
            )
            self.last_report_path = path.as_posix()
            return path.as_posix()
        except Exception as exc:  # pragma: no cover - defensive by contract
            logger.warning("reconciliation report file write failed: %s", exc)
            return None


def cfg_public(config: dict[str, object]) -> dict[str, object]:
    """Echo the public (non-sensitive) engine config so the API can show thresholds."""
    return {
        key: value
        for key, value in config.items()
        if key
        in {
            "nav_abs_tolerance",
            "nav_rel_tolerance",
            "acc_nav_abs_tolerance",
            "daily_pct_tolerance",
            "min_nav_coverage",
            "profile_major_blocks",
            "scale_blocks",
            "rates_blocks",
            "strict",
            "required_sources",
        }
    }


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


__all__ = [
    "DETAIL_FUND_LIMIT",
    "THRESHOLD_VERSION",
    "IsolatedReconciliation",
    "ReconciliationError",
    "ReconciliationService",
    "ReconciliationSourceLike",
]
