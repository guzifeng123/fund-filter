from datetime import date, datetime

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.compliance import is_risk_matched
from app.db.models import Fund as FundModel
from app.db.models import FundMetric, FundNav
from app.schemas.funds import (
    FeeSummary,
    Fund,
    FundDetail,
    FundFilterRequest,
    FundSortBy,
    ManagerProfile,
    MetricExplanation,
    NavPoint,
    RiskMatchResult,
    RiskProfile,
    SortOrder,
)


def _as_iso(value: date | datetime) -> str:
    return value.isoformat()


def _to_fund(row: FundModel) -> Fund:
    if row.metrics is None:
        raise ValueError(f"fund {row.code} has no metrics")
    return Fund(
        code=row.code,
        name=row.name,
        fund_type=row.fund_type,  # type: ignore[arg-type]
        risk_level=row.risk_level,  # type: ignore[arg-type]
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
        data_updated_at=_as_iso(row.data_updated_at),
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
    matched = is_risk_matched(risk_profile, row.risk_level)
    return FundDetail(
        **fund.model_dump(),
        navs=[
            NavPoint(trade_date=nav.trade_date, nav=nav.nav, accumulated_nav=nav.accumulated_nav)
            for nav in sorted(row.navs, key=lambda item: item.trade_date)
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
            fund_risk_level=row.risk_level,  # type: ignore[arg-type]
            matched=matched,
            message=_risk_match_message(risk_profile, row.risk_level, matched),
        ),
    )


def latest_fund_data_updated_at(db: Session) -> datetime | None:
    return db.scalar(select(func.max(FundModel.data_updated_at)))


def _sort_expression(sort_by: FundSortBy):
    return {
        "code": FundModel.code,
        "annualized_return_3y": FundMetric.annualized_return_3y,
        "annualized_return_5y": FundMetric.annualized_return_5y,
        "max_drawdown": FundMetric.max_drawdown,
        "sharpe_ratio": FundMetric.sharpe_ratio,
        "fee": FundModel.management_fee + FundModel.custody_fee,
        "size": FundModel.fund_size_billion,
    }[sort_by]


def _order_by(sort_by: FundSortBy, sort_order: SortOrder):
    expression = _sort_expression(sort_by)
    return asc(expression) if sort_order == "asc" else desc(expression)


def search_funds(
    db: Session,
    query: str,
    page: int = 1,
    page_size: int = 20,
    fund_types: list[str] | None = None,
    risk_levels: list[str] | None = None,
    sort_by: FundSortBy = "code",
    sort_order: SortOrder = "asc",
) -> tuple[list[Fund], int]:
    needle = query.strip().lower()
    stmt = select(FundModel).join(FundMetric).options(joinedload(FundModel.metrics))
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
    return [_to_fund(row) for row in rows[start:end] if row.metrics is not None], total


def get_fund(db: Session, code: str, risk_profile: RiskProfile = "C3") -> FundDetail | None:
    stmt = (
        select(FundModel)
        .where(FundModel.code == code)
        .options(joinedload(FundModel.metrics), joinedload(FundModel.navs))
    )
    row = db.scalars(stmt).unique().first()
    return _to_detail(row, risk_profile) if row and row.metrics is not None else None


def get_fund_navs(db: Session, code: str, start: str | None = None, end: str | None = None) -> list[NavPoint] | None:
    if db.get(FundModel, code) is None:
        return None
    stmt = select(FundNav).where(FundNav.fund_code == code)
    if start is not None:
        stmt = stmt.where(FundNav.trade_date >= start)
    if end is not None:
        stmt = stmt.where(FundNav.trade_date <= end)
    rows = db.scalars(stmt.order_by(FundNav.trade_date)).all()
    return [
        NavPoint(trade_date=row.trade_date, nav=row.nav, accumulated_nav=row.accumulated_nav)
        for row in rows
    ]


def filter_funds(db: Session, payload: FundFilterRequest) -> list[Fund]:
    low, high = payload.size_range
    stmt = (
        select(FundModel)
        .join(FundMetric)
        .options(joinedload(FundModel.metrics))
        .where(
            FundModel.fund_type.in_(payload.fund_types),
            FundModel.fund_size_billion >= low,
            FundModel.fund_size_billion <= high,
            FundMetric.manager_years >= payload.min_years,
            FundMetric.category_rank_percentile <= payload.return_rank_percentile,
            FundMetric.sharpe_ratio >= payload.sharpe_gte,
            FundModel.management_fee + FundModel.custody_fee <= payload.fee_lte,
        )
        .order_by(_order_by(payload.sort_by, payload.sort_order), FundModel.code)
    )
    rows = db.scalars(stmt).unique().all()
    return [_to_fund(row) for row in rows if row.metrics is not None and is_risk_matched(payload.risk_profile, row.risk_level)]


def compare_funds(db: Session, codes: list[str]) -> list[Fund]:
    selected_codes = codes[:5]
    stmt = (
        select(FundModel)
        .where(FundModel.code.in_(selected_codes))
        .options(joinedload(FundModel.metrics))
        .order_by(FundModel.code)
    )
    rows_by_code = {row.code: row for row in db.scalars(stmt).unique().all()}
    return [_to_fund(rows_by_code[code]) for code in selected_codes if code in rows_by_code and rows_by_code[code].metrics]


def upsert_fund_detail(db: Session, fund: FundDetail) -> None:
    row = db.get(FundModel, fund.code)
    payload = fund.model_dump()
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

    metric = row.metrics or FundMetric(fund_code=fund.code)
    metric.annualized_return_3y = fund.annualized_return_3y
    metric.annualized_return_5y = fund.annualized_return_5y
    metric.max_drawdown = fund.max_drawdown
    metric.sharpe_ratio = fund.sharpe_ratio
    metric.category_rank_percentile = fund.category_rank_percentile
    metric.manager_years = fund.manager_years
    metric.raw_data = payload
    row.metrics = metric

    existing_navs = {nav.trade_date: nav for nav in row.navs}
    for nav in fund.navs:
        nav_row = existing_navs.get(nav.trade_date)
        if nav_row is None:
            nav_row = FundNav(fund_code=fund.code, trade_date=nav.trade_date)
            row.navs.append(nav_row)
        nav_row.nav = nav.nav
        nav_row.accumulated_nav = nav.accumulated_nav
        nav_row.raw_data = nav.model_dump()
