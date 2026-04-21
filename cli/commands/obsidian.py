"""Helpers for enabling the obsidian skill — prompts for vault path and
persists it into .env so the user doesn't have to edit the file by hand.
"""
from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import List, Optional


def _obsidian_config_path() -> Optional[Path]:
    """Location of Obsidian's per-user config file (lists known vaults)."""
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    if system == "Windows":
        import os as _os
        appdata = _os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "obsidian" / "obsidian.json"
        return None
    # Linux / other unix
    return home / ".config" / "obsidian" / "obsidian.json"


def detect_vaults() -> List[Path]:
    """Return all vault paths Obsidian knows about, newest-used first.

    Falls back to scanning a few common locations for a `.obsidian/` dir
    if the config file is absent (Obsidian never launched, or flatpak
    install with odd paths).
    """
    vaults: List[tuple[float, Path]] = []

    cfg = _obsidian_config_path()
    if cfg and cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            for entry in (data.get("vaults") or {}).values():
                p = entry.get("path")
                ts = entry.get("ts") or 0
                if p:
                    path = Path(p)
                    if path.exists() and path.is_dir():
                        vaults.append((float(ts), path))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass

    if not vaults:
        home = Path.home()
        candidates = [
            home / "Documents",
            home / "Notes",
            home / "Obsidian",
            home,
        ]
        seen: set[Path] = set()
        for root in candidates:
            if not root.exists():
                continue
            try:
                for marker in root.glob("*/.obsidian"):
                    vault = marker.parent
                    if vault in seen:
                        continue
                    seen.add(vault)
                    try:
                        vaults.append((marker.stat().st_mtime, vault))
                    except OSError:
                        pass
            except OSError:
                continue

    vaults.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in vaults]


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

    1. If env already has a valid vault → nothing to do.
    2. Auto-detect vaults from Obsidian's own config. If exactly one
       is found, use it. If multiple, ask the user to pick.
    3. Fall back to a free-form path prompt if nothing detected.
    4. Non-TTY (scripted install) → silently log and move on.
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

    detected = detect_vaults()

    if not sys.stdin.isatty():
        if detected:
            chosen = detected[0]
            _upsert_env(project_root, "OBSIDIAN_VAULT_PATH", str(chosen))
            ui.ok(f"Auto-detected vault: {chosen}")
            return
        ui.info(
            "Set OBSIDIAN_VAULT_PATH=<path> in .env when you have a vault "
            "handy. Skill works as soon as the var is set."
        )
        return

    ui.c.print()
    ui.c.print("  [bold]Obsidian vault[/bold]")

    chosen: Optional[Path] = None
    if len(detected) == 1:
        ui.c.print(f"  [dim]Detected:[/dim] {detected[0]}")
        raw = input("  Use this? [Y/n]: ").strip().lower()
        if raw in ("", "y", "yes"):
            chosen = detected[0]
    elif len(detected) > 1:
        ui.c.print("  [dim]Detected vaults:[/dim]")
        for i, v in enumerate(detected, 1):
            ui.c.print(f"    {i}. {v}")
        ui.c.print("  [dim]Pick a number, paste a custom path, or leave empty to skip:[/dim]")
        raw = input("  Choice: ").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(detected):
                chosen = detected[idx]
        elif raw:
            chosen = Path(raw).expanduser().resolve()
    else:
        ui.c.print("  [dim]Could not auto-detect. Paste a path (empty to skip):[/dim]")
        raw = input("  Vault path: ").strip()
        if raw:
            chosen = Path(raw).expanduser().resolve()

    if chosen is None:
        ui.info("Skipped. Set OBSIDIAN_VAULT_PATH in .env later.")
        return

    if not chosen.exists():
        ui.warn(f"Path doesn't exist yet — saved anyway: {chosen}")
    elif not chosen.is_dir():
        ui.fail("Not a directory — nothing written.")
        return

    _upsert_env(project_root, "OBSIDIAN_VAULT_PATH", str(chosen))
    ui.ok(f"Wrote OBSIDIAN_VAULT_PATH={chosen} to .env")
    ui.info("Restart caliclaw to pick it up: caliclaw restart")
