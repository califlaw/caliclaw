"""caliclaw init — first-time setup wizard."""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


async def cmd_init(args: argparse.Namespace) -> None:
    """First-time setup."""
    from core.config import get_settings
    from cli.ui import ui

    settings = get_settings()
    settings.ensure_dirs()

    # --force: wipe ~/.caliclaw completely for clean slate
    if getattr(args, "force", False) and settings.project_root.exists():
        import shutil
        # Don't wipe if project_root is the source checkout (safety check)
        if not (settings.project_root / "__main__.py").exists():
            shutil.rmtree(settings.project_root, ignore_errors=True)
            settings.ensure_dirs()
            ui.info(f"Wiped {settings.project_root}")

    # Already initialized? Refuse and redirect to reforge.
    env_file = settings.project_root / ".env"
    soul_md = settings.agents_dir / "global" / "main" / "SOUL.md"
    if env_file.exists() and soul_md.exists() and not getattr(args, "force", False):
        ui.banner()
        ui.c.print()
        ui.warn("caliclaw is already initialized on this machine.")
        ui.c.print()
        ui.info("To change credentials, profile, or skills — use:")
        ui.c.print("    [bold red]caliclaw reforge[/bold red]  [dim](re-forge the soul)[/dim]")
        ui.c.print()
        ui.info("To wipe everything and start over:")
        ui.c.print("    [bold red]caliclaw init --force[/bold red]")
        ui.c.print()
        return

    ui.banner()
    ui.c.print()
    from core import get_version
    ui.c.print(f"[bold yellow]CALICLAW SETUP v{get_version()}[/bold yellow]")
    ui.c.print("[dim yellow]Copyright (C) 2026 caliclaw project[/dim yellow]")
    ui.c.print()
    ui.c.print("[yellow]>> First-time configuration[/yellow]")
    ui.c.print("[dim]   Answer a few questions to forge your agent.[/dim]")
    ui.c.print()

    # Grant base engine permissions
    from security.engine_permissions import ensure_base_permissions
    ensure_base_permissions()

    # ── Step 0: Migration ──
    migrated = await _ask_migration(settings, ui)

    # ── Step 1: Telegram ──
    env_file = settings.project_root / ".env"
    if not env_file.exists():
        ui.step(1, 5, "Telegram")
        ui.info("Get a bot token from @BotFather in Telegram")
        ui.c.print()
        token = input("  Bot Token: ").strip()

        if token:
            with ui.spin("Checking token..."):
                import aiohttp
                import ssl
                valid = False
                bot_name = ""
                for use_ssl in [None, False]:
                    try:
                        connector = aiohttp.TCPConnector(ssl=use_ssl) if use_ssl is False else None
                        async with aiohttp.ClientSession(connector=connector) as session:
                            async with session.get(
                                f"https://api.telegram.org/bot{token}/getMe",
                                timeout=aiohttp.ClientTimeout(total=10),
                            ) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    if data.get("ok"):
                                        valid = True
                                        bot_name = data["result"].get("username", "")
                        break
                    except (aiohttp.ClientError, TimeoutError, ssl.SSLError):
                        continue

            if valid:
                ui.ok(f"Token valid — @{bot_name}")
            else:
                ui.warn("Could not verify token (network/SSL) — saving anyway")
        else:
            ui.warn("No token — add TELEGRAM_BOT_TOKEN to .env later")

        from core.config import detect_system_tz
        import shutil as _shutil
        tz = detect_system_tz()

        lines = [f"TELEGRAM_BOT_TOKEN={token}"]
        lines.append(f"TZ={tz}")

        claude_path = _shutil.which("claude")
        if claude_path:
            lines.append(f"CLAUDE_BINARY={claude_path}")

        env_file.write_text("\n".join(lines) + "\n")

        pairing_code = secrets.token_hex(3).upper()
        code_file = settings.data_dir / "pairing_code.txt"
        code_file.parent.mkdir(parents=True, exist_ok=True)
        code_file.write_text(pairing_code)

        ui.ok("Config saved")
        ui.c.print()
        ui.c.print(f"  [bold yellow]Pairing code: {pairing_code}[/bold yellow]")
        ui.c.print(f"  [dim]After starting the bot, send this to your bot in Telegram:[/dim]")
        ui.c.print(f"  [bold]/pair {pairing_code}[/bold]")
    else:
        ui.ok(".env exists, skipping Telegram setup")

    # ── Step 2: Profile ──
    user_md = settings.agents_dir / "global" / "main" / "USER.md"
    language = "en"
    name = ""
    role = ""
    if migrated and user_md.exists() and len(user_md.read_text().strip()) > 30:
        ui.step(2, 5, "About you")
        ui.ok("Imported from previous project")
    else:
        ui.step(2, 5, "About you")
        ui.c.print()
        name = input("  Your name: ").strip()
        role = input("  Your role (developer, designer, student, etc): ").strip()
        language = input("  Language [en]: ").strip() or "en"

        user_md.parent.mkdir(parents=True, exist_ok=True)
        user_md.write_text(
            f"# User Profile\n\nname: {name}\nrole: {role}\nlanguage: {language}\n",
            encoding="utf-8",
        )
        ui.ok("Profile saved")

    # ── Step 3: Assistant ──
    soul_md = settings.agents_dir / "global" / "main" / "SOUL.md"
    assistant_name = "caliclaw"

    if migrated and soul_md.exists() and len(soul_md.read_text().strip()) > 50:
        ui.step(3, 5, "Your assistant")
        ui.ok("Soul imported from previous project")
        model = ui.radio([
            ("sonnet", "sonnet   Balanced  (recommended)"),
            ("opus",   "opus     Maximum reasoning, slower"),
            ("haiku",  "haiku    Fast, cheap, light tasks"),
        ], title="Default model", default="sonnet")
        from cli.commands.model import _write_model_to_env
        _write_model_to_env(settings.project_root, model)
    else:
        ui.step(3, 5, "Your assistant")
        ui.c.print()
        assistant_name = input("  Assistant name [caliclaw]: ").strip() or "caliclaw"

        style = ui.radio([
            ("concise and direct, no fluff", "Concise and direct"),
            ("friendly and casual, like a colleague", "Friendly and casual"),
            ("formal and detailed, thorough explanations", "Formal and detailed"),
        ], title="Communication style", default="concise and direct, no fluff")

        model = ui.radio([
            ("sonnet", "sonnet   Balanced  (recommended)"),
            ("opus",   "opus     Maximum reasoning, slower"),
            ("haiku",  "haiku    Fast, cheap, light tasks"),
        ], title="Default model", default="sonnet")

        from cli.commands.model import _write_model_to_env
        _write_model_to_env(settings.project_root, model)

        ui.c.print("\n  What should your assistant be good at? (comma-separated)")
        ui.c.print("  [dim]e.g. hacking, coding, marketing, devops, automation, scraping, OSINT, shipping MVPs[/dim]")
        specialties = input("  Specialties: ").strip()

        ui.c.print("\n  Rules or boundaries? (comma-separated, Enter to skip)")
        ui.c.print("  [dim]e.g. always respond in English, never touch production without asking[/dim]")
        rules_input = input("  Rules: ").strip()
        rules = [r.strip() for r in rules_input.split(",") if r.strip()] if rules_input else []

        # Generate SOUL.md
        soul_parts = [
            f"You are {assistant_name}, a personal AI assistant.",
            "You communicate through Telegram. You have full access to the system — bash, files, git, docker, etc.",
            "", "## Communication",
            f"- Style: {style}", f"- Language: {language}",
        ]
        if specialties:
            soul_parts.append(f"- Specialties: {specialties}")
        soul_parts.extend([
            "", "## About yourself",
            "- NEVER discuss your internal architecture or how you work under the hood",
            "- NEVER mention Claude, Claude Code, APIs, SDKs, or technical details about your engine",
            '- NEVER reference "approval prompts", "permission dialogs", "Allow button", or any external interface',
            "- You run NON-INTERACTIVELY through Telegram. There is no other UI. If you need user confirmation — ask in this chat, not via external tools",
            "- Focus on what you CAN DO, not how you're built",
        ])
        if rules:
            soul_parts.extend(["", "## Rules"] + [f"- {r}" for r in rules])
        soul_parts.extend([
            "", "## Core Principles",
            "- Verify before act: NEVER assume file contents or system state. Always check first.",
            "- Rate your confidence before actions (HIGH/MEDIUM/LOW). Ask user if LOW.",
            "",
            "## Approval for dangerous actions",
            "Before executing destructive or irreversible actions, output the marker on its own line:",
            "[APPROVAL_NEEDED] <short description of what you want to do>",
            "Then STOP — do NOT execute. The system will show the user Approve/Deny buttons.",
            "If approved, you will receive a follow-up message to proceed.",
            "Actions that require approval:",
            "- Deleting files, directories, databases, or user data",
            "- Deploying to production, restarting production services",
            "- Running commands on remote servers (ssh, scp to production)",
            "- Modifying system configs (sshd, nginx, systemd units)",
            "- Any action you rate as LOW confidence",
            "", "## Anti-Hallucination",
            "- NEVER assume a file exists — read it first",
            "- NEVER assume a command exists — check with which/type",
            "- NEVER assume a service is running — check with systemctl/ps",
            "- Every claim about the system must cite the check you ran",
            "", "## Memory",
            "- Read memory before starting work to understand context",
            "- Write important learnings to memory after completing tasks",
            "- Update USER.md when you learn something about the user",
            "",
        ])
        from core.souls import ORCHESTRATION_BLOCK
        soul_parts.append(ORCHESTRATION_BLOCK)
        soul_md.parent.mkdir(parents=True, exist_ok=True)
        soul_md.write_text("\n".join(soul_parts) + "\n", encoding="utf-8")

        identity_md = settings.agents_dir / "global" / "main" / "IDENTITY.md"
        identity_md.write_text(
            f"name: {assistant_name}\nrole: Personal AI Assistant\nstyle: {style}\nlanguage: {language}\n",
            encoding="utf-8",
        )
        ui.ok(f"Assistant '{assistant_name}' configured")

    # ── Step 4: Skills ──
    ui.step(4, 5, "Skills")
    available_skills = _get_available_skills()

    enabled_skills = set(ui.checkbox(
        [(n, f"{n:<18} {d}", True) for n, d in available_skills],
        title="Select skills",
    ))

    skills_config = settings.project_root / "data" / "enabled_skills.txt"
    skills_config.parent.mkdir(parents=True, exist_ok=True)
    skills_config.write_text("\n".join(sorted(enabled_skills)) + "\n")
    ui.ok(f"Skills: {', '.join(sorted(enabled_skills))}")

    import shutil
    from core.config import bundled_skills_path
    _bundled = bundled_skills_path()
    settings.skills_dir.mkdir(parents=True, exist_ok=True)
    for sname in enabled_skills:
        src = _bundled / sname
        if not src.exists():
            continue
        dst = settings.skills_dir / sname
        if dst.resolve() != src.resolve() and not dst.exists():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    from security.engine_permissions import parse_skill_permissions, grant_tools
    for sname in enabled_skills:
        perms = parse_skill_permissions(_bundled / sname / "SKILL.md")
        if perms:
            grant_tools(perms)
            ui.info(f"Granted: {', '.join(perms)} (via {sname})")

    # ── Step 5: Options ──
    ui.step(5, 5, "Options")

    selected_options = ui.checkbox([
        ("autostart", "Keep caliclaw always running (auto-start on boot)", True),
        ("dashboard", "Enable web dashboard", False),
        ("backup", "Auto-backup to Telegram (weekly)", True),
    ], title="System options")

    with ui.spin("Setting up database..."):
        from core.db import Database
        db = Database()
        await db.connect()
        await db.save_agent(name="main", scope="global")
        from automation.scheduler import HeartbeatManager
        hm = HeartbeatManager(db)
        await hm.setup_default_heartbeats()
        await db.close()
    ui.ok("Database ready")

    if "dashboard" in selected_options:
        env = settings.project_root / ".env"
        if env.exists():
            content = env.read_text()
            if "DASHBOARD_ENABLED" not in content:
                env.write_text(content + "\nDASHBOARD_ENABLED=true\n")
        ui.ok("Dashboard enabled (port 8080)")

    if "backup" in selected_options:
        env = settings.project_root / ".env"
        if env.exists():
            content = env.read_text()
            if "BACKUP_ENABLED" not in content:
                env.write_text(content + "\nBACKUP_ENABLED=true\nBACKUP_INTERVAL_DAYS=7\n")
        ui.ok("Auto-backup enabled (weekly)")

    ui.c.print()
    _install_system_deps()

    if "autostart" in selected_options:
        _install_service(settings)

    provisioned = [
        ("config", ".env written"),
        ("profile", f"{name or 'imported'} / {role or 'imported'}"),
        ("soul", f"{assistant_name} forged"),
        ("skills", f"{len(enabled_skills)} enabled"),
        ("database", "sqlite initialized"),
    ]
    if "autostart" in selected_options:
        provisioned.append(("systemd", "auto-start enabled"))
    if "dashboard" in selected_options:
        provisioned.append(("dashboard", ":8080 ready"))
    if "backup" in selected_options:
        provisioned.append(("backup", "weekly to telegram"))

    # Save project root so caliclaw works from any directory
    from core.config import save_project_root
    save_project_root(settings.project_root)

    ui.boot(provisioned, version="setup complete")
    ui.next_steps([
        "caliclaw start       Start the bot",
        "caliclaw chat        Terminal chat",
        "caliclaw pulse       System pulse",
    ])


# ── Helper functions (module-level, NOT async) ──


def _install_service(settings) -> None:
    import getpass
    import os
    import shutil
    import subprocess
    from cli.ui import ui

    user = getpass.getuser()
    home = Path.home()
    venv_python = f"{_ROOT}/.venv/bin/python"
    if not Path(venv_python).exists():
        venv_python = sys.executable

    sys_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    extra_dirs = [f"{home}/.local/bin", f"{home}/.cargo/bin", "/usr/local/bin"]
    full_path = ":".join(dict.fromkeys(extra_dirs + sys_path.split(":")))

    service = (
        "[Unit]\n"
        "Description=caliclaw Personal AI Assistant\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={user}\n"
        f"WorkingDirectory={settings.project_root}\n"
        f"ExecStart={shutil.which('caliclaw-daemon') or venv_python + ' ' + str(_ROOT / '__main__.py')}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        f'Environment="PATH={full_path}"\n'
        "TimeoutStopSec=30\n"
        "KillSignal=SIGTERM\n"
        f"StandardOutput=append:{settings.project_root}/logs/caliclaw.log\n"
        f"StandardError=append:{settings.project_root}/logs/caliclaw.log\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )

    tmp = settings.data_dir / "caliclaw.generated.service"
    tmp.write_text(service)

    try:
        subprocess.run(["sudo", "cp", str(tmp), "/etc/systemd/system/caliclaw.service"], check=True)
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", "caliclaw"], check=True)
        ui.ok("Auto-start enabled")
    except (subprocess.CalledProcessError, FileNotFoundError):
        ui.warn("Could not install service (need sudo)")
        ui.info(f"Manual: sudo cp {tmp} /etc/systemd/system/caliclaw.service")


async def _ask_migration(settings, ui) -> bool:
    from pathlib import Path

    candidates = []
    home = Path.home()
    for name, path in [
        ("openclaw", home / ".openclaw"),
        ("zeroclaw", home / ".zeroclaw"),
        ("nanoclaw", home / ".nanoclaw"),
    ]:
        if path.is_dir():
            candidates.append((name, path))

    if not candidates:
        return False

    options = [("fresh", "No, fresh start")]
    for name, path in candidates:
        options.append((name, f"Yes, from {name} ({path})"))
    options.append(("custom", "Yes, custom path"))

    choice = ui.radio(options, title="Migrating from another project?", default="fresh")

    if choice == "fresh":
        return False

    if choice == "custom":
        path_str = input("  Path to project: ").strip()
        if not path_str:
            return False
        source_path = Path(path_str).resolve()
    else:
        source_path = dict(candidates)[choice]

    if not source_path.is_dir():
        ui.fail(f"Directory not found: {source_path}")
        return False

    from core.migrate import detect_source, get_migrator, ConflictStrategy, MigrationComponent
    source_name = choice if choice != "custom" else detect_source(source_path)
    if not source_name:
        ui.fail("Could not detect project type.")
        return False

    migrator_cls = get_migrator(source_name)
    if not migrator_cls:
        ui.fail(f"No migrator for: {source_name}")
        return False

    migrator = migrator_cls(source_path, settings=settings)
    errors = migrator.validate_source()
    if errors:
        for e in errors:
            ui.fail(e)
        return False

    available = migrator.discover_components()
    available_list = [c for c, v in available.items() if v]
    if not available_list:
        ui.warn("Nothing to migrate — project is empty.")
        return False

    ui.info(f"Found {source_name} project with {len(available_list)} components")

    with ui.spin(f"Migrating from {source_name}..."):
        plan = migrator.plan(available_list, ConflictStrategy.OVERWRITE)
        result = migrator.execute(plan, ConflictStrategy.OVERWRITE)

    ui.ok(f"Migrated: {result.success} items from {source_name}")
    if result.errors:
        for e in result.errors:
            ui.warn(e)

    return result.success > 0


def _get_available_skills() -> list[tuple[str, str]]:
    import re
    from core.config import bundled_skills_path
    skills_dir = bundled_skills_path()
    results = []
    if not skills_dir.exists():
        return results
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        skill_file = d / "SKILL.md"
        if not skill_file.exists():
            continue
        content = skill_file.read_text(encoding="utf-8")
        desc = d.name
        match = re.search(r"description:\s*(.+)", content)
        if match:
            desc = match.group(1).strip()
        results.append((d.name, desc))
    return results


_SKILL_DEPS = {"browser": ["playwright"]}
_SKILL_POST_INSTALL = {"browser": ["playwright", "install", "chromium"]}


def install_skill_deps(skill_name: str) -> None:
    import subprocess
    deps = _SKILL_DEPS.get(skill_name)
    if not deps:
        return
    for dep in deps:
        try:
            __import__(dep)
        except ImportError:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", dep],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
            )
    post = _SKILL_POST_INSTALL.get(skill_name)
    if post:
        subprocess.run(
            [sys.executable, "-m"] + post,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300,
        )


def _install_system_deps() -> None:
    import shutil
    import subprocess
    from cli.ui import ui

    pkg_mgr = None
    for cmd, install_cmd in [
        ("apt-get", ["sudo", "apt-get", "install", "-y"]),
        ("dnf", ["sudo", "dnf", "install", "-y"]),
        ("pacman", ["sudo", "pacman", "-S", "--noconfirm"]),
        ("brew", ["brew", "install"]),
    ]:
        if shutil.which(cmd):
            pkg_mgr = (cmd, install_cmd)
            break

    if shutil.which("ffmpeg"):
        ui.ok("ffmpeg")
    elif pkg_mgr:
        with ui.spin("Installing ffmpeg..."):
            try:
                subprocess.run(pkg_mgr[1] + ["ffmpeg"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
                ui.ok("ffmpeg installed")
            except (subprocess.TimeoutExpired, OSError):
                ui.fail("ffmpeg — install manually: sudo apt install ffmpeg")
    else:
        ui.warn("ffmpeg not found — install manually")

    if shutil.which("whisper-cpp") or shutil.which("whisper"):
        ui.ok("whisper-cpp")
        return

    whisper_dir = _ROOT / "vendor" / "whisper.cpp"
    whisper_bin = whisper_dir / "build" / "bin" / "whisper-cli"

    if whisper_bin.exists():
        ui.ok("whisper-cpp (already built)")
    else:
        # Install build tools if missing
        if not shutil.which("cmake") or not shutil.which("git"):
            if pkg_mgr:
                tools = []
                if not shutil.which("cmake"):
                    tools.append("cmake")
                if not shutil.which("git"):
                    tools.append("git")
                if pkg_mgr[0] == "apt-get":
                    tools.extend(["build-essential"])
                with ui.spin(f"Installing {', '.join(tools)}..."):
                    try:
                        subprocess.run(
                            pkg_mgr[1] + tools,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
                        )
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                        ui.warn(f"Could not install {', '.join(tools)}")
            if not shutil.which("cmake"):
                ui.warn("cmake not found — skipping whisper-cpp build")
                return

        if pkg_mgr and pkg_mgr[0] == "apt-get":
            with ui.spin("Installing build tools..."):
                subprocess.run(
                    ["sudo", "apt-get", "install", "-y", "build-essential", "cmake", "git"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
                )

        vendor_dir = _ROOT / "vendor"
        vendor_dir.mkdir(exist_ok=True)

        if not whisper_dir.exists():
            if not shutil.which("git"):
                ui.warn("git not found — skipping whisper-cpp")
                return
            with ui.spin("Cloning whisper.cpp..."):
                try:
                    result = subprocess.run(
                        ["git", "clone", "--depth", "1", "https://github.com/ggerganov/whisper.cpp.git", str(whisper_dir)],
                        capture_output=True, timeout=120,
                    )
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    ui.fail("whisper-cpp: git clone failed")
                    return
            if result.returncode != 0:
                ui.fail("whisper-cpp: git clone failed")
                return

        build_dir = whisper_dir / "build"
        build_dir.mkdir(exist_ok=True)

        if not shutil.which("cmake"):
            ui.warn("cmake not found — skipping whisper-cpp build")
            ui.info("Install cmake: brew install cmake (macOS) or sudo apt install cmake (Linux)")
        else:
            with ui.spin("Building whisper-cpp (1-2 min)..."):
                result = subprocess.run(["cmake", ".."], cwd=str(build_dir), capture_output=True, timeout=60)
                if result.returncode != 0:
                    ui.fail("cmake failed")
                    return
                result = subprocess.run(
                    ["cmake", "--build", ".", "--config", "Release", "-j"],
                    cwd=str(build_dir), capture_output=True, timeout=300,
                )
            if result.returncode != 0:
                ui.fail("Build failed — check build-essential")
                return

        ui.ok("whisper-cpp built")

    actual_bin = None
    for candidate in [whisper_dir / "build" / "bin" / "whisper-cli", whisper_dir / "build" / "bin" / "main"]:
        if candidate.exists():
            actual_bin = candidate
            break

    if actual_bin:
        env_file = _ROOT / ".env"
        if env_file.exists():
            content = env_file.read_text()
            if "WHISPER_CPP_PATH" not in content:
                env_file.write_text(content + f"\nWHISPER_CPP_PATH={actual_bin}\n")

    models_dir = _ROOT / "models"
    models_dir.mkdir(exist_ok=True)
    model_file = models_dir / "ggml-base.bin"

    if model_file.exists():
        ui.ok("whisper model")
    else:
        model_url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
        with ui.spin("Downloading whisper model (142MB)..."):
            try:
                result = subprocess.run(
                    ["curl", "-L", "-o", str(model_file), model_url],
                    timeout=300, capture_output=True,
                )
                if result.returncode == 0 and model_file.stat().st_size > 1000000:
                    ui.ok("whisper model downloaded")
                else:
                    model_file.unlink(missing_ok=True)
                    ui.fail("Download failed")
                    ui.info(f"curl -L -o {model_file} {model_url}")
            except (subprocess.TimeoutExpired, OSError):
                ui.fail("Download failed (timeout)")
