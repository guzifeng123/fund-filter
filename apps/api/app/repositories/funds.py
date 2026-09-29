from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import SQLColumnExpression, UnaryExpression

from app.core.compliance import RISK_PROFILE_LIMITS, is_risk_matched
from app.core.config import settings
from app.core.nav_dates import nav_trade_date_precision
from app.core.nav_quality import NavQualityWarningPayload, validate_fund_navs
from app.db.models import Fund as FundModel
from app.db.models import FundMetric, FundNav, JsonObject, JsonValue
from app.repositories.fund_snapshots import (
    active_snapshot_generation_expression,
    active_snapshot_generation_id,
)
from app.schemas.funds import (
    FeeSummary,
    Fund,
    FundDetail,
    FundFilterRequest,
    FundSortBy,
    FundType,
    ManagerProfile,
    MetricExplanation,
    NavPoint,
    RiskMatchResult,
    RiskLevel,
    RiskProfile,
    SortOrder,
)

T = TypeVar("T")


@dataclass(frozen=True)
class FundDataContext:
    snapshot_generation_id: str
    source: str
    data_updated_at: datetime | None


@dataclass(frozen=True)
class FundReadResult(Generic[T]):
    data: T
    context: FundDataContext


@dataclass(frozen=True)
class FundSearchResult:
    data: list[Fund]
    total: int
    context: FundDataContext


FUND_TYPES_BY_VALUE: dict[str, FundType] = {
    "stock": "stock",
    "mixed": "mixed",
    "bond": "bond",
    "money": "money",
}

RISK_LEVELS_BY_VALUE: dict[str, RiskLevel] = {
    "R1": "R1",
    "R2": "R2",
    "R3": "R3",
    "R4": "R4",
    "R5": "R5",
}


def _as_iso(value: date | datetime) -> str:
    return value.isoformat()


def _raw_string(payload: JsonObject, key: str) -> str | None:
    value = payload.get(key)
    return str(value) if value not in (None, "") else None


def _stored_fund_type(value: str) -> FundType:
    try:
        return FUND_TYPES_BY_VALUE[value]
    except KeyError as exc:
        raise ValueError(f"unsupported stored fund_type: {value}") from exc


def _stored_risk_level(value: str) -> RiskLevel:
    try:
        return RISK_LEVELS_BY_VALUE[value]
    except KeyError as exc:
        raise ValueError(f"unsupported stored risk_level: {value}") from exc


def _to_fund(row: FundModel) -> Fund:
    if row.metrics is None or row.metrics.snapshot_generation_id != row.snapshot_generation_id:
        raise ValueError(f"fund {row.code} has no metrics")
    return Fund(
        code=row.code,
        name=row.name,
        fund_type=_stored_fund_type(row.fund_type),
        risk_level=_stored_risk_level(row.risk_level),
        manager_name=row.manager_name,
        inception_date=_as_iso(row.inception_date),
        fund_size_billion=row.fund_size_billion,
        management_fee=row.management_fee,
        custody_fee=row.custody_fee,
        annualized_return_3y=row.metrics.annualized_return_3y,
        annualized_return_5y=row.metrics.annualized_return_5y,
        max_drawdown=row.metrics.max_drawdown,
        sharpe_ratio=row.metrics.sharpe_ratio,
        category_rank_percentile=row.metrics.category_rank_percentile,
        manager_years=row.metrics.manager_years,
        source=row.source,
        provider_profile=_raw_string(row.raw_data, "provider_profile"),
        upstream_provider=_raw_string(row.raw_data, "upstream_provider"),
        data_updated_at=_as_iso(row.data_updated_at),
        snapshot_generation_id=row.snapshot_generation_id,
    )


def _format_percent(value: float) -> str:
    return f"{value:.2f}%"


def _risk_match_message(profile: RiskProfile, risk_level: str, matched: bool) -> str:
    if matched:
        return f"该基金风险等级 {risk_level} 未超过当前 {profile} 承受能力，可进入进一步研究。"
    return f"该基金风险等级 {risk_level} 超过当前 {profile} 承受能力，不应进入推荐结果。"


def _metric_explanations(row: FundModel) -> list[MetricExplanation]:
    if row.metrics is None:
        return []
    total_fee = row.management_fee + row.custody_fee
    return [
        MetricExplanation(
            key="annualized_return_3y",
            label="3年年化收益",
            value=_format_percent(row.metrics.annualized_return_3y),
            explanation="基于历史区间折算的年化表现，仅反映过往，不代表未来收益。",
        ),
        MetricExplanation(
            key="max_drawdown",
            label="最大回撤",
            value=_format_percent(row.metrics.max_drawdown),
            explanation="历史区间内从高点到低点的最大跌幅，用于观察持有过程中的波动压力。",
        ),
        MetricExplanation(
            key="sharpe_ratio",
            label="夏普比率",
            value=f"{row.metrics.sharpe_ratio:.2f}",
            explanation="单位波动下的历史收益补偿，数值越高通常代表历史风险收益比越好。",
        ),
        MetricExplanation(
            key="fee",
            label="费用合计",
            value=_format_percent(total_fee),
            explanation="管理费与托管费合计，费用越高越需要用长期表现和策略价值解释。",
        ),
    ]


def _to_detail(row: FundModel, risk_profile: RiskProfile = "C3") -> FundDetail:
    fund = _to_fund(row)
    total_fee = row.management_fee + row.custody_fee
    matched = is_risk_matched(risk_profile, fund.risk_level)
    return FundDetail(
        **fund.model_dump(),
        navs=[
            NavPoint(trade_date=nav.trade_date, nav=nav.nav, accumulated_nav=nav.accumulated_nav)
            for nav in sorted(row.navs, key=lambda item: item.trade_date)
            if nav.snapshot_generation_id == row.snapshot_generation_id
        ],
        ai_summary=row.ai_summary,
        fee_summary=FeeSummary(
            management_fee=row.management_fee,
            custody_fee=row.custody_fee,
            total_fee=total_fee,
            explanation="费用为样本数据口径下的管理费与托管费合计，暂未包含申购、赎回等交易相关费用。",
        ),
        manager_profile=ManagerProfile(
            name=row.manager_name,
            years=row.metrics.manager_years if row.metrics else 0,
            inception_date=_as_iso(row.inception_date),
            explanation="经理年限来自样本指标，用于辅助观察管理经验，不构成对未来业绩的判断。",
        ),
        metric_explanations=_metric_explanations(row),
        risk_match=RiskMatchResult(
            user_risk_profile=risk_profile,
            fund_risk_level=fund.risk_level,
            matched=matched,
            message=_risk_match_message(risk_profile, fund.risk_level, matched),
        ),
    )


def latest_fund_data_updated_at(
    db: Session,
    snapshot_generation_id: str | None = None,
) -> datetime | None:
    generation_id = snapshot_generation_id or active_snapshot_generation_expression()
    return db.scalar(
        select(func.max(FundModel.data_updated_at)).where(
            FundModel.snapshot_generation_id == generation_id
        )
    )


def fund_data_source_summary(
    db: Session,
    snapshot_generation_id: str | None = None,
) -> str:
    generation_id = snapshot_generation_id or active_snapshot_generation_expression()
    raw_sources = db.scalars(
        select(FundModel.source)
        .where(FundModel.snapshot_generation_id == generation_id)
        .distinct()
        .order_by(FundModel.source)
    ).all()
    sources = [source.strip() for source in raw_sources if source and source.strip()]
    if not sources:
        return settings.fund_data_source
    if len(sources) == 1:
        return sources[0]
    return f"mixed({','.join(sources)})"


def fund_data_context(
    db: Session,
    snapshot_generation_id: str | None = None,
) -> FundDataContext:
    generation_id = snapshot_generation_id or active_snapshot_generation_id(db)
    return FundDataContext(
        snapshot_generation_id=generation_id,
        source=fund_data_source_summary(db, generation_id),
        data_updated_at=latest_fund_data_updated_at(db, generation_id),
    )


def _sort_expression(
    sort_by: FundSortBy,
) -> SQLColumnExpression[str] | SQLColumnExpression[float]:
    if sort_by == "code":
        return FundModel.code
    if sort_by == "annualized_return_3y":
        return FundMetric.annualized_return_3y
    if sort_by == "annualized_return_5y":
        return FundMetric.annualized_return_5y
    if sort_by == "max_drawdown":
        return FundMetric.max_drawdown
    if sort_by == "sharpe_ratio":
        return FundMetric.sharpe_ratio
    if sort_by == "fee":
        return FundModel.management_fee + FundModel.custody_fee
    return FundModel.fund_size_billion


def _order_by(
    sort_by: FundSortBy,
    sort_order: SortOrder,
) -> UnaryExpression[str] | UnaryExpression[float]:
    expression = _sort_expression(sort_by)
    return expression.asc() if sort_order == "asc" else expression.desc()


def fund_inception_cutoff(as_of_date: date, min_years: int) -> date:
    """Return the latest inception date that has completed ``min_years`` years."""
    target_year = as_of_date.year - min_years
    try:
        return as_of_date.replace(year=target_year)
    except ValueError:
        # February 29 has no direct counterpart in a non-leap target year.
        return as_of_date.replace(year=target_year, day=28)


def search_funds(
    db: Session,
    query: str,
    page: int = 1,
    page_size: int = 20,
    fund_types: list[FundType] | None = None,
    risk_levels: list[RiskLevel] | None = None,
    sort_by: FundSortBy = "code",
    sort_order: SortOrder = "asc",
) -> tuple[list[Fund], int]:
    result = search_funds_with_context(
        db,
        query,
        page=page,
        page_size=page_size,
        fund_types=fund_types,
        risk_levels=risk_levels,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return result.data, result.total


def search_funds_with_context(
    db: Session,
    query: str,
    page: int = 1,
    page_size: int = 20,
    fund_types: list[FundType] | None = None,
    risk_levels: list[RiskLevel] | None = None,
    sort_by: FundSortBy = "code",
    sort_order: SortOrder = "asc",
) -> FundSearchResult:
    context = fund_data_context(db)
    generation_id = context.snapshot_generation_id
    needle = query.strip().lower()
    stmt = (
        select(FundModel)
        .join(FundMetric)
        .options(joinedload(FundModel.metrics))
        .where(
            FundModel.snapshot_generation_id == generation_id,
            FundMetric.snapshot_generation_id == generation_id,
        )
    )
    if fund_types:
        stmt = stmt.where(FundModel.fund_type.in_(fund_types))
    if risk_levels:
        stmt = stmt.where(FundModel.risk_level.in_(risk_levels))
    stmt = stmt.order_by(_order_by(sort_by, sort_order), FundModel.code)
    rows = db.scalars(stmt).unique().all()
    if needle:
        rows = [row for row in rows if needle in f"{row.code}{row.name}".lower()]
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    return FundSearchResult(
        data=[_to_fund(row) for row in rows[start:end] if row.metrics is not None],
        total=total,
        context=context,
    )


def get_fund(db: Session, code: str, risk_profile: RiskProfile = "C3") -> FundDetail | None:
    result = get_fund_with_context(db, code, risk_profile)
    return result.data if result is not None else None


def get_fund_with_context(
    db: Session,
    code: str,
    risk_profile: RiskProfile = "C3",
) -> FundReadResult[FundDetail] | None:
    context = fund_data_context(db)
    generation_id = context.snapshot_generation_id
    stmt = (
        select(FundModel)
        .where(
            FundModel.code == code,
            FundModel.snapshot_generation_id == generation_id,
        )
        .options(joinedload(FundModel.metrics), joinedload(FundModel.navs))
    )
    row = db.scalars(stmt).unique().first()
    if row is None or row.metrics is None:
        return None
    return FundReadResult(data=_to_detail(row, risk_profile), context=context)


def get_fund_navs(
    db: Session, code: str, start: str | None = None, end: str | None = None
) -> list[NavPoint] | None:
    result = get_fund_navs_with_context(db, code, start, end)
    return result.data if result is not None else None


def get_fund_navs_with_context(
    db: Session,
    code: str,
    start: str | None = None,
    end: str | None = None,
) -> FundReadResult[list[NavPoint]] | None:
    context = fund_data_context(db)
    generation_id = context.snapshot_generation_id
    if db.scalar(
        select(FundModel.code).where(
            FundModel.code == code,
            FundModel.snapshot_generation_id == generation_id,
        )
    ) is None:
        return None
    stmt = (
        select(FundNav)
        .join(FundModel, FundModel.code == FundNav.fund_code)
        .where(
            FundNav.fund_code == code,
            FundNav.snapshot_generation_id == generation_id,
            FundModel.snapshot_generation_id == generation_id,
        )
    )
    if start is not None:
        stmt = stmt.where(FundNav.trade_date >= start)
    if end is not None:
        stmt = stmt.where(FundNav.trade_date <= end)
    rows = db.scalars(stmt.order_by(FundNav.trade_date)).all()
    return FundReadResult(
        data=[
            NavPoint(trade_date=row.trade_date, nav=row.nav, accumulated_nav=row.accumulated_nav)
            for row in rows
        ],
        context=context,
    )


def filter_funds(
    db: Session,
    payload: FundFilterRequest,
    *,
    as_of_date: date | None = None,
) -> list[Fund]:
    return filter_funds_with_context(db, payload, as_of_date=as_of_date).data


def filter_funds_with_context(
    db: Session,
    payload: FundFilterRequest,
    *,
    as_of_date: date | None = None,
) -> FundReadResult[list[Fund]]:
    context = fund_data_context(db)
    generation_id = context.snapshot_generation_id
    low, high = payload.size_range
    keyword = payload.keyword.strip().lower() if payload.keyword else ""
    inception_cutoff = fund_inception_cutoff(as_of_date or date.today(), payload.min_years)
    stmt = (
        select(FundModel)
        .join(FundMetric)
        .options(joinedload(FundModel.metrics))
        .where(
            FundModel.snapshot_generation_id == generation_id,
            FundMetric.snapshot_generation_id == generation_id,
            FundModel.risk_level.in_(RISK_PROFILE_LIMITS[payload.risk_profile]),
            FundModel.fund_type.in_(payload.fund_types),
            FundModel.fund_size_billion >= low,
            FundModel.fund_size_billion <= high,
            FundModel.inception_date <= inception_cutoff,
            FundMetric.category_rank_percentile <= payload.return_rank_percentile,
            FundMetric.sharpe_ratio >= payload.sharpe_gte,
            FundModel.management_fee + FundModel.custody_fee <= payload.fee_lte,
        )
    )
    if keyword:
        stmt = stmt.where(
            or_(
                func.lower(FundModel.code).contains(keyword, autoescape=True),
                func.lower(FundModel.name).contains(keyword, autoescape=True),
            )
        )
    if payload.max_drawdown_lte_category_avg:
        category_drawdown_average = (
            select(
                FundModel.fund_type.label("fund_type"),
                func.avg(FundMetric.max_drawdown).label("average_max_drawdown"),
            )
            .join(FundMetric)
            .where(
                FundModel.snapshot_generation_id == generation_id,
                FundMetric.snapshot_generation_id == generation_id,
            )
            .group_by(FundModel.fund_type)
            .subquery()
        )
        stmt = stmt.join(
            category_drawdown_average,
            category_drawdown_average.c.fund_type == FundModel.fund_type,
        ).where(
            # Drawdowns are stored as negative percentages. A greater value means a
            # smaller loss magnitude, for example -5% is better than -10%.
            FundMetric.max_drawdown >= category_drawdown_average.c.average_max_drawdown
        )
    stmt = stmt.order_by(_order_by(payload.sort_by, payload.sort_order), FundModel.code)
    rows = db.scalars(stmt).unique().all()
    return FundReadResult(
        data=[_to_fund(row) for row in rows if row.metrics is not None],
        context=context,
    )


def compare_funds(db: Session, codes: list[str]) -> list[Fund]:
    return compare_funds_with_context(db, codes).data


def compare_funds_with_context(db: Session, codes: list[str]) -> FundReadResult[list[Fund]]:
    context = fund_data_context(db)
    generation_id = context.snapshot_generation_id
    selected_codes = codes[:5]
    stmt = (
        select(FundModel)
        .join(FundMetric)
        .where(
            FundModel.code.in_(selected_codes),
            FundModel.snapshot_generation_id == generation_id,
            FundMetric.snapshot_generation_id == generation_id,
        )
        .options(joinedload(FundModel.metrics))
        .order_by(FundModel.code)
    )
    rows_by_code = {row.code: row for row in db.scalars(stmt).unique().all()}
    return FundReadResult(
        data=[
            _to_fund(rows_by_code[code])
            for code in selected_codes
            if code in rows_by_code and rows_by_code[code].metrics
        ],
        context=context,
    )


def upsert_fund_profile(
    db: Session,
    fund: FundDetail,
    snapshot_generation_id: str | None = None,
) -> None:
    generation_id = snapshot_generation_id or active_snapshot_generation_id(db)
    row = db.get(FundModel, fund.code)
    payload = fund.model_dump(
        include={
            "code",
            "name",
            "fund_type",
            "risk_level",
            "manager_name",
            "inception_date",
            "fund_size_billion",
            "management_fee",
            "custody_fee",
            "source",
            "provider_profile",
            "upstream_provider",
            "data_updated_at",
            "ai_summary",
        }
    )
    if row is None:
        row = FundModel(code=fund.code)
        db.add(row)
    row.name = fund.name
    row.fund_type = fund.fund_type
    row.risk_level = fund.risk_level
    row.manager_name = fund.manager_name
    row.inception_date = date.fromisoformat(fund.inception_date)
    row.fund_size_billion = fund.fund_size_billion
    row.management_fee = fund.management_fee
    row.custody_fee = fund.custody_fee
    row.source = fund.source
    row.data_updated_at = datetime.fromisoformat(fund.data_updated_at)
    row.ai_summary = fund.ai_summary
    row.raw_data = payload
    row.snapshot_generation_id = generation_id


def upsert_fund_metrics(
    db: Session,
    fund: FundDetail,
    snapshot_generation_id: str | None = None,
) -> None:
    generation_id = snapshot_generation_id or active_snapshot_generation_id(db)
    row = db.get(FundModel, fund.code)
    if row is None or row.snapshot_generation_id != generation_id:
        upsert_fund_profile(db, fund, generation_id)
        db.flush()
        row = db.get(FundModel, fund.code)
    assert row is not None
    payload = fund.model_dump(
        include={
            "code",
            "annualized_return_3y",
            "annualized_return_5y",
            "max_drawdown",
            "sharpe_ratio",
            "category_rank_percentile",
            "manager_years",
            "metric_explanations",
            "source",
            "provider_profile",
            "upstream_provider",
        }
    )
    metric = row.metrics or FundMetric(fund_code=fund.code)
    metric.annualized_return_3y = fund.annualized_return_3y
    metric.annualized_return_5y = fund.annualized_return_5y
    metric.max_drawdown = fund.max_drawdown
    metric.sharpe_ratio = fund.sharpe_ratio
    metric.category_rank_percentile = fund.category_rank_percentile
    metric.manager_years = fund.manager_years
    metric.raw_data = payload
    metric.snapshot_generation_id = generation_id
    row.metrics = metric


def _warning_json(payload: NavQualityWarningPayload) -> JsonObject:
    return {
        "code": payload["code"],
        "fund_code": payload["fund_code"],
        "trade_date": payload["trade_date"],
        "field": payload["field"],
        "value": payload["value"],
        "minimum": payload["minimum"],
        "maximum": payload["maximum"],
        "message": payload["message"],
    }


def upsert_fund_navs(
    db: Session,
    fund: FundDetail,
    snapshot_generation_id: str | None = None,
) -> list[NavQualityWarningPayload]:
    generation_id = snapshot_generation_id or active_snapshot_generation_id(db)
    quality_warnings = validate_fund_navs(fund)
    warning_payloads = [warning.as_dict() for warning in quality_warnings]
    warnings_by_date: dict[str, list[NavQualityWarningPayload]] = {}
    for warning in warning_payloads:
        warnings_by_date.setdefault(warning["trade_date"], []).append(warning)

    row = db.get(FundModel, fund.code)
    if row is None or row.snapshot_generation_id != generation_id:
        upsert_fund_profile(db, fund, generation_id)
        db.flush()
        row = db.get(FundModel, fund.code)
    assert row is not None
    existing_navs = {nav.trade_date: nav for nav in row.navs}
    for nav in fund.navs:
        precision = nav_trade_date_precision(nav.trade_date)
        if precision is None:
            raise ValueError(f"fund {fund.code} has invalid NAV trade_date {nav.trade_date!r}")
        nav_row = existing_navs.get(nav.trade_date)
        if nav_row is None:
            nav_row = FundNav(fund_code=fund.code, trade_date=nav.trade_date)
            row.navs.append(nav_row)
        nav_row.trade_date_precision = precision
        nav_row.nav = nav.nav
        nav_row.accumulated_nav = nav.accumulated_nav
        stored_warnings: list[JsonValue] = [
            _warning_json(warning) for warning in warnings_by_date.get(nav.trade_date, [])
        ]
        nav_row.raw_data = {
            **nav.model_dump(),
            "source": fund.source,
            "provider_profile": fund.provider_profile,
            "upstream_provider": fund.upstream_provider,
            "trade_date_precision": precision,
            "quality_warnings": stored_warnings,
        }
        nav_row.snapshot_generation_id = generation_id
    return warning_payloads


def upsert_fund_detail(
    db: Session,
    fund: FundDetail,
    snapshot_generation_id: str | None = None,
) -> None:
    generation_id = snapshot_generation_id or active_snapshot_generation_id(db)
    upsert_fund_profile(db, fund, generation_id)
    db.flush()
    upsert_fund_metrics(db, fund, generation_id)
    upsert_fund_navs(db, fund, generation_id)


def stage_funds_batch(
    db: Session,
    funds: list[FundDetail],
    snapshot_generation_id: str,
    *,
    batch_size: int,
) -> list[NavQualityWarningPayload]:
    """Stage a full snapshot with batched flushes.

    This is the conservative batch counterpart to the historical per-fund
    flush loop in ``sync_fund_data``. It reuses the exact same profile / metric /
    NAV upsert semantics (same generation assignment, same ``raw_data`` payloads
    and the same quality warnings); the only difference is that SQLAlchemy
    flushes the unit of work in a few large chunks instead of after every fund.
    The passes are grouped (profiles, then metrics, then navs) so that every fund
    row is already persistent before the metric / NAV helpers look it up again;
    the per-point path stays available for rollback.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")
    for fund in funds:
        upsert_fund_profile(db, fund, snapshot_generation_id)
    db.flush()
    quality_warnings: list[NavQualityWarningPayload] = []
    for index, fund in enumerate(funds):
        upsert_fund_metrics(db, fund, snapshot_generation_id)
        quality_warnings.extend(upsert_fund_navs(db, fund, snapshot_generation_id))
        if (index + 1) % batch_size == 0:
            db.flush()
    db.flush()
    return quality_warnings
