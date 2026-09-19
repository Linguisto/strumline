"""CLI: telemetria app create|show|delete"""

from __future__ import annotations

from dataclasses import asdict

import typer
from rich.console import Console
from rich.panel import Panel

from telemetria.cli.helpers import get_app_key, get_factory, handle_error, print_json, run
from telemetria.cli.wizards import wizard_app_create
from telemetria.control.apps import AppService
from telemetria.domain.errors import TelemetriaError

app = typer.Typer(help="Manage apps.", no_args_is_help=True)


@app.command("create")
def create(
    project: str = typer.Argument(None, help="Project slug or UUID."),
    slug: str = typer.Argument(None, help="App slug (unique within project)."),
    name: str = typer.Option(None, "--name", "-n", help="Display name."),
    timezone: str | None = typer.Option(None, "--timezone", "-z", help="IANA display timezone."),
) -> None:
    """Create a new app in a project."""
    if not project and not slug and not name:

        async def _fetch_projects() -> list[str]:
            async with get_factory()() as session, session.begin():
                from telemetria.control.projects import ProjectService

                return [p.slug for p in await ProjectService(session).list_all()]

        try:
            project_slugs = run(_fetch_projects())
        except Exception:
            project_slugs = []

        fields = wizard_app_create(project_slugs)
        project = fields["project"]
        name = fields["name"]
        slug = fields["slug"]
        timezone = timezone or (fields["timezone"] or None)
    elif not project:
        from telemetria.cli.helpers import prompt_select

        async def _fetch_ps() -> list[str]:
            async with get_factory()() as session, session.begin():
                from telemetria.control.projects import ProjectService

                return [p.slug for p in await ProjectService(session).list_all()]

        try:
            slugs = run(_fetch_ps())
        except Exception:
            slugs = []
        project = prompt_select("Project", slugs) if slugs else typer.prompt("Project slug or UUID")
    if not slug and not name:
        from telemetria.cli.helpers import slugify

        name = typer.prompt("Name")
        slug = typer.prompt("Slug", default=slugify(name))
    elif not name:
        name = typer.prompt("Name")
    elif not slug:
        from telemetria.cli.helpers import slugify

        slug = typer.prompt("Slug", default=slugify(name))

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.create(project, slug, name, tz=timezone)

            # Automatically create the first auth token
            from telemetria.control.auth_tokens import AuthTokenService

            token, raw_key = await AuthTokenService(session, get_app_key()).create(result.id)

        console = Console()
        console.print(f"\n[green]✓[/green] App [bold]{result.slug}[/bold] created")
        console.print(
            Panel(
                f"[bold yellow]{raw_key}[/bold yellow]",
                title="Auth token key — save it now, shown only once",
                border_style="yellow",
            )
        )
        console.print(f"[dim]App ID:[/dim]    {result.id}")
        console.print(f"[dim]Token ID:[/dim]  {token.id}\n")

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("show")
def show(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    app_id: str = typer.Argument(..., help="App slug or UUID."),
) -> None:
    """Show app details as JSON."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.get(project, app_id)
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
    """Delete an app and all its auth tokens."""
    if not yes:
        typer.confirm(f"Delete app {app_id!r} and all its auth tokens?", abort=True)

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            await svc.delete(project, app_id)
            typer.echo(f"Deleted app {app_id!r}.")

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)
