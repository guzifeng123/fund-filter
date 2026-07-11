from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.jobs.sync_fund_data import sync_fund_profiles, sync_fund_navs


def seed_sample_data(db: Session) -> None:
    sync_fund_profiles(db, "sample_local")
    sync_fund_navs(db, "sample_local")


def run() -> None:
    db = get_sessionmaker()()
    try:
        seed_sample_data(db)
    finally:
        db.close()


if __name__ == "__main__":
    run()
