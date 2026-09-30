from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool, text

from app.core.config import settings
from app.db.models import *  # noqa: F403
from app.db.session import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Widest revision id today is "0004_use_pgvector_for_document_embeddings" (40
# chars). Alembic defaults alembic_version.version_num to VARCHAR(32); PostgreSQL
# enforces that length strictly, so a brand-new PG database failed when stamping
# 0004. SQLite does not enforce the length, which is why this only surfaced on
# PostgreSQL. We pre-create / widen the version table to VARCHAR(128) once,
# idempotently, before Alembic's ensure_version runs.
_VERSION_COLUMN_TYPE = "VARCHAR(128)"
_VERSION_TABLE_DDL = (
    "CREATE TABLE alembic_version ("
    "version_num VARCHAR(128) NOT NULL, "
    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
    ")"
)
_VERSION_WIDEN_DDL = (
    "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"
)


def _is_postgres_url(url: str) -> bool:
    return url.startswith(("postgresql://", "postgresql+"))


def ensure_version_column_widened(connection: Connection) -> None:
    """Idempotently guarantee ``alembic_version.version_num`` is wide enough.

    Runs once, before any migration step, on the live connection. PostgreSQL
    only: if the version table already exists we widen its column; if it does
    not exist yet we create it at ``VARCHAR(128)`` so Alembic's own
    ``ensure_version`` (which uses ``checkfirst=True``) leaves it untouched
    instead of recreating it at the default ``VARCHAR(32)``. Re-running this
    function is always safe (the second ``ALTER`` is a no-op type change).
    SQLite and other dialects never enforce the length limit and are no-ops.
    """
    if connection.dialect.name != "postgresql":
        return
    existing = connection.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'alembic_version'"
        )
    ).scalar_one_or_none()
    if existing is not None:
        connection.execute(text(_VERSION_WIDEN_DDL))
    else:
        connection.execute(text(_VERSION_TABLE_DDL))
    connection.commit()


def _emit_offline_version_column_guarantee() -> None:
    """Offline (``--sql``) mirror of :func:`ensure_version_column_widened`.

    In offline mode there is no live connection to introspect, and Alembic emits
    its own ``CREATE TABLE alembic_version`` inside the migration stream. We can
    only safely widen an *already existing* version table, so we emit an
    idempotent PL/pgSQL DO block: it alters the column when the table exists and
    is a no-op on a fresh database. This mirrors the online guarantee for
    replayed scripts; SQLite emits nothing.
    """
    if not _is_postgres_url(settings.database_url):
        return
    context.execute(
        text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'alembic_version') THEN "
            "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128); "
            "END IF; END $$"
        )
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        _emit_offline_version_column_guarantee()
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        ensure_version_column_widened(connection)
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
