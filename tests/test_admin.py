"""M6b unit tests for the admin REST API.

Tests cover:
- Disabled by default: /admin/v1 returns 404
- Enabled without key: APISettings validation fails
- Missing Authorization header: 401
- Wrong key: 401
- All CRUD routes happy paths
- Domain error mapping (404, 409, 422)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient
from pydantic import ValidationError

from telemetria.api.server import create_app
from telemetria.config import APISettings, CommonSettings

pytestmark = pytest.mark.unit

_KEY = "test-admin-key-abc123"
_AUTH = {"Authorization": f"Bearer {_KEY}"}
_BAD_AUTH = {"Authorization": "Bearer wrong-key"}

_P_ID = uuid4()
_A_ID = uuid4()
_T_ID = uuid4()


def _make_project(**kwargs):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from telemetria.domain.entities import Project

    defaults = dict(
        id=_P_ID,
        slug="my-proj",
        name="My Project",
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
        updated_at=datetime(2026, 9, 18, tzinfo=UTC),
    )
    defaults.update(kwargs)
    return Project(**defaults)


def _make_app(**kwargs):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from telemetria.domain.entities import App

    defaults = dict(
        id=_A_ID,
        project_id=_P_ID,
        slug="my-app",
        name="My App",
        timezone=None,
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
        updated_at=datetime(2026, 9, 18, tzinfo=UTC),
    )
    defaults.update(kwargs)
    return App(**defaults)


def _make_token(**kwargs):  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from telemetria.domain.entities import AuthToken

    defaults = dict(
        id=_T_ID,
        app_id=_A_ID,
        key_hash="abc" * 21 + "a",
        is_active=True,
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
        revoked_at=None,
    )
    defaults.update(kwargs)
    return AuthToken(**defaults)


def _enabled_app() -> object:
    """Create an API app with admin enabled and a mock DB session."""
    common = CommonSettings(app_key="")
    api_s = APISettings(admin_api_enabled=True, admin_api_key=_KEY)
    application = create_app(settings=common, api_settings=api_s)
    return application


def _client(application):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


# ---------------------------------------------------------------------------
# Runtime gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_disabled_returns_404() -> None:
    """When ADMIN_API_ENABLED=false, /admin/v1 routes return 404."""
    application = create_app(CommonSettings(), APISettings(admin_api_enabled=False))
    async with _client(application) as c:
        r = await c.get("/admin/v1/projects")
    assert r.status_code == 404


def test_admin_enabled_without_key_fails() -> None:
    """ADMIN_API_ENABLED=true without ADMIN_API_KEY raises validation error."""
    with pytest.raises(ValidationError):
        APISettings(admin_api_enabled=True, admin_api_key="")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_auth_header_401() -> None:
    application = _enabled_app()
    async with _client(application) as c:
        r = await c.get("/admin/v1/projects")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_key_401() -> None:
    application = _enabled_app()
    async with _client(application) as c:
        r = await c.get("/admin/v1/projects", headers=_BAD_AUTH)
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_projects() -> None:
    project = _make_project()
    with patch(
        "telemetria.control.projects.ProjectService.list_all", new=AsyncMock(return_value=[project])
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.get("/admin/v1/projects", headers=_AUTH)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["slug"] == "my-proj"
    assert data[0]["created_at"].endswith("Z")


@pytest.mark.asyncio
async def test_create_project() -> None:
    project = _make_project()
    with patch(
        "telemetria.control.projects.ProjectService.create", new=AsyncMock(return_value=project)
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.post(
                "/admin/v1/projects", json={"slug": "my-proj", "name": "My Project"}, headers=_AUTH
            )
    assert r.status_code == 201
    assert r.json()["slug"] == "my-proj"


@pytest.mark.asyncio
async def test_get_project_not_found() -> None:
    from telemetria.domain.errors import NotFoundError

    with patch(
        "telemetria.control.projects.ProjectService.get",
        new=AsyncMock(side_effect=NotFoundError("Project", "nope")),
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.get("/admin/v1/projects/nope", headers=_AUTH)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_project() -> None:
    with patch(
        "telemetria.control.projects.ProjectService.delete", new=AsyncMock(return_value=None)
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.delete("/admin/v1/projects/my-proj", headers=_AUTH)
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Apps CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_apps() -> None:
    app_obj = _make_app()
    with (
        patch("telemetria.control.apps.AppService.list_all", new=AsyncMock(return_value=[app_obj])),
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.get("/admin/v1/projects/my-proj/apps", headers=_AUTH)
    assert r.status_code == 200
    assert r.json()[0]["slug"] == "my-app"


@pytest.mark.asyncio
async def test_create_app_conflict() -> None:
    from telemetria.domain.errors import ConflictError

    with patch(
        "telemetria.control.apps.AppService.create",
        new=AsyncMock(side_effect=ConflictError("App", "slug", "my-app")),
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.post(
                "/admin/v1/projects/my-proj/apps",
                json={"slug": "my-app", "name": "My App"},
                headers=_AUTH,
            )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Auth tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_token_returns_key() -> None:
    token = _make_token()
    raw = "raw-secret-key-abc123"
    with (
        patch("telemetria.control.apps.AppService.get", new=AsyncMock(return_value=_make_app())),
        patch(
            "telemetria.control.auth_tokens.AuthTokenService.create",
            new=AsyncMock(return_value=(token, raw)),
        ),
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.post("/admin/v1/projects/my-proj/apps/my-app/tokens", headers=_AUTH)
    assert r.status_code == 201
    assert r.json()["key"] == raw


@pytest.mark.asyncio
async def test_list_tokens_no_key() -> None:
    """Token listing never exposes the key_hash."""
    token = _make_token()
    with (
        patch("telemetria.control.apps.AppService.get", new=AsyncMock(return_value=_make_app())),
        patch(
            "telemetria.control.auth_tokens.AuthTokenService.list_by_app",
            new=AsyncMock(return_value=[token]),
        ),
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.get("/admin/v1/projects/my-proj/apps/my-app/tokens", headers=_AUTH)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["key"] is None  # key is null in listings, only set at creation
    assert "key_hash" not in data[0]


@pytest.mark.asyncio
async def test_revoke_token() -> None:
    token = _make_token(is_active=False)
    with (
        patch("telemetria.control.apps.AppService.get", new=AsyncMock(return_value=_make_app())),
        patch(
            "telemetria.control.auth_tokens.AuthTokenService.revoke",
            new=AsyncMock(return_value=token),
        ),
    ):
        application = _enabled_app()
        async with _client(application) as c:
            r = await c.delete(
                f"/admin/v1/projects/my-proj/apps/my-app/tokens/{_T_ID}", headers=_AUTH
            )
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# OpenAPI docs gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docs_available_when_admin_enabled() -> None:
    """Scalar docs at / are available when ADMIN_API_ENABLED=true."""
    api_s = APISettings(admin_api_enabled=True, admin_api_key=_KEY)
    application = create_app(CommonSettings(), api_s)
    async with _client(application) as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert "scalar" in r.text.lower() or "openapi" in r.text.lower()


@pytest.mark.asyncio
async def test_docs_absent_when_admin_disabled() -> None:
    """Scalar docs at / return 404 when both admin and api_docs are disabled."""
    application = create_app(
        CommonSettings(), APISettings(admin_api_enabled=False, api_docs_enabled=False)
    )
    async with _client(application) as c:
        r = await c.get("/")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_routes_absent_when_disabled() -> None:
    """/admin/v1 routes return 404 when admin API is disabled."""
    application = create_app(CommonSettings(), APISettings(admin_api_enabled=False))
    async with _client(application) as c:
        r = await c.get("/admin/v1/projects")
    # No auth dependency registered — route doesn't exist
    assert r.status_code == 404
