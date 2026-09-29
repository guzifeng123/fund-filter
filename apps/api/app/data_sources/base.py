from typing import Protocol

from app.schemas.funds import FundDetail


class FundDataSource(Protocol):
    name: str

    def fetch_snapshot(self) -> list[FundDetail]:
        """Return one complete profile/NAV/metric snapshot from a single source read."""

    def fetch_fund_profiles(self) -> list[FundDetail]:
        """Return fund profile snapshots. Implementations should not mutate the database."""

    def fetch_fund_navs(self) -> list[FundDetail]:
        """Return fund NAV snapshots. The current local adapter returns full snapshots."""

    def fetch_risk_levels(self) -> dict[str, str]:
        """Return source risk levels keyed by fund code."""
