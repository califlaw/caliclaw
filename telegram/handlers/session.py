"""Session handlers: /fresh, /squeeze, /reset."""
from __future__ import annotations

import logging
import uuid
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

    @router.message(Command("fresh"))
    async def cmd_fresh(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        session_id = f"session-{uuid.uuid4().hex[:12]}"
        await bot.db.create_session(session_id, "main")
        bot._current_model = bot.settings.claude_default_model
        await message.answer(f"New session: `{session_id[:16]}...`", parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("squeeze"))
    async def cmd_squeeze(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        session = await bot.db.get_active_session("main")
        if not session:
            await message.answer("No active session.")
            return
        from intelligence.compaction import ConversationCompactor
        compactor = ConversationCompactor(bot.db, bot.pool)
        await message.answer("🏋️ Squeezing context...")
        compacted = await compactor.check_and_compact(session["id"])
        if compacted:
            await message.answer("✅ Lightweight now.")
        else:
            count = await bot.db.count_messages(session["id"])
            await message.answer(f"Already lean ({count} messages).")

    @router.message(Command("reset"))
    async def cmd_reset(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Session", callback_data="reset:session"),
                InlineKeyboardButton(text="Agents", callback_data="reset:agents"),
            ],
            [
                InlineKeyboardButton(text="Tasks", callback_data="reset:tasks"),
                InlineKeyboardButton(text="ALL", callback_data="reset:all"),
            ],
        ])
        await message.answer("What to reset?", reply_markup=keyboard)
