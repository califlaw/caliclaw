"""Access handlers: /unleash."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

if TYPE_CHECKING:
    from telegram.bot import CaliclawBot

logger = logging.getLogger(__name__)
router = Router()


def register(bot: CaliclawBot) -> None:
    bot.dp.include_router(router)

    @router.message(Command("unleash"))
    async def cmd_unleash(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split(maxsplit=1)

        if len(args) < 2:
            is_sandbox = bot._working_dir == bot.settings.workspace_dir
            status = "🔒 In the cage" if is_sandbox else "🔓 Unleashed"
            await message.answer(
                f"{status}\n"
                f"Working dir: `{bot._working_dir}`\n\n"
                f"/unleash `<path>` — unleash on directory\n"
                f"/unleash revoke — back to sandbox",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        target = args[1].strip()

        if target in ("revoke", "cage"):
            bot._working_dir = bot.settings.workspace_dir
            session = await bot.db.get_active_session("main")
            if session and session.get("claude_session_id"):
                await bot.db.update_session(session["id"], claude_session_id=None)
            bot._inject_context = True
            await message.answer("🔒 Back in the cage.")
            logger.info("Agent caged — back to workspace")
            return

        path = Path(target).expanduser().resolve()
        if not path.is_dir():
            await message.answer(f"Not a directory: `{path}`", parse_mode=ParseMode.MARKDOWN)
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔓 Unleash", callback_data=f"access:grant:{path}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="access:cancel"),
        ]])
        await message.answer(
            f"Unleash agent on `{path}`?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
