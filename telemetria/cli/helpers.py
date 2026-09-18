"""Shared CLI helpers: output formatting, error handling, async runner."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from datetime import datetime
from typing import Any
from uuid import UUID

import typer

from telemetria.config import DatabaseSettings
from telemetria.db.session import make_session_factory
from telemetria.domain.errors import TelemetriaError


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine from a sync CLI command."""
    return asyncio.run(coro)


def get_factory() -> Any:
    settings = DatabaseSettings()
    return make_session_factory(settings.database_url)


def _serializable(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat().replace("+00:00", "Z")
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Not serializable: {type(obj)!r}")


def print_json(data: Any) -> None:
    typer.echo(json.dumps(data, default=_serializable, indent=2))


def print_table(rows: list[dict[str, Any]], keys: list[str]) -> None:
    """Simple table output for non-JSON mode."""
    if not rows:
        typer.echo("(none)")
        return
    widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    header = "  ".join(k.upper().ljust(widths[k]) for k in keys)
    typer.echo(header)
    typer.echo("-" * len(header))
    for row in rows:
        typer.echo("  ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys))


def handle_error(exc: TelemetriaError) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=exc.exit_code)
