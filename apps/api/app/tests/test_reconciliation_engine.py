"""Pure-function tests for the C1 multi-source reconciliation engine.

All data is constructed in-memory; there is no network and no database IO.
"""

from datetime import date, datetime, timezone

import pytest

from app.core.reconciliation import (
    NavReconcileStats,
    ReconcilableNavPoint,
    ReconcilableProfile,
    ReconcileConfig,
    SourceSnapshot,
    adjudicate,
    benchmark_matches,
    build_summary,
    company_matches,
    custodian_matches,
    managers_overlap,
    map_fund_type,
    name_matches,
    normalize_benchmark,
    numbers_match,
    parse_scale_to_yi,
    reconcile_fund,
    reconcile_navs,
    split_managers,
)


def _nav(
    day: str,
    unit: float | None,
    *,
    acc: float | None = None,
    pct: float | None = None,
    source: str,
) -> ReconcilableNavPoint:
    return ReconcilableNavPoint(
        date=date.fromisoformat(day),
        unit_nav=unit,
        accumulated_nav=acc,
        daily_change_pct=pct,
        source=source,
    )


def _profile(
    *,
    source: str,
    name: str | None = "华夏成长混合",
    found: str | None = "2010-01-01",
    company: str | None = "华夏基金管理有限公司",
    custodian: str | None = "中国银行股份有限公司",
    managers: list[str] | None = None,
    fund_type_raw: str | None = "混合型-偏股",
    benchmark: str | None = "沪深300指数",
    scale_text: str | None = "39.38亿",
    rates: dict[str, float | None] | None = None,
) -> ReconcilableProfile:
    return ReconcilableProfile(
        code="000001",
        name=name,
        full_name=None,
        found_date=date.fromisoformat(found) if found else None,
        company=company,
        custodian=custodian,
        managers=list(managers) if managers is not None else ["张三", "李四"],
        fund_type_raw=fund_type_raw,
        benchmark=benchmark,
        scale_text=scale_text,
        rates=rates,
        source=source,
    )


def _snapshot(
    *,
    source: str,
    profile: ReconcilableProfile | None,
    navs: list[ReconcilableNavPoint],
    reachable: bool = True,
    error: str | None = None,
) -> SourceSnapshot:
    return SourceSnapshot(
        code="000001",
        source=source,
        profile=profile,
        nav_points=navs,
        fetched_at=datetime.now(timezone.utc),
        reachable=reachable,
        error=error,
    )


_PRIMARY = "eastmoney_direct"
_SECONDARY = "danjuan"


def _aligned_navs(*, secondary_unit_shift: float = 0.0) -> tuple[
    list[ReconcilableNavPoint], list[ReconcilableNavPoint]
]:
    days = ["2026-01-02", "2026-01-03", "2026-01-06"]
    units = [1.0000, 1.0100, 1.0200]
    primary = [
        _nav(days[0], units[0], acc=1.0000, pct=0.0, source=_PRIMARY),
        _nav(days[1], units[1], acc=1.0100, pct=1.0, source=_PRIMARY),
        _nav(days[2], units[2], acc=1.0200, pct=0.99, source=_PRIMARY),
    ]
    secondary = [
        _nav(days[0], units[0] + secondary_unit_shift, acc=None, pct=None, source=_SECONDARY),
        _nav(days[1], units[1] + secondary_unit_shift, acc=None, pct=None, source=_SECONDARY),
        _nav(
            days[2],
            units[2] + secondary_unit_shift,
            acc=1.0200,
            pct=0.99,
            source=_SECONDARY,
        ),
    ]
    return primary, secondary


def _consistent_pair() -> tuple[SourceSnapshot, SourceSnapshot]:
    primary_navs, secondary_navs = _aligned_navs()
    primary = _snapshot(
        source=_PRIMARY,
        profile=_profile(source=_PRIMARY, rates={"purchase": 1.2, "redeem": 0.5, "subscribe": 1.0}),
        navs=primary_navs,
    )
    secondary = _snapshot(
        source=_SECONDARY,
        profile=_profile(
            source=_SECONDARY,
            name="华夏成长混合C",
            company="华夏基金",
            custodian="中国银行",
            managers=["李四", "王五"],
            fund_type_raw="混合型-灵活配置",
            benchmark="沪深300指数",
            scale_text="40.10亿",
            rates={"purchase": 1.2, "redeem": 0.5, "subscribe": 1.0},
        ),
        navs=secondary_navs,
    )
    return primary, secondary


# --- Normalisation / mapping unit tests ------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("货币型", "money"),
        ("货币市场基金", "money"),
        ("混合型-偏股", "mixed"),
        ("混合型-灵活配置", "mixed"),
        ("偏股混合型", "mixed"),
        ("股票型", "stock"),
        ("债券型", "bond"),
        ("纯债", "bond"),
        ("指数型", "index"),
        ("ETF联接", "etf"),
        ("交易型开放式", "etf"),
        ("LOF", "lof"),
        ("QDII股票", "qdii"),
        ("FOF", "fof"),
        ("另类投资", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_map_fund_type_covers_canonical_buckets(raw: str | None, expected: str) -> None:
    assert map_fund_type(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("39.38亿", 39.38),
        ("5,000万", 0.5),
        ("1.234亿份", 1.234),
        (None, None),
        ("", None),
        ("规模未知", None),
        ("1234", None),  # bare number, no unit -> cannot determine 亿
    ],
)
def test_parse_scale_to_yi(text: str | None, expected: float | None) -> None:
    assert parse_scale_to_yi(text) == expected


def test_numbers_match_abs_and_rel_paths_and_boundary() -> None:
    # abs path: tiny delta dominated by absolute tolerance
    assert numbers_match(1.0001, 1.0002, 0.0005, 0.0001) is True
    # rel path: large scale, delta within relative tolerance
    assert numbers_match(100.0, 100.1, 0.0005, 0.002) is True
    # boundary: exactly equal to abs tolerance counts as match
    assert numbers_match(1.0, 1.0005, 0.0005, 0.0) is True
    # boundary: exactly equal to rel tolerance counts as match
    assert numbers_match(100.0, 100.2, 0.0, 0.002) is True
    # outside both tolerances
    assert numbers_match(1.0, 1.1, 0.0005, 0.002) is False
    # None inputs are incomparable
    assert numbers_match(None, 1.0, 0.0005, 0.002) is None
    assert numbers_match(1.0, None, 0.0005, 0.002) is None


def test_name_matches_ac_share_class_and_fullwidth_space() -> None:
    assert name_matches("华夏成长混合A", "华夏成长混合C") is True
    # fullwidth space + extra internal whitespace normalised
    assert name_matches("华夏成长混合　A", "华夏 成长 混合 C") is True
    assert name_matches("嘉实沪深300ETF联接A", "嘉实沪深300ETF联接C") is True
    assert name_matches("华夏成长混合", "南方中证500") is False


def test_company_and_custodian_containment() -> None:
    assert company_matches("华夏基金管理有限公司", "华夏基金") is True
    assert custodian_matches("中国银行股份有限公司", "中国银行") is True
    assert company_matches("易方达基金", "华夏基金") is False


def test_managers_split_and_overlap() -> None:
    assert split_managers("张三, 李四；王五") == {"张三", "李四", "王五"}
    assert managers_overlap(["张三", "李四"], ["李四", "赵六"]) is True
    assert managers_overlap(["张三"], ["赵六"]) is False


def test_benchmark_normalisation_ignores_punctuation() -> None:
    assert normalize_benchmark("沪深300 指数") == normalize_benchmark("沪深300指数")
    assert benchmark_matches("沪深300指数", "沪深300 指数") is True
    assert benchmark_matches("中证500", "沪深300") is False


# --- End-to-end adjudication tests -----------------------------------------


def test_all_consistent_fund_is_verified() -> None:
    primary, secondary = _consistent_pair()
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    assert report.status == "verified"
    assert report.nav_total == 3
    assert report.nav_matched == 3
    assert report.nav_missing == 0
    assert report.nav_mismatch == 0
    assert report.nav_coverage == pytest.approx(1.0)
    assert report.nav_agreement == pytest.approx(1.0)
    assert report.critical_failures == []


def test_single_unit_nav_over_tolerance_is_mismatch() -> None:
    primary, secondary = _consistent_pair()
    # bump the latest secondary point beyond tolerance
    bad = [
        _nav("2026-01-06", 1.0500, acc=1.0200, pct=0.99, source=_SECONDARY),
    ]
    secondary = _snapshot(
        source=_SECONDARY,
        profile=secondary.profile,
        navs=[secondary.nav_points[0], secondary.nav_points[1], bad[0]],
    )
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    assert report.nav_mismatch == 1
    assert report.status == "mismatch"
    # The disagreeing point must be an explicit, dated critical failure with the
    # two source values, not just an aggregate agreement dip.
    assert any(cf.startswith("nav_unit_mismatch: 1 ") for cf in report.critical_failures)
    assert len(report.nav_mismatch_points) == 1
    assert report.nav_mismatch_points[0].startswith("2026-01-06 unit_nav")
    assert "1.05" in report.nav_mismatch_points[0]


def test_low_nav_coverage_is_mismatch() -> None:
    primary_navs = [
        _nav(f"2026-01-{day:02d}", 1.0 + day * 0.001, source=_PRIMARY)
        for day in range(1, 11)
    ]
    # secondary only shares the single latest date
    secondary_navs = [_nav("2026-01-10", 1.009, source=_SECONDARY)]
    primary = _snapshot(
        source=_PRIMARY, profile=_profile(source=_PRIMARY), navs=primary_navs
    )
    secondary = _snapshot(
        source=_SECONDARY, profile=_profile(source=_SECONDARY), navs=secondary_navs
    )
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    assert report.nav_total == 10
    assert report.nav_coverage == pytest.approx(0.1)
    assert report.status == "mismatch"
    assert any(
        cf.startswith("nav_coverage_below_threshold:") for cf in report.critical_failures
    )


def test_found_date_mismatch_is_critical() -> None:
    primary, secondary = _consistent_pair()
    bad_profile = _profile(source=_SECONDARY, found="2011-02-03")
    secondary = _snapshot(source=_SECONDARY, profile=bad_profile, navs=secondary.nav_points)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    assert any(cf.startswith("found_date:") for cf in report.critical_failures)
    assert report.status == "mismatch"


def test_found_date_one_sided_is_unverified_not_critical() -> None:
    primary, secondary = _consistent_pair()
    bad_profile = _profile(source=_SECONDARY, found=None)
    secondary = _snapshot(source=_SECONDARY, profile=bad_profile, navs=secondary.nav_points)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    assert not any(cf.startswith("found_date:") for cf in report.critical_failures)
    assert report.status == "unverified"


def test_scale_disclosure_drift_is_only_warning() -> None:
    primary, secondary = _consistent_pair()
    # 39.38亿 vs 90亿 -> beyond 50% relative band, but scale_blocks defaults off
    drifted = _profile(source=_SECONDARY, scale_text="90.00亿")
    secondary = _snapshot(source=_SECONDARY, profile=drifted, navs=secondary.nav_points)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    assert report.status == "verified"
    assert any(w.startswith("scale:") for w in report.warnings)


def test_rate_missing_skips_without_failure() -> None:
    primary, secondary = _consistent_pair()
    no_rates = _profile(source=_SECONDARY, rates=None)
    secondary = _snapshot(source=_SECONDARY, profile=no_rates, navs=secondary.nav_points)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    rate_skips = [fc for fc in report.field_checks if fc.rule.endswith("_skipped") and fc.field.startswith("rate_")]
    assert rate_skips, "expected rate skip checks"
    assert report.status == "verified"
    assert report.critical_failures == []


def test_primary_missing_company_custodian_is_verified_with_warning() -> None:
    # Eastmoney FundDetail structurally lacks company/custodian; one-sided
    # disclosure must not be treated as a contradiction.
    primary, secondary = _consistent_pair()
    bare = _profile(source=_PRIMARY, company=None, custodian=None)
    primary = _snapshot(source=_PRIMARY, profile=bare, navs=primary.nav_points)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    assert report.status == "verified"
    assert any(w.startswith("company:") for w in report.warnings)
    assert any(w.startswith("custodian:") for w in report.warnings)
    assert not any(cf.startswith("company") for cf in report.critical_failures)
    assert not any(cf.startswith("custodian") for cf in report.critical_failures)


def test_one_sided_missing_managers_skips_not_blocking() -> None:
    primary, secondary = _consistent_pair()
    bare = _profile(source=_PRIMARY, managers=[])
    primary = _snapshot(source=_PRIMARY, profile=bare, navs=primary.nav_points)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    mgr = next(fc for fc in report.field_checks if fc.field == "managers")
    assert mgr.rule == "managers_skipped"
    assert mgr.match is False
    assert report.status == "verified"


def test_one_sided_or_unclassifiable_fund_type_skips() -> None:
    primary, secondary = _consistent_pair()
    # primary raw missing entirely
    bare = _profile(source=_PRIMARY, fund_type_raw=None)
    primary = _snapshot(source=_PRIMARY, profile=bare, navs=primary.nav_points)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    t = next(fc for fc in report.field_checks if fc.field == "fund_type")
    assert t.rule == "fund_type_skipped"
    assert report.status == "verified"

    # primary raw present but unclassifiable (-> other) also skips
    weird = _profile(source=_PRIMARY, fund_type_raw="另类投资")
    primary2 = _snapshot(source=_PRIMARY, profile=weird, navs=primary.nav_points)
    report2 = reconcile_fund(primary2, secondary, ReconcileConfig())
    t2 = next(fc for fc in report2.field_checks if fc.field == "fund_type")
    assert t2.rule == "fund_type_skipped"


def test_both_sides_company_empty_is_skipped_not_fake_match() -> None:
    primary, secondary = _consistent_pair()
    p_prof = _profile(source=_PRIMARY, company=None)
    s_prof = _profile(source=_SECONDARY, company="")
    primary = _snapshot(source=_PRIMARY, profile=p_prof, navs=primary.nav_points)
    secondary = _snapshot(source=_SECONDARY, profile=s_prof, navs=secondary.nav_points)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    company = next(fc for fc in report.field_checks if fc.field == "company")
    assert company.rule == "company_skipped"
    assert company.match is False
    assert report.status == "verified"


def test_company_disagreement_blocks_when_major_blocks_else_warns() -> None:
    primary, secondary = _consistent_pair()
    disagree = _profile(source=_SECONDARY, company="易方达基金管理有限公司")
    secondary = _snapshot(source=_SECONDARY, profile=disagree, navs=secondary.nav_points)
    blocked = reconcile_fund(primary, secondary, ReconcileConfig(profile_major_blocks=True))
    assert blocked.status == "mismatch"
    open_up = reconcile_fund(primary, secondary, ReconcileConfig(profile_major_blocks=False))
    assert open_up.status == "verified"
    assert any(w.startswith("company:") for w in open_up.warnings)


def test_required_source_unreachable_is_source_unavailable() -> None:
    primary, _secondary = _consistent_pair()
    down = _snapshot(
        source=_SECONDARY,
        profile=None,
        navs=[],
        reachable=False,
        error="connection timeout",
    )
    report = reconcile_fund(primary, down, ReconcileConfig(required_sources=("danjuan",)))
    assert report.status == "source_unavailable"
    assert any(cf.startswith("required_source_unavailable:") for cf in report.critical_failures)


def test_strict_vs_degraded_mismatch_status() -> None:
    primary, secondary = _consistent_pair()
    bad = _nav("2026-01-06", 1.0500, acc=1.0200, pct=0.99, source=_SECONDARY)
    secondary = _snapshot(
        source=_SECONDARY,
        profile=secondary.profile,
        navs=[secondary.nav_points[0], secondary.nav_points[1], bad],
    )
    strict_report = reconcile_fund(primary, secondary, ReconcileConfig(strict=True))
    assert strict_report.status == "mismatch"
    relaxed_report = reconcile_fund(primary, secondary, ReconcileConfig(strict=False))
    assert relaxed_report.status == "unverified"
    assert any("strict=false" in w for w in relaxed_report.warnings)


def test_misaligned_dates_count_as_missing() -> None:
    primary_navs, secondary_navs = _aligned_navs()
    # secondary drops the middle date -> one-sided gap
    secondary_navs = [secondary_navs[0], secondary_navs[2]]
    primary = _snapshot(source=_PRIMARY, profile=_profile(source=_PRIMARY), navs=primary_navs)
    secondary = _snapshot(source=_SECONDARY, profile=_profile(source=_SECONDARY), navs=secondary_navs)
    checks, stats = reconcile_navs(primary, secondary, ReconcileConfig())
    assert stats.missing == 1
    gap = next(c for c in checks if c.missing_sources)
    assert _SECONDARY in gap.missing_sources


def test_accumulated_nav_one_sided_does_not_mismatch() -> None:
    primary_navs, secondary_navs = _aligned_navs()
    # primary carries accumulated on all points; secondary only on the latest
    secondary_navs = [
        _nav("2026-01-02", 1.0000, acc=None, pct=None, source=_SECONDARY),
        _nav("2026-01-03", 1.0100, acc=None, pct=None, source=_SECONDARY),
        _nav("2026-01-06", 1.0200, acc=1.0200, pct=0.99, source=_SECONDARY),
    ]
    primary = _snapshot(source=_PRIMARY, profile=_profile(source=_PRIMARY), navs=primary_navs)
    secondary = _snapshot(source=_SECONDARY, profile=_profile(source=_SECONDARY), navs=secondary_navs)
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    assert report.nav_mismatch == 0
    assert report.status == "verified"


def test_profile_major_blocking_switch() -> None:
    primary, secondary = _consistent_pair()
    # disjoint managers -> major mismatch; blocked by default, ignored when off
    disjoint = _profile(source=_SECONDARY, managers=["赵六", "钱七"])
    secondary = _snapshot(source=_SECONDARY, profile=disjoint, navs=secondary.nav_points)
    blocked = reconcile_fund(primary, secondary, ReconcileConfig(profile_major_blocks=True))
    assert blocked.status == "mismatch"
    open_up = reconcile_fund(primary, secondary, ReconcileConfig(profile_major_blocks=False))
    # with major not blocking and no other hard failure -> unverified (skipped none,
    # but a non-blocking major disagreement leaves the fund unverifiable)
    assert open_up.status in {"unverified", "verified"}


def test_adjudicate_is_pure_and_returns_new_report() -> None:
    primary, secondary = _consistent_pair()
    report = reconcile_fund(primary, secondary, ReconcileConfig())
    again = adjudicate(report, ReconcileConfig())
    assert again is not report
    assert again.status == report.status


def test_build_summary_picks_worst_status() -> None:
    primary, secondary = _consistent_pair()
    good = reconcile_fund(primary, secondary, ReconcileConfig())
    bad_secondary = _snapshot(
        source=_SECONDARY, profile=None, navs=[], reachable=False, error="down"
    )
    bad = reconcile_fund(primary, bad_secondary, ReconcileConfig(required_sources=("danjuan",)))
    summary = build_summary([good, bad], ReconcileConfig())
    assert summary.overall_status == "source_unavailable"
    assert summary.generated_at.tzinfo is not None
    assert "required_sources" in summary.config


def test_reconcile_navs_returns_stats_shape() -> None:
    primary, secondary = _consistent_pair()
    checks, stats = reconcile_navs(primary, secondary, ReconcileConfig())
    assert isinstance(stats, NavReconcileStats)
    assert len(checks) == 3
    assert checks[0].unit_match is True
    assert checks[0].missing_sources == []
