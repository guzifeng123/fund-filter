"""Deterministic batch planner for the D-stage sharded job (D1).

Pure planning: loads the D0 universe snapshot, routes every fund through the
classifier, and hands the eligible set to :meth:`BatchState.build_plan`. It owns
no ambient clock beyond the injectable universe clock and never writes the
Alembic business database -- the actual download / cross-check / generation
promotion happens in the D2+ runners.

Determinism contract:

* Universe rows are already sorted by ``code`` (D0); the planner preserves that
  order and never re-sorts.
* Shard / batch / seq assignment is performed by ``build_plan`` as
  ``batch_no = pending_index // batch_size``, ``shard = pending_index % shards``.
* ``limit`` truncates the *eligible* set after the deterministic code sort, so
  truncation never reshuffles the assignment of the funds that remain.
* Re-planning is idempotent: ``build_plan`` upserts rows without resetting
  already ``done``/``skipped``/``failed`` progress or attempt counters.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from app.core.config import settings
from app.core.fund_classifier import classify
from app.data_sources.universe import (
    UniverseFilters,
    UniverseFetcher,
    default_fetcher,
    load_or_fetch_universe,
)
from app.jobs.batch_state import BatchState


def _utc_today() -> date:
    return datetime.now(tz=timezone.utc).date()


@dataclass(frozen=True)
class PlanSummary:
    """Aggregate outcome of :func:`create_batch_plan`."""

    total_universe: int
    pending: int
    batches: int
    shards: int
    routes: dict[str, int]
    skipped: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["routes"] = dict(sorted(self.routes.items()))
        payload["skipped"] = dict(sorted(self.skipped.items()))
        return payload


def _is_pending_candidate(route: str, include_short_history: bool) -> bool:
    if route == "supported":
        return True
    # classify(include_short_history=True) already promotes short-history funds to
    # supported; this second arm stays defensive if the universe pre-filter ever
    # lets a raw new_short_history decision through.
    return include_short_history and route == "new_short_history"


def create_batch_plan(
    *,
    state: BatchState,
    filters: UniverseFilters,
    shards: int = 1,
    include_short_history: bool | None = None,
    limit: int | None = None,
    codes: frozenset[str] | None = None,
    cache_dir: str | Path | None = None,
    fetcher: UniverseFetcher | None = None,
    clock: Callable[[], date] | None = None,
) -> PlanSummary:
    """Build (or rebuild) the sharded pending plan inside ``state``.

    ``codes`` adds an allow-list on top of ``filters.allow_codes``. ``limit``
    truncates the eligible set to its first N funds in code order. The 3y gate
    is applied as ``require_has_3y = not include_short_history`` so the
    short-history switch actually flips which funds reach the classifier.
    """
    if shards < 1:
        raise ValueError("shards must be >= 1")
    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0 when provided")
    include_short_history = (
        include_short_history
        if include_short_history is not None
        else settings.fund_batch_include_short_history
    )

    effective = UniverseFilters(
        type_majors=filters.type_majors,
        require_has_3y=not include_short_history,
        allow_codes=filters.allow_codes | (codes or frozenset()),
        deny_codes=filters.deny_codes,
        name_exclude_keywords=filters.name_exclude_keywords,
    )

    funds = load_or_fetch_universe(
        cache_dir=Path(cache_dir) if cache_dir is not None else settings.fund_batch_universe_cache_dir,
        filters=effective,
        clock=clock or _utc_today,
        fetcher=fetcher or default_fetcher,
    )
    decisions = {fund.code: classify(fund, include_short_history=include_short_history) for fund in funds}
    routes = Counter(decision.route for decision in decisions.values())

    eligible_all = [
        fund for fund in funds if _is_pending_candidate(decisions[fund.code].route, include_short_history)
    ]
    # Non-eligible funds are recorded as skipped; funds cut away by `limit` are
    # intentionally omitted so build_plan never re-plans them as pending.
    non_candidates = [
        fund for fund in funds if not _is_pending_candidate(decisions[fund.code].route, include_short_history)
    ]
    planned = eligible_all[:limit] if limit is not None else eligible_all
    records = [*planned, *non_candidates]

    staged = state.build_plan(
        records,
        decisions,
        shards=shards,
        include_short_history=include_short_history,
    )

    skipped = Counter(decisions[fund.code].reason for fund in non_candidates)
    batches = (staged + state.batch_size - 1) // state.batch_size if staged else 0

    routes_dict: dict[str, int] = {route: count for route, count in routes.items()}
    skipped_dict: dict[str, int] = {reason: count for reason, count in skipped.items()}
    return PlanSummary(
        total_universe=len(funds),
        pending=staged,
        batches=batches,
        shards=shards,
        routes=routes_dict,
        skipped=skipped_dict,
    )
