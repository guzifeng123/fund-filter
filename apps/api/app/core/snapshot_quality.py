from dataclasses import dataclass
from datetime import date

from app.core.config import settings
from app.schemas.funds import FundDetail


class SnapshotQualityError(ValueError):
    pass


@dataclass(frozen=True)
class SnapshotQualityThresholds:
    min_fund_count: int
    min_nav_coverage_ratio: float
    max_latest_nav_age_days: int
    max_fund_count_drop_ratio: float


def _thresholds_for_source(source_name: str, funds: list[FundDetail]) -> SnapshotQualityThresholds:
    values: dict[str, int | float] = {
        "min_fund_count": settings.fund_snapshot_min_fund_count,
        "min_nav_coverage_ratio": settings.fund_snapshot_min_nav_coverage_ratio,
        "max_latest_nav_age_days": settings.fund_snapshot_max_latest_nav_age_days,
        "max_fund_count_drop_ratio": settings.fund_snapshot_max_fund_count_drop_ratio,
    }
    candidate_keys = [source_name, *sorted({fund.source for fund in funds if fund.source})]
    for key in candidate_keys:
        values.update(settings.fund_snapshot_quality_overrides.get(key, {}))
    return SnapshotQualityThresholds(
        min_fund_count=int(values["min_fund_count"]),
        min_nav_coverage_ratio=float(values["min_nav_coverage_ratio"]),
        max_latest_nav_age_days=int(values["max_latest_nav_age_days"]),
        max_fund_count_drop_ratio=float(values["max_fund_count_drop_ratio"]),
    )


def _latest_iso_nav_date(funds: list[FundDetail]) -> date | None:
    latest: date | None = None
    for fund in funds:
        for point in fund.navs:
            if len(point.trade_date) != 10:
                continue
            try:
                parsed = date.fromisoformat(point.trade_date)
            except ValueError:
                continue
            latest = parsed if latest is None else max(latest, parsed)
    return latest


def validate_snapshot_quality(
    funds: list[FundDetail],
    *,
    source_name: str,
    previous_fund_count: int,
    today: date | None = None,
) -> SnapshotQualityThresholds:
    thresholds = _thresholds_for_source(source_name, funds)
    fund_count = len(funds)
    if fund_count < thresholds.min_fund_count:
        raise SnapshotQualityError(
            "snapshot fund count is below configured minimum: "
            f"fund_count={fund_count}, minimum={thresholds.min_fund_count}, "
            f"source={source_name}"
        )

    if fund_count > 0:
        funds_with_nav = sum(1 for fund in funds if fund.navs)
        nav_coverage_ratio = funds_with_nav / fund_count
        if nav_coverage_ratio < thresholds.min_nav_coverage_ratio:
            raise SnapshotQualityError(
                "snapshot NAV coverage is below configured minimum: "
                f"coverage={nav_coverage_ratio:.4f}, "
                f"minimum={thresholds.min_nav_coverage_ratio:.4f}, "
                f"funds_with_nav={funds_with_nav}, fund_count={fund_count}, "
                f"source={source_name}"
            )

    if thresholds.max_latest_nav_age_days > 0:
        latest_nav_date = _latest_iso_nav_date(funds)
        if latest_nav_date is None:
            raise SnapshotQualityError(
                "snapshot has no ISO NAV date for freshness threshold: "
                f"max_latest_nav_age_days={thresholds.max_latest_nav_age_days}, "
                f"source={source_name}"
            )
        cutoff = (today or date.today()).toordinal() - thresholds.max_latest_nav_age_days
        if latest_nav_date.toordinal() < cutoff:
            raise SnapshotQualityError(
                "snapshot latest NAV date is older than configured threshold: "
                f"latest_nav_date={latest_nav_date.isoformat()}, "
                f"max_latest_nav_age_days={thresholds.max_latest_nav_age_days}, "
                f"source={source_name}"
            )

    if previous_fund_count > 0 and fund_count < previous_fund_count:
        drop_ratio = (previous_fund_count - fund_count) / previous_fund_count
        if drop_ratio > thresholds.max_fund_count_drop_ratio:
            raise SnapshotQualityError(
                "snapshot fund count drop exceeds configured maximum: "
                f"drop_ratio={drop_ratio:.4f}, "
                f"maximum={thresholds.max_fund_count_drop_ratio:.4f}, "
                f"previous_fund_count={previous_fund_count}, fund_count={fund_count}, "
                f"source={source_name}"
            )

    return thresholds
