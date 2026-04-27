"""Telegram handlers package — organized by domain.

Each module exposes a `register(bot)` function that registers its handlers.
The main `register_handlers(bot)` function below orchestrates all of them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.bot import CaliclawBot


def register_handlers(bot: CaliclawBot) -> None:
    """Register all command, message, and callback handlers."""
    from telegram.handlers import (
        system,
        session,
        projects,
        agents,
        tasks,
        data,
        access,
        voice,
        messages,
        callbacks,
    )

    system.register(bot)
    session.register(bot)
    projects.register(bot)     # /project — must come before messages
    agents.register(bot)
    tasks.register(bot)
    data.register(bot)
    access.register(bot)
    voice.register(bot)        # /voice on|off|status — must come before messages
    messages.register(bot)
    callbacks.register(bot)
