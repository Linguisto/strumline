"""SQLAlchemy ORM models for the Telemetria control plane.

These map directly to the database schema managed by Alembic. Domain entity
dataclasses are constructed from these models by the repositories; the rest of
the application never imports SQLAlchemy directly.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from telemetria.db.base import Base, TimestampMixin


class ProjectModel(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    apps: Mapped[list[AppModel]] = relationship(
        "AppModel", back_populates="project", cascade="all, delete-orphan"
    )


class AppModel(Base, TimestampMixin):
    __tablename__ = "apps"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project: Mapped[ProjectModel] = relationship("ProjectModel", back_populates="apps")
    auth_tokens: Mapped[list[AuthTokenModel]] = relationship(
        "AuthTokenModel", back_populates="app", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_apps_project_slug"),)


class AuthTokenModel(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    app_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("apps.id", ondelete="CASCADE"),
        nullable=False,
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    app: Mapped[AppModel] = relationship("AppModel", back_populates="auth_tokens")
