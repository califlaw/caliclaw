"""caliclaw reforge — re-configure an already-initialized instance.

Unlike `init`, which refuses to run if .env/SOUL.md already exist, `reforge`
targets a single component: Telegram credentials, user profile, soul, skills,
or a full wipe.
"""
from __future__ import annotations

import argparse
import secrets
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


async def cmd_reforge(args: argparse.Namespace) -> None:
    """Re-forge parts of the caliclaw setup."""
    from core.config import get_settings
    from cli.ui import ui

    settings = get_settings()
    settings.ensure_dirs()

    env_file = settings.project_root / ".env"
    soul_md = settings.agents_dir / "global" / "main" / "SOUL.md"
    if not env_file.exists() or not soul_md.exists():
        ui.banner()
        ui.c.print()
        ui.fail("caliclaw is not initialized yet.")
        ui.info("Run [bold red]caliclaw init[/bold red] first.")
        ui.c.print()
        return

    ui.banner()
    ui.c.print()
    from core import get_version
    ui.c.print(f"[bold red]REFORGE v{get_version()}[/bold red]")
    ui.c.print("[dim red]Melt it down. Rebuild it.[/dim red]")
    ui.c.print()
    ui.c.print("[yellow]>> What do you want to reforge?[/yellow]")
    ui.c.print()

    choice = ui.radio(
        [
            ("creds", "Credentials      — Telegram bot token"),
            ("profile", "Profile          — your name, role, language"),
            ("soul", "Soul             — assistant personality and rules"),
            ("model", "Model            — default Claude model (haiku/sonnet/opus)"),
            ("skills", "Skills           — toggle enabled skills"),
            ("all", "All              — wipe everything and run init"),
        ],
        title="Select component to reforge",
        default="creds",
    )

    if choice == "all":
        ui.c.print()
        ui.warn("This will WIPE .env, SOUL.md, USER.md, IDENTITY.md and re-run init.")
        confirm = input("  Type 'reforge' to confirm: ").strip()
        if confirm != "reforge":
            ui.info("Cancelled.")
            return
        await _reforge_all(settings, ui)
        return

    if choice == "creds":
        await _reforge_creds(settings, ui)
    elif choice == "profile":
        _reforge_profile(settings, ui)
    elif choice == "soul":
        _reforge_soul(settings, ui)
    elif choice == "model":
        _reforge_model(settings, ui)
    elif choice == "skills":
        _reforge_skills(settings, ui)

    ui.done("Reforged.")


# ── individual reforge helpers ──


async def _reforge_creds(settings, ui) -> None:
    """Re-write Telegram token + timezone in .env, regenerate pairing code."""
    import aiohttp

    env_file = settings.project_root / ".env"
    ui.c.print()
    ui.step(1, 1, "Credentials")
    ui.info("Get a bot token from @BotFather in Telegram")
    ui.c.print()
    token = input("  Bot Token: ").strip()

    if token:
        with ui.spin("Checking token..."):
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

    from core.config import detect_system_tz
    tz = detect_system_tz()

    # Preserve existing non-credential lines
    preserved = []
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(("TELEGRAM_BOT_TOKEN=", "TZ=")):
                continue
            preserved.append(line)

    lines = [f"TELEGRAM_BOT_TOKEN={token}", f"TZ={tz}"] + preserved
    env_file.write_text("\n".join(lines) + "\n")

    # Regenerate pairing code
    pairing_code = secrets.token_hex(3).upper()
    code_file = settings.data_dir / "pairing_code.txt"
    code_file.parent.mkdir(parents=True, exist_ok=True)
    code_file.write_text(pairing_code)

    ui.ok("Credentials updated")
    ui.c.print()
    ui.c.print(f"  [bold yellow]New pairing code: {pairing_code}[/bold yellow]")
    ui.c.print(f"  [dim]Restart caliclaw and send[/dim] [bold]/pair {pairing_code}[/bold] [dim]in Telegram[/dim]")


def _reforge_profile(settings, ui) -> None:
    """Re-write USER.md."""
    ui.c.print()
    ui.step(1, 1, "Profile")
    ui.c.print()

    user_md = settings.agents_dir / "global" / "main" / "USER.md"
    existing = {}
    if user_md.exists():
        for line in user_md.read_text().splitlines():
            if ":" in line and not line.startswith("#"):
                k, _, v = line.partition(":")
                existing[k.strip()] = v.strip()

    name = input(f"  Your name [{existing.get('name', '')}]: ").strip() or existing.get("name", "")
    role = input(f"  Your role [{existing.get('role', '')}]: ").strip() or existing.get("role", "")
    language = input(f"  Language [{existing.get('language', 'en')}]: ").strip() or existing.get("language", "en")

    user_md.parent.mkdir(parents=True, exist_ok=True)
    user_md.write_text(
        f"# User Profile\n\nname: {name}\nrole: {role}\nlanguage: {language}\n",
        encoding="utf-8",
    )
    ui.ok("Profile updated")


def _reforge_soul(settings, ui) -> None:
    """Re-write SOUL.md + IDENTITY.md."""
    ui.c.print()
    ui.step(1, 1, "Soul")
    ui.c.print()

    identity_md = settings.agents_dir / "global" / "main" / "IDENTITY.md"
    existing = {}
    if identity_md.exists():
        for line in identity_md.read_text().splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                existing[k.strip()] = v.strip()

    assistant_name = input(
        f"  Assistant name [{existing.get('name', 'caliclaw')}]: "
    ).strip() or existing.get("name", "caliclaw")

    style = ui.radio([
        ("concise and direct, no fluff", "Concise and direct"),
        ("friendly and casual, like a colleague", "Friendly and casual"),
        ("formal and detailed, thorough explanations", "Formal and detailed"),
    ], title="Communication style", default=existing.get("style", "concise and direct, no fluff"))

    language = existing.get("language", "en")

    ui.c.print("\n  What should your assistant be good at? (comma-separated)")
    ui.c.print("  [dim]e.g. hacking, coding, marketing, devops, automation, scraping, OSINT, shipping MVPs[/dim]")
    specialties = input("  Specialties: ").strip()

    ui.c.print("\n  Any rules or boundaries? (one per line, empty line to finish)")
    rules = []
    while True:
        rule = input("  Rule: ").strip()
        if not rule:
            break
        rules.append(rule)

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
        soul_parts.append("")
        soul_parts.append("## Rules")
        for rule in rules:
            soul_parts.append(f"- {rule}")

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
    ])

    soul_md = settings.agents_dir / "global" / "main" / "SOUL.md"
    soul_md.write_text("\n".join(soul_parts) + "\n", encoding="utf-8")
    identity_md.write_text(
        f"name: {assistant_name}\nrole: Personal AI Assistant\nstyle: {style}\nlanguage: {language}\n",
        encoding="utf-8",
    )
    ui.ok(f"Soul reforged — {assistant_name}")


def _reforge_model(settings, ui) -> None:
    """Change default Claude model."""
    from cli.commands.model import _write_model_to_env

    ui.c.print()
    ui.step(1, 1, "Model")

    current = settings.claude_default_model
    model = ui.radio(
        [
            ("sonnet", "sonnet   Balanced  (recommended)"),
            ("opus",   "opus     Maximum reasoning, slower"),
            ("haiku",  "haiku    Fast, cheap, light tasks"),
        ],
        title=f"Default model (current: {current})",
        default=current if current in ("sonnet", "opus", "haiku") else "sonnet",
    )

    if model == current:
        ui.info(f"Already [bold red]{model}[/bold red]. Nothing to do.")
        return

    _write_model_to_env(settings.project_root, model)
    ui.ok(f"Default model: [bold red]{model}[/bold red]")
    ui.info("Restart caliclaw to apply: [bold red]caliclaw restart[/bold red]")


def _reforge_skills(settings, ui) -> None:
    """Toggle enabled skills."""
    import re
    import shutil
    from security.engine_permissions import parse_skill_permissions, grant_tools, revoke_tools
    from core.config import bundled_skills_path

    ui.c.print()
    ui.step(1, 1, "Skills")

    skills_config = settings.project_root / "data" / "enabled_skills.txt"
    currently_enabled = set()
    if skills_config.exists():
        currently_enabled = {
            l.strip() for l in skills_config.read_text().splitlines() if l.strip()
        }

    bundled = bundled_skills_path()
    available = []
    if bundled.exists():
        for d in sorted(bundled.iterdir()):
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
            available.append((d.name, desc))

    enabled_set = set(ui.checkbox(
        [(name, f"{name:<18} {desc}", name in currently_enabled) for name, desc in available],
        title="Enabled skills",
    ))

    skills_config.parent.mkdir(parents=True, exist_ok=True)
    skills_config.write_text("\n".join(sorted(enabled_set)) + "\n")

    # Sync user's skills_dir with the enabled set
    settings.skills_dir.mkdir(parents=True, exist_ok=True)
    for sname in enabled_set:
        src = bundled / sname
        dst = settings.skills_dir / sname
        if src.exists() and dst.resolve() != src.resolve() and not dst.exists():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for sname in currently_enabled - enabled_set:
        dst = settings.skills_dir / sname
        if dst.exists() and dst.resolve() != (bundled / sname).resolve():
            shutil.rmtree(dst, ignore_errors=True)

    # Apply permission diffs
    newly_enabled = enabled_set - currently_enabled
    newly_disabled = currently_enabled - enabled_set

    for sname in newly_enabled:
        perms = parse_skill_permissions(bundled / sname / "SKILL.md")
        if perms:
            grant_tools(perms)
            ui.info(f"Granted: {', '.join(perms)} (via {sname})")

    for sname in newly_disabled:
        perms = parse_skill_permissions(bundled / sname / "SKILL.md")
        if perms:
            revoke_tools(perms)
            ui.info(f"Revoked: {', '.join(perms)} (via {sname})")

    ui.ok(f"Skills: {', '.join(sorted(enabled_set))}")


async def _reforge_all(settings, ui) -> None:
    """Full wipe + re-run init."""
    import shutil

    ui.c.print()
    ui.info("Wiping old config...")
    for path in [
        settings.project_root / ".env",
        settings.agents_dir / "global" / "main" / "SOUL.md",
        settings.agents_dir / "global" / "main" / "IDENTITY.md",
        settings.agents_dir / "global" / "main" / "USER.md",
        settings.project_root / "data" / "enabled_skills.txt",
        settings.data_dir / "pairing_code.txt",
    ]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    ui.ok("Wiped")

    # Re-run init
    from cli.commands.init import cmd_init
    import argparse as _argparse
    ns = _argparse.Namespace(force=True)
    await cmd_init(ns)
