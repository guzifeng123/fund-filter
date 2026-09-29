from collections.abc import Generator
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

API_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(API_ROOT))

from app.db.models import LEGACY_SNAPSHOT_GENERATION_ID  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.repositories.fund_snapshots import (  # noqa: E402
    ensure_snapshot_state,
    refresh_snapshot_metadata,
)
from app.repositories.funds import upsert_fund_detail  # noqa: E402
from app.repositories.portfolios import ensure_default_portfolios  # noqa: E402
from app.services.sample_data import FUNDS  # noqa: E402
from app.repositories.llm_observability import (  # noqa: E402
    shutdown_default_llm_event_dispatcher,
)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = TestingSessionLocal()
    ensure_snapshot_state(db)
    for fund in FUNDS:
        upsert_fund_detail(db, fund)
    refresh_snapshot_metadata(
        db,
        generation_id=LEGACY_SNAPSHOT_GENERATION_ID,
        fallback_source="sample_local",
    )
    ensure_default_portfolios(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def reset_default_llm_dispatcher() -> Generator[None, None, None]:
    shutdown_default_llm_event_dispatcher(timeout_seconds=1.0)
    try:
        yield
    finally:
        shutdown_default_llm_event_dispatcher(timeout_seconds=1.0)
