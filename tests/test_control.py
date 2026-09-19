"""M1-B: Control service tests.

Tests project, app, and DSN services against a real PostgreSQL instance.
Covers: create, conflict, not-found, ownership, timezone validation, revocation.
"""

from __future__ import annotations

import pytest

from telemetria.control.apps import AppService
from telemetria.control.auth_tokens import AuthTokenService
from telemetria.control.projects import ProjectService
from telemetria.domain.errors import (
    AlreadyRevokedError,
    ConflictError,
    NotFoundError,
    OwnershipError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# ProjectService
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_project_create_and_get(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        svc = ProjectService(session)
        p = await svc.create("test-project-1", "Test Project 1")
    assert p.slug == "test-project-1"

    async with migrated_factory() as session, session.begin():
        svc = ProjectService(session)
        fetched = await svc.get("test-project-1")
    assert fetched.id == p.id


@pytest.mark.asyncio
async def test_project_slug_conflict(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("conflict-slug", "First")

    with pytest.raises(ConflictError):
        async with migrated_factory() as session, session.begin():
            await ProjectService(session).create("conflict-slug", "Second")


@pytest.mark.asyncio
async def test_project_not_found(migrated_factory) -> None:
    with pytest.raises(NotFoundError):
        async with migrated_factory() as session, session.begin():
            await ProjectService(session).get("does-not-exist")


@pytest.mark.asyncio
async def test_project_update(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        p = await ProjectService(session).create("update-me", "Original")

    async with migrated_factory() as session, session.begin():
        updated = await ProjectService(session).update(str(p.id), name="Updated")
    assert updated.name == "Updated"
    assert updated.id == p.id


@pytest.mark.asyncio
async def test_project_delete(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        p = await ProjectService(session).create("delete-me", "Delete Me")

    async with migrated_factory() as session, session.begin():
        await ProjectService(session).delete(str(p.id))

    with pytest.raises(NotFoundError):
        async with migrated_factory() as session, session.begin():
            await ProjectService(session).get(str(p.id))


# ---------------------------------------------------------------------------
# AppService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_create_and_list(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        p = await ProjectService(session).create("app-parent", "App Parent")

    async with migrated_factory() as session, session.begin():
        app = await AppService(session).create("app-parent", "my-app", "My App")
    assert app.project_id == p.id
    assert app.timezone is None

    async with migrated_factory() as session, session.begin():
        apps = await AppService(session).list_all("app-parent")
    assert any(a.id == app.id for a in apps)


@pytest.mark.asyncio
async def test_app_timezone_valid(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("tz-parent", "TZ Parent")

    async with migrated_factory() as session, session.begin():
        app = await AppService(session).create("tz-parent", "tz-app", "TZ App", tz="Europe/Berlin")
    assert app.timezone == "Europe/Berlin"


@pytest.mark.asyncio
async def test_app_timezone_invalid(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("tz-invalid-parent", "TZ Invalid")

    with pytest.raises(ValidationError):
        async with migrated_factory() as session, session.begin():
            await AppService(session).create(
                "tz-invalid-parent", "bad-tz", "Bad TZ", tz="Not/ATimezone"
            )


@pytest.mark.asyncio
async def test_app_set_and_clear_timezone(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("tz-set-parent", "TZ Set")
        app = await AppService(session).create("tz-set-parent", "tz-set-app", "TZ Set App")

    async with migrated_factory() as session, session.begin():
        updated = await AppService(session).set_timezone("tz-set-parent", str(app.id), "Asia/Tokyo")
    assert updated.timezone == "Asia/Tokyo"

    async with migrated_factory() as session, session.begin():
        cleared = await AppService(session).set_timezone("tz-set-parent", str(app.id), None)
    assert cleared.timezone is None


@pytest.mark.asyncio
async def test_app_ownership_check(migrated_factory) -> None:
    """Getting an app by ID using a mismatched project raises OwnershipError."""
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("owner-p1", "Owner P1")
        await ProjectService(session).create("owner-p2", "Owner P2")

    async with migrated_factory() as session, session.begin():
        app = await AppService(session).create("owner-p1", "owned-app", "Owned App")

    with pytest.raises(OwnershipError):
        async with migrated_factory() as session, session.begin():
            await AppService(session).get("owner-p2", str(app.id))


# ---------------------------------------------------------------------------
# AuthTokenService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dsn_create_and_list(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("dsn-parent", "DSN Parent")
        app = await AppService(session).create("dsn-parent", "dsn-app", "DSN App")

    async with migrated_factory() as session, session.begin():
        token, raw_key = await AuthTokenService(session).create(app.id)

    assert token.is_active
    assert len(raw_key) >= 40  # token_urlsafe(32) ≈ 43 chars
    assert token.revoked_at is None

    async with migrated_factory() as session, session.begin():
        tokens = await AuthTokenService(session).list_by_app(app.id)
    assert any(d.id == token.id for d in tokens)


@pytest.mark.asyncio
async def test_dsn_revoke(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("revoke-parent", "Revoke Parent")
        app = await AppService(session).create("revoke-parent", "revoke-app", "Revoke App")
        token, raw_key = await AuthTokenService(session).create(app.id)

    async with migrated_factory() as session, session.begin():
        revoked = await AuthTokenService(session).revoke(token.id, app.id)
    assert not revoked.is_active
    assert revoked.revoked_at is not None


@pytest.mark.asyncio
async def test_dsn_double_revoke_raises(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("dbl-revoke-parent", "Dbl Revoke")
        app = await AppService(session).create(
            "dbl-revoke-parent", "dbl-revoke-app", "Dbl Revoke App"
        )
        token, raw_key = await AuthTokenService(session).create(app.id)

    async with migrated_factory() as session, session.begin():
        await AuthTokenService(session).revoke(token.id, app.id)

    with pytest.raises(AlreadyRevokedError):
        async with migrated_factory() as session, session.begin():
            await AuthTokenService(session).revoke(token.id, app.id)


@pytest.mark.asyncio
async def test_dsn_ownership_check(migrated_factory) -> None:
    """Revoking a DSN via wrong app_id raises OwnershipError."""
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("dsn-own-parent", "DSN Own Parent")
        app1 = await AppService(session).create("dsn-own-parent", "dsn-own-app1", "App1")
        app2 = await AppService(session).create("dsn-own-parent", "dsn-own-app2", "App2")
        token_own, _ = await AuthTokenService(session).create(app1.id)

    with pytest.raises(OwnershipError):
        async with migrated_factory() as session, session.begin():
            await AuthTokenService(session).revoke(token_own.id, app2.id)


@pytest.mark.asyncio
async def test_dsn_key_entropy(migrated_factory) -> None:
    """DSN keys should be ~43 characters (256 bits via token_urlsafe(32))."""
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("entropy-parent", "Entropy Parent")
        app = await AppService(session).create("entropy-parent", "entropy-app", "Entropy App")
        token, raw_key = await AuthTokenService(session).create(app.id)

    # token_urlsafe(32) produces ceil(32*4/3) = 44 base64url chars, typically 43
    assert 40 <= len(raw_key) <= 50, f"Unexpected key length: {len(raw_key)}"
