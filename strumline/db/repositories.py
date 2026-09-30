"""Repositories for Project, App, and AuthToken.

Repositories translate between SQLAlchemy ORM models and pure domain
dataclasses. All methods accept an ``AsyncSession`` and are called inside a
transaction managed by the control services.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strumline.db.models import AppModel, AuthTokenModel, ProjectModel
from strumline.domain.entities import UNSET, App, AuthToken, Project
from strumline.domain.errors import (
    AlreadyRevokedError,
    ConflictError,
    NotFoundError,
)

# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _project_from_model(m: ProjectModel) -> Project:
    return Project(
        id=m.id,
        slug=m.slug,
        name=m.name,
        created_at=_ensure_utc(m.created_at),
        updated_at=_ensure_utc(m.updated_at),
    )


def _app_from_model(m: AppModel) -> App:
    return App(
        id=m.id,
        project_id=m.project_id,
        slug=m.slug,
        name=m.name,
        timezone=m.timezone,
        created_at=_ensure_utc(m.created_at),
        updated_at=_ensure_utc(m.updated_at),
    )


def _auth_token_from_model(m: AuthTokenModel) -> AuthToken:
    return AuthToken(
        id=m.id,
        app_id=m.app_id,
        key_hash=m.key_hash,
        is_active=m.is_active,
        created_at=_ensure_utc(m.created_at),
        revoked_at=_ensure_utc(m.revoked_at) if m.revoked_at is not None else None,
    )


# ---------------------------------------------------------------------------
# ProjectRepository
# ---------------------------------------------------------------------------


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, project: Project) -> Project:
        model = ProjectModel(
            id=project.id,
            slug=project.slug,
            name=project.name,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
        self._s.add(model)
        try:
            await self._s.flush()
        except IntegrityError as err:
            raise ConflictError("Project", "slug", project.slug) from err
        return _project_from_model(model)

    async def get_by_id(self, project_id: UUID) -> Project:
        model = await self._s.get(ProjectModel, project_id)
        if model is None:
            raise NotFoundError("Project", str(project_id))
        return _project_from_model(model)

    async def get_by_slug(self, slug: str) -> Project:
        result = await self._s.execute(select(ProjectModel).where(ProjectModel.slug == slug))
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("Project", slug)
        return _project_from_model(model)

    async def list_all(self) -> list[Project]:
        result = await self._s.execute(select(ProjectModel).order_by(ProjectModel.slug))
        return [_project_from_model(m) for m in result.scalars()]

    async def update(self, project_id: UUID, *, name: str) -> Project:
        model = await self._s.get(ProjectModel, project_id)
        if model is None:
            raise NotFoundError("Project", str(project_id))
        model.name = name
        model.updated_at = datetime.now(tz=UTC)
        await self._s.flush()
        return _project_from_model(model)

    async def delete(self, project_id: UUID) -> None:
        model = await self._s.get(ProjectModel, project_id)
        if model is None:
            raise NotFoundError("Project", str(project_id))
        await self._s.delete(model)
        await self._s.flush()


# ---------------------------------------------------------------------------
# AppRepository
# ---------------------------------------------------------------------------


class AppRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, app: App) -> App:
        model = AppModel(
            id=app.id,
            project_id=app.project_id,
            slug=app.slug,
            name=app.name,
            timezone=app.timezone,
            created_at=app.created_at,
            updated_at=app.updated_at,
        )
        self._s.add(model)
        try:
            await self._s.flush()
        except IntegrityError as err:
            raise ConflictError("App", "slug", f"{app.project_id}/{app.slug}") from err
        return _app_from_model(model)

    async def get_by_id(self, app_id: UUID) -> App:
        model = await self._s.get(AppModel, app_id)
        if model is None:
            raise NotFoundError("App", str(app_id))
        return _app_from_model(model)

    async def get_by_slug(self, project_id: UUID, slug: str) -> App:
        result = await self._s.execute(
            select(AppModel).where(AppModel.project_id == project_id, AppModel.slug == slug)
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError("App", f"{project_id}/{slug}")
        return _app_from_model(model)

    async def list_by_project(self, project_id: UUID) -> list[App]:
        result = await self._s.execute(
            select(AppModel).where(AppModel.project_id == project_id).order_by(AppModel.slug)
        )
        return [_app_from_model(m) for m in result.scalars()]

    async def update(
        self,
        app_id: UUID,
        *,
        name: str | None = None,
        tz: Any = UNSET,  # str | None | UNSET; None clears the timezone
    ) -> App:
        model = await self._s.get(AppModel, app_id)
        if model is None:
            raise NotFoundError("App", str(app_id))
        if name is not None:
            model.name = name
        if tz is not UNSET:
            model.timezone = tz
        model.updated_at = datetime.now(tz=UTC)
        await self._s.flush()
        return _app_from_model(model)

    async def delete(self, app_id: UUID) -> None:
        model = await self._s.get(AppModel, app_id)
        if model is None:
            raise NotFoundError("App", str(app_id))
        await self._s.delete(model)
        await self._s.flush()


# ---------------------------------------------------------------------------
# AuthTokenRepository
# ---------------------------------------------------------------------------


class AuthTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, token: AuthToken) -> AuthToken:
        model = AuthTokenModel(
            id=token.id,
            app_id=token.app_id,
            key_hash=token.key_hash,
            is_active=token.is_active,
            created_at=token.created_at,
            revoked_at=token.revoked_at,
        )
        self._s.add(model)
        await self._s.flush()
        return _auth_token_from_model(model)

    async def get_by_id(self, token_id: UUID) -> AuthToken:
        model = await self._s.get(AuthTokenModel, token_id)
        if model is None:
            raise NotFoundError("AuthToken", str(token_id))
        return _auth_token_from_model(model)

    async def list_by_app(self, app_id: UUID) -> list[AuthToken]:
        result = await self._s.execute(
            select(AuthTokenModel)
            .where(AuthTokenModel.app_id == app_id)
            .order_by(AuthTokenModel.created_at)
        )
        return [_auth_token_from_model(m) for m in result.scalars()]

    async def revoke(self, token_id: UUID) -> AuthToken:
        model = await self._s.get(AuthTokenModel, token_id)
        if model is None:
            raise NotFoundError("AuthToken", str(token_id))
        if not model.is_active:
            raise AlreadyRevokedError(str(token_id))
        model.is_active = False
        model.revoked_at = datetime.now(tz=UTC)
        await self._s.flush()
        return _auth_token_from_model(model)
