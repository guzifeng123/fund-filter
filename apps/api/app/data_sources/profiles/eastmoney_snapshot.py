import hashlib
import json
import math
import re
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.data_sources.profiles.eastmoney_pingzhong import (
    PINGZHONG_URL,
    PingzhongMoneyFundError,
    parse_pingzhong_navs,
)
from app.data_sources.profiles.normalized import NormalizedV1Profile
from app.schemas.funds import (
    FeeSummary,
    FundDetail,
    FundType,
    ManagerProfile,
    MetricExplanation,
    NavPoint,
    RiskLevel,
)

BASE_INFO_URL = "https://fundmobapi.eastmoney.com/FundMApi/FundBaseTypeInformation.ashx"
NAV_URL = "https://api.fund.eastmoney.com/f10/lsjz"
PROFILE_URL = "https://fundf10.eastmoney.com/jbgk_{code}.html"
MANAGER_URL = "https://fundf10.eastmoney.com/jjjl_{code}.html"
PROFILE_NAME = "eastmoney_snapshot_v1"
PROFILE_SOURCE = "eastmoney_snapshot"
UPSTREAM_PROVIDER = "eastmoney"

FUND_TYPE_PREFIXES: dict[str, FundType] = {
    "股票型": "stock",
    # OTC index feeder funds (ETF-联接, ordinary 指数型 incl. overseas QDII index
    # funds) are equity portfolios and collapse into the ``stock`` bucket; the
    # reconciliation engine re-derives a finer index/qdii bucket from the
    # secondary type_desc. This only maps the existing mobile FTYPE field onto the
    # canonical 4-bucket schema -- it does not replace any 资料 endpoint.
    "指数型": "stock",
    "混合型": "mixed",
    "债券型": "bond",
    # Fund-of-funds are multi-asset; the canonical schema has no dedicated FOF
    # bucket, so they map to the balanced ``mixed`` bucket.
    "FOF": "mixed",
    "货币型": "money",
}
RISK_LEVELS: dict[str, RiskLevel] = {
    "1": "R1",
    "2": "R2",
    "3": "R3",
    "4": "R4",
    "5": "R5",
}


class EastmoneySnapshotV1Profile(NormalizedV1Profile):
    """Read the normalized, auditable mirror produced by EastmoneySnapshotBuilder."""

    name = PROFILE_NAME
    source = PROFILE_SOURCE
    upstream_provider: str | None = UPSTREAM_PROVIDER

    def normalize_fund(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = super().normalize_fund(row)
        declared_profile = normalized.get("provider_profile")
        if declared_profile not in (None, "", self.name):
            raise ValueError(
                "eastmoney_snapshot_v1 mirror declares an incompatible provider_profile: "
                f"{declared_profile!r}"
            )
        return normalized


@dataclass(frozen=True)
class EastmoneyRawSnapshot:
    base_info: dict[str, Any]
    nav_rows: list[dict[str, Any]]
    profile_html: str
    manager_html: str
    # Diagnostics-only watermark recording which NAV path produced ``nav_rows``
    # (pingzhong fast path / legacy lsjz fallback / QDII top-up). Carries no data
    # contract; downstream consumers ignore it.
    nav_trace: str | None = None


def _required(mapping: dict[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise ValueError(f"eastmoney snapshot is missing required field {key}")
    return value


def _parse_percent(text: str, label: str) -> float:
    match = re.search(rf"{re.escape(label)}</th>\s*<td>\s*([0-9.]+)%", text)
    if match is None:
        raise ValueError(f"eastmoney profile page is missing {label}")
    return float(match.group(1))


def _parse_manager_start(text: str) -> date:
    match = re.search(r"<tr><td>(\d{4}-\d{2}-\d{2})</td><td>至今</td>", text)
    if match is None:
        raise ValueError("eastmoney manager page is missing the current manager start date")
    return date.fromisoformat(match.group(1))


def _parse_inception_date(text: str) -> date:
    """Parse the fund establishment (contract-effective) date from the F10 page.

    The mobile ``FundBaseTypeInformation`` payload only exposes ``ISSBDATE``,
    which is the public offer *start* date (发行日期), not the fund's inception
    date. The F10 overview publishes the real establishment date both in the
    header badge (``成立日期：<span>YYYY-MM-DD</span>``) and in the info table
    (``成立日期/规模`` = ``YYYY年MM月DD日 / ...``). Cross-source checks compare
    against this date (danjuan ``found_date`` matches it exactly).
    """
    header = re.search(r"成立日期[：:]\s*<span>\s*(\d{4}-\d{2}-\d{2})\s*</span>", text)
    if header is not None:
        return date.fromisoformat(header.group(1))
    table = re.search(
        r"成立日期/规模</th>\s*<td>\s*(\d{4})年(\d{1,2})月(\d{1,2})日",
        text,
    )
    if table is not None:
        return date(int(table.group(1)), int(table.group(2)), int(table.group(3)))
    raise ValueError("eastmoney profile page is missing the establishment date (成立日期)")



def _normalize_fund_type(value: str) -> FundType:
    for prefix, normalized in FUND_TYPE_PREFIXES.items():
        if value.startswith(prefix):
            return normalized
    raise ValueError(f"unsupported eastmoney fund type: {value}")


def _merge_nav_rows(
    *row_sets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge lsjz/pingzhong-style rows by ``FSRQ``, later sets winning on overlap.

    Rows are keyed by trade date; a row from a later argument replaces an earlier
    one for the same date (so the fresher lsjz top-up overrides the bundle). The
    result is sorted ascending by date, with no duplicate rows and no fabricated
    gaps. Mirrors the on-disk incremental merge in ``eastmoney_direct``.
    """
    by_date: dict[str, dict[str, Any]] = {}
    for row_set in row_sets:
        for row in row_set:
            trade_date = row.get("FSRQ")
            if isinstance(trade_date, str) and trade_date:
                by_date[trade_date] = row
    return sorted(by_date.values(), key=lambda row: str(row.get("FSRQ", "")))


def _normalize_navs(rows: list[dict[str, Any]]) -> list[NavPoint]:
    navs = [
        NavPoint(
            trade_date=str(_required(row, "FSRQ")),
            nav=float(_required(row, "DWJZ")),
            accumulated_nav=float(_required(row, "LJJZ")),
        )
        for row in rows
    ]
    navs.sort(key=lambda item: item.trade_date)
    if len(navs) < 2:
        raise ValueError("eastmoney snapshot requires at least two NAV points")
    return navs


def _annualized_return(navs: list[NavPoint], years: int) -> float:
    latest_date = date.fromisoformat(navs[-1].trade_date)
    try:
        target_date = latest_date.replace(year=latest_date.year - years)
    except ValueError:
        target_date = latest_date.replace(year=latest_date.year - years, day=28)
    points_on_or_before = [point for point in navs if date.fromisoformat(point.trade_date) <= target_date]
    points_after = [point for point in navs if date.fromisoformat(point.trade_date) > target_date]
    if not points_on_or_before and not points_after:
        raise ValueError(f"eastmoney snapshot does not cover the required {years}-year return window")
    start = points_on_or_before[-1] if points_on_or_before else points_after[0]
    start_date = date.fromisoformat(start.trade_date)
    elapsed_years = (latest_date - start_date).days / 365.2425
    if elapsed_years < years - 0.08:
        raise ValueError(f"eastmoney snapshot has only {elapsed_years:.2f} years for the {years}-year return")
    if start.accumulated_nav <= 0 or navs[-1].accumulated_nav <= 0:
        raise ValueError("eastmoney accumulated NAV must be positive")
    return float(
        ((navs[-1].accumulated_nav / start.accumulated_nav) ** (1 / elapsed_years) - 1)
        * 100
    )


def _max_drawdown(navs: list[NavPoint]) -> float:
    peak = navs[0].accumulated_nav
    drawdown = 0.0
    for point in navs:
        peak = max(peak, point.accumulated_nav)
        drawdown = min(drawdown, point.accumulated_nav / peak - 1)
    return drawdown * 100


def _sharpe_ratio(navs: list[NavPoint]) -> float:
    returns = [
        current.accumulated_nav / previous.accumulated_nav - 1
        for previous, current in zip(navs, navs[1:])
        if previous.accumulated_nav > 0
    ]
    if len(returns) < 2:
        raise ValueError("eastmoney snapshot requires at least three NAV points for Sharpe ratio")
    volatility = statistics.stdev(returns)
    if volatility == 0:
        return 0.0
    return statistics.mean(returns) / volatility * math.sqrt(250)


def build_fund_snapshot(raw: EastmoneyRawSnapshot, generated_at: datetime) -> FundDetail:
    base = raw.base_info
    navs = _normalize_navs(raw.nav_rows)
    latest_nav_date = date.fromisoformat(navs[-1].trade_date)
    manager_start = _parse_manager_start(raw.manager_html)
    rank = float(_required(base, "RANKY"))
    rank_count = float(_required(base, "YSC"))
    if rank_count <= 0:
        raise ValueError("eastmoney YSC must be positive")
    risk_level = RISK_LEVELS.get(str(_required(base, "RISKLEVEL")))
    if risk_level is None:
        raise ValueError(f"unsupported eastmoney risk level: {base['RISKLEVEL']}")
    management_fee = _parse_percent(raw.profile_html, "管理费率")
    custody_fee = _parse_percent(raw.profile_html, "托管费率")
    # Real fund establishment date from the F10 overview; ISSBDATE in the mobile
    # base payload is only the offer-start date and must not be used here.
    inception = _parse_inception_date(raw.profile_html)
    annualized_return_3y = round(_annualized_return(navs, 3), 4)
    annualized_return_5y = round(_annualized_return(navs, 5), 4)
    max_drawdown = round(_max_drawdown(navs), 4)
    sharpe_ratio = round(_sharpe_ratio(navs), 4)
    rank_percentile = round(rank / rank_count * 100, 4)
    manager_years = max(0, int((latest_nav_date - manager_start).days / 365.2425))

    fund_type_detail = str(_required(base, "FTYPE"))
    fund = FundDetail(
        code=str(_required(base, "FCODE")),
        name=str(_required(base, "SHORTNAME")),
        fund_type=_normalize_fund_type(fund_type_detail),
        risk_level=risk_level,
        manager_name=str(_required(base, "JJJL")),
        inception_date=str(inception),
        fund_size_billion=round(float(_required(base, "ENDNAV")) / 100_000_000, 4),
        management_fee=management_fee,
        custody_fee=custody_fee,
        annualized_return_3y=annualized_return_3y,
        annualized_return_5y=annualized_return_5y,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        category_rank_percentile=rank_percentile,
        manager_years=manager_years,
        source=PROFILE_SOURCE,
        provider_profile=PROFILE_NAME,
        upstream_provider=UPSTREAM_PROVIDER,
        # This field is the upstream data watermark, not the local pull time.
        # The local sync completion is recorded separately in job_runs.finished_at.
        data_updated_at=datetime.combine(
            latest_nav_date,
            datetime.min.time(),
            tzinfo=timezone(timedelta(hours=8)),
        ).isoformat(),
        navs=navs,
        ai_summary="公开站点历史快照，仅用于数据分析与功能验证；站点字段和历史表现不构成投资建议。",
        fee_summary=FeeSummary(
            management_fee=management_fee,
            custody_fee=custody_fee,
            total_fee=round(management_fee + custody_fee, 4),
            explanation="年管理费率与托管费率来自公开 F10 基金概况页快照。",
        ),
        manager_profile=ManagerProfile(
            name=str(_required(base, "JJJL")),
            years=manager_years,
            inception_date=str(inception),
            explanation="管理年限按公开基金经理页当前任期起始日至最新净值日的完整年数计算。",
        ),
        metric_explanations=[
            MetricExplanation(
                key="annualized_return_3y",
                label="3年年化",
                value=f"{annualized_return_3y:.2f}%",
                explanation="按累计净值和实际天数计算 CAGR；历史表现不预示未来收益。",
            ),
            MetricExplanation(
                key="annualized_return_5y",
                label="5年年化",
                value=f"{annualized_return_5y:.2f}%",
                explanation="目标日取当日或之前最近交易日，覆盖不足时拒绝生成。",
            ),
            MetricExplanation(
                key="max_drawdown",
                label="最大回撤",
                value=f"{max_drawdown:.2f}%",
                explanation="按镜像净值窗口内历史峰值计算，不代表未来最大损失。",
            ),
            MetricExplanation(
                key="sharpe_ratio",
                label="夏普比率",
                value=f"{sharpe_ratio:.2f}",
                explanation="按日收益、无风险利率 0 和每年 250 个交易日年化计算。",
            ),
            MetricExplanation(
                key="category_rank_percentile",
                label="同类排名",
                value=f"前 {rank_percentile:.2f}%",
                explanation="使用上游近1年同类排名除以同类总数，数值越小越靠前。",
            ),
        ],
    )
    # Carry the raw upstream FTYPE detail as a non-serialized internal attribute so
    # reconciliation collapses primary/secondary types through the same C1 mapping;
    # the stored 4-bucket fund_type above is unchanged.
    fund._fund_type_raw = fund_type_detail
    return fund


class EastmoneySnapshotBuilder:
    def __init__(self, timeout_seconds: int = 15, min_interval_seconds: float = 0.5) -> None:
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._last_request_at = 0.0

    def build(self, fund_codes: list[str], generated_at: datetime | None = None) -> list[FundDetail]:
        snapshot_time = generated_at or datetime.now(timezone.utc)
        return [build_fund_snapshot(self.fetch_raw(code, snapshot_time.date()), snapshot_time) for code in fund_codes]

    def fetch_raw(
        self,
        code: str,
        as_of: date,
        *,
        start_date: date | None = None,
    ) -> EastmoneyRawSnapshot:
        normalized_code = code.strip()
        if not re.fullmatch(r"\d{6}", normalized_code):
            raise ValueError(f"fund code must contain exactly six digits: {code}")
        base_payload = self._read_json(
            BASE_INFO_URL,
            {
                "FCODE": normalized_code,
                "deviceid": "fund-analysis-mirror",
                "plat": "Iphone",
                "product": "EFund",
                "version": "6.3.8",
            },
        )
        base_info = base_payload.get("Datas")
        if not isinstance(base_info, dict):
            raise ValueError("eastmoney base information response is missing Datas")
        # Default window keeps the historical 5-year+ lookback used by scripts and
        # existing tests; callers (for example the incremental eastmoney_direct
        # adapter) may pass a later start_date to only fetch newly published pages.
        effective_start = (
            start_date if start_date is not None else as_of - timedelta(days=5 * 366 + 45)
        )
        nav_rows, nav_trace = self._read_nav_rows(normalized_code, effective_start, as_of)
        return EastmoneyRawSnapshot(
            base_info=base_info,
            nav_rows=nav_rows,
            profile_html=self._read_text(PROFILE_URL.format(code=normalized_code)),
            manager_html=self._read_text(MANAGER_URL.format(code=normalized_code)),
            nav_trace=nav_trace,
        )

    def write_mirror(self, output_dir: Path, funds: list[FundDetail], generated_at: datetime) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        nav_dir = output_dir / "navs"
        nav_dir.mkdir(parents=True, exist_ok=True)
        profiles: list[dict[str, Any]] = []
        file_hashes: dict[str, str] = {}
        for fund in funds:
            payload = fund.model_dump(mode="json")
            navs = payload.pop("navs")
            payload["provider_profile"] = PROFILE_NAME
            payload["upstream_provider"] = UPSTREAM_PROVIDER
            profiles.append(payload)
            nav_path = nav_dir / f"{fund.code}.json"
            self._write_json(nav_path, {"navs": navs})
            file_hashes[nav_path.relative_to(output_dir).as_posix()] = self._sha256(nav_path)
        funds_path = output_dir / "funds.json"
        self._write_json(funds_path, {"funds": profiles})
        file_hashes["funds.json"] = self._sha256(funds_path)
        manifest_path = output_dir / "manifest.json"
        self._write_json(
            manifest_path,
            {
                "schema_version": 1,
                "provider_profile": PROFILE_NAME,
                "upstream_provider": UPSTREAM_PROVIDER,
                "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
                "fund_codes": [fund.code for fund in funds],
                "source_urls": [BASE_INFO_URL, NAV_URL, PROFILE_URL, MANAGER_URL],
                "files": file_hashes,
                "boundary": "Public page snapshot; not an official stable API contract. Retain old database data on failure.",
            },
        )
        return manifest_path

    def _read_nav_rows(
        self,
        code: str,
        start_date: date,
        end_date: date,
    ) -> tuple[list[dict[str, Any]], str]:
        """Return NAV rows for ``[start_date, end_date]`` via the fast path.

        Preferred path: one pingzhongdata bundle gives the full history in a single
        request, then a tiny lsjz page tops up the latest 1-2 trading days (QDII
        overseas NAVs lag the bundle by 1-2 sessions; A-share/mixed/bond bundles are
        already current, in which case the top-up only re-confirms the last point).

        Fallback path: any pingzhong transport/parse failure degrades to the legacy
        paginated lsjz pull. Money-fund shape errors propagate (they must never reach
        this pipeline).
        """
        end_iso = end_date.isoformat()
        start_iso = start_date.isoformat()
        try:
            js_text = self._read_text(PINGZHONG_URL.format(code=code))
            pz_rows = parse_pingzhong_navs(js_text, code)
        except PingzhongMoneyFundError:
            raise
        except Exception as exc:  # network, timeout, or malformed bundle -> lsjz
            return self._read_all_navs(code, start_date, end_date), (
                f"pingzhong_fallback:{type(exc).__name__}"
            )

        window_rows = [
            row for row in pz_rows if start_iso <= str(row.get("FSRQ", "")) <= end_iso
        ]
        if not window_rows:
            # Bundle parsed cleanly but has nothing inside the requested window
            # (e.g. a fund whose history starts after start_date); fall back so the
            # paginated endpoint applies its own start/end semantics.
            return self._read_all_navs(code, start_date, end_date), "pingzhong_empty_window"

        # Top up the newest points: overseas (QDII) bundles lag lsjz/sina by 1-2
        # sessions. Pull a small lsjz window starting at the bundle's last trade date
        # (one page of 20 covers weeks of sessions) and merge by trade date, letting
        # the fresher lsjz row win on overlap. Never fabricate when the top-up fails;
        # the bundle series is already complete and contiguous up to its own last date.
        pz_last = date.fromisoformat(str(window_rows[-1]["FSRQ"]))
        try:
            recent_rows = self._read_all_navs(code, pz_last, end_date)
        except Exception:
            recent_rows = []
        merged = _merge_nav_rows(window_rows, recent_rows)
        return merged, "pingzhong+lsjz_topup"

    def _read_all_navs(self, code: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_index = 1
        # The endpoint currently caps historical NAV pages at 20 and returns Data=null for oversized pages.
        page_size = 20
        while True:
            payload = self._read_json(
                NAV_URL,
                {
                    "fundCode": code,
                    "pageIndex": page_index,
                    "pageSize": page_size,
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                },
            )
            data = payload.get("Data")
            page_rows = data.get("LSJZList") if isinstance(data, dict) else None
            if not isinstance(page_rows, list):
                raise ValueError("eastmoney NAV response is missing Data.LSJZList")
            rows.extend(row for row in page_rows if isinstance(row, dict))
            total_count = int(payload.get("TotalCount") or len(rows))
            if len(rows) >= total_count or not page_rows:
                return rows
            page_index += 1

    def _read_json(self, url: str, query: dict[str, str | int]) -> dict[str, Any]:
        payload = json.loads(self._read_text(f"{url}?{urlencode(query)}"))
        if not isinstance(payload, dict):
            raise ValueError(f"eastmoney response from {url} must be an object")
        error_code = payload.get("ErrCode")
        if error_code not in (None, 0):
            raise ValueError(f"eastmoney response from {url} failed: {error_code} {payload.get('ErrMsg', '')}")
        return payload

    def _read_text(self, url: str) -> str:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        request = Request(
            url,
            headers={
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "Referer": "https://fund.eastmoney.com/",
                "User-Agent": "fund-analysis-workspace/0.1 snapshot-validator",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            self._last_request_at = time.monotonic()
            return str(
                response.read().decode(response.headers.get_content_charset() or "utf-8-sig")
            )

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
