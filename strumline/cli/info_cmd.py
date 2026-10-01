"""CLI: strumline info — Rich tree view of projects → apps → tokens."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.tree import Tree

from strumline.cli.helpers import get_factory, run_command

app = typer.Typer(help="Show all projects, apps, and tokens.", add_help_option=True)
_console = Console()


@app.callback(invoke_without_command=True)
def info() -> None:
    """Show all projects, apps, and auth tokens as a tree."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            from strumline.control.apps import AppService
            from strumline.control.auth_tokens import AuthTokenService
            from strumline.control.projects import ProjectService

            projects = await ProjectService(session).list_all()

            if not projects:
                _console.print(
                    "[dim]No projects found. "
                    "Run [bold]strumline project create[/bold] to get started.[/dim]"
                )
                return

            for project in projects:
                p_label = f"[bold cyan]{project.slug}[/bold cyan]  [dim]{project.name}[/dim]"
                p_tree = Tree(p_label)

                apps = await AppService(session).list_all(str(project.id))
                for app_obj in apps:
                    tz = f"  [dim]{app_obj.timezone}[/dim]" if app_obj.timezone else ""
                    a_label = f"[green]{app_obj.slug}[/green]  [dim]{app_obj.name}[/dim]{tz}"
                    a_tree = p_tree.add(a_label)

                    tokens = await AuthTokenService(session).list_by_app(app_obj.id)
                    for t in tokens:
                        if t.is_active:
                            date = t.created_at.strftime("%Y-%m-%d")
                            a_tree.add(f"[green]● active[/green]   token  {t.id}  {date}")
                        else:
                            date = (t.revoked_at or t.created_at).strftime("%Y-%m-%d")
                            a_tree.add(f"[dim]● revoked  token  {t.id}  {date}[/dim]")

                _console.print(p_tree)

    run_command(_run())
