import pytest

from app.data_sources import get_fund_data_source
from app.data_sources.public_http_json import PublicHttpJsonFundDataSource


class StubPublicHttpJsonFundDataSource(PublicHttpJsonFundDataSource):
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        super().__init__("https://public.example/funds/", 1)

    def _read_json(self, path: str) -> object:
        return self.payloads[path]


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
    assert funds[0].navs == []
    assert source.fetch_risk_levels() == {"800001": "R3"}


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


def test_public_http_json_can_be_selected_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_FUND_DATA_BASE_URL", "https://public.example/funds/")
    import app.core.config as config
    import app.data_sources.public_http_json as public_http_json

    config.settings.public_fund_data_base_url = "https://public.example/funds/"
    public_http_json.settings.public_fund_data_base_url = "https://public.example/funds/"

    source = get_fund_data_source("public_http_json")

    assert source.name == "public_http_json"


def test_public_http_json_requires_base_url() -> None:
    with pytest.raises(ValueError, match="PUBLIC_FUND_DATA_BASE_URL"):
        PublicHttpJsonFundDataSource("")


def test_public_http_json_reports_invalid_fund_payload() -> None:
    source = StubPublicHttpJsonFundDataSource({"funds.json": [{"code": "missing-fields"}]})

    with pytest.raises(ValueError, match="funds.json item 0 is invalid"):
        source.fetch_fund_profiles()
