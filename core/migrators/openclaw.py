"""Migrator for openclaw projects.

openclaw layout:
  agents/global/main/{SOUL.md, IDENTITY.md, USER.md, TOOLS.md}
  agents/SECURITY.md
  memory/memories.json          <-- JSON array of memory entries
  skills/*/SKILL.md
  data/openclaw.db              <-- same schema as caliclaw
  .env
  workspace/media/
"""
from __future__ import annotations

import json
import sqlite3
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
    source_description = "Migrate from openclaw (JSON memory, standard DB)"

    _SOUL_FILES = ["SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md"]
    _DB_TABLES = ["messages", "sessions", "agents", "tasks", "task_runs", "approvals", "usage_log"]

    def validate_source(self) -> List[str]:
        errors = []
        if not self.source_path.is_dir():
            errors.append(f"Not a directory: {self.source_path}")
            return errors
        if not (self.source_path / "agents").is_dir() and not (self.source_path / "data").is_dir():
            errors.append("No agents/ or data/ directory found. Not a valid openclaw project.")
        return errors

    def discover_components(self) -> Dict[MigrationComponent, bool]:
        p = self.source_path
        return {
            MigrationComponent.SOUL: (p / "agents" / "global" / "main").is_dir(),
            MigrationComponent.MEMORY: (p / "memory" / "memories.json").exists(),
            MigrationComponent.SKILLS: (p / "skills").is_dir() and any((p / "skills").iterdir()),
            MigrationComponent.DB: self._find_db() is not None,
            MigrationComponent.CONFIG: (p / ".env").exists(),
            MigrationComponent.MEDIA: (p / "workspace" / "media").is_dir(),
        }

    def plan(
        self,
        components: List[MigrationComponent],
        conflict_strategy: ConflictStrategy,
    ) -> MigrationPlan:
        plan = MigrationPlan(source_name=self.source_name, source_path=self.source_path)

        if MigrationComponent.SOUL in components:
            self._plan_soul_files(plan, conflict_strategy)
        if MigrationComponent.MEMORY in components:
            self._plan_memory(plan, conflict_strategy)
        if MigrationComponent.SKILLS in components:
            self._plan_skills(plan, conflict_strategy)
        if MigrationComponent.DB in components:
            self._plan_db(plan, conflict_strategy)
        if MigrationComponent.CONFIG in components:
            self._plan_config(plan, conflict_strategy)
        if MigrationComponent.MEDIA in components:
            self._plan_media(plan, conflict_strategy)

        return plan

    # ── Planning ──

    def _plan_soul_files(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        src_dir = self.source_path / "agents" / "global" / "main"
        tgt_dir = self.settings.agents_dir / "global" / "main"
        for f in self._SOUL_FILES:
            self._plan_file(plan, MigrationComponent.SOUL, src_dir / f, tgt_dir / f, f"Soul: {f}", strategy)

        # SECURITY.md
        self._plan_file(
            plan, MigrationComponent.SOUL,
            self.source_path / "agents" / "SECURITY.md",
            self.settings.agents_dir / "SECURITY.md",
            "Soul: SECURITY.md", strategy,
        )

        # Additional agents (projects/, ephemeral/)
        for scope in ("projects", "ephemeral"):
            scope_dir = self.source_path / "agents" / scope
            if not scope_dir.is_dir():
                continue
            for agent_dir in scope_dir.iterdir():
                if not agent_dir.is_dir():
                    continue
                tgt_agent = self.settings.agents_dir / scope / agent_dir.name
                for f in agent_dir.glob("*.md"):
                    self._plan_file(
                        plan, MigrationComponent.SOUL,
                        f, tgt_agent / f.name,
                        f"Soul: {scope}/{agent_dir.name}/{f.name}", strategy,
                    )

    def _plan_memory(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        json_path = self.source_path / "memory" / "memories.json"
        if not json_path.exists():
            return
        try:
            memories = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            plan.errors.append(f"Cannot parse memories.json: {e}")
            return

        for mem in memories:
            slug = mem.get("name", "unknown").lower().replace(" ", "_")[:40]
            mem_type = mem.get("type", "project")
            filename = f"{mem_type}_{slug}.md"
            tgt = self.settings.memory_dir / filename
            conflict = tgt.exists()
            action = "skip" if conflict and strategy == ConflictStrategy.SKIP else "convert"
            plan.items.append(MigrationItem(
                component=MigrationComponent.MEMORY,
                source_path=json_path,
                target_path=tgt,
                description=f"Memory: {mem.get('name', slug)}",
                conflict=conflict,
                action=action,
                details={"entry": mem},
            ))

        # MEMORY.md index
        self._plan_file(
            plan, MigrationComponent.MEMORY,
            self.source_path / "memory" / "MEMORY.md",
            self.settings.memory_dir / "MEMORY.md",
            "Memory: MEMORY.md index", strategy, action="merge" if strategy == ConflictStrategy.MERGE else "copy",
        )

    def _plan_skills(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        src_skills = self.source_path / "skills"
        if not src_skills.is_dir():
            return
        for skill_dir in sorted(src_skills.iterdir()):
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
        db_path = self._find_db()
        if not db_path:
            return
        try:
            conn = sqlite3.connect(str(db_path))
            for table in self._DB_TABLES:
                try:
                    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                    count = cur.fetchone()[0]
                    if count > 0:
                        plan.items.append(MigrationItem(
                            component=MigrationComponent.DB,
                            source_path=db_path,
                            target_path=None,
                            description=f"DB: {table} ({count} rows)",
                            action="import",
                            details={"table": table, "count": count, "db_path": str(db_path)},
                        ))
                except sqlite3.OperationalError:
                    plan.warnings.append(f"Table {table} not found in source DB")
            conn.close()
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
            plan.errors.append(f"Cannot read source DB: {e}")

    def _plan_config(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        self._plan_file(
            plan, MigrationComponent.CONFIG,
            self.source_path / ".env",
            self.settings.project_root / ".env",
            "Config: .env", strategy,
        )

    def _plan_media(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        media_dir = self.source_path / "workspace" / "media"
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

    # ── Execution overrides ──

    def _migrate_memory_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        """Convert JSON memory entry to frontmatter .md."""
        if item.action == "convert" and "entry" in item.details:
            if item.target_path is None:
                return
            if item.target_path.exists() and strategy == ConflictStrategy.SKIP:
                return
            entry = item.details["entry"]
            content = (
                f"---\n"
                f"name: {entry.get('name', '')}\n"
                f"description: {entry.get('description', '')}\n"
                f"type: {entry.get('type', 'project')}\n"
                f"---\n\n"
                f"{entry.get('content', '')}\n"
            )
            item.target_path.parent.mkdir(parents=True, exist_ok=True)
            item.target_path.write_text(content, encoding="utf-8")
        else:
            self._copy_file(item, strategy)

    def _migrate_db_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        """Import rows from openclaw DB into caliclaw DB."""
        table = item.details["table"]
        db_path = Path(item.details["db_path"])

        rows = self._import_table_rows(db_path, table)
        if not rows:
            return

        # Insert into caliclaw DB
        target_db = self.settings.data_dir / "caliclaw.db"
        if not target_db.exists():
            return

        conn = sqlite3.connect(str(target_db))
        try:
            for row in rows:
                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                col_names = ", ".join(cols)
                vals = [row[c] for c in cols]
                try:
                    conn.execute(
                        f"INSERT OR {('REPLACE' if strategy == ConflictStrategy.OVERWRITE else 'IGNORE')} "
                        f"INTO {table} ({col_names}) VALUES ({placeholders})",
                        vals,
                    )
                except sqlite3.OperationalError:
                    continue  # column mismatch, skip row
            conn.commit()
        finally:
            conn.close()

    # ── Helpers ──

    def _find_db(self) -> Path | None:
        """Find the source database file."""
        for name in ("openclaw.db", "caliclaw.db", "data.db"):
            p = self.source_path / "data" / name
            if p.exists():
                return p
        return None
