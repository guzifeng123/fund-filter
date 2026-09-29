from datetime import date
from typing import Literal


TradeDatePrecision = Literal["day", "year"]


def normalize_nav_trade_date(value: str) -> tuple[str, TradeDatePrecision]:
    """Return one canonical NAV date while retaining legacy year precision."""

    normalized = value.strip()
    if len(normalized) == 4 and normalized.isdigit():
        try:
            date(int(normalized), 1, 1)
        except ValueError as exc:
            raise ValueError("trade_date year must be between 0001 and 9999") from exc
        return (normalized, "year")

    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("trade_date must be YYYY-MM-DD or a legacy YYYY sample year") from exc
    canonical = parsed.isoformat()
    if normalized != canonical:
        raise ValueError("trade_date must use canonical ISO YYYY-MM-DD format")
    return (canonical, "day")


def nav_trade_date_precision(value: str) -> TradeDatePrecision | None:
    try:
        _, precision = normalize_nav_trade_date(value)
    except (AttributeError, ValueError):
        return None
    return precision
