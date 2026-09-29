from datetime import date
from math import isfinite, sqrt
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BacktestRun, Fund, FundNav
from app.repositories.fund_snapshots import active_snapshot_generation_id
from app.repositories.portfolios import list_templates
from app.schemas.backtest import BacktestPoint, BacktestRequest, BacktestResult


DateSeriesMode = Literal["daily", "yearly"]
YEARLY_SAMPLE_WARNING = (
    "当前 sample 数据仅含年度净值点；回测按每个可用年份投入一次，"
    "年化按首末年份各自 1 月 1 日之间的实际日历跨度近似计算。"
)
XIRR_METHOD: Literal["xirr"] = "xirr"


def _percent(value: float) -> float:
    return round(value * 100, 2)


def _max_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    return _percent(worst)


def _parse_trade_date(value: str) -> date | None:
    if len(value) == 4 and value.isdigit():
        return date(int(value), 1, 1)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _is_year_trade_date(value: str) -> bool:
    return len(value) == 4 and value.isdigit()


def _is_daily_trade_date(value: str) -> bool:
    parsed = _parse_trade_date(value)
    return parsed is not None and parsed.isoformat() == value


def _common_nav_dates(
    navs_by_code: dict[str, list[FundNav]],
) -> tuple[list[str], DateSeriesMode | None]:
    """Choose one coherent date precision, preferring real daily NAVs.

    Year-only sample points are used only when every selected fund contains
    exclusively year labels. This prevents stale sample rows from being mixed
    into a real daily series after a data-source upgrade.
    """

    daily_dates_by_code = [
        {nav.trade_date for nav in navs if _is_daily_trade_date(nav.trade_date)}
        for navs in navs_by_code.values()
    ]
    if daily_dates_by_code and all(daily_dates_by_code):
        common_daily_dates = sorted(set.intersection(*daily_dates_by_code))
        return (common_daily_dates, "daily")

    uses_year_only_data = all(
        navs and all(_is_year_trade_date(nav.trade_date) for nav in navs)
        for navs in navs_by_code.values()
    )
    if uses_year_only_data:
        yearly_dates_by_code = [
            {nav.trade_date for nav in navs}
            for navs in navs_by_code.values()
        ]
        return (sorted(set.intersection(*yearly_dates_by_code)), "yearly")

    return ([], None)


def _periods_per_year(trade_dates: list[str]) -> float:
    parsed_dates = [_parse_trade_date(value) for value in trade_dates]
    if len(parsed_dates) < 2 or any(value is None for value in parsed_dates):
        return 1.0
    first = parsed_dates[0]
    last = parsed_dates[-1]
    assert first is not None and last is not None
    elapsed_days = (last - first).days
    if elapsed_days <= 0:
        return 1.0
    observed = (len(parsed_dates) - 1) * 365.2425 / elapsed_days
    return min(366.0, max(1.0, observed))


def _volatility(returns: list[float], trade_dates: list[str]) -> float:
    if len(returns) < 2:
        return 0
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return _percent((variance**0.5) * sqrt(_periods_per_year(trade_dates)))


def _annualized_return(
    final_value: float,
    total_invested: float,
    trade_dates: list[str],
) -> float:
    if total_invested <= 0 or len(trade_dates) <= 1:
        return 0
    parsed_dates = [_parse_trade_date(value) for value in trade_dates]
    if any(value is None for value in parsed_dates):
        return 0
    first = parsed_dates[0]
    last = parsed_dates[-1]
    assert first is not None and last is not None
    elapsed_days = (last - first).days
    if elapsed_days <= 0:
        return 0
    years = elapsed_days / 365.2425
    return _percent((final_value / total_invested) ** (1 / years) - 1)


def _annualized_time_weighted_return(
    points: list[BacktestPoint],
    external_flows: list[float],
) -> float:
    if len(points) < 2 or len(points) != len(external_flows):
        return 0
    parsed_dates = [_parse_trade_date(point.date) for point in points]
    if any(value is None for value in parsed_dates):
        return 0
    first = parsed_dates[0]
    last = parsed_dates[-1]
    assert first is not None and last is not None
    elapsed_days = (last - first).days
    if elapsed_days <= 0:
        return 0

    growth = 1.0
    for index in range(1, len(points)):
        previous_value = points[index - 1].portfolio
        if previous_value <= 0:
            return 0
        adjusted_current_value = points[index].portfolio - external_flows[index]
        if adjusted_current_value <= 0:
            return -100
        growth *= adjusted_current_value / previous_value
    if growth <= 0:
        return -100
    years = elapsed_days / 365.2425
    return _percent(growth ** (1 / years) - 1)


def _xirr(cash_flows: list[tuple[str, float]]) -> float:
    dated_flows = [
        (parsed, amount)
        for raw_date, amount in cash_flows
        if (parsed := _parse_trade_date(raw_date)) is not None and isfinite(amount)
    ]
    if len(dated_flows) < 2:
        return 0
    dated_flows.sort(key=lambda item: item[0])
    amounts = [amount for _, amount in dated_flows]
    if not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
        return 0

    first_date = dated_flows[0][0]

    def net_present_value(rate: float) -> float:
        return float(sum(
            amount / ((1 + rate) ** ((flow_date - first_date).days / 365.2425))
            for flow_date, amount in dated_flows
        ))

    low = -0.999999
    high = 1.0
    low_value = net_present_value(low)
    high_value = net_present_value(high)
    while high_value > 0 and high < 1_000_000:
        high *= 2
        high_value = net_present_value(high)
    if low_value < 0 or high_value > 0:
        return 0

    for _ in range(100):
        mid = (low + high) / 2
        mid_value = net_present_value(mid)
        if abs(mid_value) < 0.000001:
            return _percent(mid)
        if mid_value > 0:
            low = mid
        else:
            high = mid
    return _percent((low + high) / 2)


def _contribution_dates(
    common_dates: list[str],
    strategy_type: str,
) -> tuple[set[str], bool]:
    if not common_dates:
        return (set(), False)
    if strategy_type == "rebalance":
        return ({common_dates[0]}, False)

    parsed_dates = [_parse_trade_date(value) for value in common_dates]
    uses_full_iso_dates = all(
        parsed is not None and len(raw) == 10
        for raw, parsed in zip(common_dates, parsed_dates, strict=True)
    )
    if not uses_full_iso_dates:
        return (set(common_dates), True)

    selected: set[str] = set()
    seen_periods: set[tuple[int, int]] = set()
    for raw, parsed in zip(common_dates, parsed_dates, strict=True):
        assert parsed is not None
        if strategy_type == "weekly_dca":
            iso_calendar = parsed.isocalendar()
            period = (iso_calendar.year, iso_calendar.week)
        else:
            period = (parsed.year, parsed.month)
        if period not in seen_periods:
            seen_periods.add(period)
            selected.add(raw)
    return (selected, False)


def _load_navs(
    db: Session,
    payload: BacktestRequest,
    snapshot_generation_id: str,
) -> tuple[dict[str, list[FundNav]], dict[str, str]]:
    # A year-precision request means the whole end year for real daily NAVs,
    # while the unexpanded lower bound continues to include legacy "YYYY" rows.
    end_bound = f"{payload.end}-12-31" if _is_year_trade_date(payload.end) else payload.end
    stmt = (
        select(FundNav, Fund.fund_type)
        .join(Fund, Fund.code == FundNav.fund_code)
        .where(
            FundNav.fund_code.in_(payload.fund_codes),
            FundNav.snapshot_generation_id == snapshot_generation_id,
            Fund.snapshot_generation_id == snapshot_generation_id,
            FundNav.trade_date >= payload.start,
            FundNav.trade_date <= end_bound,
        )
        .order_by(FundNav.fund_code, FundNav.trade_date)
    )
    grouped: dict[str, list[FundNav]] = {code: [] for code in payload.fund_codes}
    fund_types: dict[str, str] = {}
    for nav, fund_type in db.execute(stmt).all():
        grouped[nav.fund_code].append(nav)
        fund_types[nav.fund_code] = fund_type
    return grouped, fund_types


def _template_ratios(payload: BacktestRequest) -> tuple[float, float]:
    template = next((item for item in list_templates() if item.id == payload.template_key), None)
    if template is None:
        return (0.5, 0.5)
    return (template.stock_ratio / 100, template.bond_ratio / 100)


def _allocation_weights(
    payload: BacktestRequest,
    fund_types: dict[str, str],
) -> tuple[dict[str, float], str | None]:
    if payload.strategy_type != "template_portfolio":
        weight = 1 / len(payload.fund_codes)
        return ({code: weight for code in payload.fund_codes}, None)

    stock_codes = [code for code in payload.fund_codes if fund_types.get(code) in {"stock", "mixed"}]
    bond_codes = [code for code in payload.fund_codes if fund_types.get(code) in {"bond", "money"}]
    stock_ratio, bond_ratio = _template_ratios(payload)

    if (stock_ratio > 0 and not stock_codes) or (bond_ratio > 0 and not bond_codes):
        weight = 1 / len(payload.fund_codes)
        return (
            {code: weight for code in payload.fund_codes},
            "模板回测缺少匹配股类或债类基金，已临时按所选基金等权近似。",
        )

    weights = {code: 0.0 for code in payload.fund_codes}
    for code in stock_codes:
        weights[code] = stock_ratio / len(stock_codes)
    for code in bond_codes:
        weights[code] = bond_ratio / len(bond_codes)
    return (weights, "组合模板回测按模板股债比例分配投入，并仅用于历史学习。")


def calculate_backtest_result(db: Session, payload: BacktestRequest, run_id: str | None = None) -> BacktestResult:
    snapshot_generation_id = active_snapshot_generation_id(db)
    navs_by_code, fund_types = _load_navs(db, payload, snapshot_generation_id)
    common_dates, date_series_mode = _common_nav_dates(navs_by_code)
    if not common_dates:
        return BacktestResult(
            id=run_id or f"bt_{uuid4().hex[:12]}",
            strategy_type=payload.strategy_type,
            annualized_return=0,
            max_drawdown=0,
            volatility=0,
            sharpe_ratio=0,
            total_invested=0,
            final_value=0,
            money_weighted_return=0,
            time_weighted_return=0,
            return_calculation_method="unavailable",
            snapshot_generation_id=snapshot_generation_id,
            data_warning="数据不足，无法生成有效回测结果。",
            points=[],
        )

    nav_lookup = {
        code: {nav.trade_date: nav.nav for nav in navs}
        for code, navs in navs_by_code.items()
    }
    shares = {code: 0.0 for code in payload.fund_codes}
    allocation_weights, allocation_warning = _allocation_weights(payload, fund_types)
    total_invested = 0.0
    cash_flows: list[tuple[str, float]] = []
    points: list[BacktestPoint] = []
    external_flows: list[float] = []
    benchmark_shares = 0.0
    contribution_dates, _ = _contribution_dates(
        common_dates,
        payload.strategy_type,
    )

    for trade_date in common_dates:
        should_contribute = trade_date in contribution_dates
        external_flow = payload.amount if should_contribute else 0.0
        if should_contribute:
            for code in payload.fund_codes:
                shares[code] += (payload.amount * allocation_weights[code]) / nav_lookup[code][trade_date]
            total_invested += payload.amount
            cash_flows.append((trade_date, -payload.amount))

        first_code = payload.fund_codes[0]
        if should_contribute:
            benchmark_shares += payload.amount / nav_lookup[first_code][trade_date]

        portfolio_value = sum(shares[code] * nav_lookup[code][trade_date] for code in payload.fund_codes)
        benchmark_value = benchmark_shares * nav_lookup[first_code][trade_date]

        if payload.strategy_type in {"rebalance", "template_portfolio"} and portfolio_value > 0:
            for code in payload.fund_codes:
                target_value = portfolio_value * allocation_weights[code]
                current_value = shares[code] * nav_lookup[code][trade_date]
                drift = abs(current_value - target_value) / portfolio_value * 100
                if drift > payload.rebalance_threshold:
                    shares[code] = target_value / nav_lookup[code][trade_date]

        points.append(
            BacktestPoint(
                date=trade_date,
                portfolio=round(portfolio_value, 2),
                benchmark=round(benchmark_value, 2),
            )
        )
        external_flows.append(external_flow)

    values = [point.portfolio for point in points]
    returns = [(values[index] / values[index - 1] - 1) for index in range(1, len(values)) if values[index - 1] > 0]
    cash_flows.append((common_dates[-1], values[-1]))
    annualized = _xirr(cash_flows)
    time_weighted_return = _annualized_time_weighted_return(points, external_flows)
    volatility = _volatility(returns, common_dates)
    sharpe = round((annualized / volatility), 2) if volatility else 0
    warnings: list[str] = []
    if any(len(navs_by_code[code]) < 2 for code in payload.fund_codes):
        warnings.append("部分基金净值点不足，结果仅供数据连通性验证。")
    if allocation_warning:
        warnings.append(allocation_warning)
    if (
        payload.strategy_type in {"monthly_dca", "weekly_dca", "template_portfolio"}
        and date_series_mode == "yearly"
    ):
        warnings.append(YEARLY_SAMPLE_WARNING)

    return BacktestResult(
        id=run_id or f"bt_{uuid4().hex[:12]}",
        strategy_type=payload.strategy_type,
        annualized_return=annualized,
        max_drawdown=_max_drawdown(values),
        volatility=volatility,
        sharpe_ratio=sharpe,
        total_invested=round(total_invested, 2),
        final_value=round(values[-1], 2),
        money_weighted_return=annualized,
        time_weighted_return=time_weighted_return,
        return_calculation_method=XIRR_METHOD,
        snapshot_generation_id=snapshot_generation_id,
        data_warning=" ".join(warnings) or None,
        points=points,
    )


def create_backtest_run(db: Session, payload: BacktestRequest) -> BacktestResult:
    result = calculate_backtest_result(db, payload)
    db.add(
        BacktestRun(
            id=result.id,
            user_id="local-user",
            strategy_type=payload.strategy_type,
            request_payload=payload.model_dump(),
            result_snapshot=result.model_dump(),
            annualized_return=result.annualized_return,
            max_drawdown=result.max_drawdown,
            volatility=result.volatility,
        )
    )
    db.commit()
    return result


def get_backtest_run(db: Session, backtest_id: str) -> BacktestResult | None:
    row = db.get(BacktestRun, backtest_id)
    if row is None:
        return None
    return BacktestResult.model_validate(row.result_snapshot)
