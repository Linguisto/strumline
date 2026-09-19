"""M2-B: DSN resolver tests.

Tests use a real PostgreSQL instance (via testcontainers) and the migrated
schema. Covers: active token resolves, revoked DSN rejected, cache TTL, DB
failure outage policy.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from telemetria.control.apps import AppService
from telemetria.control.auth_tokens import AuthTokenService
from telemetria.control.projects import ProjectService
from telemetria.ingest.resolver import (
    AUTH_TOKEN_CACHE_TTL,
    AuthTokenResolver,
    AuthTokenResolverError,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def resolver_factory(migrated_factory):
    """Return a AuthTokenResolver backed by the test DB."""
    return AuthTokenResolver(migrated_factory)


@pytest.fixture
async def project_app_token(migrated_factory):
    """Create a project, app, and active DSN with unique slugs. Returns (project, app, dsn)."""
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
# Active DSN resolves
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
