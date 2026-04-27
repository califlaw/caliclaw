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

    # Optional handlers — present in some installs (e.g. local WIP), absent
    # in the published wheel. Skip silently rather than crashing the daemon
    # if the module isn't shipped.
    try:
        from telegram.handlers import voice  # /voice on|off|status
        voice.register(bot)
    except ImportError:
        pass

    messages.register(bot)
    callbacks.register(bot)
