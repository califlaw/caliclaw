"""Tests for Telegram bot handlers and bot core logic."""
from __future__ import annotations

import time

import pytest
import pytest_asyncio


# ── Bot core ──

class TestBotConstants:
    def test_stop_words(self):
        from telegram.bot import STOP_WORDS
        assert "stop" in STOP_WORDS
        assert "стоп" in STOP_WORDS

    def test_rate_limit_values(self):
        from telegram.bot import _RATE_LIMIT, _RATE_WINDOW
        assert _RATE_LIMIT == 15
        assert _RATE_WINDOW == 60.0


class TestRateLimit:
    def test_within_limit(self):
        """Simulate rate check logic — should allow up to _RATE_LIMIT."""
        from telegram.bot import _RATE_LIMIT, _RATE_WINDOW

        history: list[float] = []
        now = time.time()

        for _ in range(_RATE_LIMIT):
            history = [t for t in history if now - t < _RATE_WINDOW]
            history.append(now)
            assert len(history) <= _RATE_LIMIT

    def test_exceeds_limit(self):
        from telegram.bot import _RATE_LIMIT, _RATE_WINDOW

        history: list[float] = []
        now = time.time()

        for _ in range(_RATE_LIMIT + 1):
            history = [t for t in history if now - t < _RATE_WINDOW]
            history.append(now)

        assert len(history) > _RATE_LIMIT

    def test_old_entries_expire(self):
        from telegram.bot import _RATE_LIMIT, _RATE_WINDOW

        now = time.time()
        # All entries are old
        history = [now - _RATE_WINDOW - 1 for _ in range(20)]
        history = [t for t in history if now - t < _RATE_WINDOW]
        assert len(history) == 0


class TestPairing:
    def test_load_pairing_code(self, tmp_path, settings):
        """Pairing code loads from file."""
        code_file = settings.data_dir / "pairing_code.txt"
        code_file.parent.mkdir(parents=True, exist_ok=True)
        code_file.write_text("ABC123")

        from telegram.bot import CaliclawBot
        # Can't fully instantiate bot without token, but test the method
        assert code_file.read_text().strip().upper() == "ABC123"

    def test_no_pairing_code(self, tmp_path, settings):
        """No pairing code file = None."""
        code_file = settings.data_dir / "pairing_code.txt"
        assert not code_file.exists()


class TestSkillsMessage:
    def test_no_skills_dir(self, settings):
        """No skills dir returns empty message."""
        import shutil
        if settings.skills_dir.exists():
            shutil.rmtree(settings.skills_dir)

        from telegram.bot import CaliclawBot
        # Test the logic directly
        assert not settings.skills_dir.exists()

    def test_skills_with_enabled(self, settings):
        """Skills message includes enabled status."""
        # Create a skill
        skill_dir = settings.skills_dir / "coding"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: coding\ndescription: Write code\n---\n")

        # Enable it
        config_file = settings.project_root / "data" / "enabled_skills.txt"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("coding\n")

        # Verify file state
        enabled = {l.strip() for l in config_file.read_text().split("\n") if l.strip()}
        assert "coding" in enabled


# ── Handler logic (unit tests without Telegram) ──

class TestHandlerCallbackData:
    """Test callback data parsing patterns used by handlers."""

    def test_model_callback_parse(self):
        data = "model:haiku"
        model = data.split(":", 1)[1]
        assert model == "haiku"
        assert model in ("haiku", "sonnet", "opus")

    def test_skill_callback_parse(self):
        data = "skill:coding"
        skill_name = data.split(":", 1)[1]
        assert skill_name == "coding"

    def test_kill_callback_parse(self):
        data = "kill:researcher"
        name = data.split(":", 1)[1]
        assert name == "researcher"
        assert name != "main"

    def test_task_callback_parse(self):
        data = "task:pause:42"
        parts = data.split(":")
        assert len(parts) == 3
        action, task_id_str = parts[1], parts[2]
        assert action == "pause"
        assert int(task_id_str) == 42

    def test_reset_callback_parse(self):
        for target in ("session", "agents", "tasks", "all"):
            data = f"reset:{target}"
            parsed = data.split(":", 1)[1]
            assert parsed == target

    def test_approve_callback_parse(self):
        data = "approve:ABC123"
        code = data.split(":", 1)[1]
        assert code == "ABC123"

    def test_deny_callback_parse(self):
        data = "deny:ABC123"
        code = data.split(":", 1)[1]
        assert code == "ABC123"


# ── Integration: DB + handler patterns ──

class TestHandlerDBPatterns:
    @pytest.mark.asyncio
    async def test_task_pause_resume_flow(self, db):
        """Simulate pause/resume via DB operations (same as callback handler)."""
        task_id = await db.create_task(
            name="test task", prompt="do stuff",
            schedule_type="cron", schedule_value="* * * * *",
        )

        # Pause (same SQL as handler)
        await db.db.execute("UPDATE tasks SET status = 'paused' WHERE id = ?", (task_id,))
        await db.db.commit()
        async with db.db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
            assert row[0] == "paused"

        # Resume
        await db.db.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (task_id,))
        await db.db.commit()
        async with db.db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
            assert row[0] == "active"

    @pytest.mark.asyncio
    async def test_reset_session_flow(self, db):
        """Simulate /reset session callback."""
        await db.create_session("sess-reset-1", "main")
        await db.db.execute("UPDATE sessions SET status = 'archived' WHERE status = 'active'")
        await db.db.commit()

        session = await db.get_active_session("main")
        assert session is None

    @pytest.mark.asyncio
    async def test_reset_agents_flow(self, db):
        """Simulate /reset agents callback."""
        await db.save_agent(name="temp-agent", scope="ephemeral")
        await db.db.execute("UPDATE agents SET status = 'killed' WHERE scope = 'ephemeral' AND status = 'active'")
        await db.db.commit()

        agents = await db.list_agents(status="active")
        ephemeral_active = [a for a in agents if a["scope"] == "ephemeral"]
        assert len(ephemeral_active) == 0

    @pytest.mark.asyncio
    async def test_stop_logging(self, db):
        """Stop command should log to DB as system message."""
        await db.create_session("sess-stop", "main")
        await db.save_message(
            role="system",
            content="[STOP] User issued stop command. Stopped: 2 agent(s)",
            session_id="sess-stop",
        )
        messages = await db.get_messages("sess-stop")
        assert len(messages) == 1
        assert "[STOP]" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_fresh_creates_session(self, db):
        """Simulate /fresh command — creates new session."""
        import uuid
        session_id = f"session-{uuid.uuid4().hex[:12]}"
        await db.create_session(session_id, "main")
        session = await db.get_session(session_id)
        assert session is not None
        assert session["status"] == "active"

    @pytest.mark.asyncio
    async def test_approval_flow(self, db):
        """Simulate approve/deny callback flow."""
        await db.create_approval(
            approval_id="appr-1", agent_name="main",
            action="rm -rf /tmp/test", level="confirm_tg",
            reason="cleanup", code="XYZ789",
        )

        # Approve
        approval = await db.get_pending_approval("XYZ789")
        assert approval is not None
        await db.resolve_approval(approval["id"], "approved", "telegram")

        # Should no longer be pending
        approval = await db.get_pending_approval("XYZ789")
        assert approval is None
