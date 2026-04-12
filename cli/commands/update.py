"""caliclaw update — check PyPI and upgrade to the latest version."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request


def _parse_version(v: str) -> tuple[int, ...]:
    """Best-effort version parser — ignores anything past the numeric prefix."""
    parts: list[int] = []
    for chunk in v.split("."):
        num = ""
        for c in chunk:
            if c.isdigit():
                num += c
            else:
                break
        if num:
            parts.append(int(num))
    return tuple(parts) or (0,)


async def cmd_update(args: argparse.Namespace) -> None:
    """Check PyPI for a newer version of caliclaw and upgrade."""
    from cli.ui import ui
    from importlib.metadata import version as pkg_version, PackageNotFoundError

    try:
        current = pkg_version("caliclaw")
    except PackageNotFoundError:
        ui.fail("caliclaw is not installed via pip (running from source?).")
        ui.info("Use [bold red]git pull[/bold red] to update a source checkout.")
        return

    ui.c.print()
    ui.c.print(f"  Current version:  [bold]{current}[/bold]")

    try:
        with ui.spin("Checking PyPI for updates..."):
            req = urllib.request.Request(
                "https://pypi.org/pypi/caliclaw/json",
                headers={"User-Agent": f"caliclaw/{current}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                latest = data["info"]["version"]
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
        ui.fail(f"Could not reach PyPI: {e}")
        return

    ui.c.print(f"  Latest on PyPI:   [bold red]{latest}[/bold red]")
    ui.c.print()

    cur_t = _parse_version(current)
    lat_t = _parse_version(latest)

    if cur_t >= lat_t:
        ui.ok(f"Already on the latest version ({current}). Nothing to do.")
        return

    ui.info(f"New version available: [bold]{current}[/bold] → [bold red]{latest}[/bold red]")
    try:
        confirm = input("  Upgrade now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ui.c.print()
        return

    if confirm not in ("", "y", "yes"):
        ui.info("Cancelled.")
        return

    with ui.spin(f"Downloading {latest}..."):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "caliclaw"],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        ui.fail("Upgrade failed.")
        if result.stderr:
            tail = "\n".join(result.stderr.splitlines()[-8:])
            ui.c.print(f"[dim]{tail}[/dim]")
        return

    ui.ok(f"Upgraded to [bold red]{latest}[/bold red]")
    ui.c.print()

    # Suggest restart if the bot is running
    try:
        from cli.commands.model import _is_bot_running
        from core.config import get_settings
        alive, pid = _is_bot_running(get_settings().project_root)
    except (ImportError, RuntimeError):
        alive, pid = False, None

    if alive:
        ui.info(f"Bot is running (pid {pid}). Restart to apply:")
        ui.c.print("    [bold red]caliclaw restart[/bold red]")
    else:
        ui.info("Start the bot with [bold red]caliclaw start[/bold red].")
