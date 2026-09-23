"""Interactive wizards for create commands.

Each wizard uses questionary to present a form-like sequence of prompts with
inline validation, auto-generated suggestions, and a confirmation step.

Falls back to plain typer prompts when not running in a TTY (scripts, CI).
"""

from __future__ import annotations

import os
import re
import zoneinfo
from typing import Any

import typer

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_TTY = os.isatty(0) and os.isatty(1)


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _validate_slug(value: str) -> bool | str:
    if not value:
        return "Slug cannot be empty"
    if not _SLUG_RE.match(value):
        return "Lowercase letters, digits and hyphens only (no leading/trailing hyphens)"
    return True


def _validate_name(value: str) -> bool | str:
    return True if value.strip() else "Name cannot be empty"


def _validate_iana(value: str) -> bool | str:
    if not value:
        return True  # optional
    try:
        zoneinfo.ZoneInfo(value)
        return True
    except zoneinfo.ZoneInfoNotFoundError:
        return f"Unknown timezone {value!r} — use an IANA name like Europe/Berlin"


def _abort_on_none(value: Any) -> None:
    if value is None:
        raise typer.Abort()


# ---------------------------------------------------------------------------
# Project wizard
# ---------------------------------------------------------------------------


def wizard_project_create() -> dict[str, str]:
    """Run the project creation wizard. Returns {'name': ..., 'slug': ...}."""
    import questionary
    from rich.console import Console
    from rich.rule import Rule

    if not _TTY:
        name: str = typer.prompt("Name")
        slug: str = typer.prompt("Slug", default=_slugify(name))
        return {"name": name, "slug": slug}

    console = Console()
    console.print()
    console.print(Rule("[bold cyan]New project[/bold cyan]"))
    console.print()

    name_val = questionary.text(
        "Project name",
        validate=_validate_name,
    ).ask()
    _abort_on_none(name_val)

    slug_val = questionary.text(
        "Slug",
        default=_slugify(name_val),
        validate=_validate_slug,
    ).ask()
    _abort_on_none(slug_val)

    console.print()
    console.print(f"  [dim]name:[/dim]  {name_val}")
    console.print(f"  [dim]slug:[/dim]  {slug_val}")
    console.print()

    confirmed = questionary.confirm("Create project?", default=True).ask()
    if not confirmed:
        raise typer.Abort()

    return {"name": name_val, "slug": slug_val}


# ---------------------------------------------------------------------------
# App wizard
# ---------------------------------------------------------------------------


def wizard_app_create(project_slugs: list[str]) -> dict[str, str]:
    """Run the app creation wizard.

    Returns {'project': ..., 'name': ..., 'slug': ..., 'timezone': ...}.
    """
    import questionary
    from rich.console import Console
    from rich.rule import Rule

    if not _TTY:
        project: str = typer.prompt("Project slug or UUID")
        name: str = typer.prompt("Name")
        slug: str = typer.prompt("Slug", default=_slugify(name))
        tz: str = typer.prompt("Timezone (optional, press Enter to skip)", default="")
        return {"project": project, "name": name, "slug": slug, "timezone": tz}

    console = Console()
    console.print()
    console.print(Rule("[bold cyan]New app[/bold cyan]"))
    console.print()

    if project_slugs:
        project_val = questionary.select(
            "Project",
            choices=project_slugs,
        ).ask()
    else:
        project_val = questionary.text("Project slug or UUID").ask()
    _abort_on_none(project_val)

    name_val = questionary.text(
        "App name",
        validate=_validate_name,
    ).ask()
    _abort_on_none(name_val)

    slug_val = questionary.text(
        "Slug",
        default=_slugify(name_val),
        validate=_validate_slug,
    ).ask()
    _abort_on_none(slug_val)

    tz_val = questionary.text(
        "Display timezone (optional)",
        default="",
        validate=_validate_iana,
        instruction="IANA name e.g. Europe/Berlin, or leave blank for UTC",
    ).ask()
    _abort_on_none(tz_val)

    console.print()
    console.print(f"  [dim]project:[/dim]   {project_val}")
    console.print(f"  [dim]name:[/dim]      {name_val}")
    console.print(f"  [dim]slug:[/dim]      {slug_val}")
    if tz_val:
        console.print(f"  [dim]timezone:[/dim]  {tz_val}")
    console.print()

    confirmed = questionary.confirm("Create app?", default=True).ask()
    if not confirmed:
        raise typer.Abort()

    return {
        "project": project_val,
        "name": name_val,
        "slug": slug_val,
        "timezone": tz_val or "",
    }


# ---------------------------------------------------------------------------
# AuthToken wizard
# ---------------------------------------------------------------------------


def wizard_auth_token_create(app_choices: list[tuple[str, str]]) -> str:
    """Run the auth token creation wizard. Returns the selected app_id."""
    import questionary
    from rich.console import Console
    from rich.rule import Rule

    if not _TTY or not app_choices:
        result2: str = typer.prompt("App UUID")
        return result2

    console = Console()
    console.print()
    console.print(Rule("[bold cyan]New auth token[/bold cyan]"))
    console.print()

    labels = [label for label, _ in app_choices]
    selected_label = questionary.select(
        "App",
        choices=labels,
    ).ask()
    _abort_on_none(selected_label)

    app_id = next(uid for label, uid in app_choices if label == selected_label)

    console.print()
    console.print(f"  [dim]app:[/dim]  {selected_label}")
    console.print()
    console.print(
        "  [yellow]⚠[/yellow]  The auth token key is shown [bold]once[/bold] — save it immediately."
    )
    console.print()

    confirmed = questionary.confirm("Create auth token?", default=True).ask()
    if not confirmed:
        raise typer.Abort()

    return app_id
