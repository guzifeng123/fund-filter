from app.db.session import get_connect_args


def test_postgresql_connect_args_include_timeout() -> None:
    connect_args = get_connect_args("postgresql+psycopg://user:password@localhost:5432/database")

    connect_timeout = connect_args["connect_timeout"]
    assert isinstance(connect_timeout, int)
    assert connect_timeout >= 1


def test_sqlite_connect_args_allow_request_threads() -> None:
    assert get_connect_args("sqlite:///./local.db") == {"check_same_thread": False}


def test_unknown_database_backend_has_no_driver_specific_args() -> None:
    assert get_connect_args("mysql+pymysql://user:password@localhost/database") == {}
