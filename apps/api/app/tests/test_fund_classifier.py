"""D0: tests for app/core/fund_classifier.py (pure routing)."""

from __future__ import annotations

from datetime import date

from app.core.fund_classifier import classify
from app.data_sources.universe import UniverseFund


def _fund(
    code: str,
    name: str,
    type_major: str,
    type_detail: str = "",
    *,
    has_3y: bool | None = True,
) -> UniverseFund:
    return UniverseFund(
        code=code,
        name=name,
        type_major=type_major,
        type_detail=type_detail,
        has_3y=has_3y,
        scale=None,
        unit_nav=None,
        acc_nav=None,
        nav_date=date(2026, 9, 30),
    )


def test_money_market_is_special_caliber() -> None:
    decision = classify(_fund("000198", "华夏现金增利货币A", "货币型", "货币型-普通货币"))
    assert decision.route == "special_caliber"
    assert decision.reason == "special_caliber"
    assert decision.detail["special_kind"] == "money_market"


def test_on_exchange_etf_is_special_caliber() -> None:
    decision = classify(_fund("510300", "华泰柏瑞沪深300ETF", "指数型", "指数型-股票"))
    assert decision.route == "special_caliber"
    assert decision.detail["special_kind"] == "on_exchange_etf"


def test_otc_etf_feeder_fund_is_supported_index() -> None:
    decision = classify(_fund("110020", "易方达沪深300ETF联接A", "指数型", "指数型-股票"))
    assert decision.route == "supported"
    assert decision.reason == "eligible_open_end"


def test_otc_lof_is_treated_as_open_end() -> None:
    decision = classify(
        _fund("161725", "招商中证白酒指数(LOF)A", "指数型", "指数型-股票")
    )
    assert decision.route == "supported"
    assert decision.reason == "eligible_open_end"


def test_qdii_commodity_and_reits_are_special_caliber() -> None:
    commodity = classify(_fund("000001", "某大宗商品QDII", "QDII", "QDII-商品"))
    assert commodity.route == "special_caliber"
    assert commodity.detail["special_kind"] == "qdii_commodity_or_reits"

    reits = classify(_fund("000002", "某QDIIREITs", "QDII", "QDII-REITs"))
    assert reits.route == "special_caliber"
    assert reits.detail["special_kind"] == "qdii_commodity_or_reits"


def test_ordinary_qdii_is_supported() -> None:
    decision = classify(
        _fund("000834", "上投摩根新兴动力股票QDII", "QDII", "QDII-普通股票")
    )
    assert decision.route == "supported"


def test_fof_is_supported() -> None:
    decision = classify(_fund("005221", "嘉实领航资产配置FOFA", "FOF", "FOF-均衡型"))
    assert decision.route == "supported"


def test_bond_is_supported() -> None:
    decision = classify(_fund("110007", "易方达稳健收益债券B", "债券型", "债券型-长债"))
    assert decision.route == "supported"


def test_asset_management_name_is_unsupported_secondary() -> None:
    decision = classify(
        _fund("999999", "某券商资管集合计划", "混合型", "混合型-灵活")
    )
    assert decision.route == "unsupported_secondary"
    assert decision.reason == "broker_asset_management"


def test_short_history_is_new_short_history_by_default() -> None:
    young = _fund("005221", "年轻FOF", "FOF", "FOF-稳健型", has_3y=False)
    decision = classify(young)
    assert decision.route == "new_short_history"
    assert decision.reason == "history_lt_3y"


def test_short_history_flips_to_supported_when_flagged() -> None:
    young = _fund("005221", "年轻FOF", "FOF", "FOF-稳健型", has_3y=False)
    decision = classify(young, include_short_history=True)
    assert decision.route == "supported"
    assert decision.reason == "short_history_included"


def test_unknown_type_is_unsupported_secondary() -> None:
    decision = classify(_fund("000001", "未知类型基金", "未知", ""))
    assert decision.route == "unsupported_secondary"
    assert decision.reason == "unknown_type"


def test_rank_uncovered_unknown_age_is_supported_deferred() -> None:
    # F-phase: has_3y=None (rank-uncovered, e.g. 050025) must NOT be written off
    # as new_short_history; it becomes a supported candidate and the precise
    # >=3y check is deferred to the runner.
    deferred = _fund("050025", "博时标普500ETF联接(QDII)A", "QDII", "QDII-普通股票", has_3y=None)
    decision = classify(deferred)
    assert decision.route == "supported"
    assert decision.reason == "eligible_open_end"
    assert decision.detail["age_evidence"] == "unknown"
    # ...even when include_short_history is off.
    off = classify(deferred, include_short_history=False)
    assert off.route == "supported"


def test_hk_mutual_recognition_is_special() -> None:
    decision = classify(_fund("000001", "某港股互认基金", "混合型", "混合型-灵活", has_3y=None))
    assert decision.route == "special_caliber"
    assert decision.detail["special_kind"] == "hk_mutual_recognition"


def test_backend_and_forex_shares_stay_supported_candidates() -> None:
    # Backend / USD shares are independent sellable codes: kept as supported, not
    # dropped or merged. The danjuan gate still skips them later if unsellable.
    backend = _fund("000002", "华夏成长混合(后端)", "混合型", "混合型-灵活", has_3y=None)
    assert classify(backend).route == "supported"
    forex = _fund("000044", "嘉实美国成长股票美元现汇", "QDII", "QDII-普通股票", has_3y=None)
    assert classify(forex).route == "supported"


def test_on_exchange_etf_body_special_but_feeder_and_lof_kept() -> None:
    body = _fund("510300", "华泰柏瑞沪深300ETF", "指数型", "指数型-股票", has_3y=None)
    assert classify(body).detail["special_kind"] == "on_exchange_etf"
    feeder = _fund("000051", "华夏沪深300ETF联接A", "指数型", "指数型-股票", has_3y=None)
    assert classify(feeder).route == "supported"
    lof = _fund("161725", "招商中证白酒指数(LOF)A", "指数型", "指数型-股票", has_3y=None)
    assert classify(lof).route == "supported"
