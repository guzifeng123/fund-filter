from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, create_engine, event, inspect, text

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = WORKSPACE_ROOT / "apps" / "api"
ALEMBIC_CONFIG_PATH = API_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_PATH = API_ROOT / "alembic"

REQUIRED_TABLES = frozenset(
    {
        "ai_messages",
        "ai_threads",
        "backtest_runs",
        "document_chunks",
        "documents",
        "fund_metrics",
        "fund_navs",
        "fund_data_snapshot_state",
        "fund_data_snapshots",
        "funds",
        "job_runs",
        "llm_provider_events",
        "portfolio_positions",
        "portfolios",
        "risk_assessments",
    }
)
PRIVILEGED_POSTGRES_ROLE_FLAGS = (
    "rolsuper",
    "rolcreatedb",
    "rolcreaterole",
    "rolreplication",
    "rolbypassrls",
)


class MigrationVerificationError(RuntimeError):
    """Raised when the migration lifecycle violates its verification contract."""


@dataclass(frozen=True)
class DatabaseSnapshot:
    revision: str
    tables: frozenset[str]
    active_generation_id: str
    snapshot_indexes: tuple[str, ...]
    snapshot_checks: tuple[str, ...]
    snapshot_foreign_keys: tuple[str, ...]
    llm_event_indexes: tuple[str, ...]
    llm_event_checks: tuple[str, ...]
    pgvector_version: str | None = None
    embedding_type: str | None = None
    vector_index_definition: str | None = None
    postgres_role_flags: tuple[bool, ...] | None = None
    postgres_database_owner: bool | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Alembic migrations from an empty database through upgrade, "
            "repeat-upgrade, downgrade, and round-trip upgrade."
        )
    )
    parser.add_argument(
        "--dialect",
        choices=("sqlite", "postgresql"),
        default="sqlite",
        help="Database dialect to verify (default: sqlite).",
    )
    parser.add_argument(
        "--database-url",
        help=(
            "Disposable empty database URL. Required for PostgreSQL; when omitted for "
            "SQLite, a temporary database is created and removed automatically."
        ),
    )
    parser.add_argument(
        "--require-unprivileged-role",
        action="store_true",
        help="Fail if the PostgreSQL connection role has cluster-level privileges.",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=120,
        help="Timeout for each Alembic command (default: 120).",
    )
    return parser.parse_args()


def alembic_head() -> str:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_PATH))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise MigrationVerificationError(
            f"Expected exactly one Alembic head, found {len(heads)}: {heads}"
        )
    return heads[0]


def run_alembic(
    database_url: str,
    *arguments: str,
    timeout_seconds: int,
) -> None:
    command = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        ALEMBIC_CONFIG_PATH.name,
        *arguments,
    ]
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    printable_command = " ".join(("alembic", *arguments))
    print(f"Running: {printable_command}", flush=True)
    try:
        result = subprocess.run(
            command,
            cwd=API_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise MigrationVerificationError(
            f"Timed out after {timeout_seconds}s: {printable_command}"
        ) from error
    if result.returncode != 0:
        details = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        raise MigrationVerificationError(
            f"Alembic exited with code {result.returncode}: {printable_command}\n{details}"
        )


def _enable_sqlite_foreign_keys(
    dbapi_connection: Any,
    _connection_record: Any,
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def make_engine(database_url: str) -> Engine:
    connect_args: dict[str, int] = {}
    if database_url.startswith(("postgresql://", "postgresql+")):
        connect_args["connect_timeout"] = 10
    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def table_names(connection: Connection) -> frozenset[str]:
    return frozenset(inspect(connection).get_table_names())


def assert_empty_database(database_url: str, expected_dialect: str) -> None:
    engine = make_engine(database_url)
    try:
        with engine.connect() as connection:
            if connection.dialect.name != expected_dialect:
                raise MigrationVerificationError(
                    f"Expected {expected_dialect} but connected to {connection.dialect.name}."
                )
            existing_tables = table_names(connection)
    finally:
        engine.dispose()
    if existing_tables:
        raise MigrationVerificationError(
            "Migration verification requires an empty disposable database; found tables: "
            f"{sorted(existing_tables)}"
        )


def postgres_snapshot_fields(
    connection: Connection,
) -> tuple[str, str, str, tuple[bool, ...], bool]:
    vector_version = connection.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar_one_or_none()
    if vector_version is None:
        raise MigrationVerificationError(
            "The PostgreSQL vector extension is not installed."
        )

    embedding_type = connection.execute(
        text(
            """
            SELECT pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_catalog.pg_attribute AS attribute
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = attribute.attrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = current_schema()
              AND relation.relname = 'document_chunks'
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped
            """
        )
    ).scalar_one_or_none()
    if embedding_type != "vector(16)":
        raise MigrationVerificationError(
            f"Expected document_chunks.embedding to be vector(16), found {embedding_type!r}."
        )

    index_definition = connection.execute(
        text(
            """
            SELECT indexdef
            FROM pg_catalog.pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'document_chunks'
              AND indexname = 'ix_document_chunks_embedding_cosine'
            """
        )
    ).scalar_one_or_none()
    normalized_index_definition = (
        ""
        if index_definition is None
        else "".join(str(index_definition).lower().split())
    ).replace("'", "")
    required_index_fragments = (
        "usingivfflat(",
        "vector_cosine_ops",
        "with(lists=1)",
    )
    if any(
        fragment not in normalized_index_definition
        for fragment in required_index_fragments
    ):
        raise MigrationVerificationError(
            "The pgvector cosine index is missing or has the wrong access method, "
            "operator class, or lists setting."
        )

    role_row = connection.execute(
        text(
            """
            SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
            FROM pg_catalog.pg_roles
            WHERE rolname = current_user
            """
        )
    ).one()
    role_flags = tuple(bool(value) for value in role_row)
    database_owner = bool(
        connection.execute(
            text(
                """
                SELECT current_user = pg_catalog.pg_get_userbyid(datdba)
                FROM pg_catalog.pg_database
                WHERE datname = current_database()
                """
            )
        ).scalar_one()
    )
    return (
        str(vector_version),
        str(embedding_type),
        str(index_definition),
        role_flags,
        database_owner,
    )


def fund_snapshot_fields(
    connection: Connection,
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    inspector = inspect(connection)
    required_generation_columns = {
        "funds": "snapshot_generation_id",
        "fund_navs": "snapshot_generation_id",
        "fund_metrics": "snapshot_generation_id",
    }
    verified_indexes: list[str] = []
    verified_foreign_keys: list[str] = []
    for table_name, column_name in required_generation_columns.items():
        columns = {str(column["name"]): column for column in inspector.get_columns(table_name)}
        if column_name not in columns or columns[column_name]["nullable"]:
            raise MigrationVerificationError(
                f"{table_name}.{column_name} is missing or nullable."
            )
        expected_index = f"ix_{table_name}_{column_name}"
        indexes = {str(index["name"]) for index in inspector.get_indexes(table_name)}
        if expected_index not in indexes:
            raise MigrationVerificationError(
                f"Snapshot generation index is missing: {expected_index}."
            )
        verified_indexes.append(expected_index)
        expected_foreign_key = f"fk_{table_name}_{column_name}"
        foreign_keys = inspector.get_foreign_keys(table_name)
        has_snapshot_foreign_key = any(
            foreign_key.get("name") == expected_foreign_key
            and foreign_key.get("referred_table") == "fund_data_snapshots"
            and foreign_key.get("constrained_columns") == [column_name]
            and foreign_key.get("referred_columns") == ["generation_id"]
            for foreign_key in foreign_keys
        )
        if not has_snapshot_foreign_key:
            raise MigrationVerificationError(
                f"Snapshot generation foreign key is missing: {expected_foreign_key}."
            )
        verified_foreign_keys.append(expected_foreign_key)

    snapshot_columns = {
        str(column["name"])
        for column in inspector.get_columns("fund_data_snapshots")
    }
    expected_snapshot_columns = {
        "generation_id",
        "source",
        "status",
        "fund_count",
        "nav_count",
        "metric_count",
        "created_at",
        "promoted_at",
    }
    if not expected_snapshot_columns.issubset(snapshot_columns):
        raise MigrationVerificationError(
            "fund_data_snapshots is missing columns: "
            f"{sorted(expected_snapshot_columns - snapshot_columns)}"
        )
    snapshot_indexes = {
        str(index["name"])
        for index in inspector.get_indexes("fund_data_snapshots")
    }
    if "ix_fund_data_snapshots_status" not in snapshot_indexes:
        raise MigrationVerificationError(
            "fund_data_snapshots status index is missing."
        )
    verified_indexes.append("ix_fund_data_snapshots_status")

    snapshot_checks = {
        str(check["name"])
        for check in inspector.get_check_constraints("fund_data_snapshots")
    }
    required_snapshot_checks = {
        "ck_fund_data_snapshots_status",
        "ck_fund_data_snapshots_fund_count_nonnegative",
        "ck_fund_data_snapshots_nav_count_nonnegative",
        "ck_fund_data_snapshots_metric_count_nonnegative",
    }
    missing_snapshot_checks = required_snapshot_checks - snapshot_checks
    if missing_snapshot_checks:
        raise MigrationVerificationError(
            "fund_data_snapshots is missing checks: "
            f"{sorted(missing_snapshot_checks)}"
        )

    state_checks = {
        str(check["name"])
        for check in inspector.get_check_constraints("fund_data_snapshot_state")
    }
    if "ck_fund_data_snapshot_state_singleton" not in state_checks:
        raise MigrationVerificationError(
            "fund_data_snapshot_state singleton check is missing."
        )
    state_foreign_keys = inspector.get_foreign_keys("fund_data_snapshot_state")
    has_snapshot_foreign_key = any(
        foreign_key.get("referred_table") == "fund_data_snapshots"
        and foreign_key.get("constrained_columns") == ["active_generation_id"]
        for foreign_key in state_foreign_keys
    )
    if not has_snapshot_foreign_key:
        raise MigrationVerificationError(
            "fund_data_snapshot_state.active_generation_id foreign key is missing."
        )

    state_rows = [
        (int(row[0]), str(row[1]))
        for row in connection.execute(
            text("SELECT id, active_generation_id FROM fund_data_snapshot_state")
        ).all()
    ]
    if state_rows != [(1, "legacy-0008")]:
        raise MigrationVerificationError(
            f"Expected one legacy snapshot state row, found {state_rows}."
        )
    legacy_snapshot = connection.execute(
        text(
            """
            SELECT status, fund_count, nav_count, metric_count
            FROM fund_data_snapshots
            WHERE generation_id = 'legacy-0008'
            """
        )
    ).one_or_none()
    if legacy_snapshot != ("active", 0, 0, 0):
        raise MigrationVerificationError(
            f"Expected an empty active legacy snapshot, found {legacy_snapshot}."
        )
    if connection.dialect.name == "sqlite":
        foreign_keys_enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        if foreign_keys_enabled != 1:
            raise MigrationVerificationError(
                "SQLite verification connection does not enforce foreign keys."
            )
    return (
        "legacy-0008",
        tuple(sorted(verified_indexes)),
        tuple(sorted(required_snapshot_checks)),
        tuple(sorted(verified_foreign_keys)),
    )


def llm_observability_fields(
    connection: Connection,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    inspector = inspect(connection)
    columns = {
        str(column["name"])
        for column in inspector.get_columns("llm_provider_events")
    }
    expected_columns = {
        "id",
        "provider_name",
        "model_name",
        "outcome",
        "attempt_count",
        "retry_count",
        "latency_ms",
        "timed_out",
        "error_category",
        "created_at",
    }
    if columns != expected_columns:
        raise MigrationVerificationError(
            "llm_provider_events columns differ from the required safe event shape: "
            f"expected={sorted(expected_columns)}, actual={sorted(columns)}"
        )

    indexes = {
        str(index["name"]): tuple(str(column) for column in index["column_names"])
        for index in inspector.get_indexes("llm_provider_events")
    }
    expected_index = "ix_llm_provider_events_provider_model_created_at"
    if indexes.get(expected_index) != (
        "provider_name",
        "model_name",
        "created_at",
    ):
        raise MigrationVerificationError(
            "llm_provider_events current-provider time-window index is missing or malformed."
        )

    checks = {
        str(check["name"])
        for check in inspector.get_check_constraints("llm_provider_events")
    }
    required_checks = {
        "ck_llm_provider_events_outcome",
        "ck_llm_provider_events_attempt_retry",
        "ck_llm_provider_events_latency_ms",
        "ck_llm_provider_events_error_category",
        "ck_llm_provider_events_fallback_category",
        "ck_llm_provider_events_config_missing_attempt",
        "ck_llm_provider_events_provider_name_safe",
        "ck_llm_provider_events_model_name_safe",
    }
    missing_checks = required_checks - checks
    if missing_checks:
        raise MigrationVerificationError(
            "llm_provider_events is missing checks: "
            f"{sorted(missing_checks)}"
        )
    return (expected_index,), tuple(sorted(required_checks))


def snapshot_at_head(
    database_url: str,
    expected_dialect: str,
    expected_head: str,
    require_unprivileged_role: bool,
) -> DatabaseSnapshot:
    engine = make_engine(database_url)
    try:
        with engine.connect() as connection:
            if connection.dialect.name != expected_dialect:
                raise MigrationVerificationError(
                    f"Expected {expected_dialect} but connected to {connection.dialect.name}."
                )
            tables = table_names(connection)
            missing_tables = REQUIRED_TABLES - tables
            if missing_tables:
                raise MigrationVerificationError(
                    f"Head migration is missing tables: {sorted(missing_tables)}"
                )
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if revision != expected_head:
                raise MigrationVerificationError(
                    f"Expected Alembic head {expected_head}, found {revision}."
                )
            (
                active_generation_id,
                snapshot_indexes,
                snapshot_checks,
                snapshot_foreign_keys,
            ) = fund_snapshot_fields(connection)
            llm_event_indexes, llm_event_checks = llm_observability_fields(connection)

            if expected_dialect == "postgresql":
                (
                    vector_version,
                    embedding_type,
                    index_definition,
                    role_flags,
                    database_owner,
                ) = postgres_snapshot_fields(connection)
                if require_unprivileged_role and any(role_flags):
                    enabled_flags = [
                        name
                        for name, enabled in zip(
                            PRIVILEGED_POSTGRES_ROLE_FLAGS, role_flags, strict=True
                        )
                        if enabled
                    ]
                    raise MigrationVerificationError(
                        "PostgreSQL migration role has forbidden cluster privileges: "
                        f"{enabled_flags}"
                    )
                if require_unprivileged_role and database_owner:
                    raise MigrationVerificationError(
                        "PostgreSQL migration role must not own the verification database."
                    )
                return DatabaseSnapshot(
                    revision=str(revision),
                    tables=tables,
                    active_generation_id=active_generation_id,
                    snapshot_indexes=snapshot_indexes,
                    snapshot_checks=snapshot_checks,
                    snapshot_foreign_keys=snapshot_foreign_keys,
                    llm_event_indexes=llm_event_indexes,
                    llm_event_checks=llm_event_checks,
                    pgvector_version=vector_version,
                    embedding_type=embedding_type,
                    vector_index_definition=index_definition,
                    postgres_role_flags=role_flags,
                    postgres_database_owner=database_owner,
                )

            return DatabaseSnapshot(
                revision=str(revision),
                tables=tables,
                active_generation_id=active_generation_id,
                snapshot_indexes=snapshot_indexes,
                snapshot_checks=snapshot_checks,
                snapshot_foreign_keys=snapshot_foreign_keys,
                llm_event_indexes=llm_event_indexes,
                llm_event_checks=llm_event_checks,
            )
    finally:
        engine.dispose()


def assert_downgraded_to_base(
    database_url: str,
    expected_dialect: str,
    migrated_tables: frozenset[str],
) -> None:
    engine = make_engine(database_url)
    try:
        with engine.connect() as connection:
            if connection.dialect.name != expected_dialect:
                raise MigrationVerificationError(
                    f"Expected {expected_dialect} but connected to {connection.dialect.name}."
                )
            tables = table_names(connection)
            remaining_migrated_tables = (migrated_tables - {"alembic_version"}) & tables
            if remaining_migrated_tables:
                raise MigrationVerificationError(
                    "Downgrade to base left migrated tables behind: "
                    f"{sorted(remaining_migrated_tables)}"
                )
            unexpected_tables = tables - {"alembic_version"}
            if unexpected_tables:
                raise MigrationVerificationError(
                    f"Downgrade to base left unexpected tables: {sorted(unexpected_tables)}"
                )
            if "alembic_version" in tables:
                versions = (
                    connection.execute(text("SELECT version_num FROM alembic_version"))
                    .scalars()
                    .all()
                )
                if versions:
                    raise MigrationVerificationError(
                        f"Downgrade to base left Alembic versions behind: {versions}"
                    )
    finally:
        engine.dispose()


def verify_lifecycle(
    database_url: str,
    dialect: str,
    require_unprivileged_role: bool,
    timeout_seconds: int,
) -> DatabaseSnapshot:
    expected_head = alembic_head()
    assert_empty_database(database_url, dialect)

    run_alembic(database_url, "upgrade", "head", timeout_seconds=timeout_seconds)
    first_head = snapshot_at_head(
        database_url,
        dialect,
        expected_head,
        require_unprivileged_role,
    )

    run_alembic(database_url, "upgrade", "head", timeout_seconds=timeout_seconds)
    repeated_head = snapshot_at_head(
        database_url,
        dialect,
        expected_head,
        require_unprivileged_role,
    )
    if repeated_head != first_head:
        raise MigrationVerificationError(
            "Repeated upgrade head changed the verified database snapshot."
        )

    run_alembic(database_url, "downgrade", "base", timeout_seconds=timeout_seconds)
    assert_downgraded_to_base(database_url, dialect, first_head.tables)

    run_alembic(database_url, "upgrade", "head", timeout_seconds=timeout_seconds)
    round_trip_head = snapshot_at_head(
        database_url,
        dialect,
        expected_head,
        require_unprivileged_role,
    )
    if round_trip_head != first_head:
        raise MigrationVerificationError(
            "Downgrade/upgrade round trip changed the verified database snapshot."
        )
    return round_trip_head


def resolve_database_url(
    dialect: str,
    database_url: str | None,
) -> tuple[str, tempfile.TemporaryDirectory[str] | None]:
    if database_url:
        return database_url, None
    if dialect == "postgresql":
        raise MigrationVerificationError(
            "--database-url is required when --dialect postgresql is selected."
        )
    temporary_directory = tempfile.TemporaryDirectory(prefix="fund-migration-matrix-")
    database_path = Path(temporary_directory.name) / "migration.sqlite3"
    return f"sqlite:///{database_path.as_posix()}", temporary_directory


def main() -> int:
    args = parse_args()
    if args.command_timeout_seconds <= 0:
        print(
            "Migration verification failed: timeout must be greater than zero.",
            file=sys.stderr,
        )
        return 2
    if args.require_unprivileged_role and args.dialect != "postgresql":
        print(
            "Migration verification failed: --require-unprivileged-role requires PostgreSQL.",
            file=sys.stderr,
        )
        return 2

    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    try:
        database_url, temporary_directory = resolve_database_url(
            args.dialect, args.database_url
        )
        snapshot = verify_lifecycle(
            database_url,
            args.dialect,
            args.require_unprivileged_role,
            args.command_timeout_seconds,
        )
    except (MigrationVerificationError, OSError) as error:
        print(f"Migration verification failed: {error}", file=sys.stderr)
        return 1
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()

    suffix = ""
    if snapshot.pgvector_version is not None:
        suffix = f", pgvector={snapshot.pgvector_version}"
    print(
        "Migration lifecycle verified: "
        f"dialect={args.dialect}, head={snapshot.revision}{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
