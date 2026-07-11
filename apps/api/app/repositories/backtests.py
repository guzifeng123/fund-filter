from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BacktestRun, Fund, FundNav
from app.repositories.portfolios import list_templates
from app.schemas.backtest import BacktestPoint, BacktestRequest, BacktestResult


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


def _volatility(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return _percent(variance**0.5)


def _annualized_return(final_value: float, total_invested: float, periods: int) -> float:
    if total_invested <= 0 or periods <= 1:
        return 0
    years = max(1, periods - 1)
    return _percent((final_value / total_invested) ** (1 / years) - 1)


def _load_navs(db: Session, payload: BacktestRequest) -> dict[str, list[FundNav]]:
    stmt = (
        select(FundNav)
        .where(
            FundNav.fund_code.in_(payload.fund_codes),
            FundNav.trade_date >= payload.start,
            FundNav.trade_date <= payload.end,
        )
        .order_by(FundNav.fund_code, FundNav.trade_date)
    )
    grouped: dict[str, list[FundNav]] = {code: [] for code in payload.fund_codes}
    for row in db.scalars(stmt).all():
        grouped[row.fund_code].append(row)
    return grouped


def _template_ratios(payload: BacktestRequest) -> tuple[float, float]:
    template = next((item for item in list_templates() if item.id == payload.template_key), None)
    if template is None:
        return (0.5, 0.5)
    return (template.stock_ratio / 100, template.bond_ratio / 100)


def _allocation_weights(db: Session, payload: BacktestRequest) -> tuple[dict[str, float], str | None]:
    if payload.strategy_type != "template_portfolio":
        weight = 1 / len(payload.fund_codes)
        return ({code: weight for code in payload.fund_codes}, None)

    funds = db.scalars(select(Fund).where(Fund.code.in_(payload.fund_codes))).all()
    fund_types = {fund.code: fund.fund_type for fund in funds}
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
    navs_by_code = _load_navs(db, payload)
    common_dates = sorted(set.intersection(*(set(nav.trade_date for nav in navs) for navs in navs_by_code.values())))
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
            data_warning="数据不足，无法生成有效回测结果。",
            points=[],
        )

    nav_lookup = {
        code: {nav.trade_date: nav.nav for nav in navs}
        for code, navs in navs_by_code.items()
    }
    shares = {code: 0.0 for code in payload.fund_codes}
    allocation_weights, allocation_warning = _allocation_weights(db, payload)
    total_invested = 0.0
    points: list[BacktestPoint] = []
    benchmark_shares = 0.0
    benchmark_invested = 0.0

    for index, trade_date in enumerate(common_dates):
        if payload.strategy_type in {"monthly_dca", "weekly_dca", "template_portfolio"}:
            for code in payload.fund_codes:
                shares[code] += (payload.amount * allocation_weights[code]) / nav_lookup[code][trade_date]
            total_invested += payload.amount
        elif index == 0:
            for code in payload.fund_codes:
                shares[code] += (payload.amount * allocation_weights[code]) / nav_lookup[code][trade_date]
            total_invested += payload.amount

        first_code = payload.fund_codes[0]
        benchmark_shares += payload.amount / nav_lookup[first_code][trade_date]
        benchmark_invested += payload.amount

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

    values = [point.portfolio for point in points]
    returns = [(values[index] / values[index - 1] - 1) for index in range(1, len(values)) if values[index - 1] > 0]
    annualized = _annualized_return(values[-1], total_invested, len(points))
    volatility = _volatility(returns)
    sharpe = round((annualized / volatility), 2) if volatility else 0
    warning = None
    if any(len(navs_by_code[code]) < 2 for code in payload.fund_codes):
        warning = "部分基金净值点不足，结果仅供数据连通性验证。"
    if allocation_warning:
        warning = allocation_warning
    if payload.strategy_type in {"monthly_dca", "weekly_dca"}:
        warning = warning or "当前 sample 数据为年度净值点，定投频率会按可用净值点近似执行。"
    if payload.strategy_type == "template_portfolio" and warning == allocation_warning:
        warning = f"{allocation_warning} 当前 sample 数据为年度净值点，模板回测会按可用净值点近似执行。"

    return BacktestResult(
        id=run_id or f"bt_{uuid4().hex[:12]}",
        strategy_type=payload.strategy_type,
        annualized_return=annualized,
        max_drawdown=_max_drawdown(values),
        volatility=volatility,
        sharpe_ratio=sharpe,
        total_invested=round(total_invested, 2),
        final_value=round(values[-1], 2),
        data_warning=warning,
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
