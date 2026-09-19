"""Shared CLI helpers: output formatting, error handling, async runner.

Output modes
------------
Commands accept a ``--json`` flag for machine-readable output and default to
Rich tables for human-readable output.  A ``--plain`` flag disables Rich
formatting for use in scripts or dumb terminals.

Usage in a command::

    @app.command()
    def list_projects(json: bool = OPT_JSON, plain: bool = OPT_PLAIN) -> None:
        ...
        output(mode(json, plain), [asdict(p) for p in projects], keys=[...])
"""

from __future__ import annotations

import asyncio
import json as _json
from collections.abc import Coroutine
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from telemetria.config import DatabaseSettings
from telemetria.db.session import make_session_factory
from telemetria.domain.errors import TelemetriaError

# ---------------------------------------------------------------------------
# Shared option defaults — import and use in commands
# ---------------------------------------------------------------------------

OPT_JSON: bool = typer.Option(False, "--json", help="Output as JSON.")
OPT_PLAIN: bool = typer.Option(False, "--plain", help="Plain text, no Rich formatting.")

_console = Console()
_err_console = Console(stderr=True)


class OutputMode(StrEnum):
    RICH = "rich"
    PLAIN = "plain"
    JSON = "json"


def mode(json: bool, plain: bool) -> OutputMode:
    if json:
        return OutputMode.JSON
    if plain:
        return OutputMode.PLAIN
    return OutputMode.RICH


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug.

    'My Cool Project' → 'my-cool-project'
    """
    import re

    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def prompt_name_and_slug() -> tuple[str, str]:
    """Prompt for name first, then offer an auto-generated slug for editing."""
    name: str = typer.prompt("Name")
    suggested = slugify(name)
    slug: str = typer.prompt("Slug", default=suggested)
    return name, slug


def prompt_select(message: str, choices: list[str]) -> str:
    """Show an interactive selection menu. Falls back to a plain prompt if not a TTY."""
    import os

    if not os.isatty(0) or not choices:
        result2: str = typer.prompt(message)
        return result2
    import questionary

    result: str | None = questionary.select(message, choices=choices).ask()
    if result is None:
        raise typer.Abort()
    return result


# ---------------------------------------------------------------------------
# Async runner
# ---------------------------------------------------------------------------


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine from a sync CLI command."""
    return asyncio.run(coro)


def get_factory() -> Any:
    settings = DatabaseSettings()
    return make_session_factory(settings.database_url)


def get_app_key() -> str:
    """Return the APP_KEY from CommonSettings (empty string if unset)."""
    from telemetria.config import CommonSettings

    return CommonSettings().app_key


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _serializable(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat().replace("+00:00", "Z")
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Not serializable: {type(obj)!r}")


def _to_json(data: Any) -> str:
    return _json.dumps(data, default=_serializable, indent=2)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def print_json(data: Any) -> None:
    """Print data as indented JSON."""
    typer.echo(_to_json(data))


def output(
    out: OutputMode,
    rows: list[dict[str, Any]],
    *,
    keys: list[str],
    title: str = "",
) -> None:
    """Print a list of dicts in the requested output mode.

    Parameters
    ----------
    out:     OutputMode — RICH, PLAIN, or JSON
    rows:    List of dicts to display
    keys:    Column keys to include (determines column order)
    title:   Optional Rich table title
    """
    if out == OutputMode.JSON:
        typer.echo(_to_json(rows))
        return

    if not rows:
        if out == OutputMode.RICH:
            _console.print("[dim](none)[/dim]")
        else:
            typer.echo("(none)")
        return

    if out == OutputMode.RICH:
        table = Table(title=title or None, show_header=True, header_style="bold cyan")
        for key in keys:
            table.add_column(key.upper().replace("_", " "))
        for row in rows:
            table.add_row(*[str(row.get(k, "")) for k in keys])
        _console.print(table)
    else:
        # Plain text
        widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
        header = "  ".join(k.upper().ljust(widths[k]) for k in keys)
        typer.echo(header)
        typer.echo("-" * len(header))
        for row in rows:
            typer.echo("  ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys))


def output_one(
    out: OutputMode,
    row: dict[str, Any],
    *,
    keys: list[str],
    title: str = "",
) -> None:
    """Print a single record."""
    if out == OutputMode.JSON:
        typer.echo(_to_json(row))
        return
    output(out, [row], keys=keys, title=title)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def handle_error(exc: TelemetriaError) -> None:
    _err_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(code=exc.exit_code)


# ---------------------------------------------------------------------------
# Legacy — keep for existing commands not yet migrated
# ---------------------------------------------------------------------------


def print_table(rows: list[dict[str, Any]], keys: list[str]) -> None:
    """Simple table output (plain text, no Rich)."""
    output(OutputMode.PLAIN, rows, keys=keys)
