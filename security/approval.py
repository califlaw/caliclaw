from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Optional

from core.db import Database

logger = logging.getLogger(__name__)


class ApprovalManager:
    """Manages HITL approval requests via Telegram or terminal."""

    # Track active instances so callback handlers can find the right future
    _active_instances: list["ApprovalManager"] = []

    def __init__(self, db: Database):
        self.db = db
        self._pending_futures: dict[str, asyncio.Future] = {}
        ApprovalManager._active_instances.append(self)

    def __del__(self):
        try:
            ApprovalManager._active_instances.remove(self)
        except ValueError:
            pass

    def generate_code(self) -> str:
        return secrets.token_hex(2)  # 4-char hex code like "7f3a"

    async def request_approval(
        self,
        agent_name: str,
        action: str,
        level: str,
        reason: str = "",
        timeout: float = 300.0,
    ) -> bool:
        """Request approval and wait for it. Returns True if approved."""
        code = self.generate_code()
        approval_id = f"approval-{secrets.token_hex(6)}"

        await self.db.create_approval(
            approval_id=approval_id,
            agent_name=agent_name,
            action=action,
            level=level,
            reason=reason,
            code=code,
        )

        # Create a future to wait on
        future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._pending_futures[code] = future

        logger.info(
            "Approval requested: agent=%s action=%s level=%s code=%s",
            agent_name, action, level, code,
        )

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            await self.db.resolve_approval(approval_id, "timeout", "system")
            logger.warning("Approval timed out: %s", approval_id)
            return False
        finally:
            self._pending_futures.pop(code, None)

    async def resolve(self, code: str, approved: bool, resolved_by: str = "telegram") -> bool:
        """Resolve a pending approval. Returns True if found and resolved."""
        approval = await self.db.get_pending_approval(code)
        if not approval:
            return False

        status = "approved" if approved else "denied"
        await self.db.resolve_approval(approval["id"], status, resolved_by)

        future = self._pending_futures.get(code)
        if future and not future.done():
            future.set_result(approved)

        logger.info("Approval %s: code=%s by=%s", status, code, resolved_by)
        return True

    def get_approval_info(self, code: str) -> Optional[dict]:
        """Get info about a pending approval (sync, for display)."""
        future = self._pending_futures.get(code)
        return {"pending": future is not None and not future.done()} if future else None
