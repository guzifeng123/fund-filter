import json
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from app.core.config import settings
from app.schemas.funds import FundDetail, NavPoint


class PublicHttpJsonFundDataSource:
    name = "public_http_json"

    def __init__(self, base_url: str | None = None, timeout_seconds: int | None = None) -> None:
        self.base_url = (base_url if base_url is not None else settings.public_fund_data_base_url).strip()
        self.timeout_seconds = timeout_seconds or settings.public_fund_data_timeout_seconds
        if not self.base_url:
            raise ValueError("PUBLIC_FUND_DATA_BASE_URL is required for public_http_json data source")
        if not self.base_url.endswith("/"):
            self.base_url += "/"

    def fetch_fund_profiles(self) -> list[FundDetail]:
        return self._load_funds(include_remote_navs=False)

    def fetch_fund_navs(self) -> list[FundDetail]:
        return self._load_funds(include_remote_navs=True)

    def fetch_risk_levels(self) -> dict[str, str]:
        return {fund.code: fund.risk_level for fund in self.fetch_fund_profiles()}

    def _load_funds(self, include_remote_navs: bool) -> list[FundDetail]:
        payload = self._read_json("funds.json")
        rows = payload["funds"] if isinstance(payload, dict) and "funds" in payload else payload
        if not isinstance(rows, list):
            raise ValueError("public_http_json funds.json must be a list or an object with a funds list")

        funds: list[FundDetail] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"public_http_json funds.json item {index} must be an object")
            fund = self._parse_fund(row, index)
            if include_remote_navs and not fund.navs:
                fund.navs = self._load_navs(fund.code)
            funds.append(fund)
        return funds

    def _load_navs(self, code: str) -> list[NavPoint]:
        payload = self._read_json(f"navs/{code}.json")
        rows = payload["navs"] if isinstance(payload, dict) and "navs" in payload else payload
        if not isinstance(rows, list):
            raise ValueError(f"public_http_json navs/{code}.json must be a list or an object with a navs list")
        navs: list[NavPoint] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"public_http_json navs/{code}.json item {index} must be an object")
            navs.append(NavPoint(**row))
        navs.sort(key=lambda item: item.trade_date)
        return navs

    def _parse_fund(self, row: dict[str, Any], index: int) -> FundDetail:
        payload = {**row, "source": "public_http_json"}
        payload.setdefault("navs", [])
        payload.setdefault("ai_summary", "")
        payload.setdefault("metric_explanations", [])
        try:
            fund = FundDetail(**payload)
        except Exception as exc:
            raise ValueError(f"public_http_json funds.json item {index} is invalid: {exc}") from exc
        fund.navs.sort(key=lambda item: item.trade_date)
        return fund

    def _read_json(self, path: str) -> Any:
        url = urljoin(self.base_url, path)
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "fund-analysis-workspace/0.1"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(response.read().decode(charset))
        except Exception as exc:
            raise RuntimeError(f"failed to read public fund data from {url}: {exc}") from exc
