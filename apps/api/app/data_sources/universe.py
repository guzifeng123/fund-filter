"""Full-market open-end fund universe snapshot (D0 contract, deliverable 3).

Pulls and normalises the list of over-the-counter open-end funds used by the
D-stage sharded batch runners (D1-D4). The source is akshare:

* ``fund_name_em()`` -- ~28k rows, the **master skeleton**. It is the complete
  sellable-share list and carries the human-readable 基金简称 / 基金类型 text
  (e.g. ``混合型-灵活``, ``债券型-长债``).
* ``fund_open_fund_rank_em(symbol="全部")`` -- ~20k rows, a *subset* (only funds
  with a same-day performance ranking). It is now a **supplement** LEFT JOINed on
  基金代码 to provide the 近3年 metric (-> :pyattr:`UniverseFund.has_3y`), latest
  单位净值 / 累计净值 and the NAV date.

Why the flip (F-phase): the rank table only covers funds with a same-day
ranking, silently dropping ~7.5k real sellable shares (mostly off-exchange
bond / FOF / QDII / feeder shares that have no daily ranking). The union is now
``name ∪ rank``: every code present in the name list is kept, even when the rank
table has no row for it. Rank-missing funds keep ``has_3y=None`` (age unknown)
with empty NAV fields -- those are *never* fabricated and *never* dropped.

Contract for D1-D4 (do not loosen):

* :data:`UniverseFund` is a frozen dataclass; ``scale`` is ``None`` unless the
  source row actually carries it -- it is never fabricated.
* ``nav_date`` is derived only from the epoch-ms ``日期`` column.
* ``has_3y`` is three-state: ``True`` (rank row + non-empty 近3年 => known >=3y),
  ``False`` (rank row but empty 近3年 => known <3y), ``None`` (no rank row => age
  unknown, deferred to the per-runner inception-date check).
* Share classes (A/C/E/Y/I, 后端, 美元/现汇/现钞, 人民币) are kept as independent
  codes -- they are never merged/deduped -- and tagged on ``share_class``.
* Results are deterministically sorted by ``code``.
* akshare is imported lazily *inside* the fetch function; tests inject an inline
  pandas DataFrame and never touch the network.
* A same-day JSON cache at ``<cache_dir>/universe_YYYYMMDD.json`` always stores
  the UNFILTERED full-market snapshot. A warm cache short-circuits the pull and
  each caller's filters are reapplied in memory, so a narrow allow-list request
  can never shrink or poison the shared daily cache.

Known limitation (F-phase): ``fund_name_em()`` exposes NO survival /
liquidation / terminated-status column (only 基金代码 / 拼音缩写 / 基金简称 /
基金类型 / 拼音全称). Delisted / terminated funds are therefore NOT filtered
here; this is documented in the runbook rather than guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd  # type: ignore[import-untyped]

# Fetcher returns (rank_df, name_df). Injected in tests; the default pulls akshare.
UniverseFetcher = Callable[[], tuple[pd.DataFrame, pd.DataFrame]]

_RANK_CODE_COL = "基金代码"
_RANK_NAME_COL = "基金简称"
_RANK_UNIT_NAV_COL = "单位净值"
_RANK_ACC_NAV_COL = "累计净值"
_RANK_DATE_COL = "日期"
_RANK_3Y_COL = "近3年"
_NAME_CODE_COL = "基金代码"
_NAME_NAME_COL = "基金简称"
_NAME_TYPE_COL = "基金类型"

#: Trailing single-letter share classes. The letter must follow a CJK char or a
#: closing paren, so the trailing "I" of "QDII" / "A" of "FOFA" is NOT mistaken
#: for a share class.
_SHARE_LETTER_RE = re.compile(r"[一-鿿）)](?P<sc>[ACEYI])\s*$")


@dataclass(frozen=True)
class UniverseFund:
    """One normalised open-end fund in the full-market universe."""

    code: str
    name: str
    type_major: str
    type_detail: str
    has_3y: bool | None
    scale: float | None
    unit_nav: float | None
    acc_nav: float | None
    nav_date: date | None
    # Share-class annotation (F-phase). Independent codes are never merged; this
    # is descriptive metadata, not a routing key. None when the name carries no
    # explicit share-class marker.
    share_class: str | None = None
    share_is_backend: bool = False
    share_is_forex: bool = False


@dataclass(frozen=True)
class UniverseFilters:
    """Deterministic filters applied after the name∪rank union is built.

    Empty / default fields mean "no restriction". ``require_has_3y`` drops funds
    whose age is *known* to be short (``has_3y is False``); it deliberately keeps
    ``has_3y=None`` (rank-uncovered, age unknown) so those candidates still reach
    the classifier and the runner's precise inception-date check. ``allow_codes``
    whitelists (when non-empty); ``deny_codes`` blacklists; ``name_exclude_keywords``
    drops funds whose name contains any keyword.
    """

    type_majors: frozenset[str] = field(default_factory=frozenset)
    require_has_3y: bool = False
    allow_codes: frozenset[str] = field(default_factory=frozenset)
    deny_codes: frozenset[str] = field(default_factory=frozenset)
    name_exclude_keywords: tuple[str, ...] = ()


def derive_major_type(type_detail: str) -> str:
    """Derive the coarse major class from akshare's 基金类型 free text.

    ``混合型-灵活`` -> ``混合型``, ``FOF-稳健型`` -> ``FOF``, ``股票型`` ->
    ``股票型``, ``Reits``/``REITs`` -> ``REITs``. Unknown / empty -> ``未知``.
    """
    text = (type_detail or "").strip()
    if not text:
        return "未知"
    head = text.split("-", 1)[0].strip()
    if head.lower() == "reits":
        return "REITs"
    return head


def parse_share_class(name: str) -> tuple[str | None, bool, bool]:
    """Parse the share-class tag from a fund's short name.

    Returns ``(share_class, is_backend, is_forex)``. Forex / backend markers take
    precedence over a trailing letter so e.g. ``美元现汇`` / ``(后端)`` win over
    a bare trailing letter. Conservative: only tags an unambiguous trailing
    A/C/E/Y/I suffix following a CJK char or closing paren (so the trailing
    "I" of "QDII" / "A" of "FOFA" is not mistaken for a share class).
    """
    if not name:
        return None, False, False
    is_backend = "后端" in name
    if "现钞" in name:
        return "现钞", is_backend, True
    if "现汇" in name:
        return "现汇", is_backend, True
    if "美元" in name:
        return "美元", is_backend, True
    if is_backend:
        return "后端", True, False
    if "人民币" in name:
        return "人民币", False, False
    match = _SHARE_LETTER_RE.search(name)
    if match is not None:
        return match.group("sc"), False, False
    return None, False, False


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _epoch_ms_to_date(value: Any) -> date | None:
    seconds = _optional_float(value)
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds / 1000.0, tz=timezone.utc).date()


def build_rank_supplement(rank_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Index the rank table by 基金代码 for the LEFT-join supplement.

    Returns ``code -> {unit_nav, acc_nav, nav_date, has_3y}``. ``has_3y`` is
    ``True`` when 近3年 is present and non-empty, ``False`` when the rank row
    exists but the metric is blank (known short history).
    """
    supplement: dict[str, dict[str, Any]] = {}
    if rank_df is None or rank_df.empty:
        return supplement
    for record in rank_df.to_dict("records"):
        code = str(record.get(_RANK_CODE_COL, "")).strip()
        if not code:
            continue
        three_year = _optional_float(record.get(_RANK_3Y_COL))
        supplement[code] = {
            "has_3y": three_year is not None,
            "unit_nav": _optional_float(record.get(_RANK_UNIT_NAV_COL)),
            "acc_nav": _optional_float(record.get(_RANK_ACC_NAV_COL)),
            "nav_date": _epoch_ms_to_date(record.get(_RANK_DATE_COL)),
            "rank_name": str(record.get(_RANK_NAME_COL, "") or "").strip(),
        }
    return supplement


def _matches_filters(fund: UniverseFund, filters: UniverseFilters) -> bool:
    """Return True when a normalised fund passes every active filter."""
    if filters.allow_codes and fund.code not in filters.allow_codes:
        return False
    if fund.code in filters.deny_codes:
        return False
    if filters.type_majors and fund.type_major not in filters.type_majors:
        return False
    # require_has_3y drops only *known* short-history funds (has_3y is False).
    # has_3y=None (rank-uncovered, age unknown) must survive: its precise age is
    # checked later, per fund, in the batch runner.
    if filters.require_has_3y and fund.has_3y is False:
        return False
    if any(keyword and keyword in fund.name for keyword in filters.name_exclude_keywords):
        return False
    return True


def filter_universe(funds: Iterable[UniverseFund], filters: UniverseFilters) -> list[UniverseFund]:
    """Apply ``filters`` to an already-normalised, code-sorted universe.

    Filtering is deliberately separate from snapshot (de)normalisation so the
    shared daily cache can always hold the unfiltered full market while each
    caller's allow-list / type / 3y restrictions are applied in memory.
    """
    kept = [fund for fund in funds if _matches_filters(fund, filters)]
    if not kept:
        raise ValueError("universe filtered down to 0 funds; check filters are not over-strict")
    return kept


def normalize_universe(
    rank_df: pd.DataFrame,
    name_df: pd.DataFrame,
    *,
    filters: UniverseFilters,
) -> list[UniverseFund]:
    """Build the name∪rank union, normalise, sort by code, then apply filters.

    ``fund_name_em()`` (``name_df``) is the master skeleton; the rank table is
    the supplement. Codes from either table are kept (union, dedup by code). A
    name-only code with no rank row keeps ``has_3y=None`` and empty NAV fields.
    """
    if name_df is None or name_df.empty:
        raise ValueError("universe name table is empty; refusing to build an empty plan")
    supplement = build_rank_supplement(rank_df)
    funds: dict[str, UniverseFund] = {}

    def _ingest(code: str, name: str, type_detail: str) -> None:
        if not code or code in funds:
            return
        rank_row = supplement.get(code)
        if rank_row is None:
            # Name-only fund: age unknown, NAV fields empty -- never fabricated.
            has_3y: bool | None = None
            unit_nav: float | None = None
            acc_nav: float | None = None
            nav_date: date | None = None
        else:
            has_3y = bool(rank_row["has_3y"])
            unit_nav = rank_row["unit_nav"]
            acc_nav = rank_row["acc_nav"]
            nav_date = rank_row["nav_date"]
            # Prefer the name table's short name; fall back to the rank name.
            name = name or str(rank_row["rank_name"] or "")
        share_class, is_backend, is_forex = parse_share_class(name)
        funds[code] = UniverseFund(
            code=code,
            name=name,
            type_major=derive_major_type(type_detail),
            type_detail=type_detail,
            has_3y=has_3y,
            scale=None,  # the rank/name sources do not carry scale; never fake it.
            unit_nav=unit_nav,
            acc_nav=acc_nav,
            nav_date=nav_date,
            share_class=share_class,
            share_is_backend=is_backend,
            share_is_forex=is_forex,
        )

    # Master skeleton: every sellable share from the name list.
    for record in name_df.to_dict("records"):
        code = str(record.get(_NAME_CODE_COL, "") or "").strip()
        if not code:
            continue
        name = str(record.get(_NAME_NAME_COL, "") or "").strip()
        type_detail = str(record.get(_NAME_TYPE_COL, "") or "").strip()
        _ingest(code, name, type_detail)

    # Union: keep any rank-only codes (should not happen on the live feed, but
    # the union must not silently drop them).
    for code, rank_row in supplement.items():
        if code not in funds:
            _ingest(code, str(rank_row["rank_name"] or ""), "")

    ordered = sorted(funds.values(), key=lambda fund: fund.code)
    return filter_universe(ordered, filters)


def default_fetcher() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pull the two akshare tables. akshare is imported lazily (never at import)."""
    import akshare as ak  # type: ignore[import-untyped]

    rank_df = ak.fund_open_fund_rank_em(symbol="全部")
    name_df = ak.fund_name_em()
    return rank_df, name_df


def _cache_path(cache_dir: Path, today: date) -> Path:
    return cache_dir / f"universe_{today.strftime('%Y%m%d')}.json"


def _fund_to_dict(fund: UniverseFund) -> dict[str, Any]:
    payload = asdict(fund)
    payload["nav_date"] = fund.nav_date.isoformat() if fund.nav_date else None
    return payload


def _three_state_has_3y(value: Any) -> bool | None:
    """Decode a cached has_3y back to its three-state value (None survives)."""
    if value is None:
        return None
    return bool(value)


def _fund_from_dict(payload: dict[str, Any]) -> UniverseFund:
    nav_raw = payload.get("nav_date")
    nav_date = date.fromisoformat(nav_raw) if nav_raw else None
    return UniverseFund(
        code=str(payload["code"]),
        name=str(payload["name"]),
        type_major=str(payload["type_major"]),
        type_detail=str(payload["type_detail"]),
        has_3y=_three_state_has_3y(payload.get("has_3y")),
        scale=(float(payload["scale"]) if payload.get("scale") is not None else None),
        unit_nav=(float(payload["unit_nav"]) if payload.get("unit_nav") is not None else None),
        acc_nav=(float(payload["acc_nav"]) if payload.get("acc_nav") is not None else None),
        nav_date=nav_date,
        share_class=(
            str(payload["share_class"]) if payload.get("share_class") is not None else None
        ),
        share_is_backend=bool(payload.get("share_is_backend", False)),
        share_is_forex=bool(payload.get("share_is_forex", False)),
    )


def load_or_fetch_universe(
    *,
    cache_dir: Path,
    filters: UniverseFilters,
    clock: Callable[[], date] = lambda: datetime.now(tz=timezone.utc).date(),
    fetcher: UniverseFetcher = default_fetcher,
) -> list[UniverseFund]:
    """Return the normalised universe, reusing today's full-snapshot cache.

    The cache always holds the unfiltered full market. On a miss we fetch and
    persist that full snapshot; the caller's ``filters`` are then applied in
    memory on every path so narrow allow-list requests never poison the cache.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _cache_path(cache_dir, clock())
    if target.exists():
        payload = json.loads(target.read_text(encoding="utf-8"))
        full = [_fund_from_dict(row) for row in payload]
    else:
        rank_df, name_df = fetcher()
        full = normalize_universe(rank_df, name_df, filters=UniverseFilters())
        target.write_text(
            json.dumps([_fund_to_dict(fund) for fund in full], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    return filter_universe(full, filters)
