"""Project application service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from strumline.db.repositories import ProjectRepository
from strumline.domain.entities import Project
from strumline.domain.errors import ValidationError


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = ProjectRepository(session)

    async def create(self, slug: str, name: str) -> Project:
        now = datetime.now(tz=UTC)
        try:
            project = Project(
                id=uuid.uuid4(),
                slug=slug,
                name=name,
                created_at=now,
                updated_at=now,
            )
        except ValueError as exc:
            raise ValidationError("slug", str(exc)) from exc
        return await self._repo.create(project)

    async def get(self, slug_or_id: str) -> Project:
        try:
            uid = uuid.UUID(slug_or_id)
            return await self._repo.get_by_id(uid)
        except ValueError:
            return await self._repo.get_by_slug(slug_or_id)

    async def list_all(self) -> list[Project]:
        return await self._repo.list_all()

    async def update(self, slug_or_id: str, *, name: str) -> Project:
        project = await self.get(slug_or_id)
        return await self._repo.update(project.id, name=name)

    async def delete(self, slug_or_id: str) -> None:
        project = await self.get(slug_or_id)
        await self._repo.delete(project.id)
