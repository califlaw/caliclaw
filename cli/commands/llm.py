"""caliclaw llm — point caliclaw at a different LLM provider endpoint.

Claude Code natively respects ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN.
We persist them into .env and the daemon picks them up on next restart.

Presets:
    anthropic   — default, no override (use Claude Code login or ANTHROPIC_API_KEY)
    openrouter  — https://openrouter.ai/api/v1 (Claude models only via OR's
                  Anthropic-compatible /v1/messages endpoint)
    custom      — free-form URL + token (claude-code-router, LiteLLM, your own
                  proxy that translates to GPT/Gemini/Llama)

`status` prints the current provider without writing anything.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


_PRESETS = {
    "anthropic":  ("(default)",                          "Anthropic direct — Claude Code login or ANTHROPIC_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1",       "OpenRouter (Anthropic-compat — Claude models only)"),
    "custom":     ("",                                   "Custom URL + token (ccr / LiteLLM / your proxy)"),
}


def _upsert_env(project_root: Path, key: str, value: Optional[str]) -> None:
    """Set or remove KEY=value in .env. None / empty value removes the line."""
    env_file = project_root / ".env"
    lines: list[str] = []
    found = False
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{key}="):
                if value:
                    lines.append(f"{key}={value}")
                    found = True
                # else: skip (delete)
            else:
                lines.append(line)
    if value and not found:
        lines.append(f"{key}={value}")
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(lines) + "\n" if lines else "")


def _get_env(project_root: Path, key: str) -> str:
    env_file = project_root / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def _is_bot_running(project_root: Path) -> tuple[bool, int | None]:
    pid_file = project_root / "data" / "caliclaw.pid"
    if not pid_file.exists():
        return False, None
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except ProcessLookupError:
        return False, pid
    except PermissionError:
        return True, pid


def _print_status(project_root: Path) -> None:
    from cli.ui import ui
    base = _get_env(project_root, "ANTHROPIC_BASE_URL")
    token = _get_env(project_root, "ANTHROPIC_AUTH_TOKEN")
    ui.c.print()
    if not base:
        ui.c.print("  [bold]Provider:[/bold]  [red]anthropic (default)[/red]")
        ui.c.print("  [dim]Using Claude Code login or ANTHROPIC_API_KEY.[/dim]")
    else:
        ui.c.print(f"  [bold]Endpoint:[/bold]  [red]{base}[/red]")
        if token:
            masked = token[:6] + "…" + token[-4:] if len(token) > 12 else "set"
            ui.c.print(f"  [bold]Token:[/bold]     [dim]{masked}[/dim]")
        else:
            ui.c.print("  [bold]Token:[/bold]     [yellow]not set[/yellow]")
    ui.c.print()


def _restart_if_running(project_root: Path) -> None:
    from cli.ui import ui
    alive, pid = _is_bot_running(project_root)
    if not alive:
        ui.info("Start the bot with [bold red]caliclaw start[/bold red] to apply.")
        return
    ui.c.print()
    ui.info(f"Bot is running (pid {pid}). Restart to apply?")
    try:
        confirm = input("  Restart now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"
        ui.c.print()
    if confirm in ("", "y", "yes"):
        import subprocess
        with ui.spin("Restarting..."):
            subprocess.run(
                [sys.executable, "-m", "cli.caliclaw_cli", "restart"],
                cwd=str(project_root),
                capture_output=True,
            )
        ui.ok("Bot restarted")
    else:
        ui.info("Run [bold red]caliclaw restart[/bold red] manually when ready.")


def _apply_anthropic(project_root: Path) -> None:
    """Reset to Anthropic-direct: clear both env vars."""
    from cli.ui import ui
    _upsert_env(project_root, "ANTHROPIC_BASE_URL", None)
    _upsert_env(project_root, "ANTHROPIC_AUTH_TOKEN", None)
    ui.ok("Provider reset to Anthropic direct (cleared BASE_URL + AUTH_TOKEN).")


def _apply_openrouter(project_root: Path, token: Optional[str]) -> None:
    from cli.ui import ui
    base = _PRESETS["openrouter"][0]
    if not token:
        if not sys.stdin.isatty():
            ui.fail("Non-interactive: pass token as 3rd arg — caliclaw llm openrouter <key>")
            sys.exit(1)
        ui.c.print()
        ui.c.print("  [dim]Get a key at https://openrouter.ai/keys (starts with sk-or-...)[/dim]")
        try:
            token = input("  OpenRouter API key: ").strip()
        except (EOFError, KeyboardInterrupt):
            ui.c.print()
            ui.info("Cancelled.")
            return
    if not token:
        ui.fail("Empty token — nothing written.")
        return
    _upsert_env(project_root, "ANTHROPIC_BASE_URL", base)
    _upsert_env(project_root, "ANTHROPIC_AUTH_TOKEN", token)
    ui.ok(f"Wrote ANTHROPIC_BASE_URL={base}")
    ui.ok("Wrote ANTHROPIC_AUTH_TOKEN=*****")


def _apply_custom(project_root: Path, url: Optional[str]) -> None:
    from cli.ui import ui
    if not url:
        if not sys.stdin.isatty():
            ui.fail("Non-interactive: pass URL as 3rd arg — caliclaw llm custom <url>")
            sys.exit(1)
        ui.c.print()
        ui.c.print("  [dim]Anthropic-compatible endpoint (claude-code-router, LiteLLM, …)[/dim]")
        try:
            url = input("  Base URL (e.g. http://localhost:3456): ").strip()
        except (EOFError, KeyboardInterrupt):
            ui.c.print()
            ui.info("Cancelled.")
            return
    if not url:
        ui.fail("Empty URL — nothing written.")
        return
    token = ""
    if sys.stdin.isatty():
        try:
            token = input("  Auth token (leave empty if proxy doesn't need one): ").strip()
        except (EOFError, KeyboardInterrupt):
            ui.c.print()
            return
    _upsert_env(project_root, "ANTHROPIC_BASE_URL", url)
    _upsert_env(project_root, "ANTHROPIC_AUTH_TOKEN", token or None)
    ui.ok(f"Wrote ANTHROPIC_BASE_URL={url}")
    if token:
        ui.ok("Wrote ANTHROPIC_AUTH_TOKEN=*****")
    else:
        ui.info("No auth token set — proxy must accept unauthenticated requests.")


def _list_presets() -> None:
    from cli.ui import ui
    ui.c.print()
    ui.c.print("  [bold]Available providers:[/bold]")
    for name, (default, desc) in _PRESETS.items():
        ui.c.print(f"    [bold red]{name:<11}[/bold red] [dim]{desc}[/dim]")
    ui.c.print()
    ui.c.print("  [dim]Usage:[/dim]")
    ui.c.print("    [bold]caliclaw llm[/bold]                  show current provider")
    ui.c.print("    [bold]caliclaw llm anthropic[/bold]        reset to Claude direct")
    ui.c.print("    [bold]caliclaw llm openrouter[/bold] [<key>]  route through OpenRouter")
    ui.c.print("    [bold]caliclaw llm custom[/bold] [<url>]      custom Anthropic-compat proxy")
    ui.c.print()


async def cmd_llm(args: argparse.Namespace) -> None:
    """Configure which LLM endpoint Claude Code subprocesses hit."""
    from core.config import get_settings
    from cli.ui import ui

    settings = get_settings()
    project_root = settings.project_root

    action = (getattr(args, "llm_action", "") or "").strip().lower()
    value = (getattr(args, "llm_value", "") or "").strip()

    if not action or action == "status":
        _print_status(project_root)
        if not action:
            _list_presets()
        return

    if action == "list" or action == "help":
        _list_presets()
        return

    if action == "anthropic":
        _apply_anthropic(project_root)
    elif action == "openrouter":
        _apply_openrouter(project_root, value or None)
    elif action == "custom":
        _apply_custom(project_root, value or None)
    else:
        ui.fail(f"Unknown provider: {action}")
        _list_presets()
        sys.exit(1)
        return

    _restart_if_running(project_root)
