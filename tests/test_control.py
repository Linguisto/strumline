"""M1-B: Control service tests.

Tests project, app, and DSN services against a real PostgreSQL instance.
Covers: create, conflict, not-found, ownership, timezone validation, revocation.
"""

from __future__ import annotations

import pytest

from telemetria.control.apps import AppService
from telemetria.control.dsns import DSNService
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
# DSNService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dsn_create_and_list(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("dsn-parent", "DSN Parent")
        app = await AppService(session).create("dsn-parent", "dsn-app", "DSN App")

    async with migrated_factory() as session, session.begin():
        dsn = await DSNService(session).create(app.id)

    assert dsn.is_active
    assert len(dsn.key) >= 40  # token_urlsafe(32) ≈ 43 chars
    assert dsn.revoked_at is None

    async with migrated_factory() as session, session.begin():
        dsns = await DSNService(session).list_by_app(app.id)
    assert any(d.id == dsn.id for d in dsns)


@pytest.mark.asyncio
async def test_dsn_revoke(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("revoke-parent", "Revoke Parent")
        app = await AppService(session).create("revoke-parent", "revoke-app", "Revoke App")
        dsn = await DSNService(session).create(app.id)

    async with migrated_factory() as session, session.begin():
        revoked = await DSNService(session).revoke(dsn.id, app.id)
    assert not revoked.is_active
    assert revoked.revoked_at is not None


@pytest.mark.asyncio
async def test_dsn_double_revoke_raises(migrated_factory) -> None:
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("dbl-revoke-parent", "Dbl Revoke")
        app = await AppService(session).create(
            "dbl-revoke-parent", "dbl-revoke-app", "Dbl Revoke App"
        )
        dsn = await DSNService(session).create(app.id)

    async with migrated_factory() as session, session.begin():
        await DSNService(session).revoke(dsn.id, app.id)

    with pytest.raises(AlreadyRevokedError):
        async with migrated_factory() as session, session.begin():
            await DSNService(session).revoke(dsn.id, app.id)


@pytest.mark.asyncio
async def test_dsn_ownership_check(migrated_factory) -> None:
    """Revoking a DSN via wrong app_id raises OwnershipError."""
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("dsn-own-parent", "DSN Own Parent")
        app1 = await AppService(session).create("dsn-own-parent", "dsn-own-app1", "App1")
        app2 = await AppService(session).create("dsn-own-parent", "dsn-own-app2", "App2")
        dsn = await DSNService(session).create(app1.id)

    with pytest.raises(OwnershipError):
        async with migrated_factory() as session, session.begin():
            await DSNService(session).revoke(dsn.id, app2.id)


@pytest.mark.asyncio
async def test_dsn_key_entropy(migrated_factory) -> None:
    """DSN keys should be ~43 characters (256 bits via token_urlsafe(32))."""
    async with migrated_factory() as session, session.begin():
        await ProjectService(session).create("entropy-parent", "Entropy Parent")
        app = await AppService(session).create("entropy-parent", "entropy-app", "Entropy App")
        dsn = await DSNService(session).create(app.id)

    # token_urlsafe(32) produces ceil(32*4/3) = 44 base64url chars, typically 43
    assert 40 <= len(dsn.key) <= 50, f"Unexpected key length: {len(dsn.key)}"
