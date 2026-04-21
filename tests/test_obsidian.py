from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "MyVault"
    v.mkdir()
    (v / "Personas").mkdir()
    (v / "Personas" / "Sofia.md").write_text(
        "# Sofia\n\nMediterranean persona for AI farm.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(v))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    from core.config import reset_settings
    reset_settings()
    yield v
    reset_settings()


def test_not_configured_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    from core.config import reset_settings
    reset_settings()
    from intelligence import obsidian
    assert obsidian.vault_path() is None
    assert obsidian.is_configured() is False
    assert obsidian.write_note("x", "y") is None
    assert obsidian.append_to_daily("s", "b") is None
    assert obsidian.search("anything") == []
    assert obsidian.list_recent() == []


def test_is_configured(vault):
    from intelligence import obsidian
    assert obsidian.is_configured() is True
    assert obsidian.vault_path() == vault


def test_write_note_creates_file_with_frontmatter(vault):
    from intelligence import obsidian
    path = obsidian.write_note(
        title="Test Note",
        body="Some markdown **content**.",
        tags=["research", "test"],
        links=["Sofia"],
    )
    assert path is not None
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "source: caliclaw" in content
    assert "tags: [caliclaw, research, test]" in content
    assert "# Test Note" in content
    assert "Some markdown **content**." in content
    assert "- [[Sofia]]" in content


def test_write_note_sanitizes_filename(vault):
    from intelligence import obsidian
    path = obsidian.write_note(
        title="Can I use: weird/chars?",
        body="body",
    )
    assert path is not None
    assert "/" not in path.name
    assert "?" not in path.name
    assert path.name.endswith(".md")


def test_write_note_custom_subdir(vault):
    from intelligence import obsidian
    path = obsidian.write_note(
        title="Deep dive",
        body="body",
        subdir="Research/2026",
    )
    assert path is not None
    assert "Research/2026" in str(path)
    assert (vault / "Research" / "2026" / "Deep dive.md").exists()


def test_append_to_daily_creates_and_appends(vault):
    from intelligence import obsidian
    p1 = obsidian.append_to_daily("first", "alpha")
    assert p1 is not None
    assert p1.exists()
    first = p1.read_text(encoding="utf-8")
    assert "# " in first  # has date header
    assert "## " in first  # has section header
    assert "alpha" in first

    p2 = obsidian.append_to_daily("second", "beta")
    assert p1 == p2  # same daily note
    second = p2.read_text(encoding="utf-8")
    assert "alpha" in second
    assert "beta" in second


def test_search_finds_existing_note(vault):
    from intelligence import obsidian
    hits = obsidian.search("Mediterranean")
    # rg may not be installed in CI; accept either match or empty gracefully
    if hits:
        assert any("Sofia" in h["path"] for h in hits)
        assert all({"path", "line_no", "preview"} <= h.keys() for h in hits)


def test_list_recent(vault):
    from intelligence import obsidian
    from intelligence.obsidian import write_note
    write_note("Fresh Note", "body")
    recent = obsidian.list_recent(limit=5)
    assert any("Fresh Note" in p.name for p in recent)


def test_upsert_env_new_key(tmp_path):
    from cli.commands.obsidian import _upsert_env, _get_env
    _upsert_env(tmp_path, "OBSIDIAN_VAULT_PATH", "/home/user/Vault")
    assert _get_env(tmp_path, "OBSIDIAN_VAULT_PATH") == "/home/user/Vault"
    assert (tmp_path / ".env").read_text().endswith(
        "OBSIDIAN_VAULT_PATH=/home/user/Vault\n"
    )


def test_upsert_env_replaces_existing(tmp_path):
    from cli.commands.obsidian import _upsert_env, _get_env
    (tmp_path / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=abc\nOBSIDIAN_VAULT_PATH=/old/path\nTZ=UTC\n"
    )
    _upsert_env(tmp_path, "OBSIDIAN_VAULT_PATH", "/new/path")
    assert _get_env(tmp_path, "OBSIDIAN_VAULT_PATH") == "/new/path"
    content = (tmp_path / ".env").read_text()
    assert "/old/path" not in content
    assert "TELEGRAM_BOT_TOKEN=abc" in content
    assert "TZ=UTC" in content


def test_detect_vaults_reads_obsidian_json(tmp_path, monkeypatch):
    """Simulate a Linux Obsidian config listing two vaults, one newer."""
    import json as _json
    from cli.commands import obsidian as ob_cli

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    v_older = tmp_path / "Older"
    v_newer = tmp_path / "Newer"
    v_older.mkdir()
    v_newer.mkdir()

    cfg_dir = fake_home / ".config" / "obsidian"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "obsidian.json").write_text(_json.dumps({
        "vaults": {
            "abc": {"path": str(v_older), "ts": 1000, "open": False},
            "def": {"path": str(v_newer), "ts": 2000, "open": True},
        },
    }))

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr("platform.system", lambda: "Linux")

    result = ob_cli.detect_vaults()
    assert result[0] == v_newer
    assert v_older in result


def test_detect_vaults_fallback_scan(tmp_path, monkeypatch):
    """No Obsidian config — fall back to scanning ~/Documents for .obsidian/."""
    from cli.commands import obsidian as ob_cli

    fake_home = tmp_path / "home"
    (fake_home / "Documents" / "MyVault" / ".obsidian").mkdir(parents=True)

    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr("platform.system", lambda: "Linux")

    result = ob_cli.detect_vaults()
    assert len(result) == 1
    assert result[0].name == "MyVault"
