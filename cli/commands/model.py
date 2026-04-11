"""caliclaw model — show or change the default Claude model."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

VALID_MODELS = ("haiku", "sonnet", "opus")

_MODEL_DESCRIPTIONS = {
    "haiku": "Fast, cheap, light tasks",
    "sonnet": "Balanced (default)",
    "opus": "Maximum reasoning, slower, heavier on daily limit",
}


def _write_model_to_env(project_root: Path, model: str) -> None:
    """Replace or append CLAUDE_DEFAULT_MODEL in .env, preserving other lines."""
    env_file = project_root / ".env"
    lines: list[str] = []
    found = False
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("CLAUDE_DEFAULT_MODEL="):
                lines.append(f"CLAUDE_DEFAULT_MODEL={model}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"CLAUDE_DEFAULT_MODEL={model}")
    env_file.write_text("\n".join(lines) + "\n")


def _is_bot_running(project_root: Path) -> tuple[bool, int | None]:
    """Check data/caliclaw.pid — returns (alive, pid)."""
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
        # Process exists but owned by someone else
        return True, pid


async def cmd_model(args: argparse.Namespace) -> None:
    """Show or set the default Claude model."""
    from core.config import get_settings
    from cli.ui import ui

    settings = get_settings()
    action = (getattr(args, "model_action", "") or "").strip().lower()
    value = (getattr(args, "model_value", "") or "").strip().lower()

    # Show
    if not action or action == "show" or action == "list":
        current = settings.claude_default_model
        ui.c.print()
        ui.c.print(f"  [bold]Current default:[/bold]  [red]{current}[/red]")
        ui.c.print()
        ui.c.print("  [bold]Available:[/bold]")
        for m in VALID_MODELS:
            marker = "[red]▶[/red]" if m == current else " "
            ui.c.print(f"    {marker} [bold]{m:<8}[/bold] [dim]{_MODEL_DESCRIPTIONS[m]}[/dim]")
        ui.c.print()
        ui.c.print("  [dim]To change:[/dim] [bold red]caliclaw model set <name>[/bold red]")
        ui.c.print()
        return

    # Set
    if action == "set":
        if not value:
            ui.fail("Missing model name.")
            ui.info(f"Usage: [bold]caliclaw model set <{'|'.join(VALID_MODELS)}>[/bold]")
            sys.exit(1)

        if value not in VALID_MODELS:
            ui.fail(f"Invalid model: [bold]{value}[/bold]")
            ui.info(f"Choose: [bold]{', '.join(VALID_MODELS)}[/bold]")
            sys.exit(1)

        if value == settings.claude_default_model:
            ui.info(f"Default model already [bold red]{value}[/bold red]. Nothing to do.")
            return

        _write_model_to_env(settings.project_root, value)
        ui.ok(f"Default model: [bold red]{value}[/bold red]")

        # Auto-restart if bot is running
        alive, pid = _is_bot_running(settings.project_root)
        if alive:
            ui.c.print()
            ui.info(f"Bot is running (pid {pid}). Restart to apply the new default?")
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
                        cwd=str(settings.project_root),
                        capture_output=True,
                    )
                ui.ok("Bot restarted")
            else:
                ui.info("Run [bold red]caliclaw restart[/bold red] manually when ready.")
        else:
            ui.info("Start the bot with [bold red]caliclaw start[/bold red] to apply.")
        return

    # Unknown action
    ui.fail(f"Unknown action: {action}")
    ui.info("Usage: [bold]caliclaw model[/bold] or [bold]caliclaw model set <name>[/bold]")
    sys.exit(1)
