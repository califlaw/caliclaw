"""Activity tracking — request counts, not budget estimates.

We used to maintain a synthetic `estimated_percent` counter based on
fixed per-model weights, and gate commands on it (auto-downgrade model,
stop /loop, refuse agent runs). That metric had no connection to the
real Claude subscription — Claude itself returns `credit is too low`
or rate-limit errors when real capacity runs out, and we surface those
as hints. Keeping our own fake meter only produced false positives.

This module now logs and summarizes request *counts* per model. No
percentages, no thresholds, no auto-routing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from core.db import Database

logger = logging.getLogger(__name__)


class UsageTracker:
    """Logs request counts per agent/model and summarizes today's activity."""

    def __init__(self, db: Database):
        self.db = db

    async def log_request(
        self,
        agent_name: str,
        model: str,
        duration_ms: int = 0,
        session_id: Optional[str] = None,
    ) -> None:
        await self.db.log_usage(
            agent_name=agent_name,
            model=model,
            duration_ms=duration_ms,
            session_id=session_id,
        )

    async def get_today_summary(self) -> dict:
        """Return per-model request counts + total duration for today (UTC)."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        async with self.db.db.execute(
            """SELECT model, COUNT(*) AS count, SUM(duration_ms) AS total_ms
               FROM usage_log WHERE timestamp >= ?
               GROUP BY model""",
            (today_start,),
        ) as cur:
            rows = await cur.fetchall()

        summary = {
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
            }
            summary["total_requests"] += row["count"]
            summary["total_duration_ms"] += row["total_ms"] or 0

        return summary
