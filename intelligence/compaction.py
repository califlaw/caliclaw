from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from core.agent import AgentConfig, AgentPool
from core.config import get_settings
from core.db import Database

logger = logging.getLogger(__name__)


class ConversationCompactor:
    """Compacts long conversations by summarizing and archiving."""

    def __init__(self, db: Database, pool: AgentPool):
        self.db = db
        self.pool = pool
        self._max_messages_before_compaction = 100
        self._archive_dir = get_settings().workspace_dir / "conversations"
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    async def check_and_compact(self, session_id: str) -> bool:
        """Check if session needs compaction and do it. Returns True if compacted."""
        count = await self.db.count_messages(session_id)
        if count < self._max_messages_before_compaction:
            return False

        logger.info("Session %s has %d messages, compacting...", session_id, count)

        # Archive full conversation first
        await self._archive_conversation(session_id)

        # Summarize
        summary = await self._summarize_session(session_id)

        # Update session
        await self.db.update_session(session_id, summary=summary, status="compacted")

        logger.info("Session %s compacted. Summary: %s...", session_id, summary[:100])
        return True

    async def _archive_conversation(self, session_id: str) -> Path:
        """Save full conversation to markdown file."""
        messages = await self.db.get_messages(session_id, limit=10000)

        now = datetime.now(timezone.utc)
        filename = f"{now.strftime('%Y-%m-%d')}_{session_id[:12]}.md"
        path = self._archive_dir / filename

        lines = [f"# Conversation Archive\n", f"Session: {session_id}\n", f"Date: {now.isoformat()}\n\n---\n"]

        for msg in messages:
            role = msg["role"].upper()
            ts = datetime.fromtimestamp(msg["timestamp"], tz=timezone.utc).strftime("%H:%M:%S")
            content = msg["content"]
            lines.append(f"\n## [{ts}] {role}\n\n{content}\n")

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Archived conversation to %s", path)
        return path

    async def _summarize_session(self, session_id: str) -> str:
        """Use haiku to create a brief summary."""
        messages = await self.db.get_messages(session_id, limit=50)

        conversation = "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in messages[-20:]
        )

        config = AgentConfig(
            name="compactor",
            model="haiku",
            system_prompt="Summarize this conversation in 3-5 bullet points. Focus on decisions made and outcomes.",
            timeout_seconds=30,
        )

        result = await self.pool.run(config, f"Summarize:\n{conversation}")
        return result.text if result.text else "No summary available."


class DreamingEngine:
    """Nightly memory consolidation — reviews conversations and updates memory."""

    def __init__(self, db: Database, pool: AgentPool):
        self.db = db
        self.pool = pool

    async def dream(self) -> str:
        """Run nightly consolidation. Returns summary of what was learned."""
        settings = get_settings()
        archive_dir = settings.workspace_dir / "conversations"

        # Find today's archives
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        todays_files = list(archive_dir.glob(f"{today}*.md"))

        if not todays_files:
            return "No conversations to process."

        # Read all conversations
        all_text = ""
        for f in todays_files:
            content = f.read_text(encoding="utf-8")
            all_text += f"\n---\nFrom {f.name}:\n{content[:3000]}\n"

        if not all_text.strip():
            return "No meaningful conversations today."

        # Extract insights
        config = AgentConfig(
            name="dreamer",
            model="sonnet",
            system_prompt=(
                "You are the dreaming engine. Review today's conversations and:\n"
                "1. Extract key facts learned about the user\n"
                "2. Identify recurring patterns or preferences\n"
                "3. Note any important decisions or outcomes\n"
                "4. Suggest updates to memory files\n\n"
                "Output in this format:\n"
                "## User Insights\n...\n"
                "## Patterns\n...\n"
                "## Memory Updates\n..."
            ),
            timeout_seconds=120,
            working_dir=settings.workspace_dir,
        )

        result = await self.pool.run(config, f"Process today's conversations:\n{all_text[:8000]}")

        if result.text:
            # Save dreaming results to memory
            from intelligence.memory import MemoryManager
            mm = MemoryManager()
            mm.save(
                name=f"Dream {today}",
                description=f"Nightly consolidation for {today}",
                mem_type="project",
                content=result.text,
                filename=f"dream_{today.replace('-', '_')}.md",
            )

        return result.text or "Dreaming produced no insights."


class ContextInjector:
    """Automatically injects system context into agent prompts."""

    @staticmethod
    async def get_context() -> str:
        """Gather current system context for injection."""
        import asyncio
        from datetime import datetime

        parts = [f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M %Z')}"]

        # System stats
        try:
            proc = await asyncio.create_subprocess_exec(
                "sh", "-c",
                "echo \"Load: $(uptime | awk -F'load average:' '{print $2}')\"; "
                "echo \"Disk: $(df -h / | tail -1 | awk '{print $5}')\"; "
                "echo \"RAM: $(free -m | awk '/Mem:/{printf \"%d/%dMB\", $3, $2}')\"",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            parts.append(stdout.decode().strip())
        except (subprocess.TimeoutExpired, OSError, asyncio.TimeoutError):
            pass

        return "\n".join(parts)
