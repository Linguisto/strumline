"""CLI: telemetria doctor — health checks for all services.

Checks:
- API / Ingest / Processor HTTP health endpoints
- PostgreSQL connectivity and migration state
- Loki connectivity (if SINK_PROVIDER=loki)
- Prometheus / Grafana (optional — missing = neutral, not failure)

Non-interactive, deterministic exit codes:
  0  all required checks passed
  1  one or more required checks failed
"""

from __future__ import annotations

import asyncio
from typing import Any

import typer
from rich.console import Console

from telemetria.cli.helpers import OPT_JSON, OPT_PLAIN, OutputMode, mode, output

_console = Console()
_err = Console(stderr=True)

app = typer.Typer(help="Run health checks for all services.", add_help_option=True)

# Check result keys used in output
_KEYS = ["service", "status", "detail"]

# Status constants
_OK = "ok"
_FAIL = "fail"
_SKIP = "skip"  # optional service not configured


async def _http_get(url: str, timeout: float = 5.0) -> tuple[int, dict[str, Any]]:
    import httpx2

    async with httpx2.AsyncClient(timeout=timeout) as client:
        r = await client.get(url)
        return r.status_code, r.json()


def _check_result(service: str, status: str, detail: str = "") -> dict[str, Any]:
    return {"service": service, "status": status, "detail": detail}


async def _check_http(name: str, url: str, required: bool = True) -> dict[str, Any]:
    try:
        code, body = await _http_get(url)
        if code == 200 and body.get("status") == "ok":
            version = body.get("version", "")
            return _check_result(name, _OK, f"version={version}")
        return _check_result(
            name,
            _FAIL if required else _SKIP,
            f"HTTP {code}",
        )
    except Exception as exc:
        return _check_result(
            name,
            _FAIL if required else _SKIP,
            str(exc)[:120],
        )


async def _check_postgres() -> dict[str, Any]:
    try:
        from telemetria.config import DatabaseSettings
        from telemetria.db.session import make_session_factory

        settings = DatabaseSettings()
        factory = make_session_factory(settings.database_url)
        async with factory() as session:
            result = await session.execute(__import__("sqlalchemy").text("SELECT version()"))
            version_row = result.scalar()
            version = str(version_row or "").split(" on ")[0] if version_row else "unknown"
            return _check_result("postgres", _OK, version)
    except Exception as exc:
        return _check_result("postgres", _FAIL, str(exc)[:120])


async def _check_migrations() -> dict[str, Any]:
    try:
        import sqlalchemy
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from telemetria.config import DatabaseSettings

        settings = DatabaseSettings()
        # Use sync engine for alembic inspection
        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = sqlalchemy.create_engine(sync_url)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current = ctx.get_current_heads()

        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        head = set(script.get_heads())

        if set(current) == head:
            return _check_result("migrations", _OK, f"head={','.join(head)}")
        return _check_result(
            "migrations",
            _FAIL,
            f"current={','.join(current) or 'none'} head={','.join(head)}",
        )
    except Exception as exc:
        return _check_result("migrations", _FAIL, str(exc)[:120])


async def _check_loki(loki_url: str) -> dict[str, Any]:
    try:
        import httpx2

        async with httpx2.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{loki_url.rstrip('/')}/ready")
            if r.status_code == 200:
                return _check_result("loki", _OK, loki_url)
            return _check_result("loki", _FAIL, f"HTTP {r.status_code}")
    except Exception as exc:
        return _check_result("loki", _FAIL, str(exc)[:120])


async def _check_optional_url(name: str, url: str) -> dict[str, Any]:
    """Check an optional external service — skip gracefully if not configured."""
    if not url:
        return _check_result(name, _SKIP, "not configured")
    try:
        import httpx2

        async with httpx2.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            if r.status_code < 500:
                return _check_result(name, _OK, url)
            return _check_result(name, _SKIP, f"HTTP {r.status_code}")
    except Exception as exc:
        return _check_result(name, _SKIP, str(exc)[:80])


async def _run_checks(
    api_url_override: str | None = None,
    ingest_url_override: str | None = None,
    processor_url_override: str | None = None,
) -> list[dict[str, Any]]:
    from telemetria.config import APISettings, IngestSettings, LokiSettings, ProcessorSettings

    try:
        api_s = APISettings()
        ingest_s = IngestSettings()
        proc_s = ProcessorSettings()
        loki_s = LokiSettings()
    except Exception:
        api_s = APISettings.model_construct()
        ingest_s = IngestSettings.model_construct()
        proc_s = ProcessorSettings.model_construct()
        loki_s = LokiSettings.model_construct()

    from telemetria.config import DatabaseSettings

    # If DB_HOST is a hostname (not localhost), we're inside the Compose network.
    # The app services bind to 0.0.0.0 but are reachable by their service names.
    try:
        db_host = DatabaseSettings().db_host
    except Exception:
        db_host = "localhost"
    in_compose = db_host not in ("localhost", "127.0.0.1", "")

    def _host(h: str, service_name: str) -> str:
        if h not in ("0.0.0.0", "::"):
            return h
        return service_name if in_compose else "localhost"

    api_url = api_url_override or f"http://{_host(api_s.api_host, 'api')}:{api_s.api_port}"
    ingest_url = (
        ingest_url_override
        or f"http://{_host(ingest_s.ingest_host, 'ingest')}:{ingest_s.ingest_port}"
    )
    proc_url = (
        processor_url_override
        or f"http://{_host(proc_s.processor_host, 'processor')}:{proc_s.processor_port}"
    )
    loki_url = loki_s.loki_url
    sink_provider = proc_s.sink_provider

    tasks = [
        _check_http("api", f"{api_url}/health"),
        _check_http("ingest", f"{ingest_url}/health"),
        _check_http("processor", f"{proc_url}/health"),
        _check_postgres(),
        _check_migrations(),
    ]

    if sink_provider == "loki":
        tasks.append(_check_loki(loki_url))

    return list(await asyncio.gather(*tasks))


def _render_rich(results: list[dict[str, Any]]) -> None:
    from rich.table import Table

    table = Table(title="Doctor", show_header=True, header_style="bold cyan")
    table.add_column("SERVICE")
    table.add_column("STATUS")
    table.add_column("DETAIL")

    for row in results:
        status = row["status"]
        if status == _OK:
            status_fmt = "[green]ok[/green]"
        elif status == _FAIL:
            status_fmt = "[red]fail[/red]"
        else:
            status_fmt = "[dim]skip[/dim]"
        table.add_row(row["service"], status_fmt, row["detail"])

    _console.print(table)


@app.callback(invoke_without_command=True)
def doctor(
    json: bool = OPT_JSON,
    plain: bool = OPT_PLAIN,
    api_url: str = typer.Option("", "--api-url", help="Override API base URL."),
    ingest_url: str = typer.Option("", "--ingest-url", help="Override ingest base URL."),
    processor_url: str = typer.Option("", "--processor-url", help="Override processor base URL."),
) -> None:
    """Run health checks for all services."""
    results = asyncio.run(_run_checks(api_url or None, ingest_url or None, processor_url or None))
    out = mode(json, plain)

    if out == OutputMode.JSON or out == OutputMode.PLAIN:
        output(out, results, keys=_KEYS)
    else:
        _render_rich(results)

    failed = [r for r in results if r["status"] == _FAIL]
    if failed:
        if out != OutputMode.JSON:
            _err.print(f"\n[red]{len(failed)} check(s) failed.[/red]")
        raise typer.Exit(1)

    if out != OutputMode.JSON:
        _console.print("\n[green]✓ All checks passed.[/green]")
