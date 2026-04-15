"""CaliclawApp — composition root for the caliclaw daemon."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from core.config import get_settings
from core.db import Database
from core.agent import AgentPool
from telegram.bot import CaliclawBot
from automation.scheduler import TaskScheduler, HeartbeatManager

logger = logging.getLogger("caliclaw")


class CaliclawApp:
    """Composition root — creates all dependencies and wires them together."""

    def __init__(
        self,
        settings=None,
        db: Database | None = None,
        pool: AgentPool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db = db or Database()
        self.pool = pool or AgentPool()
        self.bot: Optional[CaliclawBot] = None
        self.scheduler: Optional[TaskScheduler] = None
        self._shutdown_event = asyncio.Event()
        self._shutting_down = False

    def _write_pid(self) -> None:
        pid_file = self.settings.data_dir / "caliclaw.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))

    def _remove_pid(self) -> None:
        try:
            pid_file = self.settings.data_dir / "caliclaw.pid"
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass

    async def start(self, debug: bool = False) -> None:
        from logging.handlers import RotatingFileHandler

        console_level = logging.DEBUG if debug else logging.WARNING
        file_level = logging.DEBUG if debug else logging.INFO

        log_file = self.settings.project_root / "logs" / "caliclaw.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))

        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))

        logging.basicConfig(level=logging.DEBUG, handlers=[console_handler, file_handler])

        logger.info("Starting caliclaw (pid %d)...", os.getpid())
        self._write_pid()

        self.settings.ensure_dirs()

        await self.db.connect()
        logger.info("Database connected")

        agent = await self.db.get_agent("main")
        if not agent:
            await self.db.save_agent(name="main", scope="global")

        hm = HeartbeatManager(self.db)
        await hm.setup_default_heartbeats()

        self.bot = CaliclawBot(db=self.db, pool=self.pool, settings=self.settings)

        notify_chat_id = (
            self.settings.telegram_allowed_users[0]
            if self.settings.telegram_allowed_users
            else None
        )

        async def notify(msg: str) -> None:
            if self.bot and notify_chat_id:
                try:
                    await self.bot.send_notification(notify_chat_id, msg)
                except (RuntimeError, ValueError, OSError):
                    logger.exception("Notification failed")

        self.scheduler = TaskScheduler(self.db, self.pool, on_notify=notify)

        import threading

        def _force_shutdown(signum, frame):
            logger.info("Signal %d received, shutting down...", signum)

            def _delayed_exit():
                import time
                time.sleep(10)
                logger.warning("Forcing exit after 10s")
                os._exit(1)

            t = threading.Thread(target=_delayed_exit, daemon=True)
            t.start()
            asyncio.create_task(self.shutdown())

        signal.signal(signal.SIGTERM, _force_shutdown)
        signal.signal(signal.SIGINT, _force_shutdown)

        tasks = [
            asyncio.create_task(self.bot.start(), name="telegram-bot"),
            asyncio.create_task(self.scheduler.start(), name="scheduler"),
        ]

        if self.settings.dashboard_enabled:
            from monitoring.dashboard import start_dashboard
            tasks.append(asyncio.create_task(start_dashboard(self.db), name="dashboard"))

        if self.settings.backup_enabled:
            tasks.append(asyncio.create_task(
                self._backup_loop(notify_chat_id), name="backup-loop"
            ))

        logger.info(
            "caliclaw running. Bot: active, Scheduler: active, Dashboard: %s",
            "active" if self.settings.dashboard_enabled else "disabled",
        )

        if sys.stdout.isatty():
            from cli.ui import ui
            bot_username = ""
            try:
                bot_info = await self.bot.bot.get_me()
                bot_username = f"@{bot_info.username}" if bot_info.username else "ok"
            except (RuntimeError, OSError, asyncio.TimeoutError):
                bot_username = "ok"

            skill_count = 0
            skills_config = self.settings.project_root / "data" / "enabled_skills.txt"
            if skills_config.exists():
                skill_count = len([
                    l for l in skills_config.read_text().splitlines() if l.strip()
                ])

            modules = [
                ("vault", "encrypted storage ready"),
                ("storage", "sqlite wal mode"),
                ("agent", f"pool capacity {self.settings.max_concurrent_agents}"),
                ("telegram", f"authorized as {bot_username}"),
                ("scheduler", "cron loop active"),
                ("skills", f"{skill_count} enabled"),
            ]
            if self.settings.dashboard_enabled:
                modules.append(("dashboard", "http://0.0.0.0:8080"))
            if self.settings.backup_enabled:
                modules.append(("backup", f"auto every {self.settings.backup_interval_days}d"))

            from core import get_version
            ui.boot(modules, version=f"v{get_version()}")
            ui.c.print("  [dim]Ctrl+C to stop. Logs: logs/caliclaw.log[/dim]")
            ui.c.print()
        else:
            print("caliclaw running. Ctrl+C to stop. Logs: logs/caliclaw.log")

        async def _notify_startup():
            await asyncio.sleep(3)
            if notify_chat_id:
                try:
                    await self.bot.send_notification(notify_chat_id, "🔱 caliclaw is up.")
                except (RuntimeError, ValueError, OSError):
                    pass
        asyncio.create_task(_notify_startup())

        # Check for updates periodically
        asyncio.create_task(self._update_check_loop(notify_chat_id))

        await self._shutdown_event.wait()

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._remove_pid()

    async def _update_check_loop(self, chat_id: int | None) -> None:
        """Check PyPI for newer version every 6 hours, notify user once."""
        import json
        import urllib.request
        import urllib.error

        CHECK_INTERVAL = 6 * 3600  # 6 hours
        notified_version: str | None = None

        await asyncio.sleep(30)  # wait for bot to settle

        while not self._shutting_down:
            try:
                from importlib.metadata import version as pkg_version
                current = pkg_version("caliclaw")

                req = urllib.request.Request(
                    "https://pypi.org/pypi/caliclaw/json",
                    headers={"User-Agent": f"caliclaw/{current}"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    latest = json.loads(resp.read())["info"]["version"]

                if latest != current and latest != notified_version:
                    cur = tuple(int(x) for x in current.split(".")[:3] if x.isdigit())
                    lat = tuple(int(x) for x in latest.split(".")[:3] if x.isdigit())
                    if lat > cur and chat_id and self.bot:
                        await self.bot.send_notification(
                            chat_id,
                            f"📦 Update available: {current} → {latest}\n"
                            f"Run: `caliclaw update`",
                        )
                        notified_version = latest
            except (urllib.error.URLError, TimeoutError, KeyError,
                    json.JSONDecodeError, OSError, ValueError):
                pass

            await asyncio.sleep(CHECK_INTERVAL)

    async def _backup_loop(self, chat_id: int | None) -> None:
        from core.backup import (
            create_backup, send_backup_to_telegram, is_backup_due, cleanup_old_backups
        )
        await asyncio.sleep(300)
        while not self._shutting_down:
            try:
                if is_backup_due(self.settings.backup_interval_days):
                    logger.info("Auto-backup: creating...")
                    backup_path = create_backup(label="auto")
                    cleanup_old_backups(keep=10)
                    if chat_id and self.bot:
                        try:
                            await send_backup_to_telegram(self.bot.bot, chat_id, backup_path)
                        except (RuntimeError, OSError) as e:
                            logger.exception("Failed to send backup: %s", e)
            except (OSError, RuntimeError):
                logger.exception("Backup loop error")
            await asyncio.sleep(3600)

    async def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Shutting down caliclaw...")

        async def _do_shutdown():
            from monitoring.dashboard import stop_dashboard
            await stop_dashboard()
            if self.scheduler:
                await self.scheduler.stop()
            if self.bot:
                await self.bot.stop()
            await self.pool.kill_all()
            await self.db.close()

        try:
            await asyncio.wait_for(_do_shutdown(), timeout=15)
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("Graceful shutdown timed out after 15s, forcing exit")
            await self.pool.kill_all()
            await self.db.close()

        logger.info("caliclaw stopped.")
        self._shutdown_event.set()
