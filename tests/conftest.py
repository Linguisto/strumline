"""Test database setup.

Uses a dedicated test database configured via TESTING_DB_* env vars (see
.env.example).  Migrations are the same as production — only the target DB
differs.  Tables are truncated once per test session for a clean slate.
"""

from __future__ import annotations

import os

import pytest

_HOST = os.environ.get("TESTING_DB_HOST", os.environ.get("DB_HOST", "localhost"))
_PORT = os.environ.get("TESTING_DB_PORT", os.environ.get("DB_PORT", "5432"))
_USER = os.environ.get("TESTING_DB_USER", os.environ.get("DB_USER", "telemetria"))
_PASSWORD = os.environ.get("TESTING_DB_PASSWORD", os.environ.get("DB_PASSWORD", "telemetria"))
_DB = os.environ.get("TESTING_DB_NAME", "test_db")

pg_url: str = f"postgresql+asyncpg://{_USER}:{_PASSWORD}@{_HOST}:{_PORT}/{_DB}"
pg_sync_url: str = f"postgresql+psycopg2://{_USER}:{_PASSWORD}@{_HOST}:{_PORT}/{_DB}"


@pytest.fixture(scope="session", autouse=True)
def _boot_test_db() -> None:
    """Create test DB if absent, migrate to head, truncate data."""
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    try:
        c = psycopg2.connect(host=_HOST, port=_PORT, user=_USER, password=_PASSWORD, dbname=_DB)
        c.close()
    except psycopg2.OperationalError:
        c = psycopg2.connect(
            host=_HOST, port=_PORT, user=_USER, password=_PASSWORD, dbname="postgres"
        )
        c.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with c.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(_DB)))
        c.close()

    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_sync_url)
    command.upgrade(cfg, "head")

    c = psycopg2.connect(host=_HOST, port=_PORT, user=_USER, password=_PASSWORD, dbname=_DB)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("TRUNCATE TABLE dsns, apps, projects RESTART IDENTITY CASCADE")
    c.close()


@pytest.fixture
def migrated_factory():
    from telemetria.db.session import make_session_factory

    return make_session_factory(pg_url)
