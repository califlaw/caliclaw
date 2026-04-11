"""Tests for caliclaw-gym skill marketplace."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_gym_constants():
    from core.gym import GYM_REPO, GYM_RAW_URL, GYM_API_URL
    assert "califlaw" in GYM_REPO
    assert "caliclaw-gym" in GYM_REPO
    assert GYM_RAW_URL.startswith("https://raw.githubusercontent.com/")
    assert GYM_API_URL.startswith("https://api.github.com/")


def test_install_skill_creates_local_dir(settings, monkeypatch):
    """install_skill should create skills/<name>/SKILL.md and enable it."""
    fake_content = b"---\nname: test-skill\ndescription: Test\n---\n\nbody"

    class FakeResp:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen(url, timeout=None):
        return FakeResp(fake_content)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.gym import install_skill
    ok = install_skill("test-skill")
    assert ok is True

    skill_md = settings.skills_dir / "test-skill" / "SKILL.md"
    assert skill_md.exists()
    assert b"test-skill" in skill_md.read_bytes()

    # Should be auto-enabled
    config = settings.project_root / "data" / "enabled_skills.txt"
    enabled = config.read_text().strip().split("\n")
    assert "test-skill" in enabled


def test_install_skill_already_exists(settings, monkeypatch):
    """install_skill returns False if skill already installed."""
    skill_dir = settings.skills_dir / "existing"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("existing")

    from core.gym import install_skill
    ok = install_skill("existing")
    assert ok is False


def test_install_skill_network_error(settings, monkeypatch):
    """install_skill returns False on network error."""
    import urllib.error

    def fake_urlopen(url, timeout=None):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.gym import install_skill
    ok = install_skill("nonexistent")
    assert ok is False


def test_publish_skill_returns_instructions(settings):
    """publish_skill returns markdown instructions for a local skill."""
    skill_dir = settings.skills_dir / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\nbody")

    from core.gym import publish_skill
    result = publish_skill("my-skill")
    assert "my-skill" in result
    assert "Fork" in result or "fork" in result
    assert "Pull Request" in result or "PR" in result


def test_publish_skill_not_found(settings):
    """publish_skill returns error if skill doesn't exist locally."""
    from core.gym import publish_skill
    result = publish_skill("nonexistent")
    assert "not found" in result.lower()


def test_list_remote_skills_network_error(monkeypatch):
    """list_remote_skills returns empty list on network error."""
    import urllib.error

    def fake_urlopen(url, timeout=None):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.gym import list_remote_skills
    result = list_remote_skills()
    assert result == []


def test_fetch_skill_ratings_parses_issues(monkeypatch):
    """_fetch_skill_ratings parses GitHub issues with skill: prefix."""
    import json as _json
    fake_issues = _json.dumps([
        {
            "title": "skill: stripe-webhooks",
            "html_url": "https://github.com/x/y/issues/1",
            "user": {"login": "alice"},
            "reactions": {"+1": 42},
        },
        {
            "title": "skill: notion-sync",
            "html_url": "https://github.com/x/y/issues/2",
            "user": {"login": "bob"},
            "reactions": {"+1": 17},
        },
        {
            "title": "bug: not a skill",  # should be ignored
            "user": {"login": "carol"},
            "reactions": {"+1": 5},
        },
    ]).encode()

    class FakeResp:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeResp(fake_issues)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.gym import _fetch_skill_ratings
    ratings = _fetch_skill_ratings()

    assert "stripe-webhooks" in ratings
    assert ratings["stripe-webhooks"]["stars"] == 42
    assert ratings["stripe-webhooks"]["author"] == "alice"
    assert "notion-sync" in ratings
    assert ratings["notion-sync"]["stars"] == 17
    # Non-skill issue should be excluded
    assert len(ratings) == 2


def test_list_remote_skills_sorts_by_stars(monkeypatch):
    """list_remote_skills returns skills sorted by stars descending."""
    import json as _json

    fake_contents = _json.dumps([
        {"name": "low-stars", "type": "dir", "html_url": "u1"},
        {"name": "high-stars", "type": "dir", "html_url": "u2"},
        {"name": "no-stars", "type": "dir", "html_url": "u3"},
    ]).encode()

    fake_issues = _json.dumps([
        {"title": "skill: high-stars", "user": {"login": "a"}, "reactions": {"+1": 100}, "html_url": "i1"},
        {"title": "skill: low-stars", "user": {"login": "b"}, "reactions": {"+1": 5}, "html_url": "i2"},
    ]).encode()

    class FakeResp:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    call_count = {"n": 0}

    def fake_urlopen(req_or_url, timeout=None):
        call_count["n"] += 1
        url = req_or_url.full_url if hasattr(req_or_url, "full_url") else req_or_url
        if "issues" in url:
            return FakeResp(fake_issues)
        if "contents" in url:
            return FakeResp(fake_contents)
        # SKILL.md fetches return empty
        return FakeResp(b"---\ndescription: test\n---\nbody")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    from core.gym import list_remote_skills
    skills = list_remote_skills()

    assert len(skills) == 3
    assert skills[0]["name"] == "high-stars"
    assert skills[0]["stars"] == 100
    assert skills[1]["name"] == "low-stars"
    assert skills[1]["stars"] == 5
    assert skills[2]["name"] == "no-stars"
    assert skills[2]["stars"] == 0
