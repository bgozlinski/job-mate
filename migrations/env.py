from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM models yet — the first migration is written by hand, so autogenerate
# stays off. Wiring metadata in here needs care: autogenerate does not know
# about the vector type, HNSW indexes or extensions and will try to drop them.
target_metadata = None

# The connection URL comes from Settings, never from alembic.ini — the .ini is
# committed and must not carry credentials (NFR-1).
settings = get_settings()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Emits SQL to stdout without connecting, so the password is deliberately
    left masked: it would otherwise end up in the generated script.
    """
    context.configure(
        url=settings.database_url.render_as_string(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Deliberately synchronous: Alembic runs migrations synchronously anyway, so
    an async engine would only add a bridge back to sync code. It also keeps
    psycopg off the asyncio event loop, which async psycopg cannot use on
    Windows (ProactorEventLoop).

    The URL object is handed to the engine directly rather than stringified —
    str(URL) masks the password as '***' and the connection would fail.
    """
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool)

    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
