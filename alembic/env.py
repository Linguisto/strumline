"""Alembic environment for async SQLAlchemy migrations.

Reads ``DATABASE_URL`` from the environment (or .env file via
``DatabaseSettings``). Uses the synchronous psycopg2 driver for migrations
(swap ``asyncpg`` → ``psycopg2`` in the URL) so Alembic can run without an
event loop.
"""

from __future__ import annotations

import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from strumline.config import DatabaseSettings
from strumline.db.base import Base
import strumline.db.models  # noqa: F401 — register models with metadata

# Alembic Config object
config = context.config

# Set up logging from alembic.ini if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate
target_metadata = Base.metadata


def _sync_url(url: str) -> str:
    """Convert asyncpg URL to psycopg2 for synchronous Alembic runs."""
    return re.sub(r"postgresql\+asyncpg://", "postgresql+psycopg2://", url)


def _get_url() -> str:
    # Allow override via alembic.ini [alembic] sqlalchemy.url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url and ini_url != "driver://user:pass@localhost/dbname":
        return _sync_url(ini_url)
    return _sync_url(DatabaseSettings().database_url)


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL script)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
