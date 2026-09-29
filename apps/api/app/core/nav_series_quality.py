"""Per-fund NAV series structural quality checks.

These checks run on the *fetched* snapshot before it is staged for promotion.
Two severities are produced:

* ``error``  -- structural corruption (duplicate / out-of-order NAV dates) that
  must reject the candidate generation so the previous generation stays visible.
* ``warning`` -- softer signals (long calendar-day gaps, single-day jumps,
  accumulated-NAV drift) that are recorded into ``job_runs.details`` and never
  silently dropped.

Zero / negative / NaN / infinite NAV values are already hard-rejected upstream by
the ``NavPoint`` pydantic schema and :mod:`app.core.nav_quality`; this module does
not duplicate that logic.

Defaults stay deliberately loose (and 0 disables gap/stale checks) so bundled
sample fixtures remain green; real sources tighten thresholds via settings and
per-source overrides.
"""

from dataclasses import dataclass
from datetime import date

from app.core.config import settings
from app.core.nav_quality import NavQualityWarningPayload
from app.schemas.funds import FundDetail, NavPoint

THRESHOLD_VERSION = "nav-series+profile-quality/v1"


class NavSeriesQualityError(ValueError):
    """Raised when a NAV series error rejects the candidate generation."""


@dataclass(frozen=True)
class NavSeriesIssue:
    severity: str  # "error" | "warning"
    code: str
    fund_code: str
    trade_date: str
    field: str
    value: float
    minimum: float
    maximum: float
    message: str

    def as_payload(self) -> NavQualityWarningPayload:
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


@dataclass(frozen=True)
class NavSeriesThresholds:
    max_gap_days: int
    max_single_day_change: float
    accumulated_decrease_tolerance: float


@dataclass(frozen=True)
class NavSeriesQualityReport:
    errors: tuple[NavSeriesIssue, ...]
    warnings: tuple[NavSeriesIssue, ...]
    thresholds: NavSeriesThresholds

    @property
    def issue_count(self) -> int:
        return len(self.errors) + len(self.warnings)


def _thresholds_for_source(source_name: str, funds: list[FundDetail]) -> NavSeriesThresholds:
    values: dict[str, int | float] = {
        "max_gap_days": settings.fund_nav_series_max_gap_days,
        "max_single_day_change": settings.fund_nav_series_max_single_day_change,
        "accumulated_decrease_tolerance": settings.fund_nav_series_accumulated_decrease_tolerance,
    }
    candidate_keys = [source_name, *sorted({fund.source for fund in funds if fund.source})]
    for key in candidate_keys:
        values.update(settings.fund_nav_series_quality_overrides.get(key, {}))
    return NavSeriesThresholds(
        max_gap_days=int(values["max_gap_days"]),
        max_single_day_change=float(values["max_single_day_change"]),
        accumulated_decrease_tolerance=float(values["accumulated_decrease_tolerance"]),
    )


def _day_points(fund: FundDetail) -> list[tuple[date, NavPoint]]:
    points: list[tuple[date, NavPoint]] = []
    for point in fund.navs:
        if len(point.trade_date) != 10:
            # Legacy year-precision samples are exempt from strict series rules;
            # their date shape is already validated upstream.
            continue
        try:
            parsed = date.fromisoformat(point.trade_date)
        except ValueError:
            continue
        points.append((parsed, point))
    return points


def _check_date_invariants(fund: FundDetail, points: list[tuple[date, NavPoint]]) -> list[NavSeriesIssue]:
    issues: list[NavSeriesIssue] = []
    seen: set[date] = set()
    previous: date | None = None
    for parsed, point in points:
        if parsed in seen:
            issues.append(
                NavSeriesIssue(
                    severity="error",
                    code="nav_series_duplicate_trade_date",
                    fund_code=fund.code,
                    trade_date=point.trade_date,
                    field="trade_date",
                    value=parsed.toordinal(),
                    minimum=parsed.toordinal(),
                    maximum=parsed.toordinal(),
                    message=f"fund {fund.code} has duplicate NAV trade_date {point.trade_date}",
                )
            )
        seen.add(parsed)
        if previous is not None and parsed < previous:
            issues.append(
                NavSeriesIssue(
                    severity="error",
                    code="nav_series_not_ascending",
                    fund_code=fund.code,
                    trade_date=point.trade_date,
                    field="trade_date",
                    value=parsed.toordinal(),
                    minimum=previous.toordinal(),
                    maximum=previous.toordinal(),
                    message=(
                        f"fund {fund.code} NAV trade_date {point.trade_date} "
                        f"is out of order after {previous.isoformat()}"
                    ),
                )
            )
        previous = parsed
    return issues


def _check_gaps(
    fund: FundDetail,
    points: list[tuple[date, NavPoint]],
    thresholds: NavSeriesThresholds,
    today: date | None,
) -> list[NavSeriesIssue]:
    if thresholds.max_gap_days <= 0 or len(points) < 2:
        return []
    issues: list[NavSeriesIssue] = []
    max_gap = 0
    max_gap_date = points[-1][0]
    for index in range(1, len(points)):
        gap = (points[index][0] - points[index - 1][0]).days
        if gap > max_gap:
            max_gap = gap
            max_gap_date = points[index][0]
    if max_gap > thresholds.max_gap_days:
        issues.append(
            NavSeriesIssue(
                severity="warning",
                code="nav_series_gap_exceeded",
                fund_code=fund.code,
                trade_date=max_gap_date.isoformat(),
                field="nav_gap_days",
                value=float(max_gap),
                minimum=0.0,
                maximum=float(thresholds.max_gap_days),
                message=(
                    f"fund {fund.code} has a {max_gap}-calendar-day NAV gap "
                    f"(limit {thresholds.max_gap_days}); holidays are not hard failures"
                ),
            )
        )
    reference = today or date.today()
    latest_age = (reference - points[-1][0]).days
    if latest_age > thresholds.max_gap_days:
        issues.append(
            NavSeriesIssue(
                severity="warning",
                code="nav_series_stale",
                fund_code=fund.code,
                trade_date=points[-1][0].isoformat(),
                field="nav_latest_age_days",
                value=float(latest_age),
                minimum=0.0,
                maximum=float(thresholds.max_gap_days),
                message=f"fund {fund.code} has no fresh NAV for {latest_age} calendar days",
            )
        )
    return issues


def _check_jumps_and_accumulated(
    fund: FundDetail,
    points: list[tuple[date, NavPoint]],
    thresholds: NavSeriesThresholds,
) -> list[NavSeriesIssue]:
    if len(points) < 2:
        return []
    issues: list[NavSeriesIssue] = []
    is_money = fund.fund_type == "money"
    tolerance = thresholds.accumulated_decrease_tolerance
    for index in range(1, len(points)):
        prev_point = points[index - 1][1]
        point = points[index][1]
        # Accumulated NAV (复权口径) should be non-decreasing. Money funds do not
        # follow this total-return convention and are checked separately.
        if not is_money:
            drop_allowance = prev_point.accumulated_nav * tolerance
            if point.accumulated_nav < prev_point.accumulated_nav - drop_allowance:
                issues.append(
                    NavSeriesIssue(
                        severity="warning",
                        code="accumulated_nav_not_monotonic",
                        fund_code=fund.code,
                        trade_date=point.trade_date,
                        field="accumulated_nav",
                        value=point.accumulated_nav,
                        minimum=prev_point.accumulated_nav,
                        maximum=prev_point.accumulated_nav,
                        message=(
                            f"fund {fund.code} accumulated NAV decreased from "
                            f"{prev_point.accumulated_nav} to {point.accumulated_nav}"
                        ),
                    )
                )
            if point.accumulated_nav + drop_allowance < point.nav:
                issues.append(
                    NavSeriesIssue(
                        severity="warning",
                        code="accumulated_nav_below_unit_nav",
                        fund_code=fund.code,
                        trade_date=point.trade_date,
                        field="accumulated_nav",
                        value=point.accumulated_nav,
                        minimum=point.nav,
                        maximum=point.nav,
                        message=(
                            f"fund {fund.code} accumulated NAV {point.accumulated_nav} "
                            f"is below unit NAV {point.nav}"
                        ),
                    )
                )
            # Single-day unit-NAV jump. A sharp *drop* that the accumulated NAV
            # rides through unchanged is treated as a dividend ex-date and
            # suppressed; an extreme spike (either direction) is still flagged.
            change = point.nav / prev_point.nav - 1.0
            if abs(change) > thresholds.max_single_day_change:
                dividend_like = change < 0 and (
                    point.accumulated_nav
                    >= prev_point.accumulated_nav - prev_point.accumulated_nav * tolerance
                )
                if not dividend_like:
                    issues.append(
                        NavSeriesIssue(
                            severity="warning",
                            code="nav_series_single_day_jump",
                            fund_code=fund.code,
                            trade_date=point.trade_date,
                            field="nav_change_ratio",
                            value=round(change, 6),
                            minimum=-thresholds.max_single_day_change,
                            maximum=thresholds.max_single_day_change,
                            message=(
                                f"fund {fund.code} unit NAV moved {change:+.2%} "
                                f"in one day (limit ±{thresholds.max_single_day_change:.2%})"
                            ),
                        )
                    )
    return issues


def assess_nav_series_quality(
    funds: list[FundDetail],
    *,
    source_name: str,
    today: date | None = None,
) -> NavSeriesQualityReport:
    thresholds = _thresholds_for_source(source_name, funds)
    errors: list[NavSeriesIssue] = []
    warnings: list[NavSeriesIssue] = []
    for fund in funds:
        points = _day_points(fund)
        for issue in _check_date_invariants(fund, points):
            (errors if issue.severity == "error" else warnings).append(issue)
        for issue in _check_gaps(fund, points, thresholds, today):
            warnings.append(issue)
        for issue in _check_jumps_and_accumulated(fund, points, thresholds):
            warnings.append(issue)
    return NavSeriesQualityReport(
        errors=tuple(errors),
        warnings=tuple(warnings),
        thresholds=thresholds,
    )
