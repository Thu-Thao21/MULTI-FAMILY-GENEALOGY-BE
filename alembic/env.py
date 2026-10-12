import asyncio
from logging.config import fileConfig
import os
import sys

# Ensure the backend directory is in the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import settings
from app.db.fingerprint import target_summary
from app.db.migration_guard import enforce_guard
from app.models.registry import target_metadata

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# DATABASE_URL from app.core.config (already normalized to postgresql+psycopg://).
# Escape % for ConfigParser interpolation.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode: renders SQL, makes NO connection, needs no guard."""
    url = settings.DATABASE_URL
    print(f"alembic offline preview (no connection): {target_summary(url)}", file=sys.stderr)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # transaction_per_migration: if 0002 stops (duplicates), the baseline stays recorded.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an Engine and associate a connection with the context."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (touches the database), behind the safety guard.

    Needs ALLOW_MIGRATE=1 and MIGRATE_EXPECT_FINGERPRINT=<fingerprint of DATABASE_URL>.
    Prints only the database name and the fingerprint: never the host, user or password.
    The guard runs BEFORE any connection is opened.
    """
    enforce_guard(settings.DATABASE_URL, os.environ)
    print(f"alembic target: {target_summary(settings.DATABASE_URL)}", file=sys.stderr)
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
