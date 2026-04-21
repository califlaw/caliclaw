"""Obsidian vault integration.

caliclaw treats the user's Obsidian vault as an external knowledge base
it can read from (search existing notes) and write to (research results,
daily notes, artifacts). This is separate from `memory/`, which is the
agent's own internal notes.

Configuration:
    OBSIDIAN_VAULT_PATH       — absolute path to vault root (required)
    OBSIDIAN_DAILY_NOTES_DIR  — subdir for daily notes (default: "Daily")
    OBSIDIAN_INBOX_DIR        — subdir where the bot writes new notes
                                (default: "Inbox/caliclaw")

All functions silently no-op (return None / []) when no vault is set so
downstream code doesn't need null-checks everywhere.
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from core.config import get_settings

logger = logging.getLogger(__name__)


def vault_path() -> Optional[Path]:
    """Return the configured vault root, or None if not configured / missing."""
    p = get_settings().obsidian_vault_path
    if not p:
        return None
    p = Path(p).expanduser()
    if not p.exists() or not p.is_dir():
        logger.warning("Obsidian vault path set but not a directory: %s", p)
        return None
    return p


def is_configured() -> bool:
    return vault_path() is not None


def daily_note_path(date: Optional[datetime] = None) -> Optional[Path]:
    """Path to today's (or a given date's) daily note. Creates parent dir."""
    vault = vault_path()
    if vault is None:
        return None
    settings = get_settings()
    date = date or datetime.now()
    daily_dir = vault / settings.obsidian_daily_notes_dir
    daily_dir.mkdir(parents=True, exist_ok=True)
    return daily_dir / f"{date.strftime('%Y-%m-%d')}.md"


_SAFE_NAME = re.compile(r"[^\w\s\-.,()']+", re.UNICODE)


def _sanitize_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "note"


def write_note(
    title: str,
    body: str,
    tags: Optional[Iterable[str]] = None,
    subdir: Optional[str] = None,
    links: Optional[Iterable[str]] = None,
) -> Optional[Path]:
    """Create a new markdown note in the vault's inbox (or a given subdir).

    Front-matter is Obsidian-compatible. `links` are appended as a
    `## Related` section of [[wikilinks]] so Obsidian's graph sees them.

    Returns the written path, or None if vault not configured.
    """
    vault = vault_path()
    if vault is None:
        return None

    settings = get_settings()
    target_dir = vault / (subdir or settings.obsidian_inbox_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = _sanitize_filename(title) + ".md"
    path = target_dir / filename

    tag_list = list(dict.fromkeys(["caliclaw", *(tags or [])]))
    tags_yaml = "[" + ", ".join(tag_list) + "]"

    frontmatter = (
        "---\n"
        f"source: caliclaw\n"
        f"created: {datetime.now().isoformat(timespec='seconds')}\n"
        f"tags: {tags_yaml}\n"
        "---\n"
    )
    parts = [frontmatter, f"# {title}\n", body.rstrip() + "\n"]
    if links:
        parts.append("\n## Related\n")
        for link in links:
            parts.append(f"- [[{link}]]\n")

    path.write_text("".join(parts), encoding="utf-8")
    logger.info("Wrote Obsidian note: %s", path)
    return path


def append_to_daily(section: str, body: str) -> Optional[Path]:
    """Append a dated section to today's daily note. Creates if missing."""
    path = daily_note_path()
    if path is None:
        return None

    header = f"\n## {datetime.now().strftime('%H:%M')} — {section}\n"
    chunk = f"{header}\n{body.rstrip()}\n"
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + chunk, encoding="utf-8")
    else:
        path.write_text(
            f"# {datetime.now().strftime('%Y-%m-%d')}\n{chunk}", encoding="utf-8",
        )
    return path


def search(query: str, max_hits: int = 20) -> List[dict]:
    """Ripgrep over the vault. Returns list of {path, line_no, preview} dicts.

    Falls back to empty list if vault not set or rg not available.
    """
    vault = vault_path()
    if vault is None:
        return []
    try:
        proc = subprocess.run(
            ["rg", "--no-heading", "--line-number", "--max-count", "1",
             "--glob", "*.md", "-e", query, str(vault)],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("Obsidian search fallback: %s", e)
        return []

    hits: List[dict] = []
    for line in proc.stdout.splitlines()[:max_hits]:
        # rg output: <path>:<line>:<content>
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if not m:
            continue
        path, line_no, preview = m.groups()
        rel = Path(path).relative_to(vault) if Path(path).is_absolute() else Path(path)
        hits.append({
            "path": str(rel),
            "line_no": int(line_no),
            "preview": preview.strip()[:300],
        })
    return hits


def list_recent(limit: int = 20) -> List[Path]:
    """Return paths of the most-recently-modified notes in the vault."""
    vault = vault_path()
    if vault is None:
        return []
    try:
        files = sorted(
            vault.rglob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    return files[:limit]
