from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _enable_sqlite_foreign_keys(
    dbapi_connection: Any,
    _connection_record: Any,
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_connect_args(database_url: str) -> dict[str, object]:
    backend_name = make_url(database_url).get_backend_name()
    if backend_name == "sqlite":
        return {"check_same_thread": False}
    if backend_name == "postgresql":
        return {"connect_timeout": settings.database_connect_timeout_seconds}
    return {}


def get_engine() -> Engine:
    global engine
    if engine is None:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            connect_args=get_connect_args(settings.database_url),
        )
        if make_url(settings.database_url).get_backend_name() == "sqlite":
            event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def get_sessionmaker() -> sessionmaker[Session]:
    global SessionLocal
    if SessionLocal is None:
        SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
