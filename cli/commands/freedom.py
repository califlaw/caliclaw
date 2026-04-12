"""caliclaw freedom — full machine control toggle."""
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_SUDOERS_FILE = Path("/etc/sudoers.d/caliclaw")


def _write_freedom_to_env(project_root: Path, enabled: bool) -> None:
    env_file = project_root / ".env"
    lines: list[str] = []
    found = False
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("FREEDOM_MODE="):
                lines.append(f"FREEDOM_MODE={'true' if enabled else 'false'}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"FREEDOM_MODE={'true' if enabled else 'false'}")
    env_file.write_text("\n".join(lines) + "\n")


def cmd_freedom(args: argparse.Namespace) -> None:
    from core.config import get_settings
    from cli.ui import ui
    from cli.commands.model import _is_bot_running

    settings = get_settings()
    action = (getattr(args, "freedom_action", "") or "").strip().lower()

    if action in ("on", "enable"):
        _enable_freedom(settings, ui)
        # Auto-restart bot
        alive, pid = _is_bot_running(settings.project_root)
        if alive:
            ui.c.print()
            import time
            from cli.caliclaw_cli import cmd_restart_sync
            cmd_restart_sync(argparse.Namespace(debug=False))
        return

    if action in ("off", "disable"):
        _disable_freedom(settings, ui)
        alive, pid = _is_bot_running(settings.project_root)
        if alive:
            ui.c.print()
            from cli.caliclaw_cli import cmd_restart_sync
            cmd_restart_sync(argparse.Namespace(debug=False))
        return

    # Status
    ui.c.print()
    if settings.freedom_mode:
        ui.c.print("  [bold red]🔓 FREEDOM: ON[/bold red]")
        ui.c.print("  [dim]☠  Full machine control — no approval, sudo without password[/dim]")
        ssh_key = Path.home() / ".ssh" / "id_ed25519"
        if ssh_key.exists():
            ui.c.print(f"  [dim]🔑 SSH key: {ssh_key} (ready)[/dim]")
        sudoers_ok = _SUDOERS_FILE.exists()
        if sudoers_ok:
            ui.c.print("  [dim]🔧 sudo NOPASSWD: active[/dim]")
    else:
        ui.c.print("  [bold green]🔒 FREEDOM: OFF[/bold green]")
        ui.c.print("  [dim]Agent asks approval before dangerous actions[/dim]")
    ui.c.print()
    if settings.freedom_mode:
        ui.c.print("  [dim]caliclaw freedom off  — restore guardrails[/dim]")
    else:
        ui.c.print("  [dim]caliclaw freedom on   — give full control (requires sudo)[/dim]")
    ui.c.print()


def _enable_freedom(settings, ui) -> None:
    ui.c.print()
    ui.c.print("[bold red]🔓 ENABLING FREEDOM MODE[/bold red]")
    ui.c.print("[dim red]Full machine control. No guardrails. No regrets.[/dim red]")
    ui.c.print()

    user = getpass.getuser()

    # 1. Write FREEDOM_MODE=true to .env
    _write_freedom_to_env(settings.project_root, True)
    ui.ok("FREEDOM_MODE=true")

    # 2. Configure sudo NOPASSWD
    if not _SUDOERS_FILE.exists():
        sudoers_line = f"{user} ALL=(ALL) NOPASSWD:ALL"
        ui.info(f"Configuring sudo NOPASSWD for '{user}'...")
        try:
            # Write to temp file first, then use sudo to move it
            tmp = settings.project_root / "data" / "caliclaw.sudoers.tmp"
            tmp.write_text(sudoers_line + "\n")
            subprocess.run(
                ["sudo", "cp", str(tmp), str(_SUDOERS_FILE)],
                check=True,
            )
            subprocess.run(
                ["sudo", "chmod", "0440", str(_SUDOERS_FILE)],
                check=True,
            )
            tmp.unlink(missing_ok=True)
            ui.ok("sudo NOPASSWD configured")
        except subprocess.CalledProcessError:
            ui.warn("Could not configure sudo (need sudo access)")
            ui.info(f"Manual: echo '{sudoers_line}' | sudo tee {_SUDOERS_FILE}")
    else:
        ui.ok("sudo NOPASSWD already configured")

    # 3. Generate SSH key if missing
    ssh_key = Path.home() / ".ssh" / "id_ed25519"
    if not ssh_key.exists():
        ui.info("Generating SSH key (ed25519, no passphrase)...")
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", str(ssh_key), "-N", ""],
            check=False,
            capture_output=True,
        )
        if ssh_key.exists():
            ui.ok(f"SSH key: {ssh_key}")
            pub = ssh_key.with_suffix(".pub").read_text().strip()
            ui.c.print(f"  [dim]Public key: {pub[:60]}...[/dim]")
        else:
            ui.warn("ssh-keygen failed")
    else:
        ui.ok(f"SSH key exists: {ssh_key}")

    # 4. Install sshpass if missing
    if not shutil.which("sshpass"):
        ui.info("Installing sshpass...")
        try:
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", "sshpass"],
                check=True,
                capture_output=True,
            )
            ui.ok("sshpass installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            ui.warn("Could not install sshpass (apt not available or sudo failed)")
    else:
        ui.ok("sshpass available")

    ui.c.print()
    ui.c.print("  [bold red]🔓 FREEDOM MODE: ON[/bold red]")
    ui.c.print("  [dim]Agent has full machine control. Use wisely.[/dim]")


def _disable_freedom(settings, ui) -> None:
    ui.c.print()
    ui.c.print("[bold green]🔒 DISABLING FREEDOM MODE[/bold green]")
    ui.c.print("[dim]Restoring guardrails.[/dim]")
    ui.c.print()

    # 1. Write FREEDOM_MODE=false to .env
    _write_freedom_to_env(settings.project_root, False)
    ui.ok("FREEDOM_MODE=false")

    # 2. Remove sudo NOPASSWD
    if _SUDOERS_FILE.exists():
        ui.info("Removing sudo NOPASSWD...")
        try:
            subprocess.run(
                ["sudo", "rm", "-f", str(_SUDOERS_FILE)],
                check=True,
            )
            ui.ok("sudo NOPASSWD removed")
        except subprocess.CalledProcessError:
            ui.warn(f"Could not remove {_SUDOERS_FILE} (need sudo)")
    else:
        ui.ok("sudo NOPASSWD was not configured")

    # SSH keys are NOT removed — they're useful regardless

    ui.c.print()
    ui.c.print("  [bold green]🔒 FREEDOM MODE: OFF[/bold green]")
    ui.c.print("  [dim]Agent will ask for approval before dangerous actions.[/dim]")
