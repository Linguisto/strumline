"""CLI: strumline project create|show|delete"""

from __future__ import annotations

from dataclasses import asdict

import typer

from strumline.cli.helpers import (
    confirm_destructive,
    get_factory,
    print_json,
    require_arg,
    run_command,
)
from strumline.cli.wizards import wizard_project_create
from strumline.control.projects import ProjectService

app = typer.Typer(help="Manage projects.", no_args_is_help=True)


@app.command("create")
def create(
    slug: str = typer.Argument(None, help="Unique slug (immutable)."),
    name: str = typer.Option(None, "--name", "-n", help="Display name."),
) -> None:
    """Create a new project.

    Fully specified (``slug`` + ``--name``) it runs non-interactively and prints
    the created project as JSON on stdout. Missing fields prompt only on a TTY;
    non-interactive callers get actionable guidance instead of a hang.
    """

    async def _run() -> None:
        nonlocal slug, name
        if not slug and not name:
            fields = wizard_project_create()
            name, slug = fields["name"], fields["slug"]
        elif not name:
            name = require_arg(None, "name", example="--name 'My Project'")
        elif not slug:
            slug = require_arg(None, "slug", example="project create my-slug")

        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            project = await svc.create(slug=slug, name=name)
            print_json(asdict(project))

    run_command(_run())


@app.command("show")
def show(
    slug_or_id: str = typer.Argument(..., help="Project slug or UUID."),
) -> None:
    """Show project details as JSON."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            project = await svc.get(slug_or_id)
            print_json(asdict(project))

    run_command(_run())


@app.command("delete")
def delete(
    slug_or_id: str = typer.Argument(..., help="Project slug or UUID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a project and all its apps and auth tokens."""

    async def _run() -> None:
        if not yes:
            confirm_destructive(f"Delete project {slug_or_id!r} and all its apps/auth tokens?")
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            await svc.delete(slug_or_id)
            typer.echo(f"Deleted project {slug_or_id!r}.")

    run_command(_run())
