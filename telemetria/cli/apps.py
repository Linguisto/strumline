"""CLI: telemetria app create|list|get|update|delete + timezone set|clear"""

from __future__ import annotations

from dataclasses import asdict

import typer

from telemetria.cli.helpers import get_factory, handle_error, print_json, run
from telemetria.control.apps import AppService
from telemetria.domain.errors import TelemetriaError

app = typer.Typer(help="Manage apps.", no_args_is_help=True)
tz_app = typer.Typer(help="Manage app display timezone.", no_args_is_help=True)
app.add_typer(tz_app, name="timezone")


@app.command("create")
def create(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    slug: str = typer.Argument(..., help="App slug (unique within project)."),
    name: str = typer.Option(..., "--name", "-n", help="Display name."),
    timezone: str | None = typer.Option(None, "--timezone", "-z", help="IANA display timezone."),
) -> None:
    """Create a new app in a project."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.create(project, slug, name, tz=timezone)
            print_json(asdict(result))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("list")
def list_apps(
    project: str = typer.Argument(..., help="Project slug or UUID."),
) -> None:
    """List apps in a project."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            apps = await svc.list_all(project)
            print_json([asdict(a) for a in apps])

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("get")
def get(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    app_id: str = typer.Argument(..., help="App slug or UUID."),
) -> None:
    """Get an app by slug or ID."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.get(project, app_id)
            print_json(asdict(result))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("update")
def update(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    app_id: str = typer.Argument(..., help="App slug or UUID."),
    name: str = typer.Option(..., "--name", "-n", help="New display name."),
) -> None:
    """Update an app's display name."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.update(project, app_id, name=name)
            print_json(asdict(result))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("delete")
def delete(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    app_id: str = typer.Argument(..., help="App slug or UUID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete an app and all its DSNs."""
    if not yes:
        typer.confirm(f"Delete app {app_id!r} and all its DSNs?", abort=True)

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            await svc.delete(project, app_id)
            typer.echo(f"Deleted app {app_id!r}.")

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@tz_app.command("set")
def tz_set(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    app_id: str = typer.Argument(..., help="App slug or UUID."),
    timezone: str = typer.Argument(..., help="IANA timezone, e.g. Europe/Berlin."),
) -> None:
    """Set the display timezone for an app."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.set_timezone(project, app_id, timezone)
            print_json(asdict(result))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@tz_app.command("clear")
def tz_clear(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    app_id: str = typer.Argument(..., help="App slug or UUID."),
) -> None:
    """Clear the display timezone for an app (falls back to APP_TIMEZONE or UTC)."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.set_timezone(project, app_id, None)
            print_json(asdict(result))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)
