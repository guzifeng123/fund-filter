"""D0: tests for scripts/pg_local.py (SQL builders, status parsing, idempotency).

These never start/stop the resident cluster: ``read_status`` is exercised against
a throwaway ``postmaster.pid`` in ``tmp_path``, and the lifecycle commands are
covered by patching ``read_status`` / ``_load_pgserver``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pg_local  # type: ignore[import-not-found]


def test_resolve_config_defaults() -> None:
    config = pg_local.resolve_config()
    assert config.host == pg_local.DEFAULT_HOST
    assert config.port == pg_local.DEFAULT_PORT
    assert config.db_name == pg_local.DEFAULT_DB
    assert config.pgdata == pg_local.REPO_ROOT.parent / "pgdata"


def test_resolve_config_explicit_overrides() -> None:
    config = pg_local.resolve_config(
        pgdata="/tmp/custom-pgdata", port=6543, db_name="custom_db"
    )
    assert config.pgdata == Path("/tmp/custom-pgdata")
    assert config.port == 6543
    assert config.db_name == "custom_db"


def test_resolve_config_rejects_bad_port() -> None:
    with pytest.raises(ValueError, match="PG_LOCAL_PORT"):
        pg_local.resolve_config(port=70000)


def test_sql_builders_are_idempotent_and_quoted() -> None:
    assert pg_local.database_exists_sql("fund_app") == (
        "SELECT 1 FROM pg_database WHERE datname = 'fund_app'"
    )
    assert pg_local.build_create_database_sql("fund_app") == (
        'CREATE DATABASE "fund_app"'
    )
    assert pg_local.build_create_extension_sql() == (
        "CREATE EXTENSION IF NOT EXISTS vector"
    )


def test_read_status_missing_pid_file(tmp_path: Path) -> None:
    status = pg_local.read_status(tmp_path)
    assert status.running is False
    assert status.pid is None


def test_read_status_parses_pid_file(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(pg_local, "_pid_alive", lambda pid: True)
    pid_file = tmp_path / "postmaster.pid"
    pid_file.write_text(
        "\n".join(
            [
                "1841",
                str(tmp_path),
                "1790749668",
                "55432",
                "/tmp",
                "localhost",
                "  1508915         9",
                "ready",
            ]
        ),
        encoding="utf-8",
    )
    status = pg_local.read_status(tmp_path)
    assert status.running is True
    assert status.pid == 1841
    assert status.port == 55432
    assert status.host == "localhost"


def test_read_status_dead_process_reports_stopped(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(pg_local, "_pid_alive", lambda pid: False)
    pid_file = tmp_path / "postmaster.pid"
    pid_file.write_text(
        "\n".join(["999999", str(tmp_path), "1790749668", "55432", "/tmp", "localhost"]),
        encoding="utf-8",
    )
    status = pg_local.read_status(tmp_path)
    assert status.running is False
    assert status.pid == 999999
    assert status.port == 55432


def test_start_is_idempotent_and_never_touches_pgserver_when_running(
    monkeypatch: Any, capsys: Any
) -> None:
    config = pg_local.resolve_config(pgdata="/tmp/x-pgdata")
    running = pg_local.PgStatus(
        running=True, pid=1841, port=55432, host="localhost", data_dir=config.pgdata
    )
    monkeypatch.setattr(pg_local, "read_status", lambda pgdata: running)

    def _must_not_be_called() -> Any:
        raise AssertionError("pgserver must not be loaded when already running")

    monkeypatch.setattr(pg_local, "_load_pgserver", _must_not_be_called)

    assert pg_local.cmd_start(config) == 0
    out = capsys.readouterr().out
    assert "already running" in out


def test_load_pgserver_missing_gives_actionable_hint(monkeypatch: Any) -> None:
    real_import = __import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pgserver":
            raise ImportError("No module named 'pgserver'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(RuntimeError, match="pgserver is not available"):
        pg_local._load_pgserver()
