"""CLI: telemetria dashboard — interactive TUI dashboard.

Shows:
- Process health (api, ingest, processor)
- Queue depth gauges (scraped from /metrics)
- Resource tree: projects → apps → tokens

Falls back cleanly when no TTY is present.
"""

from __future__ import annotations

from typing import Any

import typer

app = typer.Typer(help="Open the interactive dashboard.", add_help_option=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_text(url: str) -> str:
    import httpx2

    async with httpx2.AsyncClient(timeout=3.0) as client:
        r = await client.get(url)
        return r.text


def _parse_gauge(metrics_text: str, name: str) -> str:
    for line in metrics_text.splitlines():
        if line.startswith(name + " ") or line.startswith(name + "{"):
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                return parts[1].strip()
    return "?"


def _resolve_urls(
    api_url: str,
    ingest_url: str,
    processor_url: str,
) -> tuple[str, str, str]:
    """Resolve service URLs, using Compose service names when inside the network."""
    from telemetria.config import APISettings, DatabaseSettings, IngestSettings, ProcessorSettings

    try:
        db_host = DatabaseSettings().db_host
    except Exception:
        db_host = "localhost"
    in_compose = db_host not in ("localhost", "127.0.0.1", "")

    def _h(host: str, service: str) -> str:
        if host not in ("0.0.0.0", "::"):
            return host
        return service if in_compose else "localhost"

    try:
        api_s = APISettings()
        ing_s = IngestSettings()
        proc_s = ProcessorSettings()
        r_api = api_url or f"http://{_h(api_s.api_host, 'api')}:{api_s.api_port}"
        r_ing = ingest_url or f"http://{_h(ing_s.ingest_host, 'ingest')}:{ing_s.ingest_port}"
        r_proc = (
            processor_url
            or f"http://{_h(proc_s.processor_host, 'processor')}:{proc_s.processor_port}"
        )
    except Exception:
        r_api = api_url or "http://localhost:8000"
        r_ing = ingest_url or "http://localhost:8001"
        r_proc = processor_url or "http://localhost:8002"

    return r_api, r_ing, r_proc


# ---------------------------------------------------------------------------
# Textual app
# ---------------------------------------------------------------------------


def _build_app(api_url: str, ingest_url: str, processor_url: str) -> Any:
    from textual.app import App, ComposeResult
    from textual.reactive import reactive
    from textual.widgets import Footer, Header, Label, Static

    class ProcessStatus(Static):
        DEFAULT_CSS = """
        ProcessStatus {
            border: round $primary;
            padding: 0 1;
            margin: 0 1;
            width: 1fr;
        }
        """

        name_: str = ""
        url: str = ""
        _status: reactive[str] = reactive("…")

        def compose(self) -> ComposeResult:
            yield Label(f"[bold]{self.name_}[/bold]")
            yield Label(self._status, id=f"status-{self.name_}")

        def on_mount(self) -> None:
            self.set_interval(5, self._refresh)
            self._refresh()

        def _refresh(self) -> None:
            self.run_worker(self._fetch(), exclusive=True)

        async def _fetch(self) -> None:
            try:
                import httpx2

                async with httpx2.AsyncClient(timeout=3.0) as client:
                    r = await client.get(self.url)
                    body = r.json()
                    if body.get("status") == "ok":
                        ver = body.get("version", "")
                        self._status = f"[green]● ok[/green]  v{ver}"
                    else:
                        self._status = f"[red]● unhealthy[/red]  HTTP {r.status_code}"
            except Exception:
                self._status = "[red]● unreachable[/red]"
            lbl = self.query_one(f"#status-{self.name_}", Label)
            lbl.update(self._status)

    class QueueGauge(Static):
        DEFAULT_CSS = """
        QueueGauge {
            border: round $panel;
            padding: 0 1;
            margin: 0 1;
            width: 1fr;
        }
        """

        process: str = ""
        metrics_url: str = ""
        depth_metric: str = ""
        cap_metric: str = ""
        _text: reactive[str] = reactive("…")

        def compose(self) -> ComposeResult:
            yield Label(f"[bold]{self.process} queue[/bold]")
            yield Label(self._text, id=f"gauge-{self.process}")

        def on_mount(self) -> None:
            self.set_interval(5, self._refresh)
            self._refresh()

        def _refresh(self) -> None:
            self.run_worker(self._fetch(), exclusive=True)

        async def _fetch(self) -> None:
            try:
                text = await _fetch_text(self.metrics_url)
                depth = _parse_gauge(text, self.depth_metric)
                cap = _parse_gauge(text, self.cap_metric)
                try:
                    pct = int(float(depth) / float(cap) * 100) if cap not in ("?", "0") else 0
                    color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
                    val = f"[{color}]{depth}/{cap} ({pct}%)[/{color}]"
                except ValueError, ZeroDivisionError:
                    val = f"{depth}/{cap}"
                self._text = val
            except Exception:
                self._text = "[dim]unavailable[/dim]"
            lbl = self.query_one(f"#gauge-{self.process}", Label)
            lbl.update(self._text)

    class ResourceTree(Static):
        """Projects → apps → tokens tree, mirroring `telemetria info`."""

        DEFAULT_CSS = """
        ResourceTree {
            border: round $surface;
            padding: 0 1;
            margin: 0 1;
            height: 1fr;
            overflow-y: auto;
        }
        """

        def compose(self) -> ComposeResult:
            yield Label("[bold]Resources[/bold]")
            yield Label("[dim]loading…[/dim]", id="resource-tree-body")

        def on_mount(self) -> None:
            self.set_interval(30, self._refresh)
            self._refresh()

        def _refresh(self) -> None:
            self.run_worker(self._fetch(), exclusive=True)

        async def _fetch(self) -> None:
            try:
                from telemetria.cli.helpers import get_factory
                from telemetria.control.apps import AppService
                from telemetria.control.auth_tokens import AuthTokenService
                from telemetria.control.projects import ProjectService

                lines: list[str] = []
                async with get_factory()() as session, session.begin():
                    projects = await ProjectService(session).list_all()
                    for p in projects:
                        lines.append(f"[bold cyan]{p.slug}[/bold cyan]  [dim]{p.name}[/dim]")
                        apps = await AppService(session).list_all(str(p.id))
                        for a in apps:
                            tz = f"  [dim]{a.timezone}[/dim]" if a.timezone else ""
                            lines.append(f"  [green]{a.slug}[/green]  [dim]{a.name}[/dim]{tz}")
                            tokens = await AuthTokenService(session).list_by_app(a.id)
                            for t in tokens:
                                date = t.created_at.strftime("%Y-%m-%d")
                                if t.is_active:
                                    lines.append(
                                        f"    [green]●[/green] token  {t.id}  {date}"
                                        "  [green]active[/green]"
                                    )
                                else:
                                    lines.append(f"    [dim]● token  {t.id}  {date}  revoked[/dim]")

                body = self.query_one("#resource-tree-body", Label)
                body.update("\n".join(lines) if lines else "[dim]No resources.[/dim]")
            except Exception as exc:
                body = self.query_one("#resource-tree-body", Label)
                body.update(f"[red]Error: {exc!s:.80}[/red]")

    class TelemetriaUI(App):  # type: ignore[type-arg]
        """Telemetria TUI dashboard."""

        TITLE = "Telemetria"
        CSS = """
        Screen { layout: vertical; }
        #health-row { layout: horizontal; height: 5; margin: 1 0; }
        #queue-row  { layout: horizontal; height: 5; margin: 0 0 1 0; }
        """
        BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

        def compose(self) -> ComposeResult:
            yield Header()

            with Static(id="health-row"):
                api = ProcessStatus()
                api.name_ = "api"
                api.url = f"{api_url}/health"
                yield api

                ing = ProcessStatus()
                ing.name_ = "ingest"
                ing.url = f"{ingest_url}/health"
                yield ing

                proc = ProcessStatus()
                proc.name_ = "processor"
                proc.url = f"{processor_url}/health"
                yield proc

            with Static(id="queue-row"):
                iq = QueueGauge()
                iq.process = "ingest"
                iq.metrics_url = f"{ingest_url}/metrics"
                iq.depth_metric = "telemetria_ingest_queue_depth"
                iq.cap_metric = "telemetria_ingest_queue_capacity"
                yield iq

                pq = QueueGauge()
                pq.process = "processor"
                pq.metrics_url = f"{processor_url}/metrics"
                pq.depth_metric = "telemetria_processor_queue_depth"
                pq.cap_metric = "telemetria_processor_queue_capacity"
                yield pq

            yield ResourceTree()
            yield Footer()

        def action_refresh(self) -> None:
            self.refresh()

    return TelemetriaUI


@app.callback(invoke_without_command=True)
def dashboard(
    api_url: str = typer.Option("", "--api-url", help="Override API base URL."),
    ingest_url: str = typer.Option("", "--ingest-url", help="Override ingest base URL."),
    processor_url: str = typer.Option("", "--processor-url", help="Override processor base URL."),
) -> None:
    """Open the interactive dashboard.

    # TODO: Add interactive CRUD for projects, apps, and auth tokens
    """
    import os

    if not os.isatty(1):
        typer.echo(
            "telemetria ui requires a TTY. "
            "Use 'telemetria doctor --plain' for non-interactive output."
        )
        raise typer.Exit(1)

    r_api, r_ing, r_proc = _resolve_urls(api_url, ingest_url, processor_url)
    TelemetriaUI = _build_app(r_api, r_ing, r_proc)
    TelemetriaUI().run()
