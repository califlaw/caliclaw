"""Lossless conversation handoff — verbatim replay of recent messages.

Used when we drop a Claude-side session (API error recovery, manual /squeeze,
or auto-compaction) so the next turn can pick up exactly where the old
session left off, without paying the cost of a 100-turn replay through
Claude Code's --resume.

The handoff text is stored in `sessions.summary`. The bot consumes it
exactly once on the next user message: it prepends the verbatim history to
the new prompt, then clears `summary`. From there a fresh Claude session
takes over with a clean, bounded context.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.db import Database


# Image filename pattern that has historically poisoned Claude sessions
# (large/transparent PNGs trigger a 400 on subsequent turns). We strip
# these from the handoff so the new session can't re-Read them.
_IMAGE_PATH_RE = re.compile(
    r"(/[\w/\-.]+)?photo_\d+_\w+\.(?:jpg|jpeg|png|webp|gif)",
    re.IGNORECASE,
)


async def build_lossless_handoff(
    db: "Database",
    session_id: str,
    max_messages: int = 50,
    char_budget: int = 40000,
) -> str:
    """Return a verbatim 'User: ...\\nAssistant: ...' replay of the most
    recent messages, fitting within the char budget. Newest-first walk to
    pick what fits, then chronological order in the returned string.
    """
    messages = await db.get_messages(session_id, limit=max_messages * 4)

    picked: list[str] = []
    used = 0
    for m in reversed(messages):
        content = (m.get("content") or "").strip()
        if not content:
            continue
        content = _IMAGE_PATH_RE.sub("[image previously shared]", content)
        role = "User" if m.get("role") == "user" else "Assistant"
        line = f"{role}: {content}"
        if picked and used + len(line) > char_budget:
            break
        picked.append(line)
        used += len(line)
        if len(picked) >= max_messages:
            break

    picked.reverse()
    return "\n\n".join(picked)
