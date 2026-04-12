"""caliclaw Telegram bot — core class.

Command and callback handlers are in telegram/handlers.py.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatAction, ParseMode
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.agent import AgentConfig, AgentPool, AgentResult
from core.config import get_settings
from core.protocols import StorageProtocol, AgentRunnerProtocol
from core.queue import MessageQueue, QueuedMessage
from core.souls import SoulLoader

logger = logging.getLogger(__name__)

STOP_WORDS = {"стоп", "stop"}

_RATE_LIMIT = 15
_RATE_WINDOW = 60.0


class CaliclawBot:
    def __init__(
        self,
        db: StorageProtocol,
        pool: AgentRunnerProtocol | None = None,
        settings=None,
    ):
        self.settings = settings or get_settings()
        self.bot = Bot(token=self.settings.telegram_bot_token)
        self.dp = Dispatcher()
        self.db = db
        self.pool = pool or AgentPool()
        self.queue = MessageQueue()
        self.souls = SoulLoader()
        self._typing_tasks: dict[int, asyncio.Task] = {}
        self._current_model: str = self.settings.claude_default_model
        self._active_loops: dict[int, "AgentLoop"] = {}
        self._rate_history: dict[int, list[float]] = {}
        self._pairing_code: str | None = self._load_pairing_code()
        self._working_dir: Path = self.settings.workspace_dir
        self._inject_context: bool = False
        self._stop_requested: bool = False

        self._setup_handlers()

    def _setup_handlers(self) -> None:
        from telegram.handlers import register_handlers
        register_handlers(self)

    # ── Auth & pairing ──

    def _check_allowed(self, message: Message) -> bool:
        if not self.settings.telegram_allowed_users:
            return False
        user_id = message.from_user.id if message.from_user else 0
        return user_id in self.settings.telegram_allowed_users

    def _load_pairing_code(self) -> str | None:
        code_file = self.settings.data_dir / "pairing_code.txt"
        if not code_file.exists():
            return None
        # Check TTL — pairing code expires after 15 minutes
        age = time.time() - code_file.stat().st_mtime
        if age > 900:  # 15 minutes
            logger.warning("Pairing code expired (age: %.0fs), removing", age)
            code_file.unlink(missing_ok=True)
            return None
        return code_file.read_text().strip().upper()

    def _pair_user(self, user_id: int) -> None:
        self.settings.telegram_allowed_users = [user_id]
        env_file = self.settings.project_root / ".env"
        if env_file.exists():
            content = env_file.read_text()
            if "TELEGRAM_ALLOWED_USERS" not in content:
                content += f"\nTELEGRAM_ALLOWED_USERS={user_id}\n"
            else:
                content = re.sub(r"TELEGRAM_ALLOWED_USERS=.*", f"TELEGRAM_ALLOWED_USERS={user_id}", content)
            env_file.write_text(content)
        logger.info("Paired with user %d", user_id)

    def _check_rate_limit(self, user_id: int) -> bool:
        now = time.time()
        history = self._rate_history.get(user_id, [])
        history = [t for t in history if now - t < _RATE_WINDOW]
        history.append(now)
        self._rate_history[user_id] = history
        return len(history) <= _RATE_LIMIT

    # ── Skills helper ──

    def _build_skills_message(self) -> tuple[str, InlineKeyboardMarkup | None]:
        skills_dir = self.settings.skills_dir
        if not skills_dir or not skills_dir.exists():
            return "No skills found.", None

        skill_names = sorted([
            d.name for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        ])
        if not skill_names:
            return "No skills. Create: `skills/<name>/SKILL.md`", None

        config_file = self.settings.project_root / "data" / "enabled_skills.txt"
        enabled = set()
        if config_file.exists():
            enabled = {l.strip() for l in config_file.read_text().split("\n") if l.strip()}

        # Parse description from each SKILL.md frontmatter
        import re
        skills_info = []
        for s in skill_names:
            skill_md = skills_dir / s / "SKILL.md"
            desc = ""
            try:
                content = skill_md.read_text(encoding="utf-8")
                m = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
                if m:
                    desc = m.group(1).strip()
            except OSError:
                pass
            skills_info.append((s, desc, s in enabled))

        # Build text with name + description
        lines = ["🛠 **Skills:**\n"]
        for name, desc, is_on in skills_info:
            icon = "🟢" if is_on else "⚪"
            lines.append(f"{icon} `{name}` — _{desc}_")

        # Buttons trigger detail view, not toggle
        buttons = [
            InlineKeyboardButton(
                text=f"{'🟢' if is_on else '⚪'} {name}",
                callback_data=f"skill_view:{name}",
            )
            for name, _, is_on in skills_info
        ]
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[buttons[i:i+2] for i in range(0, len(buttons), 2)]
        )
        return "\n".join(lines), keyboard

    def _build_skill_detail(self, skill_name: str) -> tuple[str, InlineKeyboardMarkup | None]:
        """Build detail view for a single skill — full content + Enable/Disable + Back."""
        skill_md = self.settings.skills_dir / skill_name / "SKILL.md"
        if not skill_md.exists():
            return f"Skill not found: {skill_name}", None

        config_file = self.settings.project_root / "data" / "enabled_skills.txt"
        enabled = set()
        if config_file.exists():
            enabled = {l.strip() for l in config_file.read_text().split("\n") if l.strip()}
        is_on = skill_name in enabled

        # Read content, strip frontmatter
        content = skill_md.read_text(encoding="utf-8")
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                content = content[end + 4:].strip()

        # Truncate if too long for Telegram
        if len(content) > 3500:
            content = content[:3500] + "\n\n_..._"

        text = f"🛠 **{skill_name}**\n\n{content}"

        toggle_label = "⚪ Disable" if is_on else "🟢 Enable"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=toggle_label, callback_data=f"skill:{skill_name}"),
            InlineKeyboardButton(text="◀ Back", callback_data="skill_back"),
        ]])
        return text, keyboard

    # ── Stop handler ──

    async def _handle_stop(self, message: Message) -> None:
        chat_id = message.chat.id
        sender = message.from_user.full_name if message.from_user else "Unknown"
        stopped = []

        # Set stop flag so any in-flight _run_agent checks it
        self._stop_requested = True

        loop_runner = self._active_loops.get(chat_id)
        if loop_runner:
            loop_runner.cancel()
            stopped.append("loop")

        # Kill active agents
        active_before = self.pool.active_count
        if active_before > 0:
            await self.pool.kill_all()
            stopped.append(f"{active_before} agent(s)")

        # Cancel queue processing
        if self.queue.is_processing("main"):
            self.queue.cancel("main")
            if "agent" not in str(stopped):
                stopped.append("queue")

        # Cancel typing indicator
        typing_task = self._typing_tasks.pop(chat_id, None)
        if typing_task:
            typing_task.cancel()

        # DON'T reset _stop_requested here — it's reset when next message starts
        stop_detail = ", ".join(stopped) if stopped else "nothing active"
        logger.info("STOP command from %s (chat %d): %s", sender, chat_id, stop_detail)

        session = await self.db.get_active_session("main")
        if session:
            await self.db.save_message(
                role="system",
                content=f"[STOP] User issued stop command. Stopped: {stop_detail}",
                session_id=session["id"],
            )

        if stopped:
            await message.answer(f"🛑 Stopped: {', '.join(stopped)}")
        else:
            await message.answer("🛑 Nothing to stop — no agents running.")

    # ── Media handlers ──

    async def _handle_audio(self, message: Message) -> None:
        voice = message.voice or message.audio
        if not voice:
            return

        file = await self.bot.get_file(voice.file_id)
        media_dir = self.settings.workspace_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        ext = "ogg" if message.voice else "mp3"
        path = media_dir / f"audio_{int(time.time())}_{voice.file_id[-8:]}.{ext}"
        await self.bot.download_file(file.file_path, str(path))

        try:
            from media.transcribe import transcribe_audio
            text = await transcribe_audio(str(path))
            if not text:
                await message.answer("Could not transcribe audio.")
                return
            await self._process_user_message(message, text)
        except (OSError, RuntimeError) as e:
            logger.exception("Transcription failed")
            await message.answer(f"Transcription error: {e}")

    async def _handle_document(self, message: Message) -> None:
        doc = message.document
        if not doc:
            return
        file = await self.bot.get_file(doc.file_id)
        media_dir = self.settings.workspace_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        path = media_dir / f"doc_{int(time.time())}_{doc.file_name or 'file'}"
        await self.bot.download_file(file.file_path, str(path))

        caption = message.caption or f"User sent a document: {doc.file_name}"
        await self._process_user_message(message, f"{caption}\nFile saved at: {path}", media_path=str(path))

    # ── Message processing ──

    async def _process_user_message(
        self, message: Message, text: str, media_path: Optional[str] = None,
    ) -> None:
        chat_id = message.chat.id
        sender = message.from_user.full_name if message.from_user else "User"

        from safety.input_filter import check_injection
        warning = check_injection(text)
        if warning:
            logger.warning("Injection attempt from %s: %s", sender, warning)

        session = await self.db.get_active_session("main")
        if not session:
            session_id = f"session-{uuid.uuid4().hex[:12]}"
            await self.db.create_session(session_id, "main")
        else:
            session_id = session["id"]

        await self.db.save_message(
            role="user", content=text, session_id=session_id,
            telegram_message_id=message.message_id,
        )

        queued = QueuedMessage(
            text=text, sender=sender,
            telegram_message_id=message.message_id, media_path=media_path,
        )
        await self.queue.enqueue(
            session_id, queued,
            lambda sid, batch: self._run_agent(chat_id, sid, batch),
        )

    # Marker the agent outputs when it wants user approval before proceeding
    _APPROVAL_MARKER = "[APPROVAL_NEEDED]"

    async def _run_agent(
        self, chat_id: int, session_id: str, batch: list[QueuedMessage]
    ) -> None:
        if self._stop_requested:
            self._stop_requested = False
            return

        self._stop_requested = False
        typing_task = asyncio.create_task(self._keep_typing(chat_id))
        self._typing_tasks[chat_id] = typing_task

        try:
            prompt = self.queue.format_batch(batch)
            system_prompt = self.souls.load_soul("main")
            session = await self.db.get_session(session_id)
            claude_session_id = session.get("claude_session_id") if session else None

            # If directory switched, inject conversation context
            if self._inject_context:
                context = await self._build_context_summary(session_id)
                if context:
                    prompt = f"{context}\n\n---\n\nCurrent message:\n{prompt}"
                self._inject_context = False

            config = AgentConfig(
                name="main", model=self._current_model, system_prompt=system_prompt,
                continue_session=claude_session_id is not None,
                session_id=claude_session_id, working_dir=self._working_dir,
            )

            response_msg: Optional[Message] = None
            accumulated_text = ""
            last_edit_time = 0.0

            async def on_chunk(chunk: str) -> None:
                nonlocal response_msg, accumulated_text, last_edit_time
                if self._stop_requested:
                    return
                accumulated_text += chunk
                now = time.time()
                if now - last_edit_time < 2.0:
                    return
                display_text = accumulated_text[:4000]
                try:
                    if response_msg is None:
                        response_msg = await self.bot.send_message(chat_id, display_text or "...")
                    elif display_text != (response_msg.text or ""):
                        await response_msg.edit_text(display_text)
                    last_edit_time = now
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass

            result = await self.pool.run_streaming(config, prompt, on_chunk)

            # Retry once if response is empty (transient flakes)
            if not result.text and not result.error:
                logger.warning("Empty response, retrying once...")
                config.continue_session = False
                config.session_id = None
                result = await self.pool.run_streaming(config, prompt, on_chunk)

            typing_task.cancel()
            self._typing_tasks.pop(chat_id, None)

            # If stop was requested while agent was running — don't send response
            if self._stop_requested:
                return

            final_text = result.text or accumulated_text or "No response."
            if result.error:
                final_text = f"⚠️ Error: {result.error}\n\n{final_text}"

            # ── Approval flow ──
            # If agent output contains [APPROVAL_NEEDED], parse it and ask the user
            # Freedom mode skips this — agent has full autonomy
            if self._APPROVAL_MARKER in final_text and not self.settings.freedom_mode:
                await self._handle_approval_request(
                    chat_id, session_id, config, final_text, response_msg,
                )
                return

            await self._send_long_message(chat_id, final_text, response_msg)

            # Only save non-empty responses to avoid polluting context history
            if result.text:
                await self.db.save_message(role="assistant", content=result.text, session_id=session_id)
            if result.session_id:
                await self.db.update_session(session_id, claude_session_id=result.session_id)
            await self.db.log_usage(
                agent_name="main", model=config.model,
                duration_ms=result.duration_ms, session_id=session_id,
            )

        except asyncio.CancelledError:
            typing_task.cancel()
            self._typing_tasks.pop(chat_id, None)
            logger.info("Agent run cancelled (stop requested)")
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            typing_task.cancel()
            self._typing_tasks.pop(chat_id, None)
            logger.exception("Agent run failed: %s", e)
            await self.bot.send_message(chat_id, "⚠️ Processing error. Please try again.")

    async def _handle_approval_request(
        self,
        chat_id: int,
        session_id: str,
        config: AgentConfig,
        agent_text: str,
        response_msg,
    ) -> None:
        """Parse [APPROVAL_NEEDED] from agent output, send buttons, wait, re-run."""
        import re
        from security.approval import ApprovalManager

        # Extract action description from agent text
        # Format: [APPROVAL_NEEDED] <description of what the agent wants to do>
        match = re.search(
            r'\[APPROVAL_NEEDED\]\s*(.+?)(?:\n|$)', agent_text, re.DOTALL,
        )
        action_desc = match.group(1).strip() if match else "execute a potentially dangerous action"

        # Strip the marker from display text
        display_text = agent_text.replace(self._APPROVAL_MARKER, "").strip()
        if display_text:
            await self._send_long_message(chat_id, display_text, response_msg)

        # Create approval request
        mgr = ApprovalManager(self.db)

        # Send approval buttons to Telegram
        code = mgr.generate_code()
        approval_id = f"approval-{code}"
        await self.db.create_approval(
            approval_id=approval_id,
            agent_name="main",
            action=action_desc,
            level="destructive",
            reason="Agent requested user approval",
            code=code,
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{code}"),
            InlineKeyboardButton(text="❌ Deny", callback_data=f"deny:{code}"),
        ]])
        await self.bot.send_message(
            chat_id,
            f"🔐 **Approval required**\n\n`{action_desc}`\n\n"
            f"Code: `{code}`",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        # Wait for user decision (5 min timeout)
        future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        mgr._pending_futures[code] = future

        try:
            approved = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            await self.db.resolve_approval(approval_id, "timeout", "system")
            await self.bot.send_message(chat_id, "⏱ Approval timed out (5 min). Action cancelled.")
            return
        finally:
            mgr._pending_futures.pop(code, None)

        if not approved:
            await self.bot.send_message(chat_id, "❌ Action denied.")
            return

        # Re-run agent with approval context
        config.continue_session = True
        followup_prompt = f"User approved the action: {action_desc}. Proceed now."
        result = await self.pool.run(config, followup_prompt)

        final = result.text or "Done."
        if result.error:
            final = f"⚠️ {result.error}\n\n{final}"
        await self._send_long_message(chat_id, final, None)

        if result.text:
            await self.db.save_message(role="assistant", content=result.text, session_id=session_id)
        if result.session_id:
            await self.db.update_session(session_id, claude_session_id=result.session_id)

    async def _send_long_message(
        self,
        chat_id: int,
        text: str,
        first_message: Optional[Message] = None,
    ) -> None:
        """Send text as one or multiple messages, splitting on 4096 char limit.

        Splits at line breaks where possible to keep markdown intact.
        """
        MAX = 4096

        if len(text) <= MAX:
            try:
                if first_message is None:
                    await self.bot.send_message(chat_id, text)
                elif text != (first_message.text or ""):
                    await first_message.edit_text(text)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning("Failed to send response: %s", e)
                await self.bot.send_message(chat_id, text)
            return

        # Split into chunks at line boundaries
        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= MAX:
                chunks.append(remaining)
                break
            # Try to split at last newline before MAX
            split_at = remaining.rfind("\n", 0, MAX)
            if split_at == -1 or split_at < MAX // 2:
                # No good break — split at MAX (worst case)
                split_at = MAX
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        # First chunk replaces the streaming message (if any)
        try:
            if first_message is not None:
                await first_message.edit_text(chunks[0])
            else:
                await self.bot.send_message(chat_id, chunks[0])
            # Remaining chunks as new messages
            for chunk in chunks[1:]:
                await self.bot.send_message(chat_id, chunk)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning("Failed to send chunked response: %s", e)
            for chunk in chunks:
                try:
                    await self.bot.send_message(chat_id, chunk)
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass

    async def _keep_typing(self, chat_id: int) -> None:
        try:
            while not self._stop_requested:
                await self.bot.send_chat_action(chat_id, ChatAction.TYPING)
                for _ in range(8):
                    if self._stop_requested:
                        return
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    async def _build_context_summary(self, session_id: str, limit: int = 10) -> str:
        """Build context summary from recent messages for cross-session continuity."""
        messages = await self.db.get_messages(session_id, limit=limit * 2)
        # Take last N user/assistant exchanges
        relevant = [m for m in messages if m["role"] in ("user", "assistant")][-limit:]
        if not relevant:
            return ""

        lines = ["[Context from previous conversation]"]
        for m in relevant:
            role = "User" if m["role"] == "user" else "You"
            content = m["content"][:500]  # truncate long messages
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    # ── Notifications ──

    async def send_notification(self, chat_id: int, text: str) -> None:
        await self.bot.send_message(chat_id, text)

    async def send_approval_request(
        self, chat_id: int, approval_id: str, agent_name: str,
        action: str, reason: str, code: str, level: str,
    ) -> None:
        text = (
            f"🔐 **Approval Request**\n\n"
            f"Agent: `{agent_name}`\n"
            f"Action: `{action}`\n"
            f"Reason: {reason}\n"
        )
        if level == "confirm_terminal":
            text += f"\n⚠️ Critical action!\nEnter code: `/confirm {code}`"
            await self.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{code}"),
                InlineKeyboardButton(text="❌ Deny", callback_data=f"deny:{code}"),
            ]])
            await self.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    # ── Start / Stop ──

    async def start(self) -> None:
        logger.info("Starting caliclaw Telegram bot...")
        from aiogram.types import BotCommand
        await self.bot.set_my_commands([
            BotCommand(command="fresh", description="New session"),
            BotCommand(command="freedom", description="Full machine control on/off"),
            BotCommand(command="model", description="Switch model"),
            BotCommand(command="skills", description="List skills"),
            BotCommand(command="agents", description="List agents"),
            BotCommand(command="spawn", description="Create agent"),
            BotCommand(command="kill", description="Kill agent"),
            BotCommand(command="tasks", description="Scheduled tasks"),
            BotCommand(command="loop", description="Autonomous loop"),
            BotCommand(command="cron", description="Schedule task"),
            BotCommand(command="status", description="System pulse"),
            BotCommand(command="usage", description="Token usage"),
            BotCommand(command="memory", description="Show memory"),
            BotCommand(command="soul", description="Show soul"),
            BotCommand(command="unleash", description="Grant directory access"),
            BotCommand(command="confirm", description="Approve action"),
            BotCommand(command="squeeze", description="Compress context"),
            BotCommand(command="reset", description="Reset state"),
            BotCommand(command="restart", description="Restart bot"),
            BotCommand(command="help", description="All commands"),
        ])

        retry_delay = 5
        attempt = 0
        while True:
            try:
                attempt += 1
                if attempt > 1:
                    logger.info("Telegram reconnect attempt #%d", attempt)
                await self.dp.start_polling(self.bot, handle_signals=False)
                break
            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as e:
                logger.warning("Telegram connection lost: %s. Retrying in %ds...", e, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def stop(self) -> None:
        await self.dp.stop_polling()
        await self.pool.kill_all()
        await self.bot.session.close()
