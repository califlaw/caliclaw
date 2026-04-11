from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Coroutine, Optional

from croniter import croniter

from core.agent import AgentConfig, AgentPool, AgentResult
from core.config import get_settings
from core.db import Database

logger = logging.getLogger(__name__)


def cron_next_run(expression: str, tz_name: str = "UTC") -> float:
    """Calculate next cron run timestamp respecting user's timezone.

    Cron expressions like "0 9 * * *" mean "9 AM in user's local time",
    not 9 AM UTC. This function ensures that.

    Args:
        expression: cron expression (5 or 6 fields)
        tz_name: timezone name (e.g. "Europe/Moscow", "UTC")
    Returns:
        Unix timestamp of next run.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except (ImportError, Exception):
        tz = timezone.utc

    now = datetime.now(tz)
    cron = croniter(expression, now)
    next_dt = cron.get_next(datetime)
    # Ensure tz-aware so .timestamp() converts to correct UTC seconds
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=tz)
    return next_dt.timestamp()


class TaskScheduler:
    """Cron/interval/once task scheduler with heartbeat support."""

    def __init__(
        self,
        db: Database,
        pool: AgentPool,
        on_notify: Optional[Callable[[str], Coroutine]] = None,
    ):
        self.db = db
        self.pool = pool
        self._on_notify = on_notify
        self._running = False
        self._poll_interval = 30  # seconds

    async def start(self) -> None:
        self._running = True
        logger.info("Task scheduler started (poll every %ds)", self._poll_interval)
        while self._running:
            try:
                await self._poll()
            except (RuntimeError, ValueError, OSError):
                logger.exception("Scheduler poll error")
            await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False

    async def _poll(self) -> None:
        due_tasks = await self.db.get_due_tasks()
        for task in due_tasks:
            asyncio.create_task(self._execute_task(task))

    async def _execute_task(self, task: dict) -> None:
        task_id = task["id"]
        task_name = task["name"]
        start = time.time()

        logger.info("Executing scheduled task: %s", task_name)

        try:
            config = AgentConfig(
                name=f"task-{task_name}",
                model=task.get("model", "haiku"),
                system_prompt=f"You are executing a scheduled task: {task_name}. Be concise.",
                timeout_seconds=120,
                working_dir=get_settings().workspace_dir,
            )

            result = await self.pool.run(config, task["prompt"])
            duration_ms = int((time.time() - start) * 1000)

            # Log the run
            status = "success" if not result.error else "failed"
            await self.db.log_task_run(
                task_id=task_id,
                duration_ms=duration_ms,
                status=status,
                result=result.text[:2000] if result.text else None,
                error=result.error,
            )

            # Calculate next run
            next_run = self._calculate_next_run(task)
            task_status = "active" if next_run else "completed"
            await self.db.update_task_after_run(
                task_id=task_id,
                next_run=next_run,
                result=result.text[:2000] if result.text else "",
                status=task_status,
            )

            # Notify if configured
            if task.get("notify") and self._on_notify:
                if result.error:
                    msg = f"⚠️ Задача `{task_name}` провалилась:\n{result.error}"
                else:
                    msg = f"📋 Задача `{task_name}`:\n{result.text[:1000]}"
                await self._on_notify(msg)

            # Log usage
            await self.db.log_usage(
                agent_name=f"task-{task_name}",
                model=config.model,
                duration_ms=duration_ms,
            )

        except (RuntimeError, ValueError, OSError) as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.exception("Task %s failed", task_name)
            await self.db.log_task_run(
                task_id=task_id,
                duration_ms=duration_ms,
                status="failed",
                error=str(e),
            )

    def _calculate_next_run(self, task: dict) -> Optional[float]:
        stype = task["schedule_type"]
        svalue = task["schedule_value"]

        if stype == "once":
            return None

        if stype == "cron":
            try:
                return cron_next_run(svalue, get_settings().tz)
            except (ValueError, KeyError):
                logger.error("Invalid cron expression: %s", svalue)
                return None

        if stype == "interval":
            try:
                interval_seconds = int(svalue)
                return time.time() + interval_seconds
            except ValueError:
                logger.error("Invalid interval: %s", svalue)
                return None

        return None


class HeartbeatManager:
    """Manages system heartbeat tasks."""

    def __init__(self, db: Database):
        self.db = db

    async def setup_default_heartbeats(self) -> None:
        """Create default heartbeat tasks if they don't exist."""
        settings = get_settings()

        heartbeats = [
            {
                "name": "quick_pulse",
                "prompt": (
                    "Quick system check. Run: df -h, free -m, uptime. "
                    "Report ONLY if something is critical (disk >90%, RAM >85%, load high). "
                    "If everything is fine, just say 'OK'."
                ),
                "schedule_type": "cron",
                "schedule_value": settings.heartbeat_quick_cron,
                "model": "haiku",
                "notify": False,  # Only notify on problems
            },
            {
                "name": "system_review",
                "prompt": (
                    "System review. Check:\n"
                    "1. docker ps - all containers running?\n"
                    "2. Last errors in /var/log/syslog or journalctl\n"
                    "3. SSL certificates expiry\n"
                    "4. Disk space trends\n"
                    "Report only issues found."
                ),
                "schedule_type": "cron",
                "schedule_value": settings.heartbeat_review_cron,
                "model": "haiku",
                "notify": False,
            },
            {
                "name": "morning_brief",
                "prompt": (
                    "Morning briefing. Summarize:\n"
                    "1. System status overview\n"
                    "2. Any events overnight\n"
                    "3. Current resource usage\n"
                    "4. Active tasks and agents\n"
                    "Keep it under 10 lines."
                ),
                "schedule_type": "cron",
                "schedule_value": settings.heartbeat_morning_cron,
                "model": "sonnet",
                "notify": True,
            },
        ]

        for hb in heartbeats:
            # Check if already exists
            async with self.db.db.execute(
                "SELECT id FROM tasks WHERE name = ?", (hb["name"],)
            ) as cur:
                exists = await cur.fetchone()

            if not exists:
                next_run = self._get_next_run(hb["schedule_type"], hb["schedule_value"])
                await self.db.create_task(
                    name=hb["name"],
                    prompt=hb["prompt"],
                    schedule_type=hb["schedule_type"],
                    schedule_value=hb["schedule_value"],
                    next_run=next_run,
                    notify=hb["notify"],
                    model=hb["model"],
                )
                logger.info("Created heartbeat task: %s", hb["name"])

    def _get_next_run(self, stype: str, svalue: str) -> float:
        if stype == "cron":
            cron = croniter(svalue, datetime.now(timezone.utc))
            return cron.get_next(datetime).timestamp()
        if stype == "interval":
            return time.time() + int(svalue)
        return time.time()
