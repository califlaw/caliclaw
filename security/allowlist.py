from __future__ import annotations

import logging
from typing import List, Set

from core.config import get_settings

logger = logging.getLogger(__name__)


class SenderAllowlist:
    """Controls which Telegram users can interact with the bot."""

    def __init__(self, allowed_users: List[int] | None = None):
        settings = get_settings()
        self._allowed: Set[int] = set(allowed_users or settings.telegram_allowed_users)

    def is_allowed(self, user_id: int) -> bool:
        if not self._allowed:
            # No allowlist = allow all (for development)
            return True
        return user_id in self._allowed

    def add(self, user_id: int) -> None:
        self._allowed.add(user_id)
        logger.info("Added user %d to allowlist", user_id)

    def remove(self, user_id: int) -> None:
        self._allowed.discard(user_id)
        logger.info("Removed user %d from allowlist", user_id)

    @property
    def users(self) -> Set[int]:
        return self._allowed.copy()
