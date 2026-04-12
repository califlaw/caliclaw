from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from core.config import get_settings
from core.db import Database

logger = logging.getLogger(__name__)

# Rough token-per-percent estimates (varies by plan)
# These are approximations — actual usage comes from /usage
MODEL_WEIGHT = {
    "haiku": 0.05,    # ~0.05% per request
    "sonnet": 0.2,    # ~0.2% per request
    "opus": 0.8,      # ~0.8% per request
}


class UsageTracker:
    """Tracks token usage as percentage of daily limit."""

    def __init__(self, db: Database):
        self.db = db
        self._cached_usage: Optional[float] = None
        self._cache_time: float = 0

    async def get_usage_percent(self) -> float:
        """Get estimated usage for today as a percentage."""
        return await self.db.get_usage_today()

    async def log_request(
        self,
        agent_name: str,
        model: str,
        duration_ms: int = 0,
        session_id: Optional[str] = None,
    ) -> float:
        """Log a request and return estimated total usage percent."""
        estimated = MODEL_WEIGHT.get(model, 0.3)

        await self.db.log_usage(
            agent_name=agent_name,
            model=model,
            duration_ms=duration_ms,
            session_id=session_id,
            estimated_percent=estimated,
        )

        return await self.get_usage_percent()

    async def check_limits(self) -> str:
        """Check usage against limits. Returns status: 'ok', 'warning', 'emergency', 'stop'."""
        settings = get_settings()
        usage = await self.get_usage_percent()

        if usage >= settings.usage_stop_percent:
            return "stop"
        if usage >= settings.usage_emergency_percent:
            return "emergency"
        if usage >= settings.usage_pause_percent:
            return "warning"
        return "ok"

    async def get_today_summary(self) -> dict:
        """Get usage summary for today."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        async with self.db.db.execute(
            """SELECT model, COUNT(*) as count, SUM(duration_ms) as total_ms,
               SUM(estimated_percent) as total_pct
               FROM usage_log WHERE timestamp >= ?
               GROUP BY model""",
            (today_start,),
        ) as cur:
            rows = await cur.fetchall()

        summary = {
            "total_percent": 0.0,
            "total_requests": 0,
            "total_duration_ms": 0,
            "by_model": {},
        }

        for row in rows:
            row = dict(row)
            model = row["model"]
            summary["by_model"][model] = {
                "count": row["count"],
                "duration_ms": row["total_ms"] or 0,
                "percent": row["total_pct"] or 0,
            }
            summary["total_percent"] += row["total_pct"] or 0
            summary["total_requests"] += row["count"]
            summary["total_duration_ms"] += row["total_ms"] or 0

        return summary


class ModelRouter:
    """Routes requests to appropriate model based on complexity and usage."""

    def __init__(self, tracker: UsageTracker):
        self.tracker = tracker
        self._default_model = get_settings().claude_default_model

    async def select_model(
        self,
        task_type: str = "general",
        force_model: Optional[str] = None,
    ) -> str:
        """Select the appropriate model based on task type and current usage."""
        if force_model:
            return force_model

        usage_status = await self.tracker.check_limits()

        # Auto-downgrade at high usage
        if usage_status == "stop":
            return "haiku"  # Minimum possible
        if usage_status == "emergency":
            return "haiku"
        if usage_status == "warning":
            # Downgrade opus->sonnet, sonnet stays
            if task_type in ("complex", "architecture", "planning"):
                return "sonnet"
            return "haiku"

        # Normal routing by task type
        task_models = {
            "simple": "haiku",
            "lookup": "haiku",
            "heartbeat": "haiku",
            "general": "sonnet",
            "coding": "sonnet",
            "review": "sonnet",
            "complex": "opus",
            "architecture": "opus",
            "planning": "opus",
            "multi_agent": "sonnet",
        }

        return task_models.get(task_type, self._default_model)
