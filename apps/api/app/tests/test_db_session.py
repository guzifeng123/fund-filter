from app.db.session import get_connect_args, get_engine_pool_kwargs


def test_postgresql_connect_args_include_timeout() -> None:
    connect_args = get_connect_args("postgresql+psycopg://user:password@localhost:5432/database")

    connect_timeout = connect_args["connect_timeout"]
    assert isinstance(connect_timeout, int)
    assert connect_timeout >= 1


def test_postgresql_connect_args_bind_server_side_statement_timeout() -> None:
    connect_args = get_connect_args("postgresql+psycopg://user:password@localhost:5432/database")

    options = connect_args["options"]
    assert isinstance(options, str)
    # Applied per-session via libpq `options`: a positive statement_timeout in ms.
    assert options.startswith("-c statement_timeout=")
    assert int(options.rsplit("=", 1)[1]) > 0


def test_sqlite_connect_args_allow_request_threads() -> None:
    assert get_connect_args("sqlite:///./local.db") == {"check_same_thread": False}


def test_unknown_database_backend_has_no_driver_specific_args() -> None:
    assert get_connect_args("mysql+pymysql://user:password@localhost/database") == {}


def test_postgresql_engine_pool_are_sized_and_pinged() -> None:
    pool_kwargs = get_engine_pool_kwargs("postgresql+psycopg://user:password@localhost:5432/database")

    assert isinstance(pool_kwargs["pool_size"], int)
    assert pool_kwargs["pool_size"] >= 1
    assert isinstance(pool_kwargs["max_overflow"], int)
    assert pool_kwargs["max_overflow"] >= 0
    assert pool_kwargs["pool_pre_ping"] is True


def test_sqlite_engine_pool_keeps_historical_pre_ping_without_sizing() -> None:
    # SQLite path is intentionally unchanged: pre-ping on, no explicit pool size.
    assert get_engine_pool_kwargs("sqlite:///./local.db") == {"pool_pre_ping": True}


def test_unknown_database_backend_has_no_pool_kwargs() -> None:
    assert get_engine_pool_kwargs("mysql+pymysql://user:password@localhost/database") == {}
