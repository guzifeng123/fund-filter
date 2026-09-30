"""Parser for the Eastmoney ``pingzhongdata`` full-history JavaScript bundle.

The legacy F10 ``lsjz`` endpoint pages historical NAV at a hard cap of 20 rows per
request, so a 5-year window (~1200 points) costs ~60 round-trips per fund. The
public read-only bundle ``https://fund.eastmoney.com/pingzhongdata/{code}.js``
contains the fund's *entire* unit- and accumulated-NAV history in a single
~760&nbsp;KB response (~1 request / ~0.4&nbsp;s), which turns the per-fund NAV
pull into one request plus a tiny top-up page.

This module only parses the bundle into row dicts that are *byte-for-byte
contract-compatible* with the legacy ``lsjz`` rows (keys ``FSRQ`` / ``DWJZ`` /
``LJJZ`` / ``JZZZL``) so the downstream mirror builder, incremental cache merge,
quality checks, reconciliation gate and bulk repository writer need no changes.

Fail-closed contract:

* Money-market funds publish 万份收益 / 7日年化 instead of a unit-NAV series; the
  bundle either lacks ``Data_netWorthTrend`` or names the fund 货币. Such funds are
  routed to ``special_caliber`` by the classifier and must never reach this
  parser, so we raise :class:`PingzhongMoneyFundError` instead of fabricating.
* Missing variables, empty arrays, truncated/corrupt JSON and timestamp/date
  mismatches raise :class:`PingzhongDataError`; the builder catches those (and
  network errors) and degrades to the legacy paginated ``lsjz`` path. We never
  silently truncate or invent points.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

PINGZHONG_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"

# Eastmoney timestamps are "market-date" ms instants: they fall at 00:00 UTC on the
# trade date, which is 08:00 in the Beijing market timezone. Converting in
# Asia/Shanghai yields the exact trade date used by lsjz / danjuan / sina.
CN_TZ = timezone(timedelta(hours=8))

_NET_VAR = "Data_netWorthTrend"
_AC_VAR = "Data_ACWorthTrend"
_NAME_RE = re.compile(r'var\s+fS_name\s*=\s*"([^"]*)"')


class PingzhongDataError(ValueError):
    """The pingzhong bundle is present but malformed / unusable for NAV history."""


class PingzhongMoneyFundError(PingzhongDataError):
    """The bundle describes a money-market (or otherwise non-unit-NAV) fund.

    Money funds are classifier-routed to ``special_caliber`` and must never reach
    the unit-NAV pipeline; surfacing this as a loud, distinct error keeps a wrong
    upstream shape from being silently coerced into fabricated NAV points.
    """


def _extract_json_array(text: str, var_name: str) -> list[Any]:
    """Return the JSON array literal assigned to ``var_name`` in the JS text.

    A regex that only strips until the next ``;`` is unsafe because the array
    contains nested brackets and quoted strings, so we scan while tracking string
    state and bracket depth. Any deviation raises :class:`PingzhongDataError`.
    """
    match = re.search(re.escape(var_name) + r"\s*=\s*", text)
    if match is None:
        raise PingzhongDataError(f"pingzhong bundle is missing variable {var_name}")
    start = match.end()
    if start >= len(text) or text[start] != "[":
        raise PingzhongDataError(f"pingzhong variable {var_name} is not a JSON array")
    depth = 0
    in_string = False
    escaped = False
    index = start
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    blob = text[start : index + 1]
                    try:
                        value = json.loads(blob)
                    except json.JSONDecodeError as exc:
                        raise PingzhongDataError(
                            f"pingzhong variable {var_name} is not valid JSON: {exc}"
                        ) from exc
                    if not isinstance(value, list):
                        raise PingzhongDataError(
                            f"pingzhong variable {var_name} must decode to a list"
                        )
                    return value
        index += 1
    raise PingzhongDataError(f"pingzhong variable {var_name} array is unterminated")


def _ms_to_iso_date(milliseconds: Any) -> str:
    if not isinstance(milliseconds, (int, float)) or isinstance(milliseconds, bool):
        raise PingzhongDataError("pingzhong timestamp x must be a numeric millisecond epoch")
    return datetime.fromtimestamp(milliseconds / 1000, tz=CN_TZ).date().isoformat()


def parse_pingzhong_navs(js_text: str, code: str) -> list[dict[str, Any]]:
    """Parse the full unit/accumulated NAV history from a pingzhongdata bundle.

    Returns rows shaped exactly like legacy ``lsjz`` rows: ``FSRQ`` (``YYYY-MM-DD``
    string), ``DWJZ`` (unit NAV string), ``LJJZ`` (accumulated NAV string) and
    ``JZZZL`` (daily percent change string, same percent unit as lsjz). Rows are
    sorted ascending by trade date. The full history is returned unbounded; callers
    truncate to their requested window.
    """
    if not isinstance(js_text, str) or not js_text.strip():
        raise PingzhongDataError(f"pingzhong bundle for {code} is empty")

    name_match = _NAME_RE.search(js_text)
    fund_name = name_match.group(1) if name_match else ""
    if "货币" in fund_name:
        raise PingzhongMoneyFundError(
            f"fund {code} ({fund_name}) is a money-market fund; pingzhong exposes "
            "万份收益/7日年化, not a unit-NAV series, and it must not reach this pipeline"
        )

    net_trend = _extract_json_array(js_text, _NET_VAR)
    if not net_trend:
        # A non-money fund with no unit-NAV trend is either a special-caliber
        # product that slipped past the classifier or a broken bundle; either way
        # we refuse to fabricate and let the builder fall back to lsjz.
        raise PingzhongDataError(
            f"pingzhong bundle for {code} has an empty {_NET_VAR}"
        )
    ac_trend = _extract_json_array(js_text, _AC_VAR)
    if not ac_trend:
        raise PingzhongDataError(
            f"pingzhong bundle for {code} has an empty {_AC_VAR}"
        )

    accumulated_by_ms: dict[Any, float] = {}
    for point in ac_trend:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise PingzhongDataError(f"pingzhong {_AC_VAR} entry is malformed: {point!r}")
        stamp, acc = point[0], point[1]
        if not isinstance(stamp, (int, float)) or not isinstance(acc, (int, float)):
            raise PingzhongDataError(f"pingzhong {_AC_VAR} entry has non-numeric values: {point!r}")
        accumulated_by_ms[stamp] = float(acc)

    rows: list[dict[str, Any]] = []
    for point in net_trend:
        if not isinstance(point, dict):
            raise PingzhongDataError(f"pingzhong {_NET_VAR} entry is not an object: {point!r}")
        stamp = point.get("x")
        unit = point.get("y")
        if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
            raise PingzhongDataError(f"pingzhong {_NET_VAR} entry missing numeric x: {point!r}")
        if not isinstance(unit, (int, float)) or isinstance(unit, bool):
            raise PingzhongDataError(f"pingzhong {_NET_VAR} entry missing numeric y: {point!r}")
        if stamp not in accumulated_by_ms:
            raise PingzhongDataError(
                f"pingzhong accumulated NAV missing for trade timestamp {stamp}"
            )
        daily_return = point.get("equityReturn")
        rows.append(
            {
                "FSRQ": _ms_to_iso_date(stamp),
                "DWJZ": str(float(unit)),
                "LJJZ": str(accumulated_by_ms[stamp]),
                # equityReturn is already in percent (e.g. 0.1 == +0.10%), matching
                # the legacy lsjz JZZZL unit; omitted when upstream supplies nothing.
                "JZZZL": "" if daily_return is None else str(float(daily_return)),
            }
        )
    rows.sort(key=lambda item: item["FSRQ"])
    return rows
