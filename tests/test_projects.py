"""Tests for project switching (core/projects.py).

Verifies the on-disk state file, project listing, scaffold-on-create, and
the session_agent_name namespacing trick that keeps each project's
sessions isolated in the DB.
"""
from __future__ import annotations

import pytest


# ── State file: get / set / clear ────────────────────────────────────


def test_active_project_default_is_none(settings):
    from core.projects import get_active_project
    assert get_active_project() is None


def test_set_and_get_active_project(settings):
    from core.projects import get_active_project, set_active_project
    set_active_project("luna")
    assert get_active_project() == "luna"


def test_set_active_project_none_clears(settings):
    from core.projects import get_active_project, set_active_project
    set_active_project("luna")
    set_active_project(None)
    assert get_active_project() is None


def test_set_active_project_strips_whitespace(settings):
    from core.projects import get_active_project, set_active_project
    set_active_project("  pad  ")
    assert get_active_project() == "pad"


# ── List / exists / create ───────────────────────────────────────────


def test_list_projects_empty(settings):
    from core.projects import list_projects
    assert list_projects() == []


def test_list_projects_only_includes_those_with_main_soul(settings, tmp_path):
    """A directory under agents/projects/ without main/SOUL.md is ignored.
    Otherwise legacy / partial dirs would pollute the menu."""
    from core.projects import list_projects

    pdir = settings.agents_dir / "projects"
    (pdir / "real" / "main").mkdir(parents=True)
    (pdir / "real" / "main" / "SOUL.md").write_text("hello")
    (pdir / "stub_no_main").mkdir(parents=True)
    (pdir / "no_soul" / "main").mkdir(parents=True)  # has main/ but no SOUL.md

    assert list_projects() == ["real"]


def test_project_exists(settings):
    from core.projects import create_project, project_exists
    assert not project_exists("foo")
    create_project("foo")
    assert project_exists("foo")


def test_create_project_scaffolds_soul_and_workspace(settings):
    from core.projects import create_project

    pdir = create_project("luna", description="Luna persona")
    assert (pdir / "main" / "SOUL.md").exists()
    soul_text = (pdir / "main" / "SOUL.md").read_text()
    assert "Luna persona" in soul_text
    assert "luna — main agent" in soul_text
    # Workspace dir is pre-created so the agent has somewhere to write.
    assert (settings.workspace_dir / "projects" / "luna").is_dir()


def test_create_project_idempotent_on_existing_soul(settings):
    """Re-creating a project doesn't clobber an existing soul (user might
    have edited it). create_project is meant to be safe to call again."""
    from core.projects import create_project

    create_project("luna", description="first")
    soul_path = settings.agents_dir / "projects" / "luna" / "main" / "SOUL.md"
    soul_path.write_text("# my custom soul\nhand-edited content")

    create_project("luna", description="second")
    assert soul_path.read_text() == "# my custom soul\nhand-edited content"


def test_project_workspace_creates_dir(settings):
    from core.projects import project_workspace
    ws = project_workspace("brand_new")
    assert ws.is_dir()
    assert ws == settings.workspace_dir / "projects" / "brand_new"


# ── session_agent_name ──────────────────────────────────────────────


def test_session_agent_name_global():
    from core.projects import session_agent_name
    assert session_agent_name(None) == "main"
    assert session_agent_name("") == "main"


def test_session_agent_name_project():
    from core.projects import session_agent_name
    assert session_agent_name("luna") == "main:luna"


# ── Integration: session isolation across projects ──────────────────


@pytest.mark.asyncio
async def test_sessions_isolated_per_project(db, settings):
    """Two active sessions for different projects must not collide.
    `get_active_session` filters by agent_name — that's what makes
    project switching feel clean (no cross-context bleed)."""
    from core.projects import session_agent_name

    luna = session_agent_name("luna")
    sofia = session_agent_name("sofia")
    glob = session_agent_name(None)

    await db.create_session("s-luna", luna)
    await db.create_session("s-sofia", sofia)
    await db.create_session("s-global", glob)

    assert (await db.get_active_session(luna))["id"] == "s-luna"
    assert (await db.get_active_session(sofia))["id"] == "s-sofia"
    assert (await db.get_active_session(glob))["id"] == "s-global"
