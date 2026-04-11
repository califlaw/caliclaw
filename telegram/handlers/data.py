"""Data handlers: /memory, /soul, /skills, /confirm."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

if TYPE_CHECKING:
    from telegram.bot import CaliclawBot

logger = logging.getLogger(__name__)
router = Router()


def register(bot: CaliclawBot) -> None:
    bot.dp.include_router(router)

    @router.message(Command("memory"))
    async def cmd_memory(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        from intelligence.memory import MemoryManager
        mm = MemoryManager()
        entries = mm.load_all()
        if not entries:
            await message.answer("Memory is empty.")
            return
        lines = ["📝 **Memory:**\n"]
        for e in entries:
            lines.append(f"• **{e.name}** ({e.type})\n  _{e.description}_")
        await message.answer("\n".join(lines)[:4000], parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("soul"))
    async def cmd_soul(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        soul_dir = bot.settings.agents_dir / "global" / "main"
        parts = []
        for name in ["SOUL.md", "IDENTITY.md", "USER.md"]:
            path = soul_dir / name
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"**{name}:**\n```\n{content[:800]}\n```")
        if parts:
            await message.answer("\n\n".join(parts)[:4000], parse_mode=ParseMode.MARKDOWN)
        else:
            await message.answer("No soul files found.")

    @router.message(Command("skills"))
    async def cmd_skills(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        text, keyboard = bot._build_skills_message()
        await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    @router.message(Command("confirm"))
    async def cmd_confirm(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Usage: /confirm `<code>`", parse_mode=ParseMode.MARKDOWN)
            return
        code = args[1].strip()
        approval = await bot.db.get_pending_approval(code)
        if not approval:
            await message.answer("Code not found or already processed.")
            return
        await bot.db.resolve_approval(approval["id"], "approved", "telegram")
        await message.answer(f"✅ Approved: {approval['action']}")
