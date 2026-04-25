"""Tests for `caliclaw llm` CLI command and AgentProcess env injection."""
from __future__ import annotations

import pytest


# ── _upsert_env / _get_env ────────────────────────────────────────────


def test_upsert_env_appends_when_missing(tmp_path):
    from cli.commands.llm import _upsert_env, _get_env

    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=abc\n")
    _upsert_env(tmp_path, "ANTHROPIC_BASE_URL", "https://openrouter.ai/api/v1")

    assert _get_env(tmp_path, "ANTHROPIC_BASE_URL") == "https://openrouter.ai/api/v1"
    assert "TELEGRAM_BOT_TOKEN=abc" in (tmp_path / ".env").read_text()


def test_upsert_env_replaces_existing(tmp_path):
    from cli.commands.llm import _upsert_env, _get_env

    (tmp_path / ".env").write_text(
        "ANTHROPIC_BASE_URL=https://old.example.com\n"
        "TELEGRAM_BOT_TOKEN=abc\n"
    )
    _upsert_env(tmp_path, "ANTHROPIC_BASE_URL", "https://new.example.com")

    content = (tmp_path / ".env").read_text()
    assert "https://old.example.com" not in content
    assert _get_env(tmp_path, "ANTHROPIC_BASE_URL") == "https://new.example.com"
    assert "TELEGRAM_BOT_TOKEN=abc" in content


def test_upsert_env_removes_when_value_none(tmp_path):
    """Passing None deletes the key — used by `caliclaw llm anthropic` reset."""
    from cli.commands.llm import _upsert_env, _get_env

    (tmp_path / ".env").write_text(
        "ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1\n"
        "ANTHROPIC_AUTH_TOKEN=sk-or-secret\n"
        "TELEGRAM_BOT_TOKEN=abc\n"
    )
    _upsert_env(tmp_path, "ANTHROPIC_BASE_URL", None)
    _upsert_env(tmp_path, "ANTHROPIC_AUTH_TOKEN", None)

    content = (tmp_path / ".env").read_text()
    assert "ANTHROPIC_BASE_URL" not in content
    assert "ANTHROPIC_AUTH_TOKEN" not in content
    assert "TELEGRAM_BOT_TOKEN=abc" in content
    assert _get_env(tmp_path, "ANTHROPIC_BASE_URL") == ""


def test_get_env_no_file(tmp_path):
    from cli.commands.llm import _get_env
    assert _get_env(tmp_path, "ANTHROPIC_BASE_URL") == ""


# ── _apply_anthropic ──────────────────────────────────────────────────


def test_apply_anthropic_clears_both_keys(tmp_path, monkeypatch):
    from cli.commands.llm import _apply_anthropic

    (tmp_path / ".env").write_text(
        "ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1\n"
        "ANTHROPIC_AUTH_TOKEN=sk-or-xxx\n"
        "TELEGRAM_BOT_TOKEN=abc\n"
    )
    _apply_anthropic(tmp_path)

    content = (tmp_path / ".env").read_text()
    assert "ANTHROPIC_BASE_URL" not in content
    assert "ANTHROPIC_AUTH_TOKEN" not in content
    assert "TELEGRAM_BOT_TOKEN=abc" in content


# ── AgentProcess._build_env ──────────────────────────────────────────


def test_build_env_no_override(settings, monkeypatch):
    """Without provider config, env passes through unchanged."""
    from core.agent import AgentProcess, AgentConfig

    # Ensure no inherited env from the host
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    proc = AgentProcess(AgentConfig(name="t"), settings=settings)
    env = proc._build_env()

    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_build_env_overlays_settings(settings, monkeypatch):
    """When settings carry a base URL / token, they land in subprocess env."""
    from core.agent import AgentProcess, AgentConfig

    settings.anthropic_base_url = "https://openrouter.ai/api/v1"
    settings.anthropic_auth_token = "sk-or-test"

    proc = AgentProcess(AgentConfig(name="t"), settings=settings)
    env = proc._build_env()

    assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"


def test_build_env_inherits_parent(settings, monkeypatch):
    """Parent env (PATH, HOME, etc.) is inherited so claude CLI keeps working."""
    from core.agent import AgentProcess, AgentConfig

    monkeypatch.setenv("CALICLAW_CANARY_TEST", "yes")

    proc = AgentProcess(AgentConfig(name="t"), settings=settings)
    env = proc._build_env()

    assert env.get("CALICLAW_CANARY_TEST") == "yes"
    assert "PATH" in env
