from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.data_sources.sample_local import SampleLocalFundDataSource
from app.db.session import get_sessionmaker
from app.schemas.funds import FundDetail
from app.jobs.sync_fund_data import sync_all


class _SeedSampleSource(SampleLocalFundDataSource):
    def __init__(self, data_updated_at: datetime | None) -> None:
        self._data_updated_at = data_updated_at

    def fetch_snapshot(self) -> list[FundDetail]:
        funds = super().fetch_snapshot()
        if self._data_updated_at is None:
            return funds
        updated_at = self._data_updated_at.astimezone(timezone.utc).isoformat()
        return [
            fund.model_copy(update={"data_updated_at": updated_at}, deep=True)
            for fund in funds
        ]


def seed_sample_data(
    db: Session,
    *,
    refresh_data_updated_at: bool = False,
    now: datetime | None = None,
) -> None:
    timestamp = (now or datetime.now(timezone.utc)) if refresh_data_updated_at else None
    sync_all(
        db,
        "sample_local",
        source_override=_SeedSampleSource(timestamp),
    )


def run() -> None:
    db = get_sessionmaker()()
    try:
        seed_sample_data(db, refresh_data_updated_at=True)
    finally:
        db.close()


if __name__ == "__main__":
    run()
