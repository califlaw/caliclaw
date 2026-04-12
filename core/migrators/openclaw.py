"""Migrator for openclaw projects.

Real openclaw layout:
  openclaw.json                          config + auth + models
  agents/main/agent/                     agent config (models.json, auth)
  agents/main/sessions/*.jsonl           session histories
  memory/main.sqlite                     sqlite DB
  credentials/telegram-*.json            telegram config
  identity/                              device auth
  media/                                 media files
  logs/
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, List

from core.migrate import (
    BaseMigrator,
    ConflictStrategy,
    MigrationComponent,
    MigrationItem,
    MigrationPlan,
    register_migrator,
)


@register_migrator
class OpenclawMigrator(BaseMigrator):
    source_name = "openclaw"
    source_description = "Migrate from openclaw (sqlite DB, session JSONL files)"

    def validate_source(self) -> List[str]:
        errors = []
        if not self.source_path.is_dir():
            errors.append(f"Not a directory: {self.source_path}")
            return errors
        if not (self.source_path / "openclaw.json").exists():
            if not (self.source_path / "agents").is_dir():
                errors.append("No openclaw.json or agents/ found. Not a valid openclaw project.")
        return errors

    def discover_components(self) -> Dict[MigrationComponent, bool]:
        p = self.source_path
        ws = p / "workspace"
        has_sessions = (
            (p / "agents" / "main" / "sessions").is_dir()
            and any((p / "agents" / "main" / "sessions").glob("*.jsonl*"))
        )
        has_db = (p / "memory" / "main.sqlite").exists()
        has_config = (p / "openclaw.json").exists()
        has_credentials = (
            (p / "credentials").is_dir()
            and any((p / "credentials").glob("telegram-*.json"))
        )
        has_media = (p / "media").is_dir() and any((p / "media").iterdir()) if (p / "media").is_dir() else False
        has_agent_config = (p / "agents" / "main" / "agent").is_dir()

        # Workspace: soul files (AGENTS.md, CONTEXT.md) and skills
        has_soul = has_agent_config or (ws / "AGENTS.md").exists() or (ws / "CONTEXT.md").exists()
        has_skills = ws.is_dir() and (ws / "skills").is_dir() and any((ws / "skills").iterdir())
        has_memory = has_sessions or has_db or (ws / "CONTEXT.md").exists()

        return {
            MigrationComponent.SOUL: has_soul,
            MigrationComponent.MEMORY: has_memory,
            MigrationComponent.SKILLS: has_skills,
            MigrationComponent.DB: has_db,
            MigrationComponent.CONFIG: has_config or has_credentials,
            MigrationComponent.MEDIA: has_media,
        }

    def plan(
        self,
        components: List[MigrationComponent],
        conflict_strategy: ConflictStrategy,
    ) -> MigrationPlan:
        plan = MigrationPlan(source_name=self.source_name, source_path=self.source_path)

        if MigrationComponent.SOUL in components:
            self._plan_agent_config(plan, conflict_strategy)
            self._plan_workspace_soul(plan, conflict_strategy)
        if MigrationComponent.MEMORY in components:
            self._plan_sessions(plan, conflict_strategy)
            self._plan_workspace_context(plan, conflict_strategy)
        if MigrationComponent.SKILLS in components:
            self._plan_workspace_skills(plan, conflict_strategy)
        if MigrationComponent.DB in components:
            self._plan_db(plan, conflict_strategy)
        if MigrationComponent.CONFIG in components:
            self._plan_config(plan, conflict_strategy)
        if MigrationComponent.MEDIA in components:
            self._plan_media(plan, conflict_strategy)

        return plan

    # ── Planning ──

    def _plan_agent_config(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        agent_dir = self.source_path / "agents" / "main" / "agent"
        if not agent_dir.is_dir():
            return
        tgt_dir = self.settings.agents_dir / "global" / "main"
        for f in sorted(agent_dir.iterdir()):
            if f.is_file() and f.suffix == ".json":
                self._plan_file(
                    plan, MigrationComponent.SOUL,
                    f, tgt_dir / f.name,
                    f"Agent config: {f.name}", strategy,
                )

    def _plan_sessions(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        sessions_dir = self.source_path / "agents" / "main" / "sessions"
        if not sessions_dir.is_dir():
            return
        tgt_dir = self.settings.workspace_dir / "conversations"
        for f in sorted(sessions_dir.glob("*.jsonl*")):
            self._plan_file(
                plan, MigrationComponent.MEMORY,
                f, tgt_dir / f.name,
                f"Session: {f.name}", strategy,
            )

    def _plan_workspace_soul(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        ws = self.source_path / "workspace"
        if not ws.is_dir():
            return
        tgt_dir = self.settings.agents_dir / "global" / "main"
        for name in ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md"]:
            src = ws / name
            if src.exists():
                self._plan_file(
                    plan, MigrationComponent.SOUL,
                    src, tgt_dir / name,
                    f"Soul: {name}", strategy,
                )

    def _plan_workspace_context(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        ws = self.source_path / "workspace"
        if not ws.is_dir():
            return
        ctx = ws / "CONTEXT.md"
        if ctx.exists():
            tgt = self.settings.memory_dir / "project_openclaw_context.md"
            self._plan_file(
                plan, MigrationComponent.MEMORY,
                ctx, tgt,
                "Memory: CONTEXT.md (project state)", strategy,
            )

    def _plan_workspace_skills(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        ws_skills = self.source_path / "workspace" / "skills"
        if not ws_skills.is_dir():
            return
        for skill_dir in sorted(ws_skills.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                tgt = self.settings.skills_dir / skill_dir.name / "SKILL.md"
                self._plan_file(
                    plan, MigrationComponent.SKILLS,
                    skill_md, tgt,
                    f"Skill: {skill_dir.name}", strategy,
                )

    def _plan_db(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        db_path = self.source_path / "memory" / "main.sqlite"
        if not db_path.exists():
            return
        tgt = self.settings.data_dir / "openclaw_imported.sqlite"
        conflict = tgt.exists()
        action = "skip" if conflict and strategy == ConflictStrategy.SKIP else "copy"
        plan.items.append(MigrationItem(
            component=MigrationComponent.DB,
            source_path=db_path,
            target_path=tgt,
            description=f"DB: main.sqlite ({db_path.stat().st_size // 1024}KB)",
            conflict=conflict,
            action=action,
        ))

    def _plan_config(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        # openclaw.json → save as reference
        oc_json = self.source_path / "openclaw.json"
        if oc_json.exists():
            tgt = self.settings.data_dir / "openclaw_config.json"
            self._plan_file(
                plan, MigrationComponent.CONFIG,
                oc_json, tgt,
                "Config: openclaw.json", strategy,
            )

        # Telegram credentials
        creds_dir = self.source_path / "credentials"
        if creds_dir.is_dir():
            tgt_dir = self.settings.data_dir
            for f in sorted(creds_dir.glob("telegram-*.json")):
                self._plan_file(
                    plan, MigrationComponent.CONFIG,
                    f, tgt_dir / f.name,
                    f"Credentials: {f.name}", strategy,
                )

    def _plan_media(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        media_dir = self.source_path / "media"
        if not media_dir.is_dir():
            return
        tgt_media = self.settings.workspace_dir / "media"
        for f in sorted(media_dir.iterdir()):
            if f.is_file():
                self._plan_file(
                    plan, MigrationComponent.MEDIA,
                    f, tgt_media / f.name,
                    f"Media: {f.name}", strategy,
                )

    # ── Execution ──

    def execute(self, plan, conflict_strategy):
        result = super().execute(plan, conflict_strategy)
        self._post_migrate_enable_skills(plan)
        self._post_migrate_summarize_sessions()
        return result

    def _post_migrate_enable_skills(self, plan) -> None:
        """Add migrated skills to enabled_skills.txt."""
        skill_names = [
            item.description.replace("Skill: ", "")
            for item in plan.items
            if item.component == MigrationComponent.SKILLS and item.action != "skip"
        ]
        if not skill_names:
            return
        config_file = self.settings.project_root / "data" / "enabled_skills.txt"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        existing = set()
        if config_file.exists():
            existing = {l.strip() for l in config_file.read_text().splitlines() if l.strip()}
        existing.update(skill_names)
        config_file.write_text("\n".join(sorted(existing)) + "\n")

    def _post_migrate_summarize_sessions(self) -> None:
        """Parse .jsonl session files and extract key facts into memory."""
        import json as _json

        conversations_dir = self.settings.workspace_dir / "conversations"
        if not conversations_dir.is_dir():
            return

        memory_dir = self.settings.memory_dir
        memory_dir.mkdir(parents=True, exist_ok=True)

        for jsonl_file in sorted(conversations_dir.glob("*.jsonl*")):
            slug = jsonl_file.name[:8]
            tgt = memory_dir / f"session_{slug}.md"
            if tgt.exists():
                continue

            # Extract assistant messages from openclaw's nested JSONL format
            # Format: {"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"..."}]}}
            assistant_msgs = []
            try:
                for line in jsonl_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue

                    # Handle nested openclaw format
                    msg = entry.get("message", entry)
                    role = msg.get("role", "")
                    if role != "assistant":
                        continue
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        # content: [{"type":"text","text":"..."}]
                        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                        content = " ".join(texts)
                    if content and len(content) > 20:
                        assistant_msgs.append(content[:500])
            except OSError:
                continue

            if not assistant_msgs:
                continue

            # Take last 3 assistant messages as summary
            summary = "\n\n".join(assistant_msgs[-3:])

            md = (
                f"---\n"
                f"name: session-{slug}\n"
                f"description: Imported session from openclaw\n"
                f"type: project\n"
                f"---\n\n"
                f"{summary}\n"
            )
            tgt.write_text(md, encoding="utf-8")

    def _migrate_db_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        if item.target_path and item.source_path:
            if item.target_path.exists() and strategy == ConflictStrategy.SKIP:
                return
            item.target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source_path, item.target_path)
