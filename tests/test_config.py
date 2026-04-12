from __future__ import annotations

import pytest
from pathlib import Path

from core.config import Settings, get_settings, reset_settings


def test_defaults():
    reset_settings()
    # _env_file=None disables reading the project's real .env so we test
    # the actual code defaults, not whatever the host machine has configured.
    s = Settings(_env_file=None, telegram_bot_token="test")
    assert s.max_concurrent_agents == 3
    assert s.usage_pause_percent == 80
    assert s.claude_default_model == "sonnet"


def test_ensure_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("AGENTS_DIR", str(tmp_path / "agents"))
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")

    reset_settings()
    s = get_settings()
    s.ensure_dirs()

    assert (tmp_path / "data").exists()
    assert (tmp_path / "workspace" / "conversations").exists()
    assert (tmp_path / "workspace" / "media").exists()
    assert (tmp_path / "workspace" / "ipc").exists()
    reset_settings()


def test_custom_settings(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_AGENTS", "5")
    monkeypatch.setenv("CLAUDE_DEFAULT_MODEL", "opus")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "custom-token")

    reset_settings()
    s = get_settings()
    assert s.max_concurrent_agents == 5
    assert s.claude_default_model == "opus"
    assert s.telegram_bot_token == "custom-token"
    reset_settings()
