"""Message handlers: text, voice/audio, document, photo."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import Message

if TYPE_CHECKING:
    from telegram.bot import CaliclawBot

logger = logging.getLogger(__name__)
router = Router()


def register(bot: CaliclawBot) -> None:
    bot.dp.include_router(router)

    @router.message(F.voice | F.audio)
    async def handle_voice(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        await bot._handle_audio(message)

    @router.message(F.document)
    async def handle_document(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        await bot._handle_document(message)

    @router.message(F.photo)
    async def handle_photo(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        caption = message.caption or "User sent a photo."
        photo = message.photo[-1]
        file = await bot.bot.get_file(photo.file_id)
        media_dir = bot.settings.workspace_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        path = media_dir / f"photo_{int(time.time())}_{photo.file_id[-8:]}.jpg"
        await bot.bot.download_file(file.file_path, str(path))
        await bot._process_user_message(
            message,
            f"User sent a photo saved at {path}. Caption: {caption}",
            media_path=str(path),
        )

    @router.message(F.text)
    async def handle_text(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        user_id = message.from_user.id if message.from_user else 0
        if not bot._check_rate_limit(user_id):
            await message.answer("⏳ Too many messages. Please wait.")
            return
        from telegram.bot import STOP_WORDS
        text_lower = (message.text or "").strip().lower()
        if text_lower in STOP_WORDS:
            await bot._handle_stop(message)
            return
        await bot._process_user_message(message, message.text or "")
