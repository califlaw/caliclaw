"""Backup and restore — caliclaw stash & comeback."""
from __future__ import annotations

import logging
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.config import get_settings

logger = logging.getLogger(__name__)


# Files/dirs to include in backup
_BACKUP_TARGETS = [
    "data",      # SQLite DB + pairing code
    "memory",    # User memory
    "agents",    # Soul files
    "skills",    # Skill definitions
    ".env",      # Config (token + settings)
]

# Optional vault (separate path, may be in ~/.caliclaw)
_BACKUP_OPTIONAL = ["vault"]


def create_backup(label: Optional[str] = None) -> Path:
    """Create a tar.gz backup of caliclaw state.

    Returns path to the backup file.
    """
    settings = get_settings()
    backup_dir = settings.project_root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    backup_path = backup_dir / f"caliclaw-{timestamp}{suffix}.tar.gz"

    with tarfile.open(backup_path, "w:gz") as tar:
        for target in _BACKUP_TARGETS:
            src = settings.project_root / target
            if src.exists():
                tar.add(src, arcname=target)
        for target in _BACKUP_OPTIONAL:
            src = settings.project_root / target
            if src.exists():
                tar.add(src, arcname=target)

    logger.info("Backup created: %s (%d bytes)", backup_path, backup_path.stat().st_size)
    return backup_path


def list_backups() -> List[Path]:
    """List all backups sorted newest first."""
    settings = get_settings()
    backup_dir = settings.project_root / "backups"
    if not backup_dir.exists():
        return []
    backups = sorted(
        backup_dir.glob("caliclaw-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return backups


def latest_backup() -> Optional[Path]:
    """Get path to most recent backup."""
    backups = list_backups()
    return backups[0] if backups else None


def restore_backup(backup_path: Path) -> None:
    """Restore caliclaw state from a backup file.

    Overwrites current data/memory/agents/skills/.env.
    Creates a safety backup of current state first.
    """
    settings = get_settings()

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    # Safety: backup current state before overwriting
    safety = create_backup(label="pre-restore")
    logger.info("Safety backup: %s", safety)

    # Extract
    with tarfile.open(backup_path, "r:gz") as tar:
        tar.extractall(settings.project_root)

    logger.info("Restored from %s", backup_path)


def split_file(path: Path, chunk_size: int = 45 * 1024 * 1024) -> List[Path]:
    """Split a file into chunks of chunk_size bytes.

    Used for sending large backups via Telegram (50MB limit).
    Returns list of chunk paths.
    """
    chunks = []
    with open(path, "rb") as src:
        index = 0
        while True:
            data = src.read(chunk_size)
            if not data:
                break
            chunk_path = path.with_suffix(f"{path.suffix}.part{index:03d}")
            chunk_path.write_bytes(data)
            chunks.append(chunk_path)
            index += 1
    return chunks


def join_chunks(chunks: List[Path], output: Path) -> Path:
    """Join chunked files back into a single file."""
    with open(output, "wb") as dst:
        for chunk in sorted(chunks):
            dst.write(chunk.read_bytes())
    return output


def cleanup_old_backups(keep: int = 5) -> int:
    """Delete old backups, keeping only the most recent N. Returns count deleted."""
    backups = list_backups()
    if len(backups) <= keep:
        return 0
    to_delete = backups[keep:]
    for b in to_delete:
        b.unlink()
    return len(to_delete)


def is_backup_due(interval_days: int) -> bool:
    """Check if enough time has passed since last backup."""
    latest = latest_backup()
    if not latest:
        return True
    age_days = (time.time() - latest.stat().st_mtime) / 86400
    return age_days >= interval_days


async def send_backup_to_telegram(bot, chat_id: int, backup_path: Path) -> None:
    """Send backup file(s) to Telegram, splitting if >50MB.

    Args:
        bot: aiogram Bot instance
        chat_id: target chat
        backup_path: backup file to send
    """
    from aiogram.types import FSInputFile

    size_bytes = backup_path.stat().st_size
    size_mb = size_bytes / 1024 / 1024
    TELEGRAM_LIMIT = 50 * 1024 * 1024  # 50MB

    if size_bytes <= TELEGRAM_LIMIT:
        # Single file
        await bot.send_document(
            chat_id,
            FSInputFile(backup_path),
            caption=f"📦 Backup: {backup_path.name} ({size_mb:.1f}MB)",
        )
        logger.info("Backup sent to Telegram: %s", backup_path.name)
        return

    # Split into chunks (45MB each — safety margin)
    chunks = split_file(backup_path, chunk_size=45 * 1024 * 1024)
    try:
        await bot.send_message(
            chat_id,
            f"📦 Backup too large ({size_mb:.1f}MB), sending in {len(chunks)} parts.\n\n"
            f"To restore manually:\n"
            f"`cat {backup_path.name}.part* > {backup_path.name}`\n"
            f"`caliclaw comeback {backup_path.name}`",
            parse_mode="Markdown",
        )
        for i, chunk in enumerate(chunks, 1):
            await bot.send_document(
                chat_id,
                FSInputFile(chunk),
                caption=f"Part {i}/{len(chunks)}",
            )
        logger.info("Backup sent in %d chunks: %s", len(chunks), backup_path.name)
    finally:
        # Cleanup temp chunk files
        for chunk in chunks:
            chunk.unlink(missing_ok=True)
