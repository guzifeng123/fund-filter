import pytest
from urllib.request import Request

from app.core.config import settings as config_settings
from app.data_sources import get_fund_data_source
from app.data_sources.public_http_json import HttpJsonResponse, PublicHttpJsonFundDataSource


class StubPublicHttpJsonFundDataSource(PublicHttpJsonFundDataSource):
    def __init__(
        self,
        payloads: dict[str, object],
        *,
        base_url: str = "https://public.example/funds/",
        batch_size: int | None = None,
        max_pages: int | None = None,
        profile_name: str | None = None,
    ) -> None:
        self.payloads = payloads
        self.requests: list[str] = []
        super().__init__(
            base_url=base_url,
            timeout_seconds=1,
            batch_size=batch_size,
            max_pages=max_pages,
            profile_name=profile_name,
        )

    def _read_json(self, path: str) -> object:
        self.requests.append(path)
        return self.payloads[path]


class HttpStubPublicHttpJsonFundDataSource(PublicHttpJsonFundDataSource):
    def __init__(self, responses: dict[str, list[HttpJsonResponse]]) -> None:
        self.responses = responses
        self.requests: list[str] = []
        super().__init__("https://public.example/funds/", 1)

    def _read_http_json(self, path: str) -> HttpJsonResponse:
        self.requests.append(path)
        return self.responses[path].pop(0)


def fund_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": "800001",
        "name": "公开稳健混合",
        "fund_type": "mixed",
        "risk_level": "R3",
        "manager_name": "公开经理",
        "inception_date": "2020-01-01",
        "fund_size_billion": 20.5,
        "management_fee": 1.0,
        "custody_fee": 0.2,
        "annualized_return_3y": 6.1,
        "annualized_return_5y": 7.2,
        "max_drawdown": -10.2,
        "sharpe_ratio": 1.18,
        "category_rank_percentile": 25,
        "manager_years": 5,
        "data_updated_at": "2026-07-09T10:00:00+08:00",
        "ai_summary": "公开 JSON 样例",
    }
    payload.update(overrides)
    return payload


def test_public_http_json_reads_fund_profiles() -> None:
    source = StubPublicHttpJsonFundDataSource({"funds.json": {"funds": [fund_payload()]}})

    funds = source.fetch_fund_profiles()

    assert len(funds) == 1
    assert funds[0].code == "800001"
    assert funds[0].source == "public_http_json"
    assert funds[0].provider_profile == "generic_aliases_v1"
    assert funds[0].upstream_provider is None
    assert funds[0].navs == []
    assert source.fetch_risk_levels() == {"800001": "R3"}


def test_public_http_json_rotates_operator_configured_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    source = PublicHttpJsonFundDataSource(
        "https://public.example/funds/",
        timeout_seconds=1,
        proxy_urls=("http://proxy-a.example:8080", "http://proxy-b.example:8080"),
    )
    opened: list[str] = []

    class FakeOpener:
        def __init__(self, proxy_url: str) -> None:
            self.proxy_url = proxy_url

        def open(self, _request: object, *, timeout: int) -> object:
            opened.append(self.proxy_url)
            return object()

    monkeypatch.setattr(
        "app.data_sources.public_http_json.build_opener",
        lambda handler: FakeOpener(next(iter(handler.proxies.values()))),
    )
    request = Request("https://public.example/funds/funds.json")
    for _ in range(3):
        source._open_url(request)

    assert opened == [
        "http://proxy-a.example:8080",
        "http://proxy-b.example:8080",
        "http://proxy-a.example:8080",
    ]


def test_public_http_json_fetches_remote_navs_when_profile_has_no_navs() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": [fund_payload()],
            "navs/800001.json": {
                "navs": [
                    {"trade_date": "2024-01-02", "nav": 1.1, "accumulated_nav": 1.1},
                    {"trade_date": "2023-01-02", "nav": 1.0, "accumulated_nav": 1.0},
                ]
            },
        }
    )

    funds = source.fetch_fund_navs()

    assert [point.trade_date for point in funds[0].navs] == ["2023-01-02", "2024-01-02"]


def test_public_http_json_rejects_legacy_year_in_remote_real_navs() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": [fund_payload()],
            "navs/800001.json": {
                "navs": [
                    {"trade_date": "2024", "nav": 1.1, "accumulated_nav": 1.1},
                ]
            },
        }
    )

    with pytest.raises(ValueError, match="real NAV trade_date must use ISO YYYY-MM-DD"):
        source.fetch_fund_navs()


def test_public_http_json_keeps_inline_navs_sorted() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": [
                fund_payload(
                    navs=[
                        {"trade_date": "2024-01-02", "nav": 1.1, "accumulated_nav": 1.1},
                        {"trade_date": "2023-01-02", "nav": 1.0, "accumulated_nav": 1.0},
                    ]
                )
            ]
        }
    )

    funds = source.fetch_fund_navs()

    assert [point.trade_date for point in funds[0].navs] == ["2023-01-02", "2024-01-02"]


def test_public_http_json_rejects_legacy_year_in_inline_real_navs() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": [
                fund_payload(
                    navs=[
                        {"trade_date": "2024", "nav": 1.1, "accumulated_nav": 1.1},
                    ]
                )
            ]
        }
    )

    with pytest.raises(ValueError, match="real NAV trade_date must use ISO YYYY-MM-DD"):
        source.fetch_fund_navs()


def test_public_http_json_can_be_selected_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_FUND_DATA_BASE_URL", "https://public.example/funds/")
    monkeypatch.setattr(
        config_settings,
        "public_fund_data_base_url",
        "https://public.example/funds/",
    )

    source = get_fund_data_source("public_http_json")

    assert source.name == "public_http_json"


def test_public_http_json_requires_base_url() -> None:
    with pytest.raises(ValueError, match="PUBLIC_FUND_DATA_BASE_URL"):
        PublicHttpJsonFundDataSource("")


def test_public_http_json_reports_invalid_fund_payload() -> None:
    source = StubPublicHttpJsonFundDataSource({"funds.json": [{"code": "missing-fields"}]})

    with pytest.raises(ValueError, match="funds.json item 0 is invalid"):
        source.fetch_fund_profiles()


def test_public_http_json_maps_common_public_field_names() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": [
                {
                    "fundCode": "800002",
                    "fundName": "别名字段基金",
                    "fundType": "混合型",
                    "riskLevel": "R3",
                    "managerName": "别名经理",
                    "establishDate": "2021-02-03",
                    "fundSizeBillion": 18.2,
                    "managementFee": 0.8,
                    "custodyFee": 0.15,
                    "annualizedReturn3y": 5.5,
                    "annualizedReturn5y": 6.4,
                    "maxDrawdown": -8.1,
                    "sharpeRatio": 1.02,
                    "categoryRankPercentile": 30,
                    "managerYears": 4,
                    "dataUpdatedAt": "2026-07-10T10:00:00+08:00",
                    "navs": [{"tradeDate": "2024-01-02", "unitNav": 1.1, "accumulatedNav": 1.2}],
                }
            ]
        }
    )

    fund = source.fetch_fund_navs()[0]

    assert fund.code == "800002"
    assert fund.fund_type == "mixed"
    assert fund.manager_name == "别名经理"
    assert fund.navs[0].trade_date == "2024-01-02"
    assert fund.navs[0].nav == 1.1


def test_normalized_profile_reads_standard_fields_without_generic_aliases() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {"funds.json": [fund_payload()]},
        profile_name="normalized_v1",
    )

    fund = source.fetch_fund_profiles()[0]

    assert fund.code == "800001"
    assert fund.source == "public_http_json"
    assert fund.provider_profile == "normalized_v1"

    alias_source = StubPublicHttpJsonFundDataSource(
        {"funds.json": [{"fundCode": "800002"}]},
        profile_name="normalized_v1",
    )
    with pytest.raises(ValueError, match="funds.json item 0 is invalid"):
        alias_source.fetch_fund_profiles()


def test_public_http_json_rejects_unknown_profile_at_construction() -> None:
    with pytest.raises(
        ValueError,
        match="unknown PUBLIC_FUND_DATA_PROFILE.*generic_aliases_v1.*normalized_v1",
    ):
        PublicHttpJsonFundDataSource(
            "https://public.example/funds/",
            profile_name="missing_profile",
        )


def test_public_http_json_factory_rejects_unknown_configured_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config_settings,
        "public_fund_data_profile",
        "missing_profile",
    )

    with pytest.raises(ValueError, match="unknown PUBLIC_FUND_DATA_PROFILE 'missing_profile'"):
        get_fund_data_source("public_http_json")


def test_public_http_json_follows_paginated_funds() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": {"funds": [fund_payload(code="800001")], "next": "funds-page-2.json"},
            "funds-page-2.json": {"funds": [fund_payload(code="800002")]},
        }
    )

    funds = source.fetch_fund_profiles()

    assert [fund.code for fund in funds] == ["800001", "800002"]


def test_public_http_json_follows_page_and_total_pages_pagination() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": {"funds": [fund_payload(code="800001")], "page": 1, "total_pages": 2},
            "funds.json?page=2&page_size=25": {
                "funds": [fund_payload(code="800002")],
                "page": 2,
                "total_pages": 2,
            },
        },
        batch_size=25,
    )

    funds = source.fetch_fund_profiles()

    assert [fund.code for fund in funds] == ["800001", "800002"]
    assert source.requests == ["funds.json", "funds.json?page=2&page_size=25"]


def test_public_http_json_accepts_absolute_next_with_equivalent_default_port() -> None:
    absolute_next = "https://PUBLIC.EXAMPLE:443/funds/funds-page-2.json"
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": {"funds": [fund_payload(code="800001")], "next": absolute_next},
            absolute_next: {"funds": [fund_payload(code="800002")]},
        }
    )

    funds = source.fetch_fund_profiles()

    assert [fund.code for fund in funds] == ["800001", "800002"]


@pytest.mark.parametrize(
    "next_url",
    (
        "https://other.example/funds/page-2.json",
        "http://public.example/funds/page-2.json",
        "https://public.example:444/funds/page-2.json",
        "//other.example/funds/page-2.json",
        "https://user:secret@public.example/funds/page-2.json",
    ),
)
def test_public_http_json_rejects_unsafe_pagination_origins(next_url: str) -> None:
    source = StubPublicHttpJsonFundDataSource(
        {"funds.json": {"funds": [fund_payload()], "next": next_url}}
    )

    with pytest.raises(ValueError, match="public_http_json pagination URL"):
        source.fetch_fund_profiles()

    assert source.requests == ["funds.json"]


def test_public_http_json_rejects_pagination_loops_before_refetching() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {"funds.json": {"funds": [fund_payload()], "next": "funds.json"}}
    )

    with pytest.raises(ValueError, match="pagination loop detected"):
        source.fetch_fund_profiles()

    assert source.requests == ["funds.json"]


def test_public_http_json_rejects_pages_beyond_configured_limit() -> None:
    source = StubPublicHttpJsonFundDataSource(
        {
            "funds.json": {"funds": [fund_payload(code="800001")], "next": "page-2.json"},
            "page-2.json": {"funds": [fund_payload(code="800002")], "next": "page-3.json"},
            "page-3.json": {"funds": [fund_payload(code="800003")]},
        },
        max_pages=2,
    )

    with pytest.raises(ValueError, match="PUBLIC_FUND_DATA_MAX_PAGES=2"):
        source.fetch_fund_profiles()

    assert source.requests == ["funds.json", "page-2.json"]


def test_public_http_json_uses_conditional_cache_on_not_modified() -> None:
    source = HttpStubPublicHttpJsonFundDataSource(
        {
            "funds.json": [
                HttpJsonResponse(
                    body='{"funds":[{"code":"800001","name":"缓存基金","fund_type":"mixed",'
                    '"risk_level":"R3","manager_name":"缓存经理","inception_date":"2020-01-01",'
                    '"fund_size_billion":20.5,"management_fee":1.0,"custody_fee":0.2,'
                    '"annualized_return_3y":6.1,"annualized_return_5y":7.2,"max_drawdown":-10.2,'
                    '"sharpe_ratio":1.18,"category_rank_percentile":25,"manager_years":5,'
                    '"data_updated_at":"2026-07-09T10:00:00+08:00"}]}',
                    etag='"funds-v1"',
                    last_modified="Mon, 13 Jul 2026 01:00:00 GMT",
                ),
                HttpJsonResponse(body=None, not_modified=True),
            ]
        }
    )

    first = source.fetch_fund_profiles()
    second = source.fetch_fund_profiles()

    assert first[0].code == "800001"
    assert second[0].code == "800001"
    assert source._memory_cache["funds.json"].etag == '"funds-v1"'
    assert source.requests == ["funds.json", "funds.json"]


def test_public_http_json_throttle_preserves_configured_minimum_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = PublicHttpJsonFundDataSource(
        "https://public.example/funds/",
        min_interval_seconds=0.5,
    )
    source._last_request_at = 10.0
    monotonic_values = iter((10.1, 10.5))
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "app.data_sources.public_http_json.time.monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr("app.data_sources.public_http_json.time.sleep", sleep_calls.append)

    source._throttle()

    assert sleep_calls == pytest.approx([0.4])
    assert source._last_request_at == 10.5
