from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

API_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(API_ROOT))

from app.db.session import Base  # noqa: E402
from app.repositories.funds import upsert_fund_detail  # noqa: E402
from app.repositories.portfolios import ensure_default_portfolios  # noqa: E402
from app.services.sample_data import FUNDS  # noqa: E402


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = TestingSessionLocal()
    for fund in FUNDS:
        upsert_fund_detail(db, fund)
    ensure_default_portfolios(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()
