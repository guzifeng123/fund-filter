"""Pure fund routing classifier for the D-stage batch job (D0 contract, 4).

Given a :class:`~app.data_sources.universe.UniverseFund`, decide how the batch
runner should treat it. Zero IO, fully deterministic, no ambient clock/network.

Classification order matters and is documented inline -- structural / special
caliber rules are evaluated BEFORE the major-class routing, so an on-exchange
ETF or a money-market fund can never fall through to "supported" just because
its major class is 指数型:

1. Special caliber first (route ``special_caliber``):
   money-market, on-exchange ETF, QDII commodity/REITs, standalone REITs,
   commodity, Hong Kong mutual-recognition funds. These are never downloaded
   as ordinary OTC open-end NAV series.
2. Secondary / not-sellable shares (route ``unsupported_secondary``):
   broker asset-management ("资管") / custom shares.
3. Major-class routing: eligible OTC open-end classes
   (股票/混合/债券/指数 incl. ETF-联接 / FOF / ordinary QDII) with >=3y
   history -> ``supported``. Age is three-state: ``has_3y=True`` is confirmed
   eligible; ``has_3y=None`` (rank-uncovered) is ALSO routed to ``supported`` and
   its precise >=3y check is deferred to the per-fund runner (which reads the
   primary source's inception_date); only ``has_3y=False`` (known <3y) routes to
   ``new_short_history`` (promotable to ``supported`` when
   ``include_short_history=True``).

ETF-联接 funds are OTC index funds (supported); bare on-exchange ETFs are
special. A tradeable OTC LOF such as 161725 is treated as an ordinary OTC
open-end fund.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.data_sources.universe import UniverseFund

Route = Literal[
    "supported",
    "new_short_history",
    "unsupported_secondary",
    "special_caliber",
]

# Major classes we can actually backfill as ordinary OTC open-end funds.
SUPPORTED_MAJORS = frozenset(
    {
        "股票型",
        "混合型",
        "债券型",
        "指数型",  # includes ETF-联接 (OTC index feeder funds)
        "FOF",
        "QDII",
    }
)

# Name keywords that mark a share as a secondary / not-sellable instrument.
_SECONDARY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("资管", "broker_asset_management"),
    ("定制", "custom_share"),
)


@dataclass(frozen=True)
class ClassifyDecision:
    """Outcome of :func:`classify`. ``detail`` carries the fine-grained reason."""

    route: Route
    reason: str
    detail: dict[str, Any]


def _is_on_exchange_etf(name: str) -> bool:
    upper = name.upper()
    if "ETF" not in upper:
        return False
    # OTC index feeder funds carry "ETF联接" / "ETF 联接" and stay supported.
    return "ETF联接" not in name and "ETF 联接" not in name


def classify(fund: UniverseFund, *, include_short_history: bool = False) -> ClassifyDecision:
    """Route one universe fund. Pure: no IO, no ambient state."""
    major = fund.type_major

    # --- 1. Structural / special caliber (checked first) --------------------
    if major == "货币型":
        return ClassifyDecision(
            route="special_caliber",
            reason="special_caliber",
            detail={"special_kind": "money_market", "type_detail": fund.type_detail},
        )
    if "互认" in fund.name:
        # Hong Kong mutual-recognition funds are not ordinary mainland OTC
        # open-end NAV series. The current fund_name_em feed carries no 互认
        # marker (observed 0 rows); the rule is kept so any future rows are
        # routed auditablely instead of silently slipping through.
        return ClassifyDecision(
            route="special_caliber",
            reason="special_caliber",
            detail={"special_kind": "hk_mutual_recognition", "type_detail": fund.type_detail},
        )
    if major == "REITs":
        return ClassifyDecision(
            route="special_caliber",
            reason="special_caliber",
            detail={"special_kind": "reits", "type_detail": fund.type_detail},
        )
    if major == "商品":
        return ClassifyDecision(
            route="special_caliber",
            reason="special_caliber",
            detail={"special_kind": "commodity", "type_detail": fund.type_detail},
        )
    if major == "QDII" and ("商品" in fund.type_detail or "REITS" in fund.type_detail.upper()):
        return ClassifyDecision(
            route="special_caliber",
            reason="special_caliber",
            detail={"special_kind": "qdii_commodity_or_reits", "type_detail": fund.type_detail},
        )
    if _is_on_exchange_etf(fund.name):
        return ClassifyDecision(
            route="special_caliber",
            reason="special_caliber",
            detail={"special_kind": "on_exchange_etf", "type_detail": fund.type_detail},
        )

    # --- 2. Secondary / not-sellable shares --------------------------------
    for keyword, reason in _SECONDARY_KEYWORDS:
        if keyword in fund.name:
            return ClassifyDecision(
                route="unsupported_secondary",
                reason=reason,
                detail={"matched_keyword": keyword, "type_detail": fund.type_detail},
            )

    # --- 3. Major-class routing -------------------------------------------
    if major not in SUPPORTED_MAJORS:
        return ClassifyDecision(
            route="unsupported_secondary",
            reason="unknown_type",
            detail={"type_major": major, "type_detail": fund.type_detail},
        )

    if fund.has_3y is True:
        return ClassifyDecision(
            route="supported",
            reason="eligible_open_end",
            detail={"type_major": major, "type_detail": fund.type_detail, "age_evidence": "confirmed"},
        )

    # Rank-uncovered funds have no age evidence (has_3y is None). They must NOT
    # be written off as new_short_history here: they become supported candidates
    # and the precise ">=3y" check is deferred to the per-fund runner, which reads
    # the primary source's inception_date.
    if fund.has_3y is None:
        return ClassifyDecision(
            route="supported",
            reason="eligible_open_end",
            detail={"type_major": major, "type_detail": fund.type_detail, "age_evidence": "unknown"},
        )

    # has_3y is False: eligible class but known short history (rank row, blank
    # 近3年). Promotable to supported when the short-history switch is on.
    if include_short_history:
        return ClassifyDecision(
            route="supported",
            reason="short_history_included",
            detail={"type_major": major, "type_detail": fund.type_detail, "age_evidence": "short"},
        )
    return ClassifyDecision(
        route="new_short_history",
        reason="history_lt_3y",
        detail={"type_major": major, "type_detail": fund.type_detail, "age_evidence": "short"},
    )
