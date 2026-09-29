import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from app.core.config import settings
from app.core.nav_dates import nav_trade_date_precision
from app.data_sources.profiles import get_public_fund_data_profile
from app.schemas.funds import FundDetail, NavPoint


@dataclass
class HttpJsonCacheEntry:
    body: str
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class HttpJsonResponse:
    body: str | None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class PublicHttpJsonFundDataSource:
    name = "public_http_json"

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        cache_dir: str | Path | None = None,
        min_interval_seconds: float | None = None,
        batch_size: int | None = None,
        max_pages: int | None = None,
        profile_name: str | None = None,
        proxy_urls: Sequence[str] | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.public_fund_data_base_url).strip()
        configured_profile = profile_name if profile_name is not None else settings.public_fund_data_profile
        self.profile = get_public_fund_data_profile(configured_profile)
        self.timeout_seconds = timeout_seconds or settings.public_fund_data_timeout_seconds
        configured_cache_dir = cache_dir if cache_dir is not None else settings.public_fund_data_cache_dir
        self.cache_dir = Path(configured_cache_dir) if configured_cache_dir else None
        self.min_interval_seconds = (
            min_interval_seconds
            if min_interval_seconds is not None
            else settings.public_fund_data_min_interval_seconds
        )
        self.batch_size = batch_size or settings.public_fund_data_batch_size
        self.max_pages = max_pages if max_pages is not None else settings.public_fund_data_max_pages
        self.proxy_urls = tuple(proxy_urls) if proxy_urls is not None else settings.public_fund_data_proxy_urls
        self._proxy_index = 0
        if self.max_pages < 1:
            raise ValueError("PUBLIC_FUND_DATA_MAX_PAGES must be at least 1")
        self._memory_cache: dict[str, HttpJsonCacheEntry] = {}
        self._last_request_at = 0.0
        if not self.base_url:
            raise ValueError("PUBLIC_FUND_DATA_BASE_URL is required for public_http_json data source")
        if not self.base_url.endswith("/"):
            self.base_url += "/"
        self._base_origin = self._url_origin(
            self.base_url,
            context="PUBLIC_FUND_DATA_BASE_URL",
        )

    def fetch_snapshot(self) -> list[FundDetail]:
        return self._load_funds(include_remote_navs=True)

    def fetch_fund_profiles(self) -> list[FundDetail]:
        return self._load_funds(include_remote_navs=False)

    def fetch_fund_navs(self) -> list[FundDetail]:
        return self._load_funds(include_remote_navs=True)

    def fetch_risk_levels(self) -> dict[str, str]:
        return {fund.code: fund.risk_level for fund in self.fetch_fund_profiles()}

    def _load_funds(self, include_remote_navs: bool) -> list[FundDetail]:
        payloads = self._read_json_pages("funds.json")
        funds: list[FundDetail] = []
        for rows in payloads:
            if not isinstance(rows, list):
                raise ValueError("public_http_json funds.json must be a list or an object with a funds list")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"public_http_json funds.json item {len(funds)} must be an object")
                fund = self._parse_fund(row, len(funds))
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
            try:
                nav = NavPoint(**self.profile.normalize_nav(row))
            except Exception as exc:
                raise ValueError(
                    f"public_http_json navs/{code}.json item {index} is invalid: {exc}"
                ) from exc
            if nav_trade_date_precision(nav.trade_date) != "day":
                raise ValueError(
                    f"public_http_json navs/{code}.json item {index} is invalid: "
                    "real NAV trade_date must use ISO YYYY-MM-DD"
                )
            navs.append(nav)
        navs.sort(key=lambda item: item.trade_date)
        return navs

    def _parse_fund(self, row: dict[str, Any], index: int) -> FundDetail:
        payload = self.profile.normalize_fund(row)
        payload["source"] = self.profile.source
        payload["provider_profile"] = self.profile.name
        payload["upstream_provider"] = self.profile.upstream_provider
        payload.setdefault("navs", [])
        payload.setdefault("ai_summary", "")
        payload.setdefault("metric_explanations", [])
        payload["navs"] = [
            self.profile.normalize_nav(nav) if isinstance(nav, dict) else nav
            for nav in payload["navs"]
        ]
        try:
            fund = FundDetail(**payload)
        except Exception as exc:
            raise ValueError(f"public_http_json funds.json item {index} is invalid: {exc}") from exc
        legacy_date = next(
            (
                nav.trade_date
                for nav in fund.navs
                if nav_trade_date_precision(nav.trade_date) != "day"
            ),
            None,
        )
        if legacy_date is not None:
            raise ValueError(
                f"public_http_json funds.json item {index} is invalid: "
                f"real NAV trade_date must use ISO YYYY-MM-DD; got {legacy_date!r}"
            )
        fund.navs.sort(key=lambda item: item.trade_date)
        return fund

    def _read_json_pages(self, initial_path: str) -> list[list[Any]]:
        pages: list[list[Any]] = []
        visited_urls: set[str] = set()
        next_path: str | None = initial_path
        while next_path:
            page_url = self._resolve_same_origin_url(
                next_path,
                context="public_http_json pagination",
            )
            if page_url in visited_urls:
                raise ValueError(
                    "public_http_json pagination loop detected at "
                    f"{page_url!r}; check the upstream next/next_path/nextPath value"
                )
            if len(pages) >= self.max_pages:
                raise ValueError(
                    "public_http_json pagination exceeded "
                    f"PUBLIC_FUND_DATA_MAX_PAGES={self.max_pages} before {page_url!r}; "
                    "check the upstream pagination metadata or raise the configured limit"
                )
            visited_urls.add(page_url)
            payload = self._read_json(next_path)
            rows = payload["funds"] if isinstance(payload, dict) and "funds" in payload else payload
            pages.append(rows)
            next_path = self._next_page_path(payload)
        return pages

    @staticmethod
    def _url_origin(url: str, *, context: str) -> tuple[str, str, int]:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ValueError(f"{context} URL is invalid: {url!r}") from exc

        scheme = parsed.scheme.lower()
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if scheme not in {"http", "https"} or not hostname:
            raise ValueError(f"{context} URL must use http:// or https:// and include a host: {url!r}")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(f"{context} URL must not include user information: {url!r}")

        effective_port = port if port is not None else (443 if scheme == "https" else 80)
        return (scheme, hostname, effective_port)

    def _resolve_same_origin_url(self, path: str, *, context: str) -> str:
        resolved_url = urljoin(self.base_url, path)
        origin = self._url_origin(resolved_url, context=context)
        if origin != self._base_origin:
            raise ValueError(
                f"{context} URL must stay on the PUBLIC_FUND_DATA_BASE_URL origin; "
                f"got {resolved_url!r}"
            )

        parsed = urlsplit(resolved_url)
        scheme, hostname, effective_port = origin
        canonical_host = f"[{hostname}]" if ":" in hostname else hostname
        default_port = 443 if scheme == "https" else 80
        port_suffix = "" if effective_port == default_port else f":{effective_port}"
        return urlunsplit(
            (
                scheme,
                f"{canonical_host}{port_suffix}",
                parsed.path or "/",
                parsed.query,
                "",
            )
        )

    def _read_json(self, path: str) -> Any:
        response = self._read_http_json(path)
        cache_entry = self._load_cache_entry(path)
        if response.not_modified:
            if cache_entry is None:
                raise RuntimeError(f"public_http_json received 304 for {path} without a cached response")
            return json.loads(cache_entry.body)
        if response.body is None:
            raise RuntimeError(f"public_http_json response for {path} did not include a body")
        self._store_cache_entry(
            path,
            HttpJsonCacheEntry(
                body=response.body,
                etag=response.etag or (cache_entry.etag if cache_entry else None),
                last_modified=response.last_modified or (cache_entry.last_modified if cache_entry else None),
            ),
        )
        return json.loads(response.body)

    def _read_http_json(self, path: str) -> HttpJsonResponse:
        url = self._resolve_same_origin_url(path, context="public_http_json request")
        cache_entry = self._load_cache_entry(path)
        headers = {"Accept": "application/json", "User-Agent": "fund-analysis-workspace/0.1"}
        if cache_entry and cache_entry.etag:
            headers["If-None-Match"] = cache_entry.etag
        if cache_entry and cache_entry.last_modified:
            headers["If-Modified-Since"] = cache_entry.last_modified
        request = Request(url, headers=headers)
        try:
            self._throttle()
            with self._open_url(request) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return HttpJsonResponse(
                    body=response.read().decode(charset),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
        except HTTPError as exc:
            if exc.code == 304:
                return HttpJsonResponse(body=None, not_modified=True)
            raise RuntimeError(f"failed to read public fund data from {url}: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"failed to read public fund data from {url}: {exc}") from exc

    def _open_url(self, request: Request) -> Any:
        if not self.proxy_urls:
            return urlopen(request, timeout=self.timeout_seconds)
        proxy_url = self.proxy_urls[self._proxy_index % len(self.proxy_urls)]
        self._proxy_index += 1
        opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
        return opener.open(request, timeout=self.timeout_seconds)

    def _next_page_path(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        next_path = payload.get("next") or payload.get("next_path") or payload.get("nextPath")
        if isinstance(next_path, str) and next_path.strip():
            return next_path.strip()
        page = payload.get("page")
        total_pages = payload.get("total_pages") or payload.get("totalPages")
        if isinstance(page, int) and isinstance(total_pages, int) and page < total_pages:
            return f"funds.json?page={page + 1}&page_size={self.batch_size}"
        return None

    def _load_cache_entry(self, path: str) -> HttpJsonCacheEntry | None:
        if path in self._memory_cache:
            return self._memory_cache[path]
        if not self.cache_dir:
            return None
        cache_path = self._cache_path(path)
        meta_path = cache_path.with_suffix(cache_path.suffix + ".meta.json")
        if not cache_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        entry = HttpJsonCacheEntry(
            body=cache_path.read_text(encoding="utf-8"),
            etag=meta.get("etag"),
            last_modified=meta.get("last_modified"),
        )
        self._memory_cache[path] = entry
        return entry

    def _store_cache_entry(self, path: str, entry: HttpJsonCacheEntry) -> None:
        self._memory_cache[path] = entry
        if not self.cache_dir:
            return
        cache_path = self._cache_path(path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(entry.body, encoding="utf-8")
        cache_path.with_suffix(cache_path.suffix + ".meta.json").write_text(
            json.dumps({"etag": entry.etag, "last_modified": entry.last_modified}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _cache_path(self, path: str) -> Path:
        assert self.cache_dir is not None
        safe_name = path.replace("\\", "/").replace("/", "__").replace("?", "__").replace("&", "__")
        return self.cache_dir / f"{safe_name}.json"

    def _throttle(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self._last_request_at = time.monotonic()
