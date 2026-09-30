#!/usr/bin/env python3
"""Local PostgreSQL 16 + pgvector lifecycle helper (D0 batch-foundation).

This script is the single entry point for standing up a disposable, local
PostgreSQL cluster for the D-stage full-market batch job. It deliberately
mirrors the conventions already in use on this machine:

* data directory lives *outside* the repo at ``<repo>/../pgdata`` (configurable
  via ``PG_LOCAL_PGDATA``) so it is never committed;
* the cluster listens on TCP ``localhost:55432`` (configurable via
  ``PG_LOCAL_PORT``);
* the application database ``fund_app`` and the ``vector`` extension are created
  automatically on first start.

Design for testability:

* All side-effect-free helpers (:func:`read_status`, :func:`build_create_database_sql`,
  :func:`build_create_extension_sql`, :func:`database_exists_sql`) take plain
  arguments and return strings / dataclasses, so the suite can cover the SQL
  generation, the idempotent "already running" decision and the postmaster.pid
  parsing with mocks only -- it never touches the resident cluster.
* ``pgserver`` is imported *inside* the functions that actually need it. When the
  package is missing this venv reports an actionable install/venv hint instead
  of failing at import time, so ``import app`` (and the rest of the test suite)
  never depends on it.

Safety: ``start`` is idempotent -- if a cluster is already running for the
configured pgdata it is reported and left untouched. ``stop`` intentionally
tears *this* cluster down; operators must not point it at a database they care
about.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# pgdata deliberately lives *outside* the worktree: <repo>/../pgdata.
DEFAULT_PGDATA = REPO_ROOT.parent / "pgdata"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 55432
DEFAULT_DB = "fund_app"


@dataclass(frozen=True)
class PgLocalConfig:
    """Resolved, validated configuration for the local cluster."""

    pgdata: Path
    host: str
    port: int
    db_name: str


@dataclass(frozen=True)
class PgStatus:
    """Parsed view of ``postmaster.pid`` plus liveness check."""

    running: bool
    pid: int | None
    port: int | None
    host: str | None
    data_dir: Path | None


def resolve_config(
    *,
    pgdata: str | None = None,
    port: int | None = None,
    db_name: str | None = None,
    host: str = DEFAULT_HOST,
) -> PgLocalConfig:
    """Resolve pgdata / port / db from explicit args, env, then defaults."""
    raw_pgdata = pgdata if pgdata is not None else os.getenv("PG_LOCAL_PGDATA", "")
    resolved_pgdata = Path(raw_pgdata).expanduser() if raw_pgdata else DEFAULT_PGDATA
    raw_port = port if port is not None else int(os.getenv("PG_LOCAL_PORT", str(DEFAULT_PORT)))
    if raw_port < 1 or raw_port > 65535:
        raise ValueError(f"PG_LOCAL_PORT must be 1..65535, got {raw_port}")
    raw_db = db_name if db_name is not None else os.getenv("PG_LOCAL_DB", DEFAULT_DB)
    if not raw_db.strip():
        raise ValueError("database name must not be empty")
    return PgLocalConfig(pgdata=resolved_pgdata, host=host, port=raw_port, db_name=raw_db)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_status(pgdata: Path) -> PgStatus:
    """Parse ``<pgdata>/postmaster.pid`` and report whether the server is alive.

    The file format (stable across PG12+): line 1 = postmaster PID, line 2 =
    data dir, line 3 = start epoch, line 4 = port, line 5 = socket dir, line 6 =
    listen addresses (comma-separated host list), line 8 = state. We only need
    pid/port/host here.
    """
    pid_file = pgdata / "postmaster.pid"
    if not pid_file.exists():
        return PgStatus(running=False, pid=None, port=None, host=None, data_dir=None)
    try:
        lines = [line.strip() for line in pid_file.read_text().splitlines() if line.strip()]
    except OSError:
        return PgStatus(running=False, pid=None, port=None, host=None, data_dir=None)
    if len(lines) < 6:
        return PgStatus(running=False, pid=None, port=None, host=None, data_dir=None)
    try:
        pid = int(lines[0])
        port = int(lines[3])
    except ValueError:
        return PgStatus(running=False, pid=None, port=None, host=None, data_dir=None)
    host = lines[5].split(",")[0].strip() or None
    return PgStatus(
        running=_pid_alive(pid),
        pid=pid,
        port=port,
        host=host,
        data_dir=Path(lines[1]),
    )


# --------------------------------------------------------------------------- #
# Pure SQL builders -- unit-tested directly, no network.
# --------------------------------------------------------------------------- #
def database_exists_sql(db_name: str) -> str:
    """Select whether ``db_name`` already exists in ``pg_database``."""
    escaped = db_name.replace("'", "''")
    return f"SELECT 1 FROM pg_database WHERE datname = '{escaped}'"


def build_create_database_sql(db_name: str) -> str:
    """CREATE DATABASE statement (must run outside a transaction / autocommit)."""
    safe = db_name.replace('"', "")
    return f'CREATE DATABASE "{safe}"'


def build_create_extension_sql() -> str:
    """Idempotent pgvector extension install (runs against the app database)."""
    return "CREATE EXTENSION IF NOT EXISTS vector"


def admin_dsn(config: PgLocalConfig, *, database: str = "postgres") -> str:
    return f"postgresql://{config.host}:{config.port}/{database}"


# --------------------------------------------------------------------------- #
# pgserver is imported lazily inside the lifecycle functions below.
# --------------------------------------------------------------------------- #
def _load_pgserver():  # type: ignore[no-untyped-def]
    try:
        import pgserver  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001 - surface an actionable hint
        raise RuntimeError(
            "pgserver is not available in this Python environment. Either install it "
            "(`pip install pgserver`) or run scripts/pg_local.py with the repository "
            "virtualenv that bundles PostgreSQL (e.g. the main repo .venv). "
            f"Import failed with: {exc}"
        ) from exc
    return pgserver


def ensure_database_and_extension(config: PgLocalConfig) -> None:
    """CREATE DATABASE fund_app (if missing) + CREATE EXTENSION vector.

    Uses psycopg (already a project dependency) against the running cluster.
    """
    import psycopg  # type: ignore[import-untyped]

    admin_dsn = (
        f"host={config.host} port={config.port} user=postgres dbname=postgres"
    )
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(database_exists_sql(config.db_name))
            if cur.fetchone() is None:
                cur.execute(build_create_database_sql(config.db_name))

    app_dsn = (
        f"host={config.host} port={config.port} user=postgres dbname={config.db_name}"
    )
    with psycopg.connect(app_dsn, autocommit=True, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(build_create_extension_sql())


def cmd_start(config: PgLocalConfig) -> int:
    status = read_status(config.pgdata)
    if status.running:
        print(
            f"PostgreSQL already running: pid={status.pid} port={status.port} "
            f"pgdata={config.pgdata}"
        )
        print(f"DSN: {admin_dsn(config, database=config.db_name)}")
        return 0
    pgserver = _load_pgserver()
    config.pgdata.mkdir(parents=True, exist_ok=True)
    server = pgserver.PostgresServer(config.pgdata, cleanup_mode=None)
    server.ensure_pgdata_inited()
    # Start with explicit TCP on localhost:<port> (pgserver's default disables
    # TCP and picks a random socket-only port, which our DATABASE_URL cannot use).
    log_path = config.pgdata / "pg_local.log"
    pgserver.pg_ctl(
        [
            "-w",
            "-o",
            f"-h {config.host} -p {config.port}",
            "-l",
            str(log_path),
            "start",
        ],
        pgdata=config.pgdata,
        timeout=30,
    )
    ensure_database_and_extension(config)
    print(
        f"PostgreSQL started: port={config.port} pgdata={config.pgdata} "
        f"db={config.db_name}"
    )
    print(f"DSN: {admin_dsn(config, database=config.db_name)}")
    return 0


def cmd_stop(config: PgLocalConfig) -> int:
    status = read_status(config.pgdata)
    if not status.running:
        print(f"No running cluster found for pgdata={config.pgdata}")
        return 0
    pgserver = _load_pgserver()
    pgserver.pg_ctl(["-m", "fast", "stop"], pgdata=config.pgdata, timeout=30)
    print(f"PostgreSQL stopped: pgdata={config.pgdata}")
    return 0


def cmd_status(config: PgLocalConfig) -> int:
    status = read_status(config.pgdata)
    if not status.running:
        print(f"stopped: pgdata={config.pgdata}")
        return 1
    print(
        f"running: pid={status.pid} port={status.port} host={status.host} "
        f"pgdata={status.data_dir}"
    )
    print(f"DSN: {admin_dsn(config, database=config.db_name)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local pgvector PostgreSQL lifecycle")
    parser.add_argument("command", choices=("start", "stop", "status"))
    parser.add_argument("--pgdata", default=None, help="override PG_LOCAL_PGDATA")
    parser.add_argument("--port", type=int, default=None, help="override PG_LOCAL_PORT")
    parser.add_argument("--db", default=None, help="override PG_LOCAL_DB")
    args = parser.parse_args(argv)
    config = resolve_config(pgdata=args.pgdata, port=args.port, db_name=args.db)
    if args.command == "start":
        return cmd_start(config)
    if args.command == "stop":
        return cmd_stop(config)
    return cmd_status(config)


if __name__ == "__main__":
    sys.exit(main())
