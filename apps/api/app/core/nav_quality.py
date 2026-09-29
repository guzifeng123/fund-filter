from dataclasses import dataclass
from typing import TypedDict

from app.core.config import settings
from app.core.nav_dates import nav_trade_date_precision
from app.schemas.funds import FundDetail


class NavDataQualityError(ValueError):
    pass


class NavQualityWarningPayload(TypedDict):
    code: str
    fund_code: str
    trade_date: str
    field: str
    value: float
    minimum: float
    maximum: float
    message: str


@dataclass(frozen=True)
class NavQualityWarning:
    code: str
    fund_code: str
    trade_date: str
    field: str
    value: float
    minimum: float
    maximum: float
    message: str

    def as_dict(self) -> NavQualityWarningPayload:
        return {
            "code": self.code,
            "fund_code": self.fund_code,
            "trade_date": self.trade_date,
            "field": self.field,
            "value": self.value,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "message": self.message,
        }


def assess_fund_navs(fund: FundDetail) -> list[NavQualityWarning]:
    """Validate date invariants and collect configurable value-range anomalies."""

    warnings: list[NavQualityWarning] = []
    for point in fund.navs:
        precision = nav_trade_date_precision(point.trade_date)
        if precision is None:
            raise NavDataQualityError(
                f"fund {fund.code} has invalid NAV trade_date {point.trade_date!r}"
            )
        if fund.source != "sample_local" and precision != "day":
            raise NavDataQualityError(
                f"fund {fund.code} from {fund.source} must use ISO YYYY-MM-DD NAV trade_date; "
                f"got {point.trade_date!r}"
            )

        ranges = (
            ("nav", point.nav, settings.fund_nav_value_min, settings.fund_nav_value_max),
            (
                "accumulated_nav",
                point.accumulated_nav,
                settings.fund_accumulated_nav_value_min,
                settings.fund_accumulated_nav_value_max,
            ),
        )
        for field, value, minimum, maximum in ranges:
            if minimum <= value <= maximum:
                continue
            warnings.append(
                NavQualityWarning(
                    code=f"{field}_outside_configured_range",
                    fund_code=fund.code,
                    trade_date=point.trade_date,
                    field=field,
                    value=value,
                    minimum=minimum,
                    maximum=maximum,
                    message=(f"{field}={value} is outside configured range [{minimum}, {maximum}]"),
                )
            )
    return warnings


def validate_fund_navs(fund: FundDetail) -> list[NavQualityWarning]:
    warnings = assess_fund_navs(fund)
    if warnings and settings.fund_nav_reject_anomalies:
        first = warnings[0]
        raise NavDataQualityError(
            f"fund {fund.code} NAV anomaly rejected by FUND_NAV_REJECT_ANOMALIES: "
            f"{first.message}; warning_count={len(warnings)}"
        )
    return warnings
