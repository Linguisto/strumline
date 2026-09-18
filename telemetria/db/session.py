"""Async SQLAlchemy session factory pinned to UTC.

``connect_args`` passes ``server_settings`` to asyncpg which sets
``TimeZone=UTC`` for every connection. Combined with ``TIMESTAMPTZ`` columns
this guarantees that Python datetimes received from PostgreSQL are
timezone-aware UTC objects.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(database_url: str) -> AsyncEngine:
    """Create an async engine with UTC session settings."""
    return create_async_engine(
        database_url,
        connect_args={"server_settings": {"TimeZone": "UTC"}},
        pool_pre_ping=True,
    )


def make_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Return an ``async_sessionmaker`` bound to *database_url*."""
    engine = make_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Yield a transactional ``AsyncSession``, committing on success."""
    async with factory() as session, session.begin():
        yield session
