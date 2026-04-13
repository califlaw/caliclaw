#!/usr/bin/env python3
"""caliclaw CLI — run as `caliclaw <command>`.

Thin dispatcher. Command implementations live in cli/commands/.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

# Fix macOS SSL: Python doesn't auto-use certifi's certificate bundle
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass


# ── Sync commands ──


def cmd_tui(args: argparse.Namespace) -> None:
    from cli.tui import run_tui
    run_tui()


def cmd_start_sync(args: argparse.Namespace) -> None:
    import subprocess
    import time
    from cli.ui import ui

    debug = getattr(args, "debug", False)

    # Auto-init if not set up yet
    from core.config import get_settings as _gs
    _settings = _gs()
    env_file = _settings.project_root / ".env"
    if not env_file.exists():
        ui.info("First run detected — running setup first")
        from cli.commands.init import cmd_init
        asyncio.run(cmd_init(args))

    pid_file = _settings.data_dir / "caliclaw.pid"

    # Kill ANY zombie __main__.py processes from previous runs
    _kill_zombies(pid_file)

    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 0)
            ui.warn(f"Already running (pid {pid})")
            ui.next_steps(["caliclaw restart"])
            return
        except ProcessLookupError:
            pid_file.unlink()

    ui.banner_small(ui.vibe("start"))

    # Find the right way to start the bot daemon
    import shutil as _sh
    main_py = _ROOT / "__main__.py"
    # Look for caliclaw-daemon next to sys.executable (pip install puts both in same dir)
    daemon_bin = _sh.which("caliclaw-daemon") or str(Path(sys.executable).parent / "caliclaw-daemon")
    if main_py.exists():
        cmd = [sys.executable, str(main_py)]
    elif Path(daemon_bin).exists():
        cmd = [daemon_bin]
    else:
        cmd = [sys.executable, "-m", "core.daemon"]
    if debug:
        cmd.append("--debug")

    work_dir = str(_settings.project_root) if _settings.project_root.exists() else str(_ROOT)

    if debug:
        subprocess.run(cmd, cwd=work_dir)
    else:
        log_path = _settings.project_root / "logs" / "caliclaw.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a")
        proc = subprocess.Popen(
            cmd, cwd=work_dir, stdout=log_file, stderr=log_file,
            start_new_session=True,
        )
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(proc.pid))

        with ui.spin("Starting up..."):
            time.sleep(3)

        try:
            os.kill(proc.pid, 0)
            ui.ok(f"Running (pid {proc.pid})")
            code_file = _ROOT / "data" / "pairing_code.txt"
            if code_file.exists():
                code = code_file.read_text().strip()
                ui.c.print(f"\n  [bold yellow]Pair with your bot:[/bold yellow]")
                ui.c.print(f"  [bold]/pair {code}[/bold]")
                ui.c.print()
            ui.next_steps([
                "caliclaw logs       View logs",
                "caliclaw pulse      System pulse",
                "caliclaw stop       Stop bot",
            ])
        except ProcessLookupError:
            ui.fail("Process died on startup")
            ui.next_steps(["caliclaw logs       Check what went wrong"])


def _kill_zombies(pid_file: Path) -> int:
    """Find and kill any orphaned __main__.py processes.

    Returns number of zombies killed. This prevents multiple bot instances
    from connecting to the same Telegram token (causes message duplication
    and stop command not working).
    """
    import signal
    main_script = str(_ROOT / "__main__.py")
    killed = 0

    # Get PID from file (this is the "known" process)
    known_pid = None
    if pid_file.exists():
        try:
            known_pid = int(pid_file.read_text().strip())
        except (ValueError, OSError):
            pass

    # Scan /proc for any __main__.py processes we own
    try:
        import getpass
        me = getpass.getuser()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == os.getpid() or pid == known_pid:
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().decode(errors="replace")
                if main_script in cmdline or ("__main__.py" in cmdline and "caliclaw" in cmdline):
                    # Check it's our user
                    stat = (entry / "status").read_text()
                    if f"Uid:\t{os.getuid()}" in stat:
                        os.kill(pid, signal.SIGKILL)
                        killed += 1
            except (OSError, PermissionError):
                continue
    except OSError:
        pass

    return killed


def cmd_stop_sync(args: argparse.Namespace) -> None:
    import signal
    from cli.ui import ui
    from core.config import get_settings

    pid_file = get_settings().data_dir / "caliclaw.pid"

    # Kill main process
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            ui.ok(f"{ui.vibe('stop')} (pid {pid})")
        except ProcessLookupError:
            pass
        pid_file.unlink()
    else:
        ui.info("Not running (no pid file).")

    # Kill any zombies left over from previous crashes/restarts
    zombies = _kill_zombies(pid_file)
    if zombies:
        ui.info(f"Cleaned up {zombies} orphaned process(es)")


def cmd_restart_sync(args: argparse.Namespace) -> None:
    import time
    args_stop = argparse.Namespace()
    cmd_stop_sync(args_stop)
    time.sleep(1)
    args.daemon = True
    cmd_start_sync(args)


def cmd_skills(args: argparse.Namespace) -> None:
    import shutil
    from cli.commands.init import install_skill_deps
    from core.config import get_settings, bundled_skills_path

    arg = (getattr(args, "skill_arg", "") or "").strip()
    extra = (getattr(args, "skill_extra", "") or "").strip()

    settings = get_settings()
    bundled = bundled_skills_path()

    from cli.commands.init import _get_available_skills
    available = _get_available_skills()
    skill_names = {n for n, _ in available}
    config_file = settings.project_root / "data" / "enabled_skills.txt"
    enabled = set()
    if config_file.exists():
        enabled = {l.strip() for l in config_file.read_text().split("\n") if l.strip()}

    def _skill_md(name: str) -> Path:
        """Return the path to a skill's SKILL.md — user dir first, then bundled."""
        user_path = settings.skills_dir / name / "SKILL.md"
        if user_path.exists():
            return user_path
        return bundled / name / "SKILL.md"

    if not arg:
        print(f"{'Skill':<18} {'Status':<10} {'Description'}")
        print("-" * 60)
        for name, desc in available:
            status = "ON" if name in enabled else "off"
            icon = "*" if name in enabled else " "
            print(f"{icon} {name:<17} {status:<10} {desc}")

    elif arg in ("new", "create", "add"):
        name = extra or input("Skill name: ").strip()
        if not name:
            print("Name required.")
            return
        desc = input("Description: ").strip()
        instructions = input("Instructions: ").strip()
        skill_dir = settings.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\n---\n\n{instructions}\n", encoding="utf-8",
        )
        enabled.add(name)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("\n".join(sorted(enabled)) + "\n")
        print(f"Created: {name}")

    elif arg == "rm":
        if not extra:
            print("Usage: caliclaw skills rm <name>")
            return
        skill_dir = settings.skills_dir / extra
        if not skill_dir.exists():
            print(f"Skill not found: {extra}")
            return
        shutil.rmtree(skill_dir)
        enabled.discard(extra)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("\n".join(sorted(enabled)) + "\n")
        print(f"Removed: {extra}")

    elif arg == "gym":
        # Browse community skills from caliclaw-gym
        from cli.ui import ui
        from core.gym import list_remote_skills
        ui.banner_small("gym")
        with ui.spin("Loading caliclaw-gym..."):
            skills = list_remote_skills()
        if not skills:
            ui.fail("Could not load gym (network or empty repo)")
            ui.info("Repo: https://github.com/califlaw/caliclaw-gym")
            return
        ui.c.print()
        ui.c.print(f"  [bold]🏋️ caliclaw-gym ({len(skills)} skills):[/bold]\n")
        for s in skills:
            installed = " [green](installed)[/green]" if s["name"] in skill_names else ""
            stars = f"[yellow]⭐ {s['stars']:>3}[/yellow]" if s.get('stars') else "[dim]⭐   0[/dim]"
            author = f"[dim]@{s.get('author', 'anonymous')}[/dim]"
            ui.c.print(f"  {stars}  [red]{s['name']:<20}[/red] {author}")
            ui.c.print(f"          [dim]{s['description']}[/dim]{installed}")
            ui.c.print()
        ui.next_steps([
            "caliclaw skills install <name>",
            "Vote for skills: 👍 react on GitHub issue",
        ])

    elif arg == "install":
        if not extra:
            print("Usage: caliclaw skills install <name>")
            return
        from cli.ui import ui
        from core.gym import install_skill
        with ui.spin(f"Pulling {extra} from gym..."):
            ok = install_skill(extra)
        if ok:
            ui.ok(f"Installed: {extra}")
            # Apply permission side-effects
            from security.engine_permissions import parse_skill_permissions, grant_tools
            perms = parse_skill_permissions(_skill_md(extra))
            if perms:
                grant_tools(perms)
                ui.info(f"Granted: {', '.join(perms)}")
        else:
            ui.fail(f"Failed to install {extra}")
            ui.info("Maybe already installed or not in gym")

    elif arg == "publish":
        if not extra:
            print("Usage: caliclaw skills publish <name>")
            return
        from core.gym import publish_skill
        print(publish_skill(extra))

    elif arg in skill_names and extra == "on":
        enabled.add(arg)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("\n".join(sorted(enabled)) + "\n")
        # Copy bundled skill into user's skills_dir if not there yet
        src = bundled / arg
        dst = settings.skills_dir / arg
        if src.exists() and dst.resolve() != src.resolve() and not dst.exists():
            settings.skills_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        install_skill_deps(arg)
        # Apply permission side-effects
        from security.engine_permissions import parse_skill_permissions, grant_tools
        perms = parse_skill_permissions(_skill_md(arg))
        if perms:
            grant_tools(perms)
            print(f"Enabled: {arg}  (granted: {', '.join(perms)})")
        else:
            print(f"Enabled: {arg}")

    elif arg in skill_names and extra == "off":
        enabled.discard(arg)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("\n".join(sorted(enabled)) + "\n")
        # Revoke permissions
        from security.engine_permissions import parse_skill_permissions, revoke_tools
        perms = parse_skill_permissions(_skill_md(arg))
        if perms:
            revoke_tools(perms)
            print(f"Disabled: {arg}  (revoked: {', '.join(perms)})")
        else:
            print(f"Disabled: {arg}")

    elif arg in skill_names:
        skill_md = _skill_md(arg)
        if skill_md.exists():
            print(skill_md.read_text(encoding="utf-8")[:1000])
        print(f"\nStatus: {'ON' if arg in enabled else 'off'}")

    else:
        print(f"Skill not found: {arg}")
        print("Use 'caliclaw skills' to see available skills.")


def cmd_auth(args: argparse.Namespace) -> None:
    import shutil
    import subprocess

    service = args.service
    if service == "status":
        print("Auth status:")
        if shutil.which("gh"):
            result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
            if result.returncode == 0:
                info = result.stderr.strip().split("\n")
                for line in info:
                    if "Logged in" in line or "account" in line.lower():
                        print(f"  GitHub: {line.strip()}")
                        break
                else:
                    print("  GitHub: authenticated")
            else:
                print("  GitHub: not authenticated")
        else:
            print("  GitHub: gh CLI not installed")
    elif service == "github":
        if not shutil.which("gh"):
            print("Install GitHub CLI first: https://cli.github.com")
            return
        subprocess.run(["gh", "auth", "login"])


def cmd_doctor(args: argparse.Namespace) -> None:
    import shutil
    from cli.ui import ui
    from core.config import get_settings

    settings = get_settings()
    root = settings.project_root

    ui.banner_small("doctor")
    ui.c.print()

    checks = [
        ("Python", sys.version.split()[0], True),
        (".env", "found" if (root / ".env").exists() else "missing", (root / ".env").exists()),
        ("Database", "found" if (settings.data_dir / "caliclaw.db").exists() else "missing", (settings.data_dir / "caliclaw.db").exists()),
        ("Engine", shutil.which("claude") or "not found", bool(shutil.which("claude"))),
        ("ffmpeg", shutil.which("ffmpeg") or "not found", bool(shutil.which("ffmpeg"))),
    ]

    whisper_found = shutil.which("whisper-cpp") or shutil.which("whisper")
    if not whisper_found:
        for candidate in [root / "vendor" / "whisper.cpp" / "build" / "bin" / "whisper-cli", _ROOT / "vendor" / "whisper.cpp" / "build" / "bin" / "whisper-cli"]:
            if candidate.exists():
                whisper_found = str(candidate)
                break
    checks.append(("whisper-cpp", whisper_found or "not found", bool(whisper_found)))

    model_path = root / "models" / "ggml-base.bin"
    if not model_path.exists():
        model_path = _ROOT / "models" / "ggml-base.bin"
    checks.append(("whisper model", "found" if model_path.exists() else "not found", model_path.exists()))

    agents_dir = settings.agents_dir / "global" / "main"
    checks.append(("Main agent", "found" if agents_dir.exists() else "missing", agents_dir.exists()))

    all_ok = True
    for name, value, ok in checks:
        if ok:
            ui.ok(f"{name}: {value}")
        else:
            ui.fail(f"{name}: {value}")
            all_ok = False

    for sf in ["SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md"]:
        exists = (agents_dir / sf).exists() if agents_dir.exists() else False
        (ui.ok if exists else ui.warn)(f"{sf}{'' if exists else ' missing'}")

    # Auto-cleanup stale openclaw files (causes "Credit is too low")
    stale_files = []
    for stale_name in ["auth-profiles.json", "models.json"]:
        f = agents_dir / stale_name
        if agents_dir.exists() and f.exists():
            f.unlink()
            stale_files.append(stale_name)
    for stale_name in ["openclaw_config.json", "telegram-default-allowFrom.json", "telegram-pairing.json"]:
        f = settings.data_dir / stale_name
        if f.exists():
            f.unlink()
            stale_files.append(stale_name)
    if stale_files:
        ui.warn(f"Removed stale openclaw files: {', '.join(stale_files)}")
        ui.info("These conflict with Claude Code subscription. Run: caliclaw restart")

    if all_ok:
        ui.done("All checks passed.")
    else:
        ui.c.print()
        ui.fail("Some checks failed")
        ui.next_steps(["caliclaw init    Fix missing components"])


def cmd_backup(args: argparse.Namespace) -> None:
    """Create a backup or list existing ones."""
    from cli.ui import ui
    from core.backup import create_backup, list_backups, cleanup_old_backups

    arg = (getattr(args, "backup_arg", "") or "").strip()

    if arg == "list":
        backups = list_backups()
        if not backups:
            ui.info("No backups yet.")
            return
        ui.c.print(f"\n  [bold]Backups ({len(backups)}):[/bold]\n")
        for b in backups:
            size_mb = b.stat().st_size / 1024 / 1024
            mtime = b.stat().st_mtime
            from datetime import datetime
            ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            ui.c.print(f"  [dim]{ts}[/dim]  {b.name}  [red]{size_mb:.1f}MB[/red]")
        ui.c.print()
        return

    with ui.spin("Creating backup..."):
        backup_path = create_backup()

    size_mb = backup_path.stat().st_size / 1024 / 1024
    ui.ok(f"Backup created: {backup_path.name} ({size_mb:.1f}MB)")

    # Cleanup old
    deleted = cleanup_old_backups(keep=10)
    if deleted:
        ui.info(f"Cleaned up {deleted} old backup(s)")


def cmd_comeback(args: argparse.Namespace) -> None:
    """Restore from a backup. 'I'll be back.'"""
    from cli.ui import ui
    from core.backup import latest_backup, restore_backup, list_backups

    arg = (getattr(args, "backup_file", "") or "").strip()

    if not arg:
        # Use latest
        backup_path = latest_backup()
        if not backup_path:
            ui.fail("No backups found.")
            ui.info("Run: caliclaw backup")
            return
    else:
        # Specific file or name
        backup_path = Path(arg)
        if not backup_path.exists():
            # Try as name in backups dir
            backup_path = _ROOT / "backups" / arg
            if not backup_path.exists():
                ui.fail(f"Backup not found: {arg}")
                return

    ui.c.print(f"\n  [bold]Restoring from:[/bold] {backup_path.name}")
    confirm = input("  Continue? (yes/no): ").strip().lower()
    if confirm not in ("yes", "y"):
        ui.info("Cancelled.")
        return

    with ui.spin("Reviving..."):
        restore_backup(backup_path)

    ui.c.print()
    ui.c.print("  [bold green]🔱 I'll be back.[/bold green]")
    ui.ok(f"Restored from {backup_path.name}")
    ui.next_steps(["caliclaw restart    Apply restored state"])


def cmd_service(args: argparse.Namespace) -> None:
    """Install/uninstall systemd service for auto-start."""
    import getpass
    import subprocess
    from cli.ui import ui

    action = (getattr(args, "service_action", "") or "").strip()

    if action == "install":
        user = getpass.getuser()
        home = Path.home()
        venv_python = f"{_ROOT}/.venv/bin/python"
        if not Path(venv_python).exists():
            venv_python = sys.executable

        # Build PATH that includes common user-local bin dirs
        # so systemd can find claude CLI and other tools
        sys_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        extra_dirs = [
            f"{home}/.local/bin",
            f"{home}/.cargo/bin",
            "/usr/local/bin",
        ]
        full_path = ":".join(dict.fromkeys(
            extra_dirs + sys_path.split(":")
        ))

        service = (
            "[Unit]\n"
            "Description=caliclaw Personal AI Assistant\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"User={user}\n"
            f"WorkingDirectory={_ROOT}\n"
            f"ExecStart={venv_python} {_ROOT}/__main__.py\n"
            "Restart=on-failure\n"
            "RestartSec=10\n"
            f"Environment=PYTHONUNBUFFERED=1\n"
            f'Environment="PATH={full_path}"\n'
            "TimeoutStopSec=30\n"
            "KillSignal=SIGTERM\n"
            f"StandardOutput=append:{_ROOT}/logs/caliclaw.log\n"
            f"StandardError=append:{_ROOT}/logs/caliclaw.log\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )

        service_path = Path("/etc/systemd/system/caliclaw.service")
        tmp_path = _ROOT / "data" / "caliclaw.generated.service"
        tmp_path.write_text(service)

        ui.info(f"Installing service for user '{user}'...")
        try:
            subprocess.run(["sudo", "cp", str(tmp_path), str(service_path)], check=True)
            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            subprocess.run(["sudo", "systemctl", "enable", "caliclaw"], check=True)
            subprocess.run(["sudo", "systemctl", "start", "caliclaw"], check=True)
            ui.ok("Locked in. Never skips a session.")
            ui.info("Auto-starts on boot, auto-restarts on failure")
        except subprocess.CalledProcessError as e:
            ui.fail(f"Failed: {e}")
            ui.info(f"Manual install: sudo cp {tmp_path} /etc/systemd/system/caliclaw.service")

    elif action == "uninstall":
        ui.info("Removing service...")
        try:
            subprocess.run(["sudo", "systemctl", "stop", "caliclaw"], check=False)
            subprocess.run(["sudo", "systemctl", "disable", "caliclaw"], check=False)
            subprocess.run(["sudo", "rm", "-f", "/etc/systemd/system/caliclaw.service"], check=False)
            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            ui.ok("Unlocked. Rest day.")
        except subprocess.CalledProcessError as e:
            ui.fail(f"Failed: {e}")

    elif action == "status":
        subprocess.run(["systemctl", "status", "caliclaw", "--no-pager"])

    else:
        print("Usage:")
        print("  caliclaw service install     Lock in — auto-start on boot")
        print("  caliclaw service uninstall   Unlock — remove auto-start")
        print("  caliclaw service status      Check if locked in")


def cmd_immortal(args: argparse.Namespace) -> None:
    """Make caliclaw immortal — auto-start on boot, auto-restart on crash.

    Maps:
      caliclaw immortal           → status (clean summary)
      caliclaw immortal on        → install + enable + start (systemd)
      caliclaw immortal off       → stop + disable + uninstall
    """
    import subprocess
    from cli.ui import ui

    action = (getattr(args, "immortal_action", "") or "").strip().lower()

    if action in ("on", "enable", "install"):
        forwarded = argparse.Namespace(service_action="install")
        cmd_service(forwarded)
        return

    if action in ("off", "disable", "uninstall"):
        forwarded = argparse.Namespace(service_action="uninstall")
        cmd_service(forwarded)
        return

    # Default: clean status summary
    try:
        enabled = subprocess.run(
            ["systemctl", "is-enabled", "caliclaw"],
            capture_output=True, text=True,
        ).stdout.strip()
    except FileNotFoundError:
        ui.fail("systemctl not found — this command needs a systemd host.")
        return

    active = subprocess.run(
        ["systemctl", "is-active", "caliclaw"],
        capture_output=True, text=True,
    ).stdout.strip()

    ui.c.print()
    if enabled == "enabled":
        ui.c.print("  [bold red]☠[/bold red]  [bold]IMMORTAL[/bold]  [dim]survives reboots and crashes[/dim]")
    elif enabled in ("disabled", "static"):
        ui.c.print("  [yellow]![/yellow]  [bold]Mortal but installed[/bold]  [dim]systemd unit present, not enabled[/dim]")
    else:
        ui.c.print("  [dim]✗[/dim]  [bold]Mortal[/bold]  [dim]caliclaw won't survive a reboot[/dim]")

    if active == "active":
        ui.c.print("  [bold green]♥[/bold green]  [bold]Alive right now[/bold]")
    elif active == "inactive":
        ui.c.print("  [dim]·  Not running right now[/dim]")
    elif active == "failed":
        ui.c.print("  [bold red]✗[/bold red]  [bold red]Crashed[/bold red]  [dim]check: caliclaw logs[/dim]")

    ui.c.print()
    ui.c.print("  [dim]caliclaw immortal on   — make it immortal[/dim]")
    ui.c.print("  [dim]caliclaw immortal off  — break the seal[/dim]")
    ui.c.print()


# ── Async commands ──


async def cmd_status(args: argparse.Namespace) -> None:
    from core.db import Database
    from monitoring.tracking import UsageTracker
    from cli.ui import ui

    db = Database()
    await db.connect()
    tracker = UsageTracker(db)
    summary = await tracker.get_today_summary()
    agents = await db.list_agents()
    limit_status = await tracker.check_limits()

    ui.banner_small("pulse")
    ui.c.print()
    pct = summary["total_percent"]
    bar_color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
    ui.c.print(f"  Usage:    [{bar_color}]{pct:.1f}%[/{bar_color}] ({limit_status})")
    ui.c.print(f"  Requests: {summary['total_requests']}")
    ui.c.print(f"  Agents:   {len(agents)} registered")

    if summary["by_model"]:
        ui.c.print()
        ui.table(["Model", "Requests", "Usage"], [(m, str(d["count"]), f"{d['percent']:.1f}%") for m, d in summary["by_model"].items()])

    if agents:
        ui.c.print()
        rows = []
        for a in agents:
            color = {"active": "green", "paused": "yellow", "killed": "red"}.get(a["status"], "dim")
            rows.append((a["name"], a["scope"], f"[{color}]{a['status']}[/{color}]"))
        ui.table(["Agent", "Scope", "Status"], rows)

    async with db.db.execute("SELECT name, schedule_value, status FROM tasks ORDER BY name") as cur:
        tasks = [dict(r) for r in await cur.fetchall()]
    if tasks:
        ui.c.print()
        ui.table(["Task", "Schedule", "Status"], [(t["name"], t["schedule_value"], t["status"]) for t in tasks])

    await db.close()
    ui.c.print()


async def cmd_agents(args: argparse.Namespace) -> None:
    from core.db import Database
    from cli.ui import ui

    db = Database()
    await db.connect()
    agents = await db.list_agents()
    if not agents:
        ui.info("No agents registered.")
    else:
        rows = []
        for a in agents:
            color = {"active": "green", "paused": "yellow", "killed": "red"}.get(a["status"], "dim")
            rows.append((a["name"], a["scope"], f"[{color}]{a['status']}[/{color}]", a.get("project") or "—"))
        ui.table(["Name", "Scope", "Status", "Project"], rows)
    await db.close()


async def cmd_tasks(args: argparse.Namespace) -> None:
    from core.db import Database
    from cli.ui import ui

    db = Database()
    await db.connect()
    async with db.db.execute("SELECT * FROM tasks ORDER BY status, name") as cur:
        tasks = [dict(r) for r in await cur.fetchall()]
    if not tasks:
        ui.info("No scheduled tasks.")
    else:
        rows = [(str(t["id"]), t["name"], f"{t['schedule_type']}:{t['schedule_value']}", t.get("model", "—"), t["status"]) for t in tasks]
        ui.table(["ID", "Name", "Schedule", "Model", "Status"], rows)
    await db.close()


async def cmd_reset(args: argparse.Namespace) -> None:
    from core.db import Database

    from cli.ui import ui

    target = (args.target or "").strip()
    if not target:
        target = ui.radio([
            ("session", "Session — archive active sessions"),
            ("agents", "Agents — kill ephemeral agents"),
            ("tasks", "Tasks — pause all tasks"),
            ("all", "All — full reset"),
        ], title="What to reset?")

    if target not in ("session", "agents", "tasks", "all"):
        print(f"Unknown target: {target}. Use: session, agents, tasks, all")
        return

    db = Database()
    await db.connect()
    if target == "session":
        await db.db.execute("UPDATE sessions SET status = 'archived' WHERE status = 'active'")
        await db.db.commit()
        print("Sessions archived.")
    elif target == "agents":
        await db.db.execute("UPDATE agents SET status = 'killed' WHERE scope = 'ephemeral' AND status = 'active'")
        await db.db.commit()
        print("Ephemeral agents killed.")
    elif target == "tasks":
        await db.db.execute("UPDATE tasks SET status = 'paused'")
        await db.db.commit()
        print("All tasks paused.")
    elif target == "all":
        confirm = input("Full reset? (yes/no): ").strip().lower()
        if confirm not in ("yes", "y"):
            print("Cancelled.")
            await db.close()
            return
        await db.db.execute("UPDATE sessions SET status = 'archived' WHERE status = 'active'")
        await db.db.execute("UPDATE agents SET status = 'killed' WHERE scope = 'ephemeral'")
        await db.db.execute("UPDATE tasks SET status = 'paused'")
        await db.db.commit()
        print("Full reset done.")
    await db.close()


async def cmd_confirm(args: argparse.Namespace) -> None:
    from core.db import Database
    from security.approval import ApprovalManager

    db = Database()
    await db.connect()
    code = (args.code or "").strip()

    if not code:
        async with db.db.execute("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at DESC") as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        if not rows:
            print("No pending approvals.")
        else:
            print(f"Pending approvals ({len(rows)}):\n")
            for r in rows:
                print(f"  Code: {r['code']}  Agent: {r['agent_name']}  Action: {r['action']}  Level: {r['level']}")
        await db.close()
        return

    approval = await db.get_pending_approval(code)
    if not approval:
        print(f"No pending approval with code: {code}")
        await db.close()
        return

    print(f"  Agent:  {approval['agent_name']}")
    print(f"  Action: {approval['action']}")
    print(f"  Level:  {approval['level']}")
    confirm = input("\nApprove? (yes/no): ").strip().lower()

    mgr = ApprovalManager(db)
    await mgr.resolve(code, confirm in ("yes", "y"), "terminal")
    print("Approved." if confirm in ("yes", "y") else "Denied.")
    await db.close()


async def cmd_memory(args: argparse.Namespace) -> None:
    from intelligence.memory import MemoryManager
    mm = MemoryManager()
    query = (args.query or "").strip()

    if not query:
        entries = mm.load_all()
        if not entries:
            print("Memory is empty.")
        else:
            print(f"{'Name':<30} {'Type':<12} {'File':<30}")
            print("-" * 72)
            for e in entries:
                print(f"{e.name:<30} {e.type:<12} {e.filename:<30}")
    elif query == "flush":
        confirm = input("Flush ALL memory? This cannot be undone. (yes/no): ").strip().lower()
        if confirm in ("yes", "y"):
            for e in mm.load_all():
                mm.delete(e.filename)
            print("Memory flushed.")
    else:
        results = mm.search(query)
        if not results:
            print(f"Nothing found for '{query}'.")
        else:
            for e in results:
                print(f"\n## {e.name} ({e.type})")
                print(e.content[:500])


async def cmd_vault(args: argparse.Namespace) -> None:
    from security.vault import Vault
    import getpass

    vault = Vault()
    arg = (getattr(args, "vault_arg", "") or "").strip()
    value = (getattr(args, "vault_value", "") or "").strip()

    if arg == "init":
        pwd = getpass.getpass("Master password: ")
        pwd2 = getpass.getpass("Confirm: ")
        if pwd != pwd2:
            print("Passwords don't match.")
            return
        vault.initialize(pwd)
        print("Vault initialized.")
    elif not arg:
        pwd = getpass.getpass("Master password: ")
        if not vault.unlock(pwd):
            print("Wrong password.")
            return
        keys = vault.list_keys()
        if not keys:
            print("Vault is empty.")
        else:
            print(f"Secrets ({len(keys)}):")
            for k in keys:
                print(f"  - {k}")
    elif value:
        pwd = getpass.getpass("Master password: ")
        if not vault.unlock(pwd):
            print("Wrong password.")
            return
        vault.set(arg, value)
        print(f"Stored: {arg}")
    else:
        pwd = getpass.getpass("Master password: ")
        if not vault.unlock(pwd):
            print("Wrong password.")
            return
        try:
            val = vault.get(arg)
            print(f"{arg} = {val}")
        except KeyError:
            print(f"Not found: {arg}")


async def cmd_logs(args: argparse.Namespace) -> None:
    from core.config import get_settings
    log_file = get_settings().project_root / "logs" / "caliclaw.log"
    if not log_file.exists():
        print("No logs yet.")
        return
    lines = log_file.read_text().strip().split("\n")
    n = getattr(args, "lines", 50) or 50
    for line in lines[-n:]:
        print(line)


# ── Main ──


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="caliclaw",
        description="caliclaw — Personal AI Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  init              First-time setup
  start             Start bot (daemon)
  start --debug     Start in foreground
  stop              Stop bot
  restart           Restart bot
  chat              Terminal chat
  status            System status
  agents            List agents
  tasks             List scheduled tasks
  memory            Show all memory
  memory <query>    Search memory
  memory flush      Wipe all memory
  skills            List skills
  skills <name>     Show skill details
  skills <name> on  Enable skill
  skills <name> off Disable skill
  skills new        Create skill
  skills rm <name>  Remove skill
  skills gym        Browse community skills (caliclaw-gym)
  skills install <name>  Install from gym
  skills publish <name>  Publish your skill to gym
  confirm           List pending approvals
  confirm <code>    Approve action
  reset             Interactive reset
  vault             List secrets
  vault <key>       Get secret
  vault <key> <val> Set secret
  logs              Show recent logs (default 50)
  logs <N>          Show last N lines
  doctor            Health check
  backup            Create backup
  backup list       List existing backups
  comeback          Restore from latest backup ("I'll be back")
  comeback <file>   Restore from specific backup
  migrate <path>    Migrate from another *claw project
""",
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="First-time setup")
    p_init.add_argument("--force", action="store_true", help="Wipe existing config and re-init")
    sub.add_parser("reforge", help="Re-configure creds / profile / soul / skills / model")

    p_model = sub.add_parser("model", help="Show or set default Claude model")
    p_model.add_argument("model_action", nargs="?", default="")
    p_model.add_argument("model_value", nargs="?", default="")

    sub.add_parser("update", help="Check PyPI and upgrade to the latest version")
    p_start = sub.add_parser("start", help="Start bot")
    p_start.add_argument("--debug", action="store_true")
    sub.add_parser("stop", help="Stop bot")
    p_restart = sub.add_parser("restart", help="Restart bot")
    p_restart.add_argument("--debug", action="store_true")
    sub.add_parser("chat", help="Terminal chat")
    sub.add_parser("tui", help="Terminal chat (alias)")
    sub.add_parser("pulse", help="System pulse — usage, agents, tasks")
    sub.add_parser("status", help="Alias for pulse")
    sub.add_parser("agents", help="List agents")
    sub.add_parser("tasks", help="Scheduled tasks")

    p_skills = sub.add_parser("skills", help="List or manage skills")
    p_skills.add_argument("skill_arg", nargs="?", default="")
    p_skills.add_argument("skill_extra", nargs="?", default="")

    p_auth = sub.add_parser("auth", help="Authenticate services")
    p_auth.add_argument("service", choices=["github", "status"])
    sub.add_parser("doctor", help="Health check")

    p_service = sub.add_parser("service", help="Install auto-start service")
    p_service.add_argument("service_action", nargs="?", default="")

    p_immortal = sub.add_parser("immortal", help="Make caliclaw immortal — on/off/status")
    p_immortal.add_argument("immortal_action", nargs="?", default="")

    p_freedom = sub.add_parser("freedom", help="Full machine control — on/off/status")
    p_freedom.add_argument("freedom_action", nargs="?", default="")

    p_backup = sub.add_parser("backup", help="Create or list backups")
    p_backup.add_argument("backup_arg", nargs="?", default="")

    p_comeback = sub.add_parser("comeback", help="Restore from backup — I'll be back")
    p_comeback.add_argument("backup_file", nargs="?", default="")

    p_confirm = sub.add_parser("confirm", help="Approve or list pending actions")
    p_confirm.add_argument("code", nargs="?", default="")
    p_approve = sub.add_parser("approve")
    p_approve.add_argument("code", nargs="?", default="")

    p_reset = sub.add_parser("reset", help="Reset system state")
    p_reset.add_argument("target", nargs="?", default="")

    p_memory = sub.add_parser("memory", help="Show or search memory")
    p_memory.add_argument("query", nargs="?", default="")

    p_vault = sub.add_parser("vault", help="Manage secrets")
    p_vault.add_argument("vault_arg", nargs="?", default="")
    p_vault.add_argument("vault_value", nargs="?", default="")

    p_logs = sub.add_parser("logs", help="Show recent logs")
    p_logs.add_argument("lines", nargs="?", type=int, default=50)

    from cli.migrate import register_migrate_parser
    register_migrate_parser(sub)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    # Sync commands
    sync_map = {
        "chat": cmd_tui, "tui": cmd_tui,
        "start": cmd_start_sync, "stop": cmd_stop_sync, "restart": cmd_restart_sync,
        "skills": cmd_skills, "auth": cmd_auth, "doctor": cmd_doctor, "service": cmd_service,
        "immortal": cmd_immortal,
        "freedom": lambda a: __import__("cli.commands.freedom", fromlist=["cmd_freedom"]).cmd_freedom(a),
        "backup": cmd_backup, "comeback": cmd_comeback,
    }
    if args.command in sync_map:
        sync_map[args.command](args)
        return

    if args.command == "migrate":
        from cli.migrate import cmd_migrate
        cmd_migrate(args)
        return

    # Async commands
    async_map = {
        "init": None,  # special
        "pulse": cmd_status, "status": cmd_status,
        "agents": cmd_agents, "tasks": cmd_tasks,
        "confirm": cmd_confirm, "approve": cmd_confirm,
        "reset": cmd_reset, "memory": cmd_memory,
        "vault": cmd_vault, "logs": cmd_logs,
    }

    try:
        if args.command == "init":
            from cli.commands.init import cmd_init
            asyncio.run(cmd_init(args))
        elif args.command == "reforge":
            from cli.commands.reforge import cmd_reforge
            asyncio.run(cmd_reforge(args))
        elif args.command == "model":
            from cli.commands.model import cmd_model
            asyncio.run(cmd_model(args))
        elif args.command == "update":
            from cli.commands.update import cmd_update
            asyncio.run(cmd_update(args))
        elif args.command in async_map:
            asyncio.run(async_map[args.command](args))
    except (KeyboardInterrupt, EOFError):
        from cli.ui import ui
        ui.c.print()
        ui.warn("Aborted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
