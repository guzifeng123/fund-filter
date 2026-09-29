"""Fund profile (资料字段) logical consistency checks.

These are softer sanity rules over the static fund metadata that ships in a
snapshot. They never carry structural "reject the generation" weight by default
(see ``FUND_PROFILE_REJECT_ERRORS``); findings are recorded as warnings alongside
the NAV-series warnings in ``job_runs.details``.
"""

from dataclasses import dataclass

from app.core.config import settings
from app.core.nav_quality import NavQualityWarningPayload
from app.schemas.funds import FundDetail

PROFILE_THRESHOLD_VERSION = "nav-series+profile-quality/v1"


@dataclass(frozen=True)
class ProfileIssue:
    severity: str  # "error" | "warning"
    code: str
    fund_code: str
    field: str
    value: float
    minimum: float
    maximum: float
    message: str

    def as_payload(self) -> NavQualityWarningPayload:
        return {
            "code": self.code,
            "fund_code": self.fund_code,
            "trade_date": "",
            "field": self.field,
            "value": self.value,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "message": self.message,
        }


@dataclass(frozen=True)
class ProfileThresholds:
    management_fee_max: float
    custody_fee_max: float
    min_history_years_for_3y: int
    min_history_years_for_5y: int


@dataclass(frozen=True)
class ProfileQualityReport:
    errors: tuple[ProfileIssue, ...]
    warnings: tuple[ProfileIssue, ...]
    thresholds: ProfileThresholds

    @property
    def issue_count(self) -> int:
        return len(self.errors) + len(self.warnings)


def _thresholds_for_source(source_name: str, funds: list[FundDetail]) -> ProfileThresholds:
    values: dict[str, int | float] = {
        "management_fee_max": settings.fund_profile_management_fee_max,
        "custody_fee_max": settings.fund_profile_custody_fee_max,
        "min_history_years_for_3y": settings.fund_profile_min_history_years_for_3y,
        "min_history_years_for_5y": settings.fund_profile_min_history_years_for_5y,
    }
    candidate_keys = [source_name, *sorted({fund.source for fund in funds if fund.source})]
    for key in candidate_keys:
        values.update(settings.fund_profile_quality_overrides.get(key, {}))
    return ProfileThresholds(
        management_fee_max=float(values["management_fee_max"]),
        custody_fee_max=float(values["custody_fee_max"]),
        min_history_years_for_3y=int(values["min_history_years_for_3y"]),
        min_history_years_for_5y=int(values["min_history_years_for_5y"]),
    )


def _nav_year_span(fund: FundDetail) -> tuple[int, int] | None:
    years: list[int] = []
    for point in fund.navs:
        raw = point.trade_date
        if len(raw) == 4 and raw.isdigit():
            years.append(int(raw))
        elif len(raw) == 10:
            years.append(int(raw[:4]))
    if not years:
        return None
    return min(years), max(years)


def _inception_year(fund: FundDetail) -> int | None:
    raw = fund.inception_date
    if len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return None


def _check_fund(fund: FundDetail, thresholds: ProfileThresholds) -> list[ProfileIssue]:
    issues: list[ProfileIssue] = []
    if fund.management_fee > thresholds.management_fee_max:
        issues.append(
            ProfileIssue(
                severity="warning",
                code="profile_management_fee_out_of_range",
                fund_code=fund.code,
                field="management_fee",
                value=fund.management_fee,
                minimum=0.0,
                maximum=thresholds.management_fee_max,
                message=(
                    f"fund {fund.code} management fee {fund.management_fee}% "
                    f"exceeds configured max {thresholds.management_fee_max}%"
                ),
            )
        )
    if fund.custody_fee > thresholds.custody_fee_max:
        issues.append(
            ProfileIssue(
                severity="warning",
                code="profile_custody_fee_out_of_range",
                fund_code=fund.code,
                field="custody_fee",
                value=fund.custody_fee,
                minimum=0.0,
                maximum=thresholds.custody_fee_max,
                message=(
                    f"fund {fund.code} custody fee {fund.custody_fee}% "
                    f"exceeds configured max {thresholds.custody_fee_max}%"
                ),
            )
        )
    if fund.fund_size_billion < 0:
        issues.append(
            ProfileIssue(
                severity="warning",
                code="profile_fund_size_negative",
                fund_code=fund.code,
                field="fund_size_billion",
                value=fund.fund_size_billion,
                minimum=0.0,
                maximum=fund.fund_size_billion,
                message=f"fund {fund.code} has negative size {fund.fund_size_billion}",
            )
        )

    inception_year = _inception_year(fund)
    span = _nav_year_span(fund)
    latest_year = span[1] if span else inception_year
    if inception_year is not None and latest_year is not None:
        fund_age_years = latest_year - inception_year
        if fund.manager_years > fund_age_years:
            issues.append(
                ProfileIssue(
                    severity="warning",
                    code="profile_manager_years_exceed_fund_age",
                    fund_code=fund.code,
                    field="manager_years",
                    value=float(fund.manager_years),
                    minimum=0.0,
                    maximum=float(fund_age_years),
                    message=(
                        f"fund {fund.code} manager tenure {fund.manager_years}y "
                        f"exceeds fund age {fund_age_years}y"
                    ),
                )
            )

    if span is not None:
        history_years = span[1] - span[0]
        if (
            thresholds.min_history_years_for_3y > 0
            and fund.annualized_return_3y > 0
            and history_years < thresholds.min_history_years_for_3y
        ):
            issues.append(
                ProfileIssue(
                    severity="warning",
                    code="profile_3y_return_claim_unsupported_by_history",
                    fund_code=fund.code,
                    field="annualized_return_3y",
                    value=float(history_years),
                    minimum=float(thresholds.min_history_years_for_3y),
                    maximum=float(thresholds.min_history_years_for_3y),
                    message=(
                        f"fund {fund.code} claims 3y return but NAV history spans only "
                        f"{history_years} years"
                    ),
                )
            )
        if (
            thresholds.min_history_years_for_5y > 0
            and fund.annualized_return_5y > 0
            and history_years < thresholds.min_history_years_for_5y
        ):
            issues.append(
                ProfileIssue(
                    severity="warning",
                    code="profile_5y_return_claim_unsupported_by_history",
                    fund_code=fund.code,
                    field="annualized_return_5y",
                    value=float(history_years),
                    minimum=float(thresholds.min_history_years_for_5y),
                    maximum=float(thresholds.min_history_years_for_5y),
                    message=(
                        f"fund {fund.code} claims 5y return but NAV history spans only "
                        f"{history_years} years"
                    ),
                )
            )
    return issues


def assess_profile_quality(
    funds: list[FundDetail],
    *,
    source_name: str,
) -> ProfileQualityReport:
    thresholds = _thresholds_for_source(source_name, funds)
    errors: list[ProfileIssue] = []
    warnings: list[ProfileIssue] = []
    for fund in funds:
        for issue in _check_fund(fund, thresholds):
            (errors if issue.severity == "error" else warnings).append(issue)
    return ProfileQualityReport(
        errors=tuple(errors),
        warnings=tuple(warnings),
        thresholds=thresholds,
    )
