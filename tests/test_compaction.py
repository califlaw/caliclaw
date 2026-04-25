"""Tests for /squeeze compaction.

The key invariant: after compaction, `claude_session_id` is None and
`summary` holds a verbatim replay of recent messages so the bot's
existing handoff path picks it up on the next turn.
"""
from __future__ import annotations

import pytest


# ── core.handoff ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lossless_handoff_chronological(db):
    from core.handoff import build_lossless_handoff

    await db.create_session("s1", "main")
    await db.save_message(role="user", content="first user msg", session_id="s1")
    await db.save_message(role="assistant", content="first reply", session_id="s1")
    await db.save_message(role="user", content="second user msg", session_id="s1")
    await db.save_message(role="assistant", content="second reply", session_id="s1")

    handoff = await build_lossless_handoff(db, "s1")
    # Chronological order
    assert handoff.index("first user msg") < handoff.index("first reply")
    assert handoff.index("first reply") < handoff.index("second user msg")
    assert handoff.index("second user msg") < handoff.index("second reply")
    assert "User: first user msg" in handoff
    assert "Assistant: second reply" in handoff


@pytest.mark.asyncio
async def test_lossless_handoff_strips_image_paths(db):
    from core.handoff import build_lossless_handoff

    await db.create_session("s1", "main")
    await db.save_message(
        role="user",
        content="check /workspace/media/photo_123_abc.jpg please",
        session_id="s1",
    )

    handoff = await build_lossless_handoff(db, "s1")
    assert "photo_123_abc.jpg" not in handoff
    assert "[image previously shared]" in handoff


@pytest.mark.asyncio
async def test_lossless_handoff_respects_char_budget(db):
    from core.handoff import build_lossless_handoff

    await db.create_session("s1", "main")
    # 10 messages of ~200 chars each = 2KB total
    for i in range(10):
        await db.save_message(
            role="user", content=f"msg{i} " + "x" * 200, session_id="s1",
        )

    handoff = await build_lossless_handoff(db, "s1", char_budget=500)
    # Budget enforced, so handoff is small but contains the *most recent* msgs
    assert len(handoff) < 1500
    # Newest messages preserved (msg9 is the last one written)
    assert "msg9" in handoff


@pytest.mark.asyncio
async def test_lossless_handoff_empty_session(db):
    from core.handoff import build_lossless_handoff

    await db.create_session("s1", "main")
    handoff = await build_lossless_handoff(db, "s1")
    assert handoff == ""


# ── ConversationCompactor.check_and_compact ──────────────────────────


@pytest.mark.asyncio
async def test_compactor_force_runs_below_threshold(db, settings):
    """force=True must compact even with just a few messages.

    Without force, the threshold (100 msgs) skips small sessions —
    that path stays for auto-compact, but `/squeeze` always honors intent.
    """
    from intelligence.compaction import ConversationCompactor

    await db.create_session("s1", "main")
    await db.update_session("s1", claude_session_id="claude-abc")
    for i in range(5):
        await db.save_message(role="user", content=f"hello {i}", session_id="s1")

    compactor = ConversationCompactor(db)
    ran = await compactor.check_and_compact("s1", force=True)
    assert ran is True

    session = await db.get_session("s1")
    # Claude-side session was dropped — bloat goes with it
    assert session["claude_session_id"] is None
    # Verbatim handoff staged in summary for next-turn injection
    assert session["summary"]
    assert "hello 0" in session["summary"]
    assert "hello 4" in session["summary"]
    assert session["status"] == "compacted"


@pytest.mark.asyncio
async def test_compactor_skips_below_threshold_without_force(db, settings):
    from intelligence.compaction import ConversationCompactor

    await db.create_session("s1", "main")
    await db.update_session("s1", claude_session_id="claude-abc")
    for i in range(5):
        await db.save_message(role="user", content=f"hi {i}", session_id="s1")

    compactor = ConversationCompactor(db)
    ran = await compactor.check_and_compact("s1", force=False)
    assert ran is False

    # Untouched
    session = await db.get_session("s1")
    assert session["claude_session_id"] == "claude-abc"
    assert not session["summary"]


@pytest.mark.asyncio
async def test_compactor_archives_to_disk(db, settings):
    from intelligence.compaction import ConversationCompactor

    await db.create_session("s1", "main")
    await db.save_message(role="user", content="archive me", session_id="s1")

    compactor = ConversationCompactor(db)
    await compactor.check_and_compact("s1", force=True)

    archives = list((settings.workspace_dir / "conversations").glob("*.md"))
    assert any("archive me" in a.read_text() for a in archives)
