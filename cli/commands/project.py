"""caliclaw project — switch active project from the terminal.

Mirrors /project in Telegram. State and storage are shared (state file at
data/state/active_project, projects under agents/projects/<name>/).
"""
from __future__ import annotations

import argparse
import sys


async def cmd_project(args: argparse.Namespace) -> None:
    from cli.ui import ui
    from core.projects import (
        create_project,
        get_active_project,
        list_projects,
        project_exists,
        set_active_project,
    )

    action = (getattr(args, "project_action", "") or "").strip().lower()
    arg = (getattr(args, "project_value", "") or "").strip()

    active = get_active_project()
    projects = list_projects()

    def _print_status() -> None:
        ui.c.print()
        if active:
            ui.c.print(f"  [bold]Active:[/bold] [red]{active}[/red]")
        else:
            ui.c.print("  [bold]Active:[/bold] [dim]global (no project)[/dim]")
        ui.c.print()
        if projects:
            ui.c.print("  [bold]Projects:[/bold]")
            for p in projects:
                marker = "[red]▶[/red]" if p == active else " "
                ui.c.print(f"    {marker} [bold]{p}[/bold]")
        else:
            ui.c.print("  [dim]No projects yet — `caliclaw project new <name>` to scaffold.[/dim]")
        ui.c.print()

    if not action or action == "status":
        _print_status()
        if not action:
            ui.c.print("  [dim]Commands:[/dim]")
            ui.c.print("    [bold]caliclaw project use <name>[/bold]   switch")
            ui.c.print("    [bold]caliclaw project new <name>[/bold]   scaffold + switch")
            ui.c.print("    [bold]caliclaw project off[/bold]          back to global")
            ui.c.print("    [bold]caliclaw project list[/bold]         list only")
            ui.c.print()
        return

    if action == "list":
        if not projects:
            ui.info("No projects yet.")
            return
        for p in projects:
            marker = "▶" if p == active else " "
            ui.c.print(f"  {marker} [bold]{p}[/bold]")
        return

    if action == "off":
        if not active:
            ui.info("Already on global.")
            return
        set_active_project(None)
        ui.ok("Switched to global.")
        return

    if action == "use":
        if not arg:
            ui.fail("Need a project name. caliclaw project use <name>")
            sys.exit(1)
        if not project_exists(arg):
            ui.fail(f"Project '{arg}' not found.")
            if projects:
                ui.info(f"Available: {', '.join(projects)}")
            ui.info(f"Create: caliclaw project new {arg}")
            sys.exit(1)
        set_active_project(arg)
        ui.ok(f"Switched to project [bold red]{arg}[/bold red].")
        return

    if action == "new":
        if not arg:
            ui.fail("Need a project name. caliclaw project new <name>")
            sys.exit(1)
        if project_exists(arg):
            ui.warn(f"Project '{arg}' already exists.")
            ui.info(f"Switch: caliclaw project use {arg}")
            return
        pdir = create_project(arg)
        # Don't auto-activate — the soul is just a template stub. User
        # edits it and explicitly switches with `caliclaw project use`.
        ui.ok(f"Project [bold red]{arg}[/bold red] scaffolded.")
        ui.info(f"Edit: {pdir / 'main' / 'SOUL.md'}")
        ui.info(f"Then activate: caliclaw project use {arg}")
        return

    ui.fail(f"Unknown action: {action}")
    ui.info("Try: caliclaw project")
    sys.exit(1)
