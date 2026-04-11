from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import shutil

import pytest
import pytest_asyncio

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Override settings for tests
os.environ["TELEGRAM_BOT_TOKEN"] = "test-token-123"
os.environ["LOG_LEVEL"] = "DEBUG"


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_claude: test needs claude CLI")


def pytest_collection_modifyitems(config, items):
    if not shutil.which("claude"):
        skip = pytest.mark.skip(reason="claude CLI not found")
        for item in items:
            if "requires_claude" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest_asyncio.fixture
async def db(tmp_path):
    from core.db import Database
    db = Database(db_path=tmp_path / "test.db")
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    from core.config import reset_settings, Settings

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("AGENTS_DIR", str(tmp_path / "agents"))
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    # Force known defaults so tests don't read values from the host's real .env
    monkeypatch.setenv("CLAUDE_DEFAULT_MODEL", "sonnet")

    reset_settings()
    from core.config import get_settings
    s = get_settings()
    s.ensure_dirs()
    yield s
    reset_settings()
