"""Multi-source cross-check reconciliation engine (C1).

This module is a *pure function + dataclass* contract layer. It performs **no
HTTP calls and no database IO**: every input is a fully materialised
:class:`SourceSnapshot` and every output is an immutable dataclass that C3
(write-gate + API) persists or serialises. C2 (danjuan / sina clients) is
responsible for fetching snapshots and mapping upstream payloads into the
:class:`ReconcilableProfile` / :class:`ReconcilableNavPoint` shapes declared
here; C3 is responsible for the strict/fail-closed write decision that sits on
top of the :class:`FundReconciliationReport.status` this engine produces.

The engine only *describes* agreement/disagreement; it never raises business
exceptions and never mutates inputs.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from app.core.config import Settings

# --- Canonical fund-type bucket -------------------------------------------
# The closed set every source must collapse into. C2 maps eastmoney ``type``
# and danjuan ``type_desc`` through :func:`map_fund_type`; C3 compares the
# canonical string, never the raw upstream label.
CANONICAL_FUND_TYPES = frozenset(
    {
        "stock",
        "mixed",
        "bond",
        "index",
        "qdii",
        "fof",
        "money",
        "etf",
        "lof",
        "other",
    }
)

# Fee comparison tolerance (fees are disclosed as percentage points, e.g.
# 0.15). Either-side missing value skips the check rather than failing it.
_FEE_ABS_TOL = 0.1
_FEE_REL_TOL = 0.1

# Fund scale moves between disclosure periods; "same order of magnitude" uses a
# generous relative tolerance. scale_blocks defaults to False so a scale delta
# is only a warning unless explicitly hardened.
_SCALE_REL_TOL = 0.5

# Canonical rate keys shared by both sources. C2 maps:
#   purchase = declare_rate (申购), redeem = withdraw_rate (赎回),
#   subscribe = subscribe_rate (认购).
_RATE_KEYS = ("purchase", "redeem", "subscribe")

_SHARE_CLASS_LETTERS = frozenset({"A", "B", "C", "E", "I", "R"})

_WHITESPACE_RE = re.compile(r"\s+")
_MANAGER_SPLIT_RE = re.compile(r"[\s,，、;；]+")
_BENCHMARK_PUNCT_RE = re.compile(r"[\s　.,，。;；:：、\-—–()（）\[\]【】'\"“”/]+")
_TRAILING_SHARE_CLASS_RE = re.compile(r"[\s\-—–]*([A-Z])$")


# --- Contract dataclasses ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReconcilableNavPoint:
    """One traded NAV point from a single source."""

    date: date
    unit_nav: float | None
    accumulated_nav: float | None
    daily_change_pct: float | None
    source: str


@dataclass(frozen=True, slots=True)
class ReconcilableProfile:
    """Static fund metadata normalised from a single source.

    ``rates`` uses the canonical keys :data:`_RATE_KEYS`
    (purchase / redeem / subscribe); a value of ``None`` means the source did
    not disclose that fee (the check skips rather than failing).
    """

    code: str
    name: str | None
    full_name: str | None
    found_date: date | None
    company: str | None
    custodian: str | None
    managers: list[str]
    fund_type_raw: str | None
    benchmark: str | None
    scale_text: str | None
    rates: dict[str, float | None] | None
    source: str


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """A fully materialised pull of one fund from one upstream source."""

    code: str
    source: str
    profile: ReconcilableProfile | None
    nav_points: list[ReconcilableNavPoint]
    fetched_at: datetime | None
    reachable: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class FieldCheck:
    """Result of comparing one profile field across two sources."""

    field: str
    severity: Literal["critical", "major", "minor"]
    values: dict[str, object]
    match: bool
    rule: str
    detail: str


@dataclass(frozen=True, slots=True)
class NavPointCheck:
    """Per-date NAV agreement. ``missing_sources`` lists sources absent on the
    date (a one-sided / misaligned date); accumulated / pct are ``None`` when
    that series was not comparable across both sources."""

    date: date
    values: dict[str, float | None]
    unit_match: bool
    accumulated_match: bool | None
    pct_match: bool | None
    missing_sources: list[str]


@dataclass(frozen=True, slots=True)
class FundReconciliationReport:
    code: str
    display_name: str
    status: Literal["verified", "mismatch", "unverified", "source_unavailable"]
    sources: list[str]
    field_checks: list[FieldCheck]
    nav_total: int
    nav_matched: int
    nav_missing: int
    nav_mismatch: int
    nav_coverage: float
    nav_agreement: float
    critical_failures: list[str]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    funds: list[FundReconciliationReport]
    overall_status: str
    generated_at: datetime
    config: dict[str, object]


@dataclass(frozen=True, slots=True)
class NavReconcileStats:
    """Aggregated NAV cross-check counters returned alongside per-point checks."""

    total: int
    matched: int
    missing: int
    mismatch: int
    coverage: float
    agreement: float


# --- Reconciliation configuration ------------------------------------------


@dataclass(frozen=True, slots=True)
class ReconcileConfig:
    """Tolerances / switches that drive the pure reconciliation logic.

    IO-oriented settings (timeouts, intervals, sina batch, report dir,
    apply-to-source allow-list, enabled flag) live on :class:`Settings` and are
    consumed by C2/C3; only the values below affect engine decisions.
    """

    nav_abs_tolerance: float = 0.0005
    nav_rel_tolerance: float = 0.002
    acc_nav_abs_tolerance: float = 0.005
    daily_pct_tolerance: float = 0.3
    min_nav_coverage: float = 0.99
    profile_major_blocks: bool = True
    scale_blocks: bool = False
    rates_blocks: bool = False
    strict: bool = True
    required_sources: tuple[str, ...] = ("danjuan",)

    @classmethod
    def from_settings(cls, settings: Settings) -> ReconcileConfig:
        return cls(
            nav_abs_tolerance=settings.fund_reconcile_nav_abs_tolerance,
            nav_rel_tolerance=settings.fund_reconcile_nav_rel_tolerance,
            acc_nav_abs_tolerance=settings.fund_reconcile_acc_nav_abs_tolerance,
            daily_pct_tolerance=settings.fund_reconcile_daily_pct_tolerance,
            min_nav_coverage=settings.fund_reconcile_min_nav_coverage,
            profile_major_blocks=settings.fund_reconcile_profile_major_blocks,
            scale_blocks=settings.fund_reconcile_scale_blocks,
            rates_blocks=settings.fund_reconcile_rates_blocks,
            strict=settings.fund_reconcile_strict,
            required_sources=tuple(settings.fund_reconcile_required_sources),
        )

    def as_public_dict(self) -> dict[str, object]:
        return {
            "nav_abs_tolerance": self.nav_abs_tolerance,
            "nav_rel_tolerance": self.nav_rel_tolerance,
            "acc_nav_abs_tolerance": self.acc_nav_abs_tolerance,
            "daily_pct_tolerance": self.daily_pct_tolerance,
            "min_nav_coverage": self.min_nav_coverage,
            "profile_major_blocks": self.profile_major_blocks,
            "scale_blocks": self.scale_blocks,
            "rates_blocks": self.rates_blocks,
            "strict": self.strict,
            "required_sources": list(self.required_sources),
        }


# --- Normalisation / mapping pure functions --------------------------------


def normalize_text(text: str | None) -> str:
    """Trim, unify fullwidth/nbsp to ASCII space, and collapse whitespace."""
    if not text:
        return ""
    unified = text.replace("　", " ").replace(" ", " ")
    return _WHITESPACE_RE.sub(" ", unified).strip()


def normalize_name(name: str | None) -> str:
    """Whitespace-normalise a fund display name (original share class kept)."""
    return normalize_text(name)


def _base_name(normalized: str) -> str:
    """Strip a trailing share-class letter (A/C/...) for containment compare."""
    match = _TRAILING_SHARE_CLASS_RE.search(normalized)
    if match and match.group(1) in _SHARE_CLASS_LETTERS:
        return normalized[: match.start()].strip()
    return normalized.strip()


def name_matches(a: str | None, b: str | None) -> bool:
    """Names agree if normalised-equal, or containment after share-class strip."""
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    base_a = _base_name(na)
    base_b = _base_name(nb)
    if not base_a or not base_b:
        return False
    compact_a = base_a.replace(" ", "")
    compact_b = base_b.replace(" ", "")
    return compact_a in compact_b or compact_b in compact_a


def _contains(a: str | None, b: str | None) -> bool:
    """Containment comparison for company / custodian names."""
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def company_matches(a: str | None, b: str | None) -> bool:
    return _contains(a, b)


def custodian_matches(a: str | None, b: str | None) -> bool:
    return _contains(a, b)


def split_managers(text: str | None) -> set[str]:
    """Split a manager string on whitespace / commas / Chinese separators."""
    if not text:
        return set()
    return {part.strip() for part in _MANAGER_SPLIT_RE.split(text) if part.strip()}


def managers_overlap(a: list[str], b: list[str]) -> bool:
    sa: set[str] = set()
    for entry in a:
        sa |= split_managers(entry)
    sb: set[str] = set()
    for entry in b:
        sb |= split_managers(entry)
    return bool(sa & sb)


def parse_scale_to_yi(text: str | None) -> float | None:
    """Parse a disclosed fund scale into 亿元.

    ``"39.38亿" -> 39.38``, ``"5000万" -> 0.5``. Bare numbers without a
    recognised unit, ``None``, empty or abnormal text all return ``None`` and
    never raise.
    """
    if not text:
        return None
    compact = text.replace(",", "").strip()
    if not compact:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", compact)
    if not match:
        return None
    try:
        value = float(match.group(0))
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if "亿" in compact:
        return value
    if "万" in compact:
        return value / 10_000.0
    return None


def normalize_benchmark(text: str | None) -> str:
    """Strip whitespace and punctuation for benchmark equality/containment."""
    if not text:
        return ""
    return _BENCHMARK_PUNCT_RE.sub("", text).upper()


def benchmark_matches(a: str | None, b: str | None) -> bool:
    na = normalize_benchmark(a)
    nb = normalize_benchmark(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def map_fund_type(*raw_types: str | None) -> str:
    """Map eastmoney ``type`` / danjuan ``type_desc`` to a canonical bucket.

    Structural type flags (money / qdii / fof / etf / lof) take precedence;
    broad asset class is matched next; anything unrecognised is ``other``.
    """
    text = " ".join(part for part in raw_types if part).lower()
    if not text.strip():
        return "other"
    if "货币" in text:
        return "money"
    if "qdii" in text:
        return "qdii"
    if "fof" in text:
        return "fof"
    if "lof" in text:
        return "lof"
    if "etf" in text or "交易型开放式" in text:
        return "etf"
    if "指数" in text or "被动" in text:
        return "index"
    if "债券" in text or "纯债" in text or "固收" in text or "转债" in text:
        return "bond"
    # Broad-asset order matters: "混合型-偏股" / "偏股混合型" are hybrid funds,
    # so the 混合 bucket is tested before the pure-stock bucket.
    if "混合" in text or "灵活配置" in text or "平衡" in text:
        return "mixed"
    if "股票" in text or "偏股" in text:
        return "stock"
    return "other"


def numbers_match(
    a: float | None,
    b: float | None,
    abs_tol: float,
    rel_tol: float,
) -> bool | None:
    """|a-b| <= abs_tol OR |a-b| <= rel_tol*max(|a|,|b|).

    Returns ``None`` when either input is ``None`` (incomparable; the caller
    decides skip / missing). Boundary values exactly equal to a tolerance are
    considered matching (``<=``).
    """
    if a is None or b is None:
        return None
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    scale = max(abs(a), abs(b))
    if scale > 0 and diff <= rel_tol * scale:
        return True
    return False


# --- NAV reconciliation -----------------------------------------------------


def _nav_index(points: list[ReconcilableNavPoint]) -> dict[date, ReconcilableNavPoint]:
    indexed: dict[date, ReconcilableNavPoint] = {}
    for point in points:
        indexed[point.date] = point
    return indexed


def reconcile_navs(
    primary: SourceSnapshot,
    secondary: SourceSnapshot,
    cfg: ReconcileConfig,
) -> tuple[list[NavPointCheck], NavReconcileStats]:
    """Inner-join NAV series by date and compare unit / accumulated / pct.

    Coverage = shared dates / primary dates. Agreement = matching unit-nav
    points / shared dates. Dates present on only one side are recorded as
    ``missing`` (and listed in ``missing_sources``); accumulated NAV is only
    compared when both sides carry it (danjuan history often lacks it).
    """
    primary_index = _nav_index(primary.nav_points)
    secondary_index = _nav_index(secondary.nav_points)
    primary_dates = set(primary_index)
    secondary_dates = set(secondary_index)
    common_dates = primary_dates & secondary_dates

    checks: list[NavPointCheck] = []
    matched = 0
    mismatch = 0
    missing = 0

    for day in sorted(primary_dates | secondary_dates):
        p = primary_index.get(day)
        s = secondary_index.get(day)
        values: dict[str, float | None] = {
            primary.source: p.unit_nav if p is not None else None,
            secondary.source: s.unit_nav if s is not None else None,
        }
        missing_sources: list[str] = []
        if p is None:
            missing_sources.append(primary.source)
        if s is None:
            missing_sources.append(secondary.source)

        if p is not None and s is not None:
            if p.unit_nav is not None and s.unit_nav is not None:
                unit_ok = bool(
                    numbers_match(
                        p.unit_nav,
                        s.unit_nav,
                        cfg.nav_abs_tolerance,
                        cfg.nav_rel_tolerance,
                    )
                )
            else:
                unit_ok = False
            acc_ok = None
            if p.accumulated_nav is not None and s.accumulated_nav is not None:
                acc_ok = bool(
                    numbers_match(
                        p.accumulated_nav,
                        s.accumulated_nav,
                        cfg.acc_nav_abs_tolerance,
                        0.0,
                    )
                )
            pct_ok = None
            if p.daily_change_pct is not None and s.daily_change_pct is not None:
                pct_ok = bool(
                    numbers_match(
                        p.daily_change_pct,
                        s.daily_change_pct,
                        cfg.daily_pct_tolerance,
                        0.0,
                    )
                )
            if p.unit_nav is not None and s.unit_nav is not None:
                if unit_ok:
                    matched += 1
                else:
                    mismatch += 1
        else:
            unit_ok = False
            acc_ok = None
            pct_ok = None
            missing += 1

        checks.append(
            NavPointCheck(
                date=day,
                values=values,
                unit_match=unit_ok,
                accumulated_match=acc_ok,
                pct_match=pct_ok,
                missing_sources=missing_sources,
            )
        )

    total = len(primary.nav_points)
    coverage = (len(common_dates) / total) if total else 1.0
    agreement = (matched / len(common_dates)) if common_dates else 1.0
    stats = NavReconcileStats(
        total=total,
        matched=matched,
        missing=missing,
        mismatch=mismatch,
        coverage=coverage,
        agreement=agreement,
    )
    return checks, stats


# --- Profile reconciliation -------------------------------------------------


def _field_check(
    field: str,
    severity: Literal["critical", "major", "minor"],
    rule: str,
    match: bool,
    primary_value: object,
    secondary_value: object,
    detail: str,
) -> FieldCheck:
    return FieldCheck(
        field=field,
        severity=severity,
        values={"primary": primary_value, "secondary": secondary_value},
        match=match,
        rule=rule,
        detail=detail,
    )


def reconcile_profile(
    primary: SourceSnapshot,
    secondary: SourceSnapshot,
    cfg: ReconcileConfig,
) -> list[FieldCheck]:
    """Compare static profile fields. Missing data yields a ``*_skipped`` check
    (treated as unverifiable, not a contradiction); active disagreements are
    rated critical / major / minor per the contract."""
    del cfg  # tolerances for profile fields are fixed contract constants
    checks: list[FieldCheck] = []
    p = primary.profile
    s = secondary.profile

    # --- found_date (critical; strict equality; either side None -> skip) ---
    if p is None or s is None or p.found_date is None or s.found_date is None:
        checks.append(
            _field_check(
                "found_date",
                "critical",
                "found_date_skipped",
                False,
                None if p is None else p.found_date,
                None if s is None else s.found_date,
                "found_date unavailable from at least one source; cannot verify",
            )
        )
    elif p.found_date == s.found_date:
        checks.append(
            _field_check(
                "found_date",
                "critical",
                "found_date_exact",
                True,
                p.found_date.isoformat(),
                s.found_date.isoformat(),
                "found dates match exactly",
            )
        )
    else:
        checks.append(
            _field_check(
                "found_date",
                "critical",
                "found_date_mismatch",
                False,
                p.found_date.isoformat(),
                s.found_date.isoformat(),
                f"found date differs: {p.found_date.isoformat()} vs {s.found_date.isoformat()}",
            )
        )

    # --- major fields -------------------------------------------------------
    if p is None or s is None:
        for name, rule in (
            ("name", "name_skipped"),
            ("company", "company_skipped"),
            ("custodian", "custodian_skipped"),
            ("managers", "managers_skipped"),
            ("fund_type", "fund_type_skipped"),
        ):
            checks.append(
                _field_check(name, "major", rule, False, "", "", "profile unavailable; cannot verify")
            )
    else:
        name_ok = name_matches(p.name, s.name)
        checks.append(
            _field_check(
                "name",
                "major",
                "name_match" if name_ok else "name_mismatch",
                name_ok,
                p.name,
                s.name,
                "names agree" if name_ok else f"name differs: {p.name!r} vs {s.name!r}",
            )
        )
        company_ok = company_matches(p.company, s.company)
        checks.append(
            _field_check(
                "company",
                "major",
                "company_match" if company_ok else "company_mismatch",
                company_ok,
                p.company,
                s.company,
                "company agrees" if company_ok else f"company differs: {p.company!r} vs {s.company!r}",
            )
        )
        custodian_ok = custodian_matches(p.custodian, s.custodian)
        checks.append(
            _field_check(
                "custodian",
                "major",
                "custodian_match" if custodian_ok else "custodian_mismatch",
                custodian_ok,
                p.custodian,
                s.custodian,
                "custodian agrees" if custodian_ok else f"custodian differs: {p.custodian!r} vs {s.custodian!r}",
            )
        )
        managers_ok = managers_overlap(p.managers, s.managers)
        checks.append(
            _field_check(
                "managers",
                "major",
                "managers_overlap" if managers_ok else "managers_disjoint",
                managers_ok,
                list(p.managers),
                list(s.managers),
                "managers overlap" if managers_ok else "manager sets are disjoint",
            )
        )
        p_type = map_fund_type(p.fund_type_raw)
        s_type = map_fund_type(s.fund_type_raw)
        type_ok = p_type == s_type
        checks.append(
            _field_check(
                "fund_type",
                "major",
                "fund_type_match" if type_ok else "fund_type_mismatch",
                type_ok,
                p_type,
                s_type,
                f"canonical type {p_type} vs {s_type}",
            )
        )

        # --- minor fields ---------------------------------------------------
        bench_ok = benchmark_matches(p.benchmark, s.benchmark)
        checks.append(
            _field_check(
                "benchmark",
                "minor",
                "benchmark_match" if bench_ok else "benchmark_mismatch",
                bench_ok,
                p.benchmark,
                s.benchmark,
                "benchmark agrees" if bench_ok else "benchmark differs (warning only)",
            )
        )

        p_scale = parse_scale_to_yi(p.scale_text)
        s_scale = parse_scale_to_yi(s.scale_text)
        if p_scale is None or s_scale is None:
            checks.append(
                _field_check(
                    "scale",
                    "minor",
                    "scale_skipped",
                    False,
                    p.scale_text,
                    s.scale_text,
                    "scale undisclosed by at least one source (warning only)",
                )
            )
        else:
            scale_ok = bool(numbers_match(p_scale, s_scale, 0.0, _SCALE_REL_TOL))
            checks.append(
                _field_check(
                    "scale",
                    "minor",
                    "scale_match" if scale_ok else "scale_mismatch",
                    scale_ok,
                    p_scale,
                    s_scale,
                    f"scale {p_scale:.2f}亿 vs {s_scale:.2f}亿 (disclosure drift, warning only)",
                )
            )

        for rate_key in _RATE_KEYS:
            p_rate = None if p.rates is None else p.rates.get(rate_key)
            s_rate = None if s.rates is None else s.rates.get(rate_key)
            if p_rate is None or s_rate is None:
                checks.append(
                    _field_check(
                        f"rate_{rate_key}",
                        "minor",
                        f"rate_{rate_key}_skipped",
                        False,
                        p_rate,
                        s_rate,
                        f"{rate_key} fee undisclosed by at least one source (skip)",
                    )
                )
            else:
                rate_ok = bool(
                    numbers_match(p_rate, s_rate, _FEE_ABS_TOL, _FEE_REL_TOL)
                )
                checks.append(
                    _field_check(
                        f"rate_{rate_key}",
                        "minor",
                        f"rate_{rate_key}_match" if rate_ok else f"rate_{rate_key}_mismatch",
                        rate_ok,
                        p_rate,
                        s_rate,
                        f"{rate_key} fee {p_rate} vs {s_rate}",
                    )
                )

    return checks


# --- Adjudication -----------------------------------------------------------


def _required_unreachable(
    primary: SourceSnapshot,
    secondary: SourceSnapshot,
    cfg: ReconcileConfig,
) -> list[str]:
    present = {primary.source, secondary.source}
    reachable = {
        snap.source for snap in (primary, secondary) if snap.reachable
    }
    return [
        source
        for source in cfg.required_sources
        if source in present and source not in reachable
    ]


def reconcile_fund(
    primary: SourceSnapshot,
    secondary: SourceSnapshot,
    cfg: ReconcileConfig,
) -> FundReconciliationReport:
    """Compose NAV + profile cross-check into an adjudicated report."""
    sources: list[str] = []
    for snap in (primary, secondary):
        if snap.source not in sources:
            sources.append(snap.source)

    nav_checks, stats = reconcile_navs(primary, secondary, cfg)
    del nav_checks  # per-point checks are surfaced via C3 if needed
    field_checks = reconcile_profile(primary, secondary, cfg)

    critical_failures: list[str] = []
    warnings: list[str] = []

    for snap in (primary, secondary):
        if not snap.reachable and snap.error:
            warnings.append(f"source {snap.source} error: {snap.error}")

    for check in field_checks:
        if check.rule.endswith("_skipped"):
            continue
        if check.severity == "critical" and not check.match:
            critical_failures.append(f"{check.field}: {check.detail}")
        elif check.severity == "minor" and not check.match:
            warnings.append(f"{check.field}: {check.detail}")

    for source in _required_unreachable(primary, secondary, cfg):
        critical_failures.append(f"required_source_unavailable: {source}")

    display_name = primary.code
    if primary.profile is not None and primary.profile.name:
        display_name = primary.profile.name

    report = FundReconciliationReport(
        code=primary.code,
        display_name=display_name,
        status="unverified",  # placeholder; adjudicate below
        sources=sources,
        field_checks=list(field_checks),
        nav_total=stats.total,
        nav_matched=stats.matched,
        nav_missing=stats.missing,
        nav_mismatch=stats.mismatch,
        nav_coverage=stats.coverage,
        nav_agreement=stats.agreement,
        critical_failures=list(critical_failures),
        warnings=list(warnings),
    )
    return adjudicate(report, cfg)


def adjudicate(
    report: FundReconciliationReport,
    cfg: ReconcileConfig,
) -> FundReconciliationReport:
    """Derive ``status`` from an assembled report. Pure: no IO, no exceptions.

    - required source unreachable            -> source_unavailable
    - critical failure / nav coverage gap / unit-nav mismatch /
      (blocking major mismatch)             -> mismatch (strict) or
                                              unverified (degraded)
    - skipped critical/major data            -> unverified
    - only minor findings / clean            -> verified (warnings kept)
    """
    warnings = list(report.warnings)

    source_unavailable = any(
        cf.startswith("required_source_unavailable:") for cf in report.critical_failures
    )
    hard_critical = [
        cf
        for cf in report.critical_failures
        if not cf.startswith("required_source_unavailable:")
    ]
    major_fails = [
        fc
        for fc in report.field_checks
        if fc.severity == "major" and not fc.match and not fc.rule.endswith("_skipped")
    ]
    scale_fails = [
        fc
        for fc in report.field_checks
        if fc.field == "scale" and not fc.match and not fc.rule.endswith("_skipped")
    ]
    rate_fails = [
        fc
        for fc in report.field_checks
        if fc.field.startswith("rate_") and not fc.match and not fc.rule.endswith("_skipped")
    ]
    skipped_core = [
        fc
        for fc in report.field_checks
        if fc.rule.endswith("_skipped") and fc.severity in {"critical", "major"}
    ]

    if source_unavailable:
        status: Literal["verified", "mismatch", "unverified", "source_unavailable"] = (
            "source_unavailable"
        )
    else:
        hard = bool(hard_critical)
        if report.nav_coverage < cfg.min_nav_coverage:
            hard = True
        if report.nav_mismatch > 0:
            hard = True
        if cfg.profile_major_blocks and major_fails:
            hard = True
        if cfg.scale_blocks and scale_fails:
            hard = True
        if cfg.rates_blocks and rate_fails:
            hard = True

        if hard:
            if cfg.strict:
                status = "mismatch"
            else:
                status = "unverified"
                warnings.append(
                    "strict=false: cross-check mismatch downgraded to unverified"
                )
        elif skipped_core:
            status = "unverified"
        else:
            status = "verified"

    return FundReconciliationReport(
        code=report.code,
        display_name=report.display_name,
        status=status,
        sources=list(report.sources),
        field_checks=list(report.field_checks),
        nav_total=report.nav_total,
        nav_matched=report.nav_matched,
        nav_missing=report.nav_missing,
        nav_mismatch=report.nav_mismatch,
        nav_coverage=report.nav_coverage,
        nav_agreement=report.nav_agreement,
        critical_failures=list(report.critical_failures),
        warnings=warnings,
    )


# --- Summary ----------------------------------------------------------------


_STATUS_SEVERITY = {
    "verified": 0,
    "unverified": 1,
    "mismatch": 2,
    "source_unavailable": 3,
}


def build_summary(
    reports: list[FundReconciliationReport],
    cfg: ReconcileConfig,
) -> ReconciliationSummary:
    """Roll per-fund reports up; overall_status is the most severe fund."""
    overall = "verified"
    worst = _STATUS_SEVERITY["verified"]
    for report in reports:
        rank = _STATUS_SEVERITY.get(report.status, 0)
        if rank > worst:
            worst = rank
            overall = report.status
    return ReconciliationSummary(
        funds=list(reports),
        overall_status=overall,
        generated_at=datetime.now(timezone.utc),
        config=cfg.as_public_dict(),
    )


# Re-export a stable import surface C2/C3 can rely on.
__all__ = [
    "CANONICAL_FUND_TYPES",
    "NavPointCheck",
    "NavReconcileStats",
    "FieldCheck",
    "FundReconciliationReport",
    "ReconcilableNavPoint",
    "ReconcilableProfile",
    "ReconcileConfig",
    "ReconciliationSummary",
    "SourceSnapshot",
    "adjudicate",
    "benchmark_matches",
    "build_summary",
    "company_matches",
    "custodian_matches",
    "managers_overlap",
    "map_fund_type",
    "name_matches",
    "normalize_benchmark",
    "normalize_name",
    "normalize_text",
    "numbers_match",
    "parse_scale_to_yi",
    "reconcile_fund",
    "reconcile_navs",
    "reconcile_profile",
    "split_managers",
]
