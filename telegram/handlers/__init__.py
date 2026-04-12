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
        agents,
        tasks,
        data,
        access,
        messages,
        callbacks,
    )

    system.register(bot)
    session.register(bot)
    agents.register(bot)
    tasks.register(bot)
    data.register(bot)
    access.register(bot)
    messages.register(bot)
    callbacks.register(bot)
