"""Test database setup.

Integration tests inherit from ``DatabaseTestCase`` to declare they need a DB.
Unit tests are plain classes or functions with no base class.

    class TestMyFeature(DatabaseTestCase):
        async def test_something(self, migrated_factory): ...

Configuration: DB_HOST / DB_PORT / DB_USER / DB_PASSWORD (same as the app).
Override with TESTING_DB_* if needed. DB name is always ``test_db``.
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


# ---------------------------------------------------------------------------
# One-time DB boot (session-scoped, called lazily by DatabaseTestCase)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _db_boot() -> None:
    """Create test_db if absent, migrate to head, truncate data."""
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
def migrated_factory(_db_boot: None):
    from telemetria.db.session import make_session_factory

    return make_session_factory(pg_url)


# ---------------------------------------------------------------------------
# Base class for integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.usefixtures("_db_boot")
class DatabaseTestCase:
    """Inherit from this class to declare that a test requires a database.

    The database is booted once per session (migrations + truncate).
    Tests that don't inherit this class never touch the DB.
    """
