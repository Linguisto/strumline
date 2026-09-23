"""CLI: strumline project create|show|delete"""

from __future__ import annotations

from dataclasses import asdict

import typer

from strumline.cli.helpers import get_factory, handle_error, print_json, run
from strumline.cli.wizards import wizard_project_create
from strumline.control.projects import ProjectService
from strumline.domain.errors import StrumlineError

app = typer.Typer(help="Manage projects.", no_args_is_help=True)


@app.command("create")
def create(
    slug: str = typer.Argument(None, help="Unique slug (immutable)."),
    name: str = typer.Option(None, "--name", "-n", help="Display name."),
) -> None:
    """Create a new project."""
    if not slug and not name:
        fields = wizard_project_create()
        name, slug = fields["name"], fields["slug"]
    elif not name:
        name = typer.prompt("Name")
    elif not slug:
        from strumline.cli.helpers import slugify

        slug = typer.prompt("Slug", default=slugify(name))

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            project = await svc.create(slug=slug, name=name)
            print_json(asdict(project))

    try:
        run(_run())
    except StrumlineError as e:
        handle_error(e)


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

    try:
        run(_run())
    except StrumlineError as e:
        handle_error(e)


@app.command("delete")
def delete(
    slug_or_id: str = typer.Argument(..., help="Project slug or UUID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a project and all its apps and auth tokens."""
    if not yes:
        typer.confirm(f"Delete project {slug_or_id!r} and all its apps/auth tokens?", abort=True)

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = ProjectService(session)
            await svc.delete(slug_or_id)
            typer.echo(f"Deleted project {slug_or_id!r}.")

    try:
        run(_run())
    except StrumlineError as e:
        handle_error(e)
