"""Helpers for enabling the obsidian skill — prompts for vault path and
persists it into .env so the user doesn't have to edit the file by hand.
"""
from __future__ import annotations

from pathlib import Path


def _upsert_env(project_root: Path, key: str, value: str) -> None:
    """Set KEY=value in .env, replacing any existing line."""
    env_file = project_root / ".env"
    lines: list[str] = []
    found = False
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines) + "\n")


def _get_env(project_root: Path, key: str) -> str:
    env_file = project_root / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def configure_after_enable(project_root: Path) -> None:
    """Interactive setup run right after `caliclaw skills obsidian on`.

    Prompts for the vault path unless one is already configured and valid.
    Silently skips when stdin isn't a TTY (scripted installs).
    """
    import sys
    from cli.ui import ui

    current = _get_env(project_root, "OBSIDIAN_VAULT_PATH")
    if current:
        p = Path(current).expanduser()
        if p.exists() and p.is_dir():
            ui.info(f"Obsidian vault already set: {p}")
            return
        ui.warn(f"OBSIDIAN_VAULT_PATH points to a missing dir: {current}")

    if not sys.stdin.isatty():
        ui.info(
            "Set OBSIDIAN_VAULT_PATH=<path> in .env when you have a vault "
            "handy. Skill works as soon as the var is set."
        )
        return

    ui.c.print()
    ui.c.print("  [bold]Obsidian vault[/bold]")
    ui.c.print("  [dim]Absolute path to your vault (empty to skip):[/dim]")
    raw = input("  Vault path: ").strip()
    if not raw:
        ui.info("Skipped. Set OBSIDIAN_VAULT_PATH in .env later.")
        return

    path = Path(raw).expanduser().resolve()
    if not path.exists():
        ui.warn(f"Path doesn't exist yet — saved anyway: {path}")
    elif not path.is_dir():
        ui.fail("Not a directory — nothing written.")
        return

    _upsert_env(project_root, "OBSIDIAN_VAULT_PATH", str(path))
    ui.ok(f"Wrote OBSIDIAN_VAULT_PATH={path} to .env")
    ui.info("Restart caliclaw to pick it up: caliclaw restart")
