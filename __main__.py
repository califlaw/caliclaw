"""caliclaw — Personal AI Assistant via Telegram + Claude Code."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Fix macOS SSL: Python doesn't auto-use certifi's certificate bundle
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

from core.config import get_settings
from core.db import Database
from core.agent import AgentPool
from telegram.bot import CaliclawBot
from automation.scheduler import TaskScheduler, HeartbeatManager

logger = logging.getLogger("caliclaw")

_PID_FILE = Path(__file__).resolve().parent / "data" / "caliclaw.pid"


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
        self.bot: CaliclawBot | None = None
        self.scheduler: TaskScheduler | None = None
        self._shutdown_event = asyncio.Event()
        self._shutting_down = False

    def _write_pid(self) -> None:
        _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PID_FILE.write_text(str(os.getpid()))

    def _remove_pid(self) -> None:
        try:
            _PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    async def start(self, debug: bool = False) -> None:
        # Setup logging
        from logging.handlers import RotatingFileHandler

        console_level = logging.DEBUG if debug else logging.WARNING
        file_level = logging.DEBUG if debug else logging.INFO

        log_file = self.settings.project_root / "logs" / "caliclaw.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Rotate at 10MB, keep 5 backups (50MB total max)
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

        # Ensure directories
        self.settings.ensure_dirs()

        # Connect database
        await self.db.connect()
        logger.info("Database connected")

        # Register main agent if not exists
        agent = await self.db.get_agent("main")
        if not agent:
            await self.db.save_agent(name="main", scope="global")

        # Setup heartbeats
        hm = HeartbeatManager(self.db)
        await hm.setup_default_heartbeats()

        # Create bot — inject shared pool and settings
        self.bot = CaliclawBot(db=self.db, pool=self.pool, settings=self.settings)

        # Get chat_id for notifications (first allowed user)
        notify_chat_id = (
            self.settings.telegram_allowed_users[0]
            if self.settings.telegram_allowed_users
            else None
        )

        # Create scheduler
        async def notify(msg: str) -> None:
            if self.bot and notify_chat_id:
                try:
                    await self.bot.send_notification(notify_chat_id, msg)
                except (RuntimeError, ValueError, OSError):
                    logger.exception("Notification failed")

        self.scheduler = TaskScheduler(self.db, self.pool, on_notify=notify)

        # Register shutdown on SIGTERM/SIGINT
        # Use threading to ensure os._exit runs even if event loop is stuck
        import threading

        def _force_shutdown(signum, frame):
            logger.info("Signal %d received, shutting down...", signum)

            def _delayed_exit():
                import time
                time.sleep(10)
                logger.warning("Forcing exit after 10s")
                os._exit(1)

            # Start a watchdog thread that will force-kill if shutdown hangs
            t = threading.Thread(target=_delayed_exit, daemon=True)
            t.start()

            # Trigger graceful shutdown
            asyncio.create_task(self.shutdown())

        signal.signal(signal.SIGTERM, _force_shutdown)
        signal.signal(signal.SIGINT, _force_shutdown)

        # Start all services
        tasks = [
            asyncio.create_task(self.bot.start(), name="telegram-bot"),
            asyncio.create_task(self.scheduler.start(), name="scheduler"),
        ]

        # Optional dashboard
        if self.settings.dashboard_enabled:
            from monitoring.dashboard import start_dashboard
            tasks.append(asyncio.create_task(start_dashboard(self.db), name="dashboard"))

        # Auto-backup loop
        if self.settings.backup_enabled:
            tasks.append(asyncio.create_task(
                self._backup_loop(notify_chat_id), name="backup-loop"
            ))

        logger.info(
            "caliclaw running. Bot: active, Scheduler: active, Dashboard: %s",
            "active" if self.settings.dashboard_enabled else "disabled",
        )

        # BIOS-style boot display (skipped under systemd where stdout is log file)
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
                modules.append((
                    "backup",
                    f"auto every {self.settings.backup_interval_days}d",
                ))

            ui.boot(modules, version="v1.0.0")
            ui.c.print(
                "  [dim]Ctrl+C to stop. Logs: logs/caliclaw.log[/dim]"
            )
            ui.c.print()
        else:
            print("caliclaw running. Ctrl+C to stop. Logs: logs/caliclaw.log")

        # Notify owner that bot is up (delay to let polling start)
        async def _notify_startup():
            await asyncio.sleep(3)
            if notify_chat_id:
                try:
                    await self.bot.send_notification(notify_chat_id, "🔱 caliclaw is up.")
                except (RuntimeError, ValueError, OSError):
                    pass
        asyncio.create_task(_notify_startup())

        # Wait for shutdown
        await self._shutdown_event.wait()

        # Cancel all tasks with timeout
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        self._remove_pid()

    async def _handle_signal(self) -> None:
        """Handle SIGTERM/SIGINT — shutdown and force exit."""
        try:
            await asyncio.wait_for(self.shutdown(), timeout=10)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("Shutdown timed out, forcing exit")
        # Force exit to prevent zombie processes
        os._exit(0)

    async def _backup_loop(self, chat_id: int | None) -> None:
        """Periodic auto-backup to Telegram."""
        from core.backup import (
            create_backup, send_backup_to_telegram, is_backup_due, cleanup_old_backups
        )

        # Wait initial 5 minutes after startup before first check
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

            # Check every hour
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

        # Graceful shutdown with 15s timeout (compat with Python 3.10)
        try:
            await asyncio.wait_for(_do_shutdown(), timeout=15)
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("Graceful shutdown timed out after 15s, forcing exit")
            await self.pool.kill_all()
            await self.db.close()

        logger.info("caliclaw stopped.")
        self._shutdown_event.set()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Verbose console output")
    args = parser.parse_args()

    app = CaliclawApp()
    try:
        asyncio.run(app.start(debug=args.debug))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
