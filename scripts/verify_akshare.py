"""Smoke-test the AKShare contracts used by the fund workspace.

AKShare has renamed a few endpoints over time, so this intentionally resolves
the current and legacy fund function names.  The script is diagnostic only: it
does not write to the application database or silently fabricate rows.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _call_with_retry(fn: Callable[..., Any], *, attempts: int = 3, **kwargs: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn(**kwargs)
        except Exception as exc:  # upstream providers are outside our process
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.0 * (attempt + 1))
    assert last_error is not None
    raise last_error


def _fund_frame(ak: Any, code: str) -> Any:
    fn = getattr(ak, "fund_em_open_fund_daily", None) or getattr(ak, "fund_open_fund_daily_em", None)
    if fn is None:
        raise RuntimeError("AKShare has no open-fund daily endpoint")
    # The legacy endpoint accepted fund=; the current endpoint returns the
    # complete daily universe and is filtered locally by 基金代码.
    try:
        frame = _call_with_retry(fn, fund=code)
    except TypeError:
        frame = _call_with_retry(fn)
        if "基金代码" not in frame.columns:
            raise RuntimeError("AKShare fund daily response lacks 基金代码")
        frame = frame[frame["基金代码"].astype(str).str.zfill(6) == code]
    if frame is None or len(frame) == 0:
        raise RuntimeError(f"AKShare returned no daily row for fund {code}")
    return frame


def _fund_nav_frame(ak: Any, code: str) -> Any:
    fn = getattr(ak, "fund_open_fund_info_em", None)
    if fn is None:
        raise RuntimeError("AKShare has no historical open-fund endpoint")
    return _call_with_retry(fn, symbol=code, indicator="单位净值走势", period="成立来")


def _stock_frame(ak: Any, code: str) -> Any:
    # Sina's legacy endpoint is retained as a fallback, while EastMoney's
    # endpoint is the preferred implementation in current AKShare releases.
    fn = getattr(ak, "stock_zh_a_hist", None)
    if fn is not None:
        try:
            return _call_with_retry(
                fn,
                symbol=code,
                period="daily",
                start_date="20200101",
                end_date=datetime.now().strftime("%Y%m%d"),
                adjust="",
            )
        except Exception:
            pass
    fn = getattr(ak, "stock_zh_a_daily", None)
    if fn is None:
        raise RuntimeError("AKShare has no A-share daily endpoint")
    return _call_with_retry(fn, symbol=f"sh{code}", adjust="")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fund", default="000001")
    parser.add_argument("--stock", default="600036")
    parser.add_argument("--output", type=Path, default=Path("output/akshare-smoke.json"))
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False, "provider": "akshare", "fund": {}, "stock": {}}
    try:
        import akshare as ak

        daily = _fund_frame(ak, args.fund)
        nav = _fund_nav_frame(ak, args.fund)
        result["fund"] = {
            "code": args.fund,
            "daily_rows": int(len(daily)),
            "nav_rows": int(len(nav)),
            "daily_columns": [str(c) for c in daily.columns],
            "nav_columns": [str(c) for c in nav.columns],
        }
        stock = _stock_frame(ak, args.stock)
        if stock is None or len(stock) == 0:
            raise RuntimeError(f"AKShare returned no daily rows for stock {args.stock}")
        result["stock"] = {
            "symbol": args.stock,
            "rows": int(len(stock)),
            "columns": [str(c) for c in stock.columns],
        }
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
