from datetime import datetime, timezone
from typing import Any

COMPLIANCE_DISCLAIMER = "本工具基于历史数据，仅供分析学习，不构成投资建议。历史表现不预示未来收益。"
AI_DISCLAIMER = "AI 输出仅供分析学习，不构成投资建议；无法替代持牌机构的适当性意见。"
DEFAULT_SOURCE = "sample_local"

RISK_PROFILE_LIMITS: dict[str, list[str]] = {
    "C1": ["R1"],
    "C2": ["R1", "R2"],
    "C3": ["R1", "R2", "R3"],
    "C4": ["R1", "R2", "R3", "R4"],
    "C5": ["R1", "R2", "R3", "R4", "R5"],
}


def _format_data_updated_at(data_updated_at: datetime | str | None) -> str:
    if data_updated_at is None:
        return datetime.now(timezone.utc).astimezone().isoformat()
    if isinstance(data_updated_at, datetime):
        return data_updated_at.isoformat()
    return data_updated_at


def meta(
    source: str = DEFAULT_SOURCE,
    data_updated_at: datetime | str | None = None,
    pagination: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "data_updated_at": _format_data_updated_at(data_updated_at),
        "disclaimer": COMPLIANCE_DISCLAIMER,
        "pagination": pagination,
    }


def envelope(
    data: Any,
    source: str = DEFAULT_SOURCE,
    data_updated_at: datetime | str | None = None,
    pagination: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {"data": data, "meta": meta(source, data_updated_at, pagination)}


def error_envelope(
    code: str,
    message: str,
    detail: Any | None = None,
    source: str = DEFAULT_SOURCE,
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": detail}, "meta": meta(source)}


def is_risk_matched(profile: str, level: str) -> bool:
    return level in RISK_PROFILE_LIMITS.get(profile, [])
