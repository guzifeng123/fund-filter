from app.schemas.funds import FundDetail
from app.services.sample_data import FUNDS


class SampleLocalFundDataSource:
    name = "sample_local"

    def fetch_snapshot(self) -> list[FundDetail]:
        return FUNDS

    def fetch_fund_profiles(self) -> list[FundDetail]:
        return FUNDS

    def fetch_fund_navs(self) -> list[FundDetail]:
        return FUNDS

    def fetch_risk_levels(self) -> dict[str, str]:
        return {fund.code: fund.risk_level for fund in FUNDS}
