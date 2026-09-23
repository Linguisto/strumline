"""App application service."""

from __future__ import annotations

import uuid
import zoneinfo
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from strumline.db.repositories import UNSET, AppRepository, ProjectRepository
from strumline.domain.entities import App
from strumline.domain.errors import OwnershipError, ValidationError


class AppService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AppRepository(session)
        self._projects = ProjectRepository(session)

    async def create(
        self,
        project_slug_or_id: str,
        slug: str,
        name: str,
        tz: str | None = None,
    ) -> App:
        if tz is not None:
            _validate_tz(tz)
        project = (
            await self._projects.get_by_slug(project_slug_or_id)
            if not _is_uuid(project_slug_or_id)
            else await self._projects.get_by_id(uuid.UUID(project_slug_or_id))
        )
        now = datetime.now(tz=UTC)
        try:
            app = App(
                id=uuid.uuid4(),
                project_id=project.id,
                slug=slug,
                name=name,
                timezone=tz,
                created_at=now,
                updated_at=now,
            )
        except ValueError as exc:
            raise ValidationError("slug", str(exc)) from exc
        return await self._repo.create(app)

    async def get(self, project_slug_or_id: str, app_slug_or_id: str) -> App:
        project = await self._resolve_project(project_slug_or_id)
        if _is_uuid(app_slug_or_id):
            app = await self._repo.get_by_id(uuid.UUID(app_slug_or_id))
            if app.project_id != project.id:
                raise OwnershipError("App", app_slug_or_id, str(project.id))
            return app
        return await self._repo.get_by_slug(project.id, app_slug_or_id)

    async def list_all(self, project_slug_or_id: str) -> list[App]:
        project = await self._resolve_project(project_slug_or_id)
        return await self._repo.list_by_project(project.id)

    async def update(
        self,
        project_slug_or_id: str,
        app_slug_or_id: str,
        *,
        name: str | None = None,
        tz: Any = UNSET,
    ) -> App:
        if not isinstance(tz, type(UNSET)) and tz is not None:
            _validate_tz(tz)
        app = await self.get(project_slug_or_id, app_slug_or_id)
        return await self._repo.update(app.id, name=name, tz=tz)

    async def delete(self, project_slug_or_id: str, app_slug_or_id: str) -> None:
        app = await self.get(project_slug_or_id, app_slug_or_id)
        await self._repo.delete(app.id)

    async def set_timezone(
        self, project_slug_or_id: str, app_slug_or_id: str, tz: str | None
    ) -> App:
        if tz is not None:
            _validate_tz(tz)
        app = await self.get(project_slug_or_id, app_slug_or_id)
        return await self._repo.update(app.id, tz=tz)

    async def _resolve_project(self, slug_or_id: str) -> Any:
        if _is_uuid(slug_or_id):
            return await self._projects.get_by_id(uuid.UUID(slug_or_id))
        return await self._projects.get_by_slug(slug_or_id)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _validate_tz(tz: str) -> None:
    try:
        zoneinfo.ZoneInfo(tz)
    except zoneinfo.ZoneInfoNotFoundError as err:
        raise ValidationError("timezone", f"Unknown IANA timezone: {tz!r}") from err
