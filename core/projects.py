"""Project switching for caliclaw — multi-context isolation.

A project bundles three things together:
  - **Soul** — `agents/projects/<name>/main/SOUL.md` (and optional IDENTITY.md,
    USER.md, TOOLS.md, AGENTS.md). Loaded by SoulLoader with scope="project".
  - **Session** — DB sessions are filtered by `agent_name = "main:<project>"`,
    so each project has its own claude_session_id and message history. Switching
    projects doesn't pollute the previous context.
  - **Workspace** — `workspace/projects/<name>/` becomes the agent's
    `working_dir`. File ops stay scoped to the project tree.

The active project is persisted as a one-line state file at
`<data_dir>/state/active_project`. Absent file == global (default) scope.

Why state file (not DB): same pattern we use for `voice_mode`. It's a tiny
piece of UI state that survives restarts; no need for migrations or
transactions.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from core.config import get_settings


_STATE_FILENAME = "active_project"


def _state_file(settings=None) -> Path:
    settings = settings or get_settings()
    return settings.data_dir / "state" / _STATE_FILENAME


def get_active_project(settings=None) -> Optional[str]:
    """Return the active project name, or None when on global scope."""
    f = _state_file(settings)
    if not f.exists():
        return None
    try:
        name = f.read_text().strip()
    except OSError:
        return None
    return name or None


def set_active_project(name: Optional[str], settings=None) -> None:
    """Switch to a project (or pass None to return to global)."""
    f = _state_file(settings)
    f.parent.mkdir(parents=True, exist_ok=True)
    if name:
        f.write_text(name.strip() + "\n", encoding="utf-8")
    elif f.exists():
        f.unlink()


def list_projects(settings=None) -> List[str]:
    """All projects with at least a main agent — `agents/projects/<name>/main/SOUL.md`."""
    settings = settings or get_settings()
    projects_dir = settings.agents_dir / "projects"
    if not projects_dir.is_dir():
        return []
    out: List[str] = []
    for entry in projects_dir.iterdir():
        if entry.is_dir() and (entry / "main" / "SOUL.md").exists():
            out.append(entry.name)
    return sorted(out)


def project_exists(name: str, settings=None) -> bool:
    """A project is "real" only when it has a main agent SOUL.md."""
    settings = settings or get_settings()
    return (settings.agents_dir / "projects" / name / "main" / "SOUL.md").exists()


def create_project(name: str, description: str = "", settings=None) -> Path:
    """Scaffold a new project with a placeholder main soul + workspace dir."""
    settings = settings or get_settings()
    project_dir = settings.agents_dir / "projects" / name
    main_dir = project_dir / "main"
    main_dir.mkdir(parents=True, exist_ok=True)
    soul = main_dir / "SOUL.md"
    if not soul.exists():
        body = description or (
            "Describe what this project is and how the agent should behave.\n\n"
            "## Goals\n- ...\n\n"
            "## Constraints\n- ...\n"
        )
        soul.write_text(f"# {name} — main agent\n\n{body}", encoding="utf-8")
    # Pre-create the workspace dir so the agent has somewhere to land.
    (settings.workspace_dir / "projects" / name).mkdir(parents=True, exist_ok=True)
    return project_dir


def project_workspace(name: str, settings=None) -> Path:
    """Return (and create) the workspace dir for a project."""
    settings = settings or get_settings()
    ws = settings.workspace_dir / "projects" / name
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def session_agent_name(project: Optional[str]) -> str:
    """DB `agent_name` to use when looking up / creating sessions.

    Global scope keeps the legacy "main" so existing rows aren't orphaned.
    Project scope namespaces sessions as "main:<project>" so each project
    keeps its own claude_session_id and message history.
    """
    if not project:
        return "main"
    return f"main:{project}"
