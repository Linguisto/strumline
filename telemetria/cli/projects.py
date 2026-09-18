"""CLI: telemetria project create|list|get|update|delete"""

from __future__ import annotations

from dataclasses import asdict

import typer

from telemetria.cli.helpers import get_factory, handle_error, print_json, run
from telemetria.control.projects import ProjectService
from telemetria.domain.errors import TelemetriaError

app = typer.Typer(help="Manage projects.", no_args_is_help=True)


@app.command("create")
def create(
    slug: str = typer.Argument(..., help="Unique slug (immutable)."),
    name: str = typer.Option(..., "--name", "-n", help="Display name."),
) -> None:
    """Create a new project."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            project = await svc.create(slug=slug, name=name)
            print_json(asdict(project))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("list")
def list_projects() -> None:
    """List all projects."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            projects = await svc.list_all()
            print_json([asdict(p) for p in projects])

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("get")
def get(
    slug_or_id: str = typer.Argument(..., help="Project slug or UUID."),
) -> None:
    """Get a project by slug or ID."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            project = await svc.get(slug_or_id)
            print_json(asdict(project))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("update")
def update(
    slug_or_id: str = typer.Argument(..., help="Project slug or UUID."),
    name: str = typer.Option(..., "--name", "-n", help="New display name."),
) -> None:
    """Update a project's display name."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            project = await svc.update(slug_or_id, name=name)
            print_json(asdict(project))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("delete")
def delete(
    slug_or_id: str = typer.Argument(..., help="Project slug or UUID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a project and all its apps and DSNs."""
    if not yes:
        typer.confirm(f"Delete project {slug_or_id!r} and all its apps/DSNs?", abort=True)

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            await svc.delete(slug_or_id)
            typer.echo(f"Deleted project {slug_or_id!r}.")

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)
