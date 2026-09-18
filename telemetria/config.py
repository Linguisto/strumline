"""Shared configuration primitives for all Telemetria processes.

Each process imports only the settings group it owns. ``BaseSettings`` reads
values from environment variables and an optional ``.env`` file. Invalid or
missing required values raise a ``ValidationError`` at import time, which
causes the process to exit with a clear message rather than failing silently
later.

UTC is the only storage and transmission timezone. ``APP_TIMEZONE`` is an
optional IANA key used exclusively for human-facing display; it never affects
persisted or transmitted timestamps.
"""

from __future__ import annotations

import zoneinfo
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Base(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=False,
        extra="ignore",
    )


class DatabaseSettings(_Base):
    """Database connection settings.

    URLs are assembled from parts at runtime — never stored as a single string.

    App DB (control plane, CLI, migrations):
        postgresql+asyncpg://<DB_USER>:<DB_PASSWORD>@<DB_HOST>:<DB_PORT>/<DB_NAME>

    Ingest role (read-only DSN resolver, same DB, different credentials):
        postgresql+asyncpg://<INGEST_DB_USER>:<INGEST_DB_PASSWORD>@<DB_HOST>:<DB_PORT>/<DB_NAME>
    """

    # App database
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "telemetria"
    db_user: str = "telemetria"
    db_password: str = "telemetria"

    # Ingest role — same host/port/database as the app DB, read-only credentials.
    # Populated after running the bootstrap script.
    ingest_db_user: str = "telemetria_ingest"
    ingest_db_password: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def ingest_database_url(self) -> str:
        """Empty string if the ingest role has not been bootstrapped yet."""
        if not self.ingest_db_password:
            return ""
        return (
            f"postgresql+asyncpg://{self.ingest_db_user}:{self.ingest_db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


class CommonSettings(_Base):
    """Settings shared across all processes."""

    app_timezone: str = ""
    """Optional IANA display timezone (e.g. 'Europe/Berlin'). Empty means UTC.
    Affects presentation only; all storage and transmission is UTC."""

    metrics_enabled: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("app_timezone", mode="after")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        if v:
            try:
                zoneinfo.ZoneInfo(v)
            except zoneinfo.ZoneInfoNotFoundError as exc:
                raise ValueError(f"Unknown IANA timezone: {v!r}") from exc
        return v


class APISettings(_Base):
    """Settings for the API process (control plane + optional admin REST)."""

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @model_validator(mode="after")
    def _validate_port(self) -> APISettings:
        if not (1 <= self.api_port <= 65535):
            raise ValueError(f"API_PORT must be 1–65535, got {self.api_port}")
        return self


class IngestSettings(_Base):
    """Settings for the ingest process (HTTP receiver + IPC writer)."""

    ingest_host: str = "0.0.0.0"
    ingest_port: int = 8001
    ipc_socket_path: str = "/var/run/telemetria/ipc.sock"

    # Admission limits
    max_payload_bytes: int = 1 * 1024 * 1024  # 1 MiB
    max_batch_events: int = 300
    queue_size: int = 10_000

    @model_validator(mode="after")
    def _validate_port(self) -> IngestSettings:
        if not (1 <= self.ingest_port <= 65535):
            raise ValueError(f"INGEST_PORT must be 1–65535, got {self.ingest_port}")
        return self


class ProcessorSettings(_Base):
    """Settings for the processor process (IPC reader, batching, sink dispatch)."""

    processor_host: str = "0.0.0.0"
    processor_port: int = 8002
    ipc_socket_path: str = "/var/run/telemetria/ipc.sock"

    # Sink selection
    sink_provider: str = "null"

    # Batch flush triggers
    batch_max_size: int = 500
    batch_max_wait_seconds: float = 1.0

    # Sink retry policy
    sink_max_retries: int = 3
    sink_retry_base_seconds: float = 0.25
    sink_retry_max_seconds: float = 10.0

    @model_validator(mode="after")
    def _validate_port(self) -> ProcessorSettings:
        if not (1 <= self.processor_port <= 65535):
            raise ValueError(f"PROCESSOR_PORT must be 1–65535, got {self.processor_port}")
        return self
