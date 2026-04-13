from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from core.config import get_settings

logger = logging.getLogger(__name__)

SOUL_FILES = ["SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md", "AGENTS.md", "CONTEXT.md"]


class SoulLoader:
    """Loads and manages soul files for agents."""

    def __init__(self, agents_dir: Optional[Path] = None):
        self._agents_dir = agents_dir or get_settings().agents_dir

    def get_agent_soul_dir(self, agent_name: str, scope: str = "global", project: Optional[str] = None) -> Path:
        if scope == "global":
            return self._agents_dir / "global" / agent_name
        elif scope == "project" and project:
            return self._agents_dir / "projects" / project / agent_name
        else:
            return self._agents_dir / "ephemeral" / agent_name

    def load_soul(self, agent_name: str, scope: str = "global", project: Optional[str] = None) -> str:
        """Load all soul files for an agent and combine into system prompt."""
        soul_dir = self.get_agent_soul_dir(agent_name, scope, project)
        parts: List[str] = []

        # Always load security rules first (cannot be overridden)
        security = self._load_file(self._agents_dir / "SECURITY.md")
        if security:
            parts.append(f"# SECURITY (mandatory)\n{security}")

        # Load global main soul as base (for non-main agents)
        if agent_name != "main":
            main_soul = self._load_file(self._agents_dir / "global" / "main" / "SOUL.md")
            if main_soul:
                parts.append(f"# Base System Instructions\n{main_soul}")

        # Load agent-specific soul files
        for filename in SOUL_FILES:
            content = self._load_file(soul_dir / filename)
            if content:
                label = filename.replace(".md", "").upper()
                parts.append(f"# {label}\n{content}")

        # Load skills
        skills_content = self._load_skills(agent_name, scope, project)
        if skills_content:
            parts.append(f"# SKILLS\n{skills_content}")

        # Load memory
        memory_content = self._load_memory()
        if memory_content:
            parts.append(f"# MEMORY\n{memory_content}")

        # Freedom mode override
        settings = get_settings()
        if settings.freedom_mode:
            parts.append(
                "# FULL AUTONOMY\n"
                "You have COMPLETE control over this machine. Execute all actions immediately.\n"
                "- Do NOT output [APPROVAL_NEEDED] — you are pre-approved for everything\n"
                "- sudo works without password — use it freely\n"
                "- SSH keys are configured — prefer key auth over passwords\n"
                "- For hosts without keys: use sshpass -p <pass> ssh ...\n"
                "- Use -y flags for package managers, --force when confident\n"
                "- You are the master of this host. Act accordingly."
            )

        return "\n\n---\n\n".join(parts)

    def _load_file(self, path: Path) -> Optional[str]:
        try:
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
        except (OSError, IOError) as e:
            logger.warning("Failed to load %s: %s", path, e)
        return None

    def _load_skills(self, agent_name: str, scope: str, project: Optional[str]) -> Optional[str]:
        """Load skill INDEX (name + description) into prompt. Full content on-demand.

        Instead of injecting full SKILL.md content for every skill (~25K tokens),
        we list skill names + descriptions (~500 tokens). The agent reads the full
        skill file when needed via: cat skills/<name>/SKILL.md
        """
        import re
        from core.config import bundled_skills_path
        settings = get_settings()

        enabled_file = settings.project_root / "data" / "enabled_skills.txt"
        enabled_names: Optional[set[str]] = None
        if enabled_file.exists():
            enabled_names = {
                l.strip() for l in enabled_file.read_text().splitlines() if l.strip()
            }

        skill_index: List[str] = []
        loaded: set[str] = set()

        def _scan(skills_dir):
            if not skills_dir or not skills_dir.exists():
                return
            for skill_dir in sorted(skills_dir.iterdir()):
                if not skill_dir.is_dir() or skill_dir.name in loaded:
                    continue
                if enabled_names is not None and skill_dir.name not in enabled_names:
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    content = skill_file.read_text(encoding="utf-8")
                    desc = skill_dir.name
                    match = re.search(r"description:\s*(.+)", content)
                    if match:
                        desc = match.group(1).strip()
                    skill_index.append(f"- {skill_dir.name}: {desc}")
                    loaded.add(skill_dir.name)

        _scan(settings.skills_dir)
        _scan(bundled_skills_path())

        if not skill_index:
            return None

        skills_path = settings.skills_dir
        return (
            f"## Available Skills ({len(skill_index)})\n\n"
            + "\n".join(skill_index)
            + f"\n\nTo use a skill, read its full content first:\n"
            f"  cat {skills_path}/<skill-name>/SKILL.md\n"
            f"Read the skill BEFORE acting on tasks that match it."
        )

    def _load_memory(self) -> Optional[str]:
        """Load memory INDEX into prompt. Full entries on-demand.

        MEMORY.md index + list of available memory files. Agent reads
        specific files when needed via cat. Session summaries and large
        memory files are NOT injected into every prompt.
        """
        settings = get_settings()
        parts: List[str] = []

        # MEMORY.md index (always loaded — small)
        memory_index = settings.memory_dir / "MEMORY.md"
        if memory_index.exists():
            idx = memory_index.read_text(encoding="utf-8").strip()
            if idx:
                parts.append(idx)

        # List available memory files (names only, not content)
        mem_files: List[str] = []
        if settings.memory_dir.exists():
            for f in sorted(settings.memory_dir.iterdir()):
                if f.name == "MEMORY.md" or not f.name.endswith(".md"):
                    continue
                mem_files.append(f"- {f.stem}")

        if mem_files:
            parts.append(
                f"## Available memory entries ({len(mem_files)})\n"
                + "\n".join(mem_files)
                + f"\n\nRead when needed: cat {settings.memory_dir}/<name>.md"
            )

        return "\n\n".join(parts) if parts else None

    def create_agent_soul(
        self,
        agent_name: str,
        scope: str = "ephemeral",
        project: Optional[str] = None,
        soul: str = "",
        identity: str = "",
        skills: Optional[List[str]] = None,
    ) -> Path:
        """Create soul files for a new agent. Returns the soul directory."""
        soul_dir = self.get_agent_soul_dir(agent_name, scope, project)
        soul_dir.mkdir(parents=True, exist_ok=True)

        if soul:
            (soul_dir / "SOUL.md").write_text(soul, encoding="utf-8")
        if identity:
            (soul_dir / "IDENTITY.md").write_text(identity, encoding="utf-8")

        logger.info("Created soul for agent %s at %s", agent_name, soul_dir)
        return soul_dir

    def delete_agent_soul(self, agent_name: str, scope: str = "ephemeral", project: Optional[str] = None) -> None:
        import shutil
        soul_dir = self.get_agent_soul_dir(agent_name, scope, project)
        if soul_dir.exists():
            shutil.rmtree(soul_dir)
            logger.info("Deleted soul for agent %s", agent_name)

    def list_agents(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {"global": [], "project": [], "ephemeral": []}
        for scope in ("global", "ephemeral"):
            scope_dir = self._agents_dir / scope
            if scope_dir.exists():
                for d in scope_dir.iterdir():
                    if d.is_dir() and (d / "SOUL.md").exists():
                        result[scope if scope != "projects" else "project"].append(d.name)

        projects_dir = self._agents_dir / "projects"
        if projects_dir.exists():
            for proj_dir in projects_dir.iterdir():
                if proj_dir.is_dir():
                    for d in proj_dir.iterdir():
                        if d.is_dir() and (d / "SOUL.md").exists():
                            result["project"].append(f"{proj_dir.name}/{d.name}")
        return result
