"""Tests for backup/restore system."""
from __future__ import annotations

import tarfile
from pathlib import Path

import pytest


def test_create_backup(settings):
    """Backup should create a tar.gz with project files."""
    # Create some test data
    (settings.data_dir / "caliclaw.db").write_bytes(b"fake db data")
    (settings.memory_dir / "test.md").write_text("test memory")
    (settings.agents_dir / "global" / "main").mkdir(parents=True, exist_ok=True)
    (settings.agents_dir / "global" / "main" / "SOUL.md").write_text("test soul")
    (settings.project_root / ".env").write_text("TELEGRAM_BOT_TOKEN=test")

    from core.backup import create_backup
    backup_path = create_backup()

    assert backup_path.exists()
    assert backup_path.name.startswith("caliclaw-")
    assert backup_path.suffix == ".gz"

    # Verify contents
    with tarfile.open(backup_path, "r:gz") as tar:
        names = tar.getnames()
        assert any("caliclaw.db" in n for n in names)
        assert any("test.md" in n for n in names)
        assert any("SOUL.md" in n for n in names)
        assert ".env" in names


def test_list_backups(settings):
    """list_backups should return backups sorted newest first."""
    from core.backup import create_backup, list_backups
    import time

    (settings.data_dir / "caliclaw.db").write_bytes(b"data")

    b1 = create_backup()
    time.sleep(1.1)  # Ensure different mtime
    b2 = create_backup()

    backups = list_backups()
    assert len(backups) == 2
    assert backups[0] == b2  # newest first
    assert backups[1] == b1


def test_latest_backup(settings):
    """latest_backup returns the most recent."""
    from core.backup import create_backup, latest_backup
    (settings.data_dir / "caliclaw.db").write_bytes(b"data")

    assert latest_backup() is None  # no backups yet

    b1 = create_backup()
    assert latest_backup() == b1


def test_restore_backup(settings):
    """restore_backup should restore files and create safety backup."""
    from core.backup import create_backup, restore_backup, list_backups

    # Create initial state
    (settings.memory_dir / "test.md").write_text("original")
    (settings.data_dir / "caliclaw.db").write_bytes(b"original db")

    # Backup it
    backup = create_backup(label="test")

    # Modify state
    (settings.memory_dir / "test.md").write_text("modified")

    # Restore
    restore_backup(backup)

    # Verify restored
    assert (settings.memory_dir / "test.md").read_text() == "original"

    # Safety backup should have been created (pre-restore)
    backups = list_backups()
    assert any("pre-restore" in b.name for b in backups)


def test_split_and_join(tmp_path):
    """split_file → join_chunks roundtrip."""
    from core.backup import split_file, join_chunks

    # Create 100KB file
    src = tmp_path / "data.bin"
    src.write_bytes(b"X" * 100_000)

    # Split into 30KB chunks
    chunks = split_file(src, chunk_size=30_000)
    assert len(chunks) == 4  # 30+30+30+10

    # Join back
    joined = tmp_path / "joined.bin"
    join_chunks(chunks, joined)

    assert joined.read_bytes() == src.read_bytes()


def test_cleanup_old_backups(settings):
    """Old backups beyond keep limit should be deleted."""
    from core.backup import create_backup, cleanup_old_backups, list_backups
    import time

    (settings.data_dir / "caliclaw.db").write_bytes(b"data")

    # Create 5 backups
    for i in range(5):
        create_backup(label=f"test{i}")
        time.sleep(0.05)

    assert len(list_backups()) == 5

    # Keep only 3
    deleted = cleanup_old_backups(keep=3)
    assert deleted == 2
    assert len(list_backups()) == 3
