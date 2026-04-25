"""Session handlers: /fresh, /squeeze, /context, /reset."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
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
        count = await bot.db.count_messages(session["id"])
        if count == 0:
            await message.answer("Nothing to squeeze yet.")
            return
        from intelligence.compaction import ConversationCompactor
        compactor = ConversationCompactor(bot.db)
        await message.answer(f"🏋️ Squeezing context ({count} messages)...")
        await compactor.check_and_compact(session["id"], force=True)
        await message.answer(
            "✅ Compacted. Fresh Claude session next turn — "
            "I'll still remember our recent conversation."
        )

    @router.message(Command("context"))
    async def cmd_context(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        session = await bot.db.get_active_session("main")
        if not session:
            await message.answer("No active session. Send a message to start one.")
            return

        sid = session["id"]
        count = await bot.db.count_messages(sid)
        msgs = await bot.db.get_messages(sid, limit=10000)
        chars = sum(len(m.get("content") or "") for m in msgs)

        created = session.get("created_at") or 0
        age_h = max(0.0, (time.time() - created) / 3600)
        if age_h < 1:
            age_str = f"{int(age_h * 60)}m"
        elif age_h < 48:
            age_str = f"{age_h:.1f}h"
        else:
            age_str = f"{age_h / 24:.1f}d"

        claude_alive = bool(session.get("claude_session_id"))
        has_handoff = bool(session.get("summary"))

        # Heuristic: ~4 chars per token. Claude Sonnet context window = 200K
        # tokens. Warn at 60K tokens (~30%) — that's where the slowdown
        # typically starts to bite.
        est_tokens = chars // 4
        if est_tokens > 60_000:
            health = "🔴 heavy — `/squeeze` recommended"
        elif est_tokens > 30_000:
            health = "🟡 building up"
        else:
            health = "🟢 lean"

        started = datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M") if created else "?"

        lines = [
            "*Context*",
            f"Session: `{sid[:16]}…`",
            f"Started: {started} ({age_str} ago)",
            f"Messages: {count}",
            f"Chars: {chars:,} (~{est_tokens:,} tokens)",
            f"Health: {health}",
            f"Claude side: {'live' if claude_alive else 'fresh next turn'}",
        ]
        if has_handoff:
            lines.append("Handoff: staged (will replay on next turn)")

        await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

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
