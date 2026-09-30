"""M2-B: auth token resolver tests.

Tests use a real PostgreSQL instance (via testcontainers) and the migrated
schema. Covers: active token resolves, revoked token rejected, cache TTL, DB
failure outage policy.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import tests.conftest as conf
from strumline.control.apps import AppService
from strumline.control.auth_tokens import AuthTokenService
from strumline.control.projects import ProjectService
from strumline.db.session import make_session_factory
from strumline.ingest.resolver import (
    AUTH_TOKEN_CACHE_MAX_ENTRIES,
    AUTH_TOKEN_CACHE_TTL,
    AuthTokenResolver,
    AuthTokenResolverError,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def restricted_factory(
    _db_boot: None,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    """Create an isolated role matching the production ingest grants."""
    role = f"strumline_ingest_test_{uuid.uuid4().hex[:12]}"
    password = secrets.token_urlsafe(24)
    conn = psycopg2.connect(
        host=conf._HOST,
        port=conf._PORT,
        user=conf._USER,
        password=conf._PASSWORD,
        dbname=conf._DB,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(role)),
            (password,),
        )
        cur.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(conf._DB), sql.Identifier(role)
            )
        )
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        cur.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(role)))
        for table in ("auth_tokens", "apps", "projects"):
            cur.execute(
                sql.SQL("GRANT SELECT ON {} TO {}").format(
                    sql.Identifier(table), sql.Identifier(role)
                )
            )

    factory = make_session_factory(
        f"postgresql+asyncpg://{role}:{password}@{conf._HOST}:{conf._PORT}/{conf._DB}"
    )
    try:
        yield factory
    finally:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        conn.close()


@pytest.fixture
def resolver_factory(migrated_factory):
    """Return a AuthTokenResolver backed by the test DB."""
    return AuthTokenResolver(migrated_factory)


@pytest.fixture
async def project_app_token(migrated_factory):
    """Create a project, app, and active auth token with unique slugs."""
    import uuid as _uuid

    suffix = _uuid.uuid4().hex[:8]
    proj_slug = f"resolver-proj-{suffix}"
    app_slug = f"resolver-app-{suffix}"

    async with migrated_factory() as session, session.begin():
        project = await ProjectService(session).create(proj_slug, "Resolver Project")
        app = await AppService(session).create(proj_slug, app_slug, "Resolver App")
        token, raw_key = await AuthTokenService(session).create(app.id)
    return project, app, token, raw_key


# ---------------------------------------------------------------------------
# Active auth token resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_active_token(resolver_factory, project_app_token):
    project, app, token, raw_key = project_app_token
    resolver = resolver_factory

    result = await resolver.resolve(raw_key)
    assert result.token_id == str(token.id)
    assert result.app_id == str(app.id)
    assert result.app_slug == app.slug
    assert result.project_id == str(project.id)
    assert result.project_slug == project.slug


@pytest.mark.asyncio
async def test_restricted_role_resolves_token(restricted_factory, project_app_token):
    project, app, token, raw_key = project_app_token
    result = await AuthTokenResolver(restricted_factory).resolve(raw_key)
    assert result.token_id == str(token.id)
    assert result.app_id == str(app.id)
    assert result.project_id == str(project.id)


@pytest.mark.asyncio
async def test_restricted_role_cannot_write_or_create(restricted_factory):
    async with restricted_factory() as session:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(text("DELETE FROM auth_tokens"))
        await session.rollback()
        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(text("CREATE TABLE ingest_must_not_create (id integer)"))


# ---------------------------------------------------------------------------
# Unknown token rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_unknown_token(resolver_factory):
    resolver = resolver_factory
    with pytest.raises(AuthTokenResolverError):
        await resolver.resolve("nonexistent-key-12345")


# ---------------------------------------------------------------------------
# Revoked token rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_revoked_token(migrated_factory, project_app_token):
    project, app, token, raw_key = project_app_token
    resolver = AuthTokenResolver(migrated_factory, ttl=AUTH_TOKEN_CACHE_TTL)

    # Revoke the auth token
    async with migrated_factory() as session, session.begin():
        await AuthTokenService(session).revoke(token.id, app.id)

    with pytest.raises(AuthTokenResolverError, match="revoked"):
        await resolver.resolve(raw_key)


# ---------------------------------------------------------------------------
# Cache: second resolve hits cache (no DB call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_uses_cache(migrated_factory, project_app_token):
    _, _, token, raw_key = project_app_token
    resolver = AuthTokenResolver(migrated_factory, ttl=60)

    # First call populates cache
    result1 = await resolver.resolve(raw_key)
    # Patch _query to ensure it is NOT called on second resolve
    with patch.object(resolver, "_query", new_callable=AsyncMock) as mock_query:
        result2 = await resolver.resolve(raw_key)
        mock_query.assert_not_called()

    assert result1.token_id == result2.token_id


# ---------------------------------------------------------------------------
# Cache: expired entry triggers fresh DB query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_expires(migrated_factory, project_app_token):
    _, _, token, raw_key = project_app_token
    resolver = AuthTokenResolver(migrated_factory, ttl=0)  # TTL=0 → always expired

    result1 = await resolver.resolve(raw_key)

    call_count = 0
    original_query = resolver._query

    async def counting_query(key: str):
        nonlocal call_count
        call_count += 1
        return await original_query(key)

    with patch.object(resolver, "_query", side_effect=counting_query):
        result2 = await resolver.resolve(raw_key)

    assert call_count == 1  # cache expired, DB was hit again
    assert result1.token_id == result2.token_id


# ---------------------------------------------------------------------------
# Cache miss + DB failure → fail closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_failure_on_cache_miss_fails_closed(migrated_factory):
    resolver = AuthTokenResolver(migrated_factory, ttl=60)

    async def failing_query(key: str):
        raise RuntimeError("simulated DB outage")

    with (
        patch.object(resolver, "_query", side_effect=failing_query),
        pytest.raises(AuthTokenResolverError, match="unavailable"),
    ):
        await resolver.resolve("some-key")


# ---------------------------------------------------------------------------
# DB failure with stale cache → serve cached value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_failure_serves_stale_cache(migrated_factory, project_app_token):
    _, _, token, raw_key = project_app_token
    resolver = AuthTokenResolver(migrated_factory, ttl=3600)

    # Warm the cache
    result1 = await resolver.resolve(raw_key)

    # Now DB fails — should still return cached value
    async def failing_query(key: str):
        raise RuntimeError("simulated DB outage")

    with patch.object(resolver, "_query", side_effect=failing_query):
        result2 = await resolver.resolve(raw_key)

    assert result1.token_id == result2.token_id


@pytest.mark.asyncio
async def test_cache_is_bounded_and_does_not_store_raw_keys(migrated_factory):
    resolver = AuthTokenResolver(migrated_factory, ttl=60, max_entries=3)

    for index in range(5):
        with pytest.raises(AuthTokenResolverError):
            await resolver.resolve(f"unknown-secret-{index}")

    assert len(resolver._cache) == 3
    assert all("unknown-secret" not in cache_key for cache_key in resolver._cache)


def test_cache_capacity_must_be_positive(migrated_factory):
    with pytest.raises(ValueError, match="max_entries"):
        AuthTokenResolver(migrated_factory, max_entries=0)


def test_default_cache_capacity_is_bounded(migrated_factory):
    resolver = AuthTokenResolver(migrated_factory)
    assert resolver._max_entries == AUTH_TOKEN_CACHE_MAX_ENTRIES


@pytest.mark.asyncio
async def test_db_failure_log_redacts_exception_message(migrated_factory, caplog):
    resolver = AuthTokenResolver(migrated_factory)

    async def failing_query(key_hash: str):
        raise RuntimeError("password=should-never-appear")

    with (
        patch.object(resolver, "_query", side_effect=failing_query),
        pytest.raises(AuthTokenResolverError),
    ):
        await resolver.resolve("raw-token")

    assert "RuntimeError" in caplog.text
    assert "should-never-appear" not in caplog.text
    assert "raw-token" not in caplog.text
