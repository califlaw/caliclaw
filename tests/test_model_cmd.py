"""Tests for `caliclaw model` CLI command."""
from __future__ import annotations

import argparse

import pytest


def test_write_model_to_env_appends_when_missing(settings):
    """_write_model_to_env appends CLAUDE_DEFAULT_MODEL when not present."""
    from cli.commands.model import _write_model_to_env

    env_file = settings.project_root / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=abc\nTZ=UTC\n")

    _write_model_to_env(settings.project_root, "opus")

    content = env_file.read_text()
    assert "CLAUDE_DEFAULT_MODEL=opus" in content
    assert "TELEGRAM_BOT_TOKEN=abc" in content
    assert "TZ=UTC" in content


def test_write_model_to_env_replaces_existing(settings):
    """_write_model_to_env replaces existing CLAUDE_DEFAULT_MODEL line."""
    from cli.commands.model import _write_model_to_env

    env_file = settings.project_root / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=abc\nCLAUDE_DEFAULT_MODEL=sonnet\nTZ=UTC\n")

    _write_model_to_env(settings.project_root, "haiku")

    content = env_file.read_text()
    assert "CLAUDE_DEFAULT_MODEL=haiku" in content
    assert "CLAUDE_DEFAULT_MODEL=sonnet" not in content
    # Other lines untouched
    assert "TELEGRAM_BOT_TOKEN=abc" in content
    assert "TZ=UTC" in content
    # Exactly one model line
    lines = [l for l in content.splitlines() if l.startswith("CLAUDE_DEFAULT_MODEL=")]
    assert len(lines) == 1


def test_write_model_creates_env_if_missing(settings):
    """_write_model_to_env creates .env if it doesn't exist."""
    from cli.commands.model import _write_model_to_env

    env_file = settings.project_root / ".env"
    env_file.unlink(missing_ok=True)

    _write_model_to_env(settings.project_root, "sonnet")

    assert env_file.exists()
    assert "CLAUDE_DEFAULT_MODEL=sonnet" in env_file.read_text()


def test_is_bot_running_no_pidfile(settings):
    """_is_bot_running returns (False, None) when pidfile missing."""
    from cli.commands.model import _is_bot_running

    alive, pid = _is_bot_running(settings.project_root)
    assert alive is False
    assert pid is None


def test_is_bot_running_dead_pid(settings):
    """_is_bot_running returns (False, pid) when process doesn't exist."""
    from cli.commands.model import _is_bot_running

    pid_file = settings.project_root / "data" / "caliclaw.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("999999")  # very unlikely to exist

    alive, pid = _is_bot_running(settings.project_root)
    assert alive is False


@pytest.mark.asyncio
async def test_cmd_model_show_default(settings, capsys):
    """cmd_model with no args prints current default."""
    from cli.commands.model import cmd_model

    args = argparse.Namespace(model_action="", model_value="")
    await cmd_model(args)

    captured = capsys.readouterr()
    assert "sonnet" in captured.out.lower()
    assert "available" in captured.out.lower()


@pytest.mark.asyncio
async def test_cmd_model_set_invalid_exits(settings, capsys):
    """cmd_model set <invalid> exits non-zero and leaves .env untouched."""
    from cli.commands.model import cmd_model

    env_file = settings.project_root / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=abc\n")
    before = env_file.read_text()

    args = argparse.Namespace(model_action="set", model_value="gpt4")
    with pytest.raises(SystemExit) as exc:
        await cmd_model(args)
    assert exc.value.code == 1

    # .env unchanged
    assert env_file.read_text() == before


@pytest.mark.asyncio
async def test_cmd_model_set_valid_updates_env(settings, monkeypatch, capsys):
    """cmd_model set opus writes CLAUDE_DEFAULT_MODEL=opus to .env."""
    from cli.commands.model import cmd_model

    env_file = settings.project_root / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=abc\n")

    # Bot not running — no restart prompt
    args = argparse.Namespace(model_action="set", model_value="opus")
    await cmd_model(args)

    content = env_file.read_text()
    assert "CLAUDE_DEFAULT_MODEL=opus" in content
