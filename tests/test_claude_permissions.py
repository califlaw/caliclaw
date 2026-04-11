"""Tests for Claude permission management via skill side-effects."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Use a temporary settings.json instead of real ~/.claude/settings.json."""
    fake_settings = tmp_path / "settings.json"
    monkeypatch.setattr("security.claude_permissions._SETTINGS_PATH", fake_settings)
    return fake_settings


def test_parse_skill_permissions_inline(tmp_path):
    """Inline list format: requires_permissions: [a, b]"""
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: test\nrequires_permissions: [WebSearch, WebFetch]\n---\n\nbody")

    from security.claude_permissions import parse_skill_permissions
    perms = parse_skill_permissions(skill)
    assert perms == ["WebSearch", "WebFetch"]


def test_parse_skill_permissions_yaml_list(tmp_path):
    """YAML list format with hyphen-prefixed items."""
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\n"
        "name: test\n"
        "requires_permissions:\n"
        "  - WebSearch\n"
        "  - WebFetch\n"
        "---\n\nbody"
    )

    from security.claude_permissions import parse_skill_permissions
    perms = parse_skill_permissions(skill)
    assert perms == ["WebSearch", "WebFetch"]


def test_parse_skill_no_permissions(tmp_path):
    """Skill without requires_permissions returns empty."""
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: test\ndescription: hello\n---\n\nbody")

    from security.claude_permissions import parse_skill_permissions
    perms = parse_skill_permissions(skill)
    assert perms == []


def test_parse_skill_no_frontmatter(tmp_path):
    """Skill file without frontmatter returns empty."""
    skill = tmp_path / "SKILL.md"
    skill.write_text("just plain content")

    from security.claude_permissions import parse_skill_permissions
    perms = parse_skill_permissions(skill)
    assert perms == []


def test_grant_tools(settings_file):
    """grant_tools adds to allow list."""
    from security.claude_permissions import grant_tools, get_allowed_tools

    grant_tools(["WebSearch", "WebFetch"])
    assert get_allowed_tools() == {"WebSearch", "WebFetch"}

    # Verify file content
    data = json.loads(settings_file.read_text())
    assert data["permissions"]["allow"] == ["WebFetch", "WebSearch"]


def test_grant_tools_idempotent(settings_file):
    """Granting same tool twice doesn't duplicate."""
    from security.claude_permissions import grant_tools, get_allowed_tools

    grant_tools(["WebSearch"])
    grant_tools(["WebSearch"])
    assert get_allowed_tools() == {"WebSearch"}


def test_revoke_tools(settings_file):
    """revoke_tools removes from allow list."""
    from security.claude_permissions import grant_tools, revoke_tools, get_allowed_tools

    grant_tools(["WebSearch", "WebFetch", "Bash"])
    revoke_tools(["WebSearch", "WebFetch"])
    assert get_allowed_tools() == {"Bash"}


def test_revoke_nonexistent(settings_file):
    """Revoking a tool that's not granted is a no-op."""
    from security.claude_permissions import revoke_tools, get_allowed_tools

    revoke_tools(["WebSearch"])
    assert get_allowed_tools() == set()


def test_grant_preserves_other_settings(settings_file):
    """Granting doesn't wipe unrelated settings keys."""
    settings_file.write_text(json.dumps({
        "voiceEnabled": True,
        "voice": {"enabled": True},
    }))

    from security.claude_permissions import grant_tools

    grant_tools(["WebSearch"])

    data = json.loads(settings_file.read_text())
    assert data["voiceEnabled"] is True
    assert data["voice"] == {"enabled": True}
    assert data["permissions"]["allow"] == ["WebSearch"]


def test_web_access_skill_exists():
    """The bundled web-access skill should exist with correct permissions."""
    from pathlib import Path
    skill_path = Path(__file__).parent.parent / "skills" / "web-access" / "SKILL.md"
    assert skill_path.exists()

    from security.claude_permissions import parse_skill_permissions
    perms = parse_skill_permissions(skill_path)
    assert "WebSearch" in perms
    assert "WebFetch" in perms
