"""Full-market open-end fund universe snapshot (D0 contract, deliverable 3).

Pulls and normalises the list of over-the-counter open-end funds used by the
D-stage sharded batch runners (D1-D4). The source is akshare:

* ``fund_open_fund_rank_em(symbol="全部")`` -- ~20k ranked funds with Chinese
  columns 基金代码 / 基金简称 / 单位净值 / 累计净值 / 日期(epoch ms) / 近3年 / 手续费.
* ``fund_name_em()`` -- ~28k rows providing the human-readable 基金类型
  (e.g. ``混合型-灵活``) that the rank table lacks.

The rank table is LEFT JOINed on 基金代码 against the name table; a fund present
in the rank list but missing from the name table is kept with an empty type
(``type_major="未知"``) rather than guessed.

Contract for D1-D4 (do not loosen):

* :data:`UniverseFund` is a frozen dataclass; ``scale`` is ``None`` unless the
  source row actually carries it -- it is never fabricated.
* ``nav_date`` is derived only from the epoch-ms ``日期`` column.
* ``has_3y`` is ``True`` iff the ``近3年`` metric is present and non-empty.
* Results are deterministically sorted by ``code``.
* akshare is imported lazily *inside* the fetch function; tests inject an inline
  pandas DataFrame and never touch the network.
* A same-day JSON cache at ``<cache_dir>/universe_YYYYMMDD.json`` always stores
  the UNFILTERED full-market snapshot. A warm cache short-circuits the pull and
  each caller's filters are reapplied in memory, so a narrow allow-list request
  can never shrink or poison the shared daily cache.
"""

from __future__ import annotations

import json
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
_NAME_TYPE_COL = "基金类型"


@dataclass(frozen=True)
class UniverseFund:
    """One normalised open-end fund in the full-market universe."""

    code: str
    name: str
    type_major: str
    type_detail: str
    has_3y: bool
    scale: float | None
    unit_nav: float | None
    acc_nav: float | None
    nav_date: date | None


@dataclass(frozen=True)
class UniverseFilters:
    """Deterministic filters applied after the LEFT JOIN.

    Empty / default fields mean "no restriction". ``require_has_3y`` drops funds
    without a 近3年 metric; ``allow_codes`` whitelists (when non-empty);
    ``deny_codes`` blacklists; ``name_exclude_keywords`` drops funds whose name
    contains any keyword.
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


def build_name_type_map(name_df: pd.DataFrame) -> dict[str, str]:
    """Map 基金代码 -> 基金类型 (raw text) from the name table."""
    type_map: dict[str, str] = {}
    if name_df is None or name_df.empty:
        return type_map
    for record in name_df.to_dict("records"):
        code = str(record.get(_RANK_CODE_COL, "")).strip()
        if not code:
            continue
        type_map[code] = str(record.get(_NAME_TYPE_COL, "") or "").strip()
    return type_map


def _matches_filters(fund: UniverseFund, filters: UniverseFilters) -> bool:
    """Return True when a normalised fund passes every active filter."""
    if filters.allow_codes and fund.code not in filters.allow_codes:
        return False
    if fund.code in filters.deny_codes:
        return False
    if filters.type_majors and fund.type_major not in filters.type_majors:
        return False
    if filters.require_has_3y and not fund.has_3y:
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
    """LEFT JOIN rank<->name, normalise, sort by code, then apply filters."""
    if rank_df is None or rank_df.empty:
        raise ValueError("universe rank table is empty; refusing to build an empty plan")
    type_map = build_name_type_map(name_df)
    funds: list[UniverseFund] = []
    for record in rank_df.to_dict("records"):
        code = str(record.get(_RANK_CODE_COL, "")).strip()
        if not code:
            continue
        name = str(record.get(_RANK_NAME_COL, "") or "").strip()
        type_detail = type_map.get(code, "")
        type_major = derive_major_type(type_detail)
        three_year = _optional_float(record.get(_RANK_3Y_COL))
        has_3y = three_year is not None
        funds.append(
            UniverseFund(
                code=code,
                name=name,
                type_major=type_major,
                type_detail=type_detail,
                has_3y=has_3y,
                scale=None,  # the rank/name sources do not carry scale; never fake it.
                unit_nav=_optional_float(record.get(_RANK_UNIT_NAV_COL)),
                acc_nav=_optional_float(record.get(_RANK_ACC_NAV_COL)),
                nav_date=_epoch_ms_to_date(record.get(_RANK_DATE_COL)),
            )
        )
    funds.sort(key=lambda fund: fund.code)
    return filter_universe(funds, filters)


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


def _fund_from_dict(payload: dict[str, Any]) -> UniverseFund:
    nav_raw = payload.get("nav_date")
    nav_date = date.fromisoformat(nav_raw) if nav_raw else None
    return UniverseFund(
        code=str(payload["code"]),
        name=str(payload["name"]),
        type_major=str(payload["type_major"]),
        type_detail=str(payload["type_detail"]),
        has_3y=bool(payload["has_3y"]),
        scale=(float(payload["scale"]) if payload.get("scale") is not None else None),
        unit_nav=(float(payload["unit_nav"]) if payload.get("unit_nav") is not None else None),
        acc_nav=(float(payload["acc_nav"]) if payload.get("acc_nav") is not None else None),
        nav_date=nav_date,
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
