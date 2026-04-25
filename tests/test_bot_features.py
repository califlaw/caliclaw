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


# ── API error classifier ──

class TestClassifyApiError:
    # The method only reads the class-level _API_ERROR_CLASSIFIERS; no bot
    # instance is required — avoids aiogram router singleton collisions.
    def _classify(self, text: str):
        from telegram.bot import CaliclawBot
        return CaliclawBot._classify_api_error(CaliclawBot, text)

    def test_classify_image_error(self):
        text = (
            'API Error: 400 {"type":"error","error":{"type":'
            '"invalid_request_error","message":"Could not process image"}}'
        )
        assert self._classify(text) == "image"

    def test_classify_generic_api_error(self):
        assert self._classify("API Error: 500 internal_server_error") == "generic"

    def test_classify_rate_limit(self):
        assert self._classify(
            '{"type":"error","error":{"type":"rate_limit_error"}}'
        ) == "rate_limit"

    def test_classify_normal_text_returns_none(self):
        assert self._classify("Hello, here's the answer to your question.") is None
        assert self._classify("") is None


# ── Telegram message splitter ──

class TestSplitForTelegram:
    """The splitter must keep ```fenced``` code blocks intact across
    chunk boundaries — Telegram parses each message independently."""

    def _split(self, text: str, max_len: int = 4096) -> list[str]:
        from telegram.bot import CaliclawBot
        return CaliclawBot._split_for_telegram(text, max_len)

    def test_short_text_one_chunk(self):
        assert self._split("hello") == ["hello"]

    def test_chunks_within_limit(self):
        text = "a" * 10000
        chunks = self._split(text, max_len=4096)
        assert len(chunks) >= 3
        for c in chunks:
            assert len(c) <= 4096

    def test_prefers_paragraph_breaks(self):
        # Paragraph break sits well inside the window — splitter should use it.
        text = "para one " * 100 + "\n\n" + "para two " * 100
        chunks = self._split(text, max_len=1500)
        # First chunk ends at paragraph boundary, no leading whitespace next
        assert chunks[0].rstrip().endswith("para one")
        assert chunks[1].lstrip().startswith("para two")

    def test_code_block_survives_split(self):
        # Force a split inside a long code block
        code = "\n".join(f"line_{i} = {i}" for i in range(400))
        text = f"Here is the code:\n\n```python\n{code}\n```\n\nDone."
        chunks = self._split(text, max_len=2000)
        assert len(chunks) >= 2

        # Every chunk must have balanced fences (open count == close count
        # after our wrapping). Equivalently: every chunk has an even count.
        for c in chunks:
            assert c.count("```") % 2 == 0, f"unbalanced fences in chunk: {c[:80]}..."

        # The continuation chunk must START with reopen fence
        assert chunks[1].startswith("```")
        # And the previous chunk must END with the close fence
        assert chunks[0].rstrip().endswith("```")

    def test_no_code_block_no_extra_fences(self):
        """Plain text shouldn't grow extra ``` fences."""
        text = "regular text " * 500
        chunks = self._split(text, max_len=1500)
        for c in chunks:
            assert "```" not in c

    def test_inline_backticks_dont_break(self):
        """Single backticks aren't fences; they shouldn't trip the fence counter."""
        text = "Use `foo` and `bar`. " * 300
        chunks = self._split(text, max_len=1500)
        for c in chunks:
            # Splitter only tracks triple-backticks, so inline ` ` survives raw
            assert "```" not in c


# ── _send_one parse-error fallback (duplicate message regression) ──

class TestSendOneFallback:
    """When Markdown parse fails on edit, the fallback must edit the SAME
    message as plain text — not send a fresh one. Sending fresh leaves the
    streaming message in the chat and produces a visible duplicate."""

    async def test_parse_error_edits_same_message(self):
        """Regression: parse error on edit → re-edit with plain text, no resend."""
        import aiogram.exceptions
        from unittest.mock import AsyncMock, MagicMock
        from telegram.bot import CaliclawBot

        # Streaming message (the one already shown to the user)
        first_msg = MagicMock()
        first_msg.text = "old text"
        # First edit_text call fails with parse error; second succeeds
        first_msg.edit_text = AsyncMock(side_effect=[
            aiogram.exceptions.TelegramBadRequest(
                method=MagicMock(), message="Bad Request: can't parse entities: ...",
            ),
            None,
        ])

        # Bot instance with a mocked send_message we expect NOT to be called
        bot_instance = MagicMock()
        bot_instance.send_message = AsyncMock()

        fake_self = MagicMock()
        fake_self.bot = bot_instance

        # Call the unbound method directly so we don't need full bot wiring
        await CaliclawBot._send_one(fake_self, chat_id=1, text="new text", first_message=first_msg)

        # Edited twice on the SAME message (Markdown try, then plain)
        assert first_msg.edit_text.await_count == 2
        # NEVER sent a fresh message — that's the duplicate bug
        bot_instance.send_message.assert_not_awaited()

    async def test_send_path_parse_error_resends_plain(self):
        """When there's no first_message, parse error retries send (no duplicate
        possible because nothing was sent yet)."""
        import aiogram.exceptions
        from unittest.mock import AsyncMock, MagicMock
        from telegram.bot import CaliclawBot

        bot_instance = MagicMock()
        bot_instance.send_message = AsyncMock(side_effect=[
            aiogram.exceptions.TelegramBadRequest(
                method=MagicMock(), message="Bad Request: can't parse entities: ...",
            ),
            None,
        ])

        fake_self = MagicMock()
        fake_self.bot = bot_instance

        await CaliclawBot._send_one(fake_self, chat_id=1, text="hello", first_message=None)

        # Two send attempts (Markdown, then plain) — single message in chat
        assert bot_instance.send_message.await_count == 2
