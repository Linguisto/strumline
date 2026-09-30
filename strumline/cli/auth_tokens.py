"""CLI: strumline token create|revoke"""

from __future__ import annotations

import typer

from strumline.cli.helpers import (
    confirm_destructive,
    get_app_key,
    get_factory,
    parse_uuid,
    print_json,
    prompt_select,
    require_arg,
    run_command,
)
from strumline.cli.wizards import wizard_auth_token_create
from strumline.control.auth_tokens import AuthTokenService

app = typer.Typer(help="Manage auth tokens.", no_args_is_help=True)


async def _fetch_app_choices() -> list[tuple[str, str]]:
    """Return [(label, app_id), ...] for all apps across all projects."""
    async with get_factory()() as session, session.begin():
        from strumline.control.apps import AppService
        from strumline.control.projects import ProjectService

        projects = await ProjectService(session).list_all()
        pairs = []
        for p in projects:
            apps = await AppService(session).list_all(str(p.id))
            for a in apps:
                pairs.append((f"{p.slug} / {a.slug}", str(a.id)))
        return pairs


@app.command("create")
def create(
    app_id: str = typer.Argument(None, help="App UUID."),
) -> None:
    """Create a new auth token for an app.

    The raw key is shown once, here, as JSON on stdout — save it immediately.
    It is never emitted again by list/show/log output.
    """

    async def _run() -> None:
        nonlocal app_id
        if not app_id:
            # A failure loading the picker (e.g. DB unreachable) surfaces as an
            # operational error rather than collapsing into an empty list.
            app_id = wizard_auth_token_create(await _fetch_app_choices())
        resolved_app_id = parse_uuid(app_id, "app_id")

        async with get_factory()() as session, session.begin():
            svc = AuthTokenService(session, get_app_key())
            token, raw_key = await svc.create(resolved_app_id)

        # One-time token disclosure: creation result only.
        print_json(
            {
                "token_id": str(token.id),
                "app_id": str(resolved_app_id),
                "token_key": raw_key,
            }
        )

    run_command(_run())


@app.command("revoke")
def revoke(
    app_id: str = typer.Argument(None, help="App UUID."),
    token_id: str = typer.Argument(None, help="Token UUID to revoke."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Revoke an auth token."""

    async def _run() -> None:
        nonlocal app_id, token_id
        if not app_id:
            choices = await _fetch_app_choices()
            if choices:
                labels = [label for label, _ in choices]
                selected = prompt_select("App", labels)
                app_id = next(uid for label, uid in choices if label == selected)
            else:
                app_id = require_arg(None, "app_id", example="token revoke <app_id> <token_id>")
        resolved_app_id = parse_uuid(app_id, "app_id")

        if not token_id:

            async def _active_tokens() -> list[tuple[str, str]]:
                async with get_factory()() as session, session.begin():
                    svc = AuthTokenService(session, get_app_key())
                    tokens = await svc.list_by_app(resolved_app_id)
                    return [
                        (
                            f"{str(d.id)[:8]}…  created {d.created_at.strftime('%Y-%m-%d')}",
                            str(d.id),
                        )
                        for d in tokens
                        if d.is_active
                    ]

            token_choices = await _active_tokens()
            if token_choices:
                labels = [label for label, _ in token_choices]
                selected = prompt_select("Token to revoke", labels)
                token_id = next(uid for label, uid in token_choices if label == selected)
            else:
                token_id = require_arg(None, "token_id", example="token revoke <app_id> <token_id>")
        resolved_token_id = parse_uuid(token_id, "token_id")

        # Destructive: require explicit intent. A missing TTY never implies
        # consent — non-interactive callers must pass --yes.
        if not yes:
            confirm_destructive(f"Revoke token {token_id!r}?")

        async with get_factory()() as session, session.begin():
            svc = AuthTokenService(session, get_app_key())
            await svc.revoke(resolved_token_id, resolved_app_id)
            typer.echo(f"Revoked token {token_id!r}.")

    run_command(_run())
