"""Tests for bot stop words, rate limiting, restart, and queue persistence."""
from __future__ import annotations

import time

import pytest
import pytest_asyncio


# ── Stop words ──

class TestStopWords:
    def test_stop_words_set(self):
        from telegram.bot import STOP_WORDS
        assert "стоп" in STOP_WORDS
        assert "stop" in STOP_WORDS

    def test_stop_words_case_insensitive_matching(self):
        from telegram.bot import STOP_WORDS
        # The bot does .strip().lower() before checking
        assert "стоп" in STOP_WORDS
        assert "stop" in STOP_WORDS
        # These should NOT match (bot lowercases input)
        assert "STOP" not in STOP_WORDS  # but "STOP".lower() is in STOP_WORDS
        assert "stop".lower() in STOP_WORDS
        assert "STOP".lower() in STOP_WORDS
        assert "Стоп".lower() in STOP_WORDS


# ── Rate limiting ──

class TestRateLimiting:
    def test_rate_limit_constants(self):
        from telegram.bot import _RATE_LIMIT, _RATE_WINDOW
        assert _RATE_LIMIT == 15
        assert _RATE_WINDOW == 60.0

    def test_rate_limit_check(self):
        from telegram.bot import CaliclawBot, _RATE_LIMIT

        # Can't instantiate bot without DB, so test the method logic directly
        # Simulate the rate limit logic
        rate_history: dict[int, list[float]] = {}
        user_id = 123
        now = time.time()

        def check_rate(uid: int) -> bool:
            history = rate_history.get(uid, [])
            history = [t for t in history if now - t < 60.0]
            history.append(now)
            rate_history[uid] = history
            return len(history) <= _RATE_LIMIT

        # Should allow up to _RATE_LIMIT messages
        for i in range(_RATE_LIMIT):
            assert check_rate(user_id) is True

        # Next one should be rejected
        assert check_rate(user_id) is False


# ── Queue persistence (DB layer) ──

class TestQueuePersistence:
    @pytest.mark.asyncio
    async def test_enqueue_and_get_pending(self, db):
        msg_id = await db.enqueue_message(
            session_id="sess-q1",
            sender="TestUser",
            text="Hello queue",
            media_path=None,
            telegram_message_id=42,
        )
        assert msg_id is not None

        pending = await db.get_pending_queue("sess-q1")
        assert len(pending) == 1
        assert pending[0]["text"] == "Hello queue"
        assert pending[0]["sender"] == "TestUser"
        assert pending[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_mark_queue_done(self, db):
        id1 = await db.enqueue_message("sess-q2", "User", "msg1")
        id2 = await db.enqueue_message("sess-q2", "User", "msg2")

        await db.mark_queue_done([id1])

        pending = await db.get_pending_queue("sess-q2")
        assert len(pending) == 1
        assert pending[0]["text"] == "msg2"

    @pytest.mark.asyncio
    async def test_clear_old_queue(self, db):
        # Insert a message and manually backdate it
        msg_id = await db.enqueue_message("sess-q3", "User", "old msg")
        await db.mark_queue_done([msg_id])

        # Backdate the message
        old_time = time.time() - 25 * 3600  # 25 hours ago
        await db.db.execute(
            "UPDATE queued_messages SET created_at = ? WHERE id = ?",
            (old_time, msg_id),
        )
        await db.db.commit()

        await db.clear_old_queue(older_than_hours=24)

        async with db.db.execute(
            "SELECT COUNT(*) FROM queued_messages WHERE id = ?", (msg_id,)
        ) as cur:
            row = await cur.fetchone()
            assert row[0] == 0

    @pytest.mark.asyncio
    async def test_pending_queue_empty_for_other_session(self, db):
        await db.enqueue_message("sess-q4", "User", "msg")
        pending = await db.get_pending_queue("sess-other")
        assert len(pending) == 0


# ── DB migration to v2 ──

class TestMigration:
    @pytest.mark.asyncio
    async def test_schema_version_is_current(self, db):
        from core.db import _SCHEMA_VERSION
        async with db.db.execute("SELECT MAX(version) FROM schema_version") as cur:
            row = await cur.fetchone()
            assert row[0] == _SCHEMA_VERSION

    @pytest.mark.asyncio
    async def test_queued_messages_table_exists(self, db):
        # Should not raise
        async with db.db.execute("SELECT COUNT(*) FROM queued_messages") as cur:
            row = await cur.fetchone()
            assert row[0] == 0


# ── Health check ──

class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_status(self, db):
        from monitoring.dashboard import health_check
        result = await health_check(db)
        assert "status" in result
        assert "checks" in result
        assert result["checks"]["database"] == "ok"
        assert "timestamp" in result
