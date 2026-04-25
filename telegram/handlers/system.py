"""System handlers: /pair, /start, /help, /status, /usage, /model, /restart."""
from __future__ import annotations

import logging
import os
import signal as sig_mod
import subprocess
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

if TYPE_CHECKING:
    from telegram.bot import CaliclawBot

logger = logging.getLogger(__name__)
router = Router()


def register(bot: CaliclawBot) -> None:
    bot.dp.include_router(router)

    @router.message(Command("pair"))
    async def cmd_pair(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            return
        code = args[1].strip().upper()
        # Re-check from disk (TTL might have expired since startup)
        bot._pairing_code = bot._load_pairing_code()
        expected = bot._pairing_code
        if not expected:
            return
        if code == expected:
            bot._pair_user(user_id)
            bot._pairing_code = None
            code_file = bot.settings.data_dir / "pairing_code.txt"
            code_file.unlink(missing_ok=True)
            await message.answer("🔱 Paired. You're the owner now.\n\nSend a message or /help")
            logger.info("Paired with user %d via code", user_id)

    @router.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        if not bot._check_allowed(message):
            return

        # Count enabled skills for the BIOS display
        skills_config = bot.settings.project_root / "data" / "enabled_skills.txt"
        skill_count = 0
        if skills_config.exists():
            skill_count = len([
                l for l in skills_config.read_text().splitlines() if l.strip()
            ])

        from core import get_version
        bios = (
            "```\n"
            f"CALICLAW BIOS v{get_version()}\n"
            "Copyright (C) 2026 caliclaw\n"
            "\n"
            ">> Initializing boot sequence...\n"
            "\n"
            "[ OK ] bot.module         authorized\n"
            "[ OK ] agent.module       ready\n"
            f"[ OK ] skills.module     {skill_count} loaded\n"
            "[ OK ] memory.module      active\n"
            "[ OK ] vault.module       encrypted\n"
            "\n"
            "[100%] ████████████████████████\n"
            "\n"
            ">> caliclaw ready.\n"
            "```\n"
            "\n"
            "Just send a message — I'll handle it.\n"
            'Type "stop" to abort.\n\n'
            "/fresh — new session\n"
            "/status — system info\n"
            "/soul — who am I\n"
            "/help — all commands"
        )
        await message.answer(bios, parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        await message.answer(
            "🔱 **caliclaw commands**\n\n"
            "**Session:**\n"
            "/fresh — new session\n"
            "/squeeze — compress context\n"
            "/context — show context size & health\n"
            "/reset — reset state\n\n"
            "**Agents:**\n"
            "/agents — list agents\n"
            "/spawn — create agent\n"
            "/kill — kill agent\n"
            "/promote — promote agent\n\n"
            "**Tasks:**\n"
            "/tasks — scheduled tasks\n"
            "/loop — autonomous loop (`/loop stop` to cancel)\n"
            "/cron — schedule task\n"
            "/pause /resume — control tasks\n\n"
            "**System:**\n"
            "/status — system status\n"
            "/usage — token usage\n"
            "/model — switch model\n"
            "/llm — switch LLM provider (anthropic / openrouter / custom)\n"
            "/memory — show memory\n"
            "/soul — show soul\n"
            "/skills — list skills\n"
            "/confirm — approve action\n"
            "/unleash — grant agent access to directories\n"
            "/freedom — full machine control on/off\n"
            "/restart — restart bot",
            parse_mode=ParseMode.MARKDOWN,
        )

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        from monitoring.tracking import UsageTracker
        tracker = UsageTracker(bot.db)
        summary = await tracker.get_today_summary()
        agents = await bot.db.list_agents()
        active = bot.pool.active_count

        text = (
            f"🔱 **caliclaw Status**\n\n"
            f"Model: `{bot._current_model}`\n"
            f"Agents: {active}/{bot.settings.max_concurrent_agents} active, {len(agents)} total\n"
            f"Requests today: {summary['total_requests']}\n"
            f"Queue: {'processing...' if bot.queue.is_processing('main') else 'empty'}"
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("usage"))
    async def cmd_usage(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        from monitoring.tracking import UsageTracker
        tracker = UsageTracker(bot.db)
        summary = await tracker.get_today_summary()

        lines = [f"📊 **Requests today: {summary['total_requests']}**\n"]
        for model, data in summary.get("by_model", {}).items():
            dur = data['duration_ms'] / 1000 if data['duration_ms'] else 0
            lines.append(f"  `{model}`: {data['count']} reqs, {dur:.0f}s")

        lines.append(
            "\nClaude returns its own rate-limit / budget errors when real "
            "capacity is exhausted — we surface those with a hint."
        )
        await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("model"))
    async def cmd_model(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) >= 2 and args[1].strip() in ("haiku", "sonnet", "opus"):
            bot._current_model = args[1].strip()
            await message.answer(f"Model: `{bot._current_model}`", parse_mode=ParseMode.MARKDOWN)
            return

        current = bot._current_model
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"{'> ' if current == m else ''}{m}",
                callback_data=f"model:{m}",
            )
            for m in ("haiku", "sonnet", "opus")
        ]])
        await message.answer(f"Current model: `{current}`", parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    @router.message(Command("freedom"))
    async def cmd_freedom(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args_text = (message.text or "").split(maxsplit=1)
        arg = args_text[1].strip().lower() if len(args_text) >= 2 else ""

        if arg in ("on", "off"):
            from cli.commands.freedom import _write_freedom_to_env
            enabled = arg == "on"
            _write_freedom_to_env(bot.settings.project_root, enabled)
            bot.settings.freedom_mode = enabled

            if enabled:
                await message.answer(
                    "🔓 **FREEDOM: ON**\n\n"
                    "Full machine control. No approval needed.\n"
                    "sudo works without password.\n\n"
                    "Use `/freedom off` to restore guardrails.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await message.answer(
                    "🔒 **FREEDOM: OFF**\n\n"
                    "Approval required for dangerous actions.\n\n"
                    "Use `/freedom on` to unlock.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            return

        # Status
        if bot.settings.freedom_mode:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔒 Turn OFF", callback_data="freedom:off"),
            ]])
            await message.answer(
                "🔓 **FREEDOM: ON**\n☠ Full machine control — no approval, no limits",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔓 Turn ON", callback_data="freedom:on"),
            ]])
            await message.answer(
                "🔒 **FREEDOM: OFF**\nAgent asks approval before dangerous actions",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )

    @router.message(Command("llm"))
    async def cmd_llm(message: Message) -> None:
        """Switch the LLM provider endpoint (Anthropic direct / OpenRouter / custom).

        Forms:
            /llm                           — show current provider
            /llm anthropic                 — reset to Claude direct
            /llm openrouter <key>          — route through OpenRouter
            /llm custom <url> [token]      — point at any Anthropic-compat proxy
        """
        if not bot._check_allowed(message):
            return

        from cli.commands.llm import _upsert_env, _get_env

        parts = (message.text or "").split(maxsplit=3)
        action = parts[1].strip().lower() if len(parts) >= 2 else ""
        arg1 = parts[2].strip() if len(parts) >= 3 else ""
        arg2 = parts[3].strip() if len(parts) >= 4 else ""

        root = bot.settings.project_root

        def _mask(tok: str) -> str:
            if not tok:
                return "—"
            return tok[:6] + "…" + tok[-4:] if len(tok) > 12 else "set"

        # Status
        if not action or action == "status":
            base = _get_env(root, "ANTHROPIC_BASE_URL")
            tok = _get_env(root, "ANTHROPIC_AUTH_TOKEN")
            if not base:
                provider = "anthropic (default)"
                detail = "Using Claude Code login or ANTHROPIC_API_KEY"
            else:
                provider = base
                detail = f"Token: `{_mask(tok)}`"
            await message.answer(
                f"*LLM provider*\n"
                f"Endpoint: `{provider}`\n"
                f"{detail}\n\n"
                f"Switch:\n"
                f"`/llm anthropic`\n"
                f"`/llm openrouter <sk-or-...>`\n"
                f"`/llm custom <url> [token]`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if action == "anthropic":
            _upsert_env(root, "ANTHROPIC_BASE_URL", None)
            _upsert_env(root, "ANTHROPIC_AUTH_TOKEN", None)
            bot.settings.anthropic_base_url = None
            bot.settings.anthropic_auth_token = None
            await message.answer("✅ Reset to Anthropic direct.")
            return

        if action == "openrouter":
            if not arg1:
                await message.answer(
                    "Need an OpenRouter key.\n"
                    "`/llm openrouter sk-or-v1-...`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            url = "https://openrouter.ai/api/v1"
            _upsert_env(root, "ANTHROPIC_BASE_URL", url)
            _upsert_env(root, "ANTHROPIC_AUTH_TOKEN", arg1)
            bot.settings.anthropic_base_url = url
            bot.settings.anthropic_auth_token = arg1
            await message.answer(
                f"✅ Routing through OpenRouter.\n"
                f"Endpoint: `{url}`\n"
                f"Token: `{_mask(arg1)}`\n\n"
                f"⚠️ The key is in your chat history — delete the message if it bothers you.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if action == "custom":
            if not arg1:
                await message.answer(
                    "Need a URL.\n"
                    "`/llm custom http://localhost:3456 [token]`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            _upsert_env(root, "ANTHROPIC_BASE_URL", arg1)
            _upsert_env(root, "ANTHROPIC_AUTH_TOKEN", arg2 or None)
            bot.settings.anthropic_base_url = arg1
            bot.settings.anthropic_auth_token = arg2 or None
            tok_line = f"Token: `{_mask(arg2)}`" if arg2 else "No token (proxy must accept unauthenticated)"
            await message.answer(
                f"✅ Routing through custom endpoint.\n"
                f"Endpoint: `{arg1}`\n"
                f"{tok_line}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await message.answer(
            f"Unknown provider: `{action}`\n"
            f"Try: `/llm` for status.",
            parse_mode=ParseMode.MARKDOWN,
        )

    @router.message(Command("restart"))
    async def cmd_restart(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        await message.answer("🔄 Restarting...")
        await bot.pool.kill_all()
        under_systemd = os.environ.get("INVOCATION_ID") is not None

        if under_systemd:
            logger.info("Restart requested (systemd will auto-restart)")
        else:
            import shutil
            import platform
            pid_file = bot.settings.data_dir / "caliclaw.pid"
            pid_file.unlink(missing_ok=True)
            daemon_bin = shutil.which("caliclaw-daemon") or str(
                Path(sys.executable).parent / "caliclaw-daemon"
            )
            work_dir = str(bot.settings.project_root)
            use_new_session = platform.system() != "Darwin"
            subprocess.Popen(
                ["bash", "-c", f"sleep 2 && {daemon_bin}"],
                cwd=work_dir,
                start_new_session=use_new_session,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            logger.info("Restart requested (new daemon scheduled)")

        os.kill(os.getpid(), sig_mod.SIGTERM)
