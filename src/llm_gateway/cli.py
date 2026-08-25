"""CLI test console: chat REPL, one-shot ask, quota status, provider listing."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .client import Gateway
from .errors import GatewayError
from .models import GatewayResponse, ProviderStatus

app = typer.Typer(
    name="llm-gateway",
    help="Free-tier LLM gateway with automatic provider failover.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="TOML overlay (e.g. demo.toml for the failover demo)."),
]

_OUTCOME_ICONS = {
    "success": "[green]✔[/green]",
    "skipped_local_limit": "[yellow]⏭ local limit[/yellow]",
    "rate_limited": "[red]⏭ rate limited[/red]",
    "server_error": "[red]⏭ server error[/red]",
    "timeout": "[red]⏭ timeout[/red]",
    "auth_error": "[red]⏭ bad key[/red]",
    "bad_request": "[red]⏭ rejected[/red]",
}


def _footer(resp: GatewayResponse) -> str:
    tokens = resp.usage.total_tokens if resp.usage else None
    parts = [
        f"served by [bold cyan]{resp.provider}[/bold cyan]/{resp.model}",
        f"{resp.latency_ms:.0f}ms",
    ]
    if tokens:
        parts.append(f"{tokens} tok")
    line = " · ".join(parts)
    if resp.failed_over:
        trail = " → ".join(
            f"{a.provider} {_OUTCOME_ICONS.get(a.outcome, a.outcome)}" for a in resp.attempts
        )
        line += f"\ntrail: {trail}"
    return line


def _print_response(resp: GatewayResponse) -> None:
    console.print(Panel(resp.text, border_style="cyan"))
    console.print(_footer(resp), style="dim", highlight=False)


def _fmt_quota(used: int | None, limit: int | None) -> str:
    if limit is None:
        return "—" if used in (None, 0) else f"{used}/∞"
    used = used or 0
    style = "red" if used >= limit else ("yellow" if used >= 0.8 * limit else "green")
    return f"[{style}]{used}/{limit}[/{style}]"


def _fmt_next_available(s: ProviderStatus) -> str:
    if not s.enabled:
        return "[dim]disabled[/dim]"
    if not s.has_key:
        return "[dim]NO KEY[/dim]"
    if s.next_available is None:
        return "[green]now[/green]"
    delta = (s.next_available - datetime.now(s.next_available.tzinfo)).total_seconds()
    local = s.next_available.astimezone().strftime("%H:%M:%S")
    if delta >= 3600:
        return f"[red]{local} (~{delta / 3600:.1f}h)[/red]"
    return f"[red]{local} (~{max(1, int(delta / 60))}m)[/red]"


def _status_table(statuses: list[ProviderStatus]) -> Table:
    table = Table(title="Provider quota status (local view — server 429s are ground truth)")
    for col in ("#", "Provider", "Model", "Key", "RPM", "RPD", "Tok/min", "Tok/day",
                "Cooldown", "Available"):
        table.add_column(col)
    for s in sorted(statuses, key=lambda s: s.priority):
        cooldown = (
            f"{s.cooldown_reason} until {s.cooldown_until.astimezone():%H:%M:%S}"
            if s.cooldown_until
            else "—"
        )
        table.add_row(
            str(s.priority),
            s.name,
            s.model,
            "[green]✔[/green]" if s.has_key else "[red]✘[/red]",
            _fmt_quota(s.rpm_used, s.rpm_limit),
            _fmt_quota(s.rpd_used, s.rpd_limit),
            _fmt_quota(s.tokens_minute_used, s.tpm_limit),
            _fmt_quota(s.tokens_day_used, s.tpd_limit),
            cooldown,
            _fmt_next_available(s),
        )
    return table


@app.command()
def chat(config: ConfigOpt = None) -> None:
    """Interactive REPL. In-session commands: /status, /quit."""
    gw = Gateway(config_file=config)
    active = [p.name for p in gw.config.active_providers()]
    if not active:
        console.print("[red]No providers have API keys set.[/red] Run `llm-gateway providers` "
                      "to see which environment variables to set.")
        raise typer.Exit(1)
    console.print(
        Panel(
            f"Failover chain: [bold]{' → '.join(active)}[/bold]\n"
            "Type a question, or /status, /quit.",
            title="llm-gateway chat",
            border_style="cyan",
        )
    )
    while True:
        try:
            line = console.input("[bold]you>[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            break
        if line == "/status":
            console.print(_status_table(gw.status()))
            continue
        try:
            with console.status("[dim]asking...[/dim]"):
                resp = gw.ask(line)
            _print_response(resp)
        except GatewayError as exc:
            console.print(f"[red]{exc}[/red]")
    gw.close()


@app.command()
def ask(
    prompt: Annotated[str, typer.Argument(help="The question to ask.")],
    config: ConfigOpt = None,
    image: Annotated[
        list[str] | None,
        typer.Option("--image", "-i", help="Attach an image (file path or URL); repeatable."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print full response envelope.")] = False,
) -> None:
    """One-shot question (scripting-friendly). Add --image for vision queries."""
    gw = Gateway(config_file=config)
    try:
        resp = gw.ask(prompt, images=image or ())
    except (GatewayError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    finally:
        gw.close()
    if as_json:
        console.print_json(resp.model_dump_json(exclude={"raw"}))
    else:
        _print_response(resp)


@app.command()
def status(config: ConfigOpt = None) -> None:
    """Show per-provider quota usage, cooldowns, and next availability."""
    gw = Gateway(config_file=config)
    console.print(_status_table(gw.status()))
    gw.close()


@app.command()
def providers(config: ConfigOpt = None) -> None:
    """List the provider registry, including disabled entries and why."""
    gw = Gateway(config_file=config)
    table = Table(title="Provider registry")
    for col in ("#", "Provider", "Model", "Env var", "Key set", "Enabled", "Notes"):
        table.add_column(col)
    for p in gw.config.providers:
        table.add_row(
            str(p.priority),
            p.name,
            p.model,
            p.api_key_env,
            "[green]✔[/green]" if p.resolve_api_key() else "[red]✘[/red]",
            "[green]yes[/green]" if p.enabled else "[dim]no[/dim]",
            p.notes,
        )
    console.print(table)
    gw.close()


@app.command()
def reset(
    config: ConfigOpt = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="Reset one provider only.")
    ] = None,
) -> None:
    """Clear local usage counters and cooldowns (e.g. after a demo)."""
    gw = Gateway(config_file=config)
    gw.reset_state(provider)
    target = provider or "all providers"
    console.print(f"Local usage state cleared for {target}.")
    gw.close()


if __name__ == "__main__":
    app()
