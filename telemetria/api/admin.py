"""Admin REST API — CRUD for projects, apps, and auth tokens.

Mounted at ``/admin/v1`` only when ``ADMIN_API_ENABLED=true``.
Every route requires ``Authorization: Bearer <ADMIN_API_KEY>`` with
constant-time comparison to prevent timing attacks.

All routes have typed response models so Scalar shows the full resource
schema. Domain errors map centrally to stable HTTP envelopes.

Routes
------
GET    /admin/v1/projects
POST   /admin/v1/projects
GET    /admin/v1/projects/{project_slug}
PATCH  /admin/v1/projects/{project_slug}
DELETE /admin/v1/projects/{project_slug}

GET    /admin/v1/projects/{project_slug}/apps
POST   /admin/v1/projects/{project_slug}/apps
GET    /admin/v1/projects/{project_slug}/apps/{app_slug}
PATCH  /admin/v1/projects/{project_slug}/apps/{app_slug}
DELETE /admin/v1/projects/{project_slug}/apps/{app_slug}

GET    /admin/v1/projects/{project_slug}/apps/{app_slug}/tokens
POST   /admin/v1/projects/{project_slug}/apps/{app_slug}/tokens
DELETE /admin/v1/projects/{project_slug}/apps/{app_slug}/tokens/{token_id}
"""

from __future__ import annotations

import hmac
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from telemetria.control.apps import AppService
from telemetria.control.auth_tokens import AuthTokenService
from telemetria.control.projects import ProjectService
from telemetria.db.repositories import UNSET
from telemetria.domain.errors import TelemetriaError

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def make_auth_dependency(api_key: str):  # type: ignore[no-untyped-def]
    async def _check(
        authorization: str | None = Header(default=None, alias="Authorization"),  # noqa: B008
    ) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Bearer token required")
        token = authorization[len("Bearer ") :]
        if not hmac.compare_digest(token.encode(), api_key.encode()):
            raise HTTPException(status_code=401, detail="Invalid admin API key")

    return _check


# ---------------------------------------------------------------------------
# Session dependency
# ---------------------------------------------------------------------------


def make_session_dependency(  # type: ignore[no-untyped-def]
    session_factory: Any,
):
    async def _get_session() -> Any:
        async with session_factory() as session, session.begin():
            yield session

    return _get_session


# ---------------------------------------------------------------------------
# Domain error → HTTP mapping
# ---------------------------------------------------------------------------


def _domain_response(exc: TelemetriaError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    slug: str
    name: str


class ProjectUpdate(BaseModel):
    name: str


class AppCreate(BaseModel):
    slug: str
    name: str
    timezone: str | None = None


class AppUpdate(BaseModel):
    name: str | None = None
    timezone: str | None = None
    clear_timezone: bool = False


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ProjectResponse(BaseModel):
    id: str
    slug: str
    name: str
    created_at: str
    updated_at: str


class AppResponse(BaseModel):
    id: str
    project_id: str
    slug: str
    name: str
    timezone: str | None
    created_at: str
    updated_at: str


class AuthTokenResponse(BaseModel):
    id: str
    app_id: str
    is_active: bool
    created_at: str
    revoked_at: str | None
    key: str | None = None  # only present at creation time


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _utc(dt: Any) -> str | None:
    if dt is None:
        return None
    result: str = dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return result


def _project_out(p: Any) -> ProjectResponse:
    return ProjectResponse(
        id=str(p.id),
        slug=p.slug,
        name=p.name,
        created_at=_utc(p.created_at) or "",
        updated_at=_utc(p.updated_at) or "",
    )


def _app_out(a: Any) -> AppResponse:
    return AppResponse(
        id=str(a.id),
        project_id=str(a.project_id),
        slug=a.slug,
        name=a.name,
        timezone=a.timezone,
        created_at=_utc(a.created_at) or "",
        updated_at=_utc(a.updated_at) or "",
    )


def _token_out(t: Any, raw_key: str | None = None) -> AuthTokenResponse:
    return AuthTokenResponse(
        id=str(t.id),
        app_id=str(t.app_id),
        is_active=t.is_active,
        created_at=_utc(t.created_at) or "",
        revoked_at=_utc(t.revoked_at),
        key=raw_key,
    )


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def make_admin_router(
    session_factory: Any,
    api_key: str,
    app_key: str = "",
) -> APIRouter:
    """Build and return the /admin/v1 router."""

    auth = make_auth_dependency(api_key)
    get_session = make_session_dependency(session_factory)

    router = APIRouter(prefix="/admin/v1", dependencies=[Depends(auth)])

    # -----------------------------------------------------------------------
    # Projects
    # -----------------------------------------------------------------------

    @router.get("/projects", tags=["Projects"], response_model=list[ProjectResponse])
    async def list_projects(
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            projects = await ProjectService(session).list_all()
            return [_project_out(p) for p in projects]
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.post("/projects", tags=["Projects"], status_code=201, response_model=ProjectResponse)
    async def create_project(
        body: ProjectCreate,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            p = await ProjectService(session).create(slug=body.slug, name=body.name)
            return _project_out(p)
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.get("/projects/{project_slug}", tags=["Projects"], response_model=ProjectResponse)
    async def get_project(
        project_slug: str,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            p = await ProjectService(session).get(project_slug)
            return _project_out(p)
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.patch("/projects/{project_slug}", tags=["Projects"], response_model=ProjectResponse)
    async def update_project(
        project_slug: str,
        body: ProjectUpdate,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            p = await ProjectService(session).update(project_slug, name=body.name)
            return _project_out(p)
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.delete("/projects/{project_slug}", tags=["Projects"], status_code=204)
    async def delete_project(
        project_slug: str,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> None:
        try:
            await ProjectService(session).delete(project_slug)
        except TelemetriaError as exc:
            raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc

    # -----------------------------------------------------------------------
    # Apps
    # -----------------------------------------------------------------------

    @router.get("/projects/{project_slug}/apps", tags=["Apps"], response_model=list[AppResponse])
    async def list_apps(
        project_slug: str,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            apps = await AppService(session).list_all(project_slug)
            return [_app_out(a) for a in apps]
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.post(
        "/projects/{project_slug}/apps",
        tags=["Apps"],
        status_code=201,
        response_model=AppResponse,
    )
    async def create_app(
        project_slug: str,
        body: AppCreate,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            a = await AppService(session).create(
                project_slug, body.slug, body.name, tz=body.timezone
            )
            return _app_out(a)
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.get(
        "/projects/{project_slug}/apps/{app_slug}",
        tags=["Apps"],
        response_model=AppResponse,
    )
    async def get_app(
        project_slug: str,
        app_slug: str,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            a = await AppService(session).get(project_slug, app_slug)
            return _app_out(a)
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.patch(
        "/projects/{project_slug}/apps/{app_slug}",
        tags=["Apps"],
        response_model=AppResponse,
    )
    async def update_app(
        project_slug: str,
        app_slug: str,
        body: AppUpdate,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            tz: Any = UNSET
            if body.clear_timezone:
                tz = None
            elif body.timezone is not None:
                tz = body.timezone
            a = await AppService(session).update(project_slug, app_slug, name=body.name, tz=tz)
            return _app_out(a)
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.delete("/projects/{project_slug}/apps/{app_slug}", tags=["Apps"], status_code=204)
    async def delete_app(
        project_slug: str,
        app_slug: str,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> None:
        try:
            await AppService(session).delete(project_slug, app_slug)
        except TelemetriaError as exc:
            raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc

    # -----------------------------------------------------------------------
    # Auth tokens
    # -----------------------------------------------------------------------

    @router.get(
        "/projects/{project_slug}/apps/{app_slug}/tokens",
        tags=["Auth Tokens"],
        response_model=list[AuthTokenResponse],
    )
    async def list_tokens(
        project_slug: str,
        app_slug: str,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            app_obj = await AppService(session).get(project_slug, app_slug)
            tokens = await AuthTokenService(session, app_key).list_by_app(app_obj.id)
            return [_token_out(t) for t in tokens]
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.post(
        "/projects/{project_slug}/apps/{app_slug}/tokens",
        tags=["Auth Tokens"],
        status_code=201,
        response_model=AuthTokenResponse,
    )
    async def create_token(
        project_slug: str,
        app_slug: str,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> Any:
        try:
            app_obj = await AppService(session).get(project_slug, app_slug)
            token, raw_key = await AuthTokenService(session, app_key).create(app_obj.id)
            return _token_out(token, raw_key=raw_key)
        except TelemetriaError as exc:
            return _domain_response(exc)

    @router.delete(
        "/projects/{project_slug}/apps/{app_slug}/tokens/{token_id}",
        tags=["Auth Tokens"],
        status_code=204,
    )
    async def revoke_token(
        project_slug: str,
        app_slug: str,
        token_id: str,
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> None:
        try:
            app_obj = await AppService(session).get(project_slug, app_slug)
            await AuthTokenService(session, app_key).revoke(uuid.UUID(token_id), app_obj.id)
        except TelemetriaError as exc:
            raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc

    return router
