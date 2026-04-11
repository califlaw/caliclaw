"""Migrator for nanoclaw projects.

nanoclaw layout (minimal variant):
  agents/main/{SOUL.md, IDENTITY.md, USER.md}   <-- no TOOLS.md, flat structure
  memory/*.yaml                                   <-- individual YAML files
  skills/*/SKILL.md
  data/nanoclaw.db                                <-- minimal schema (no tasks, approvals)
  .env
"""
from __future__ import annotations

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
class NanoclawMigrator(BaseMigrator):
    source_name = "nanoclaw"
    source_description = "Migrate from nanoclaw (YAML memory, minimal DB)"

    _SOUL_FILES = ["SOUL.md", "IDENTITY.md", "USER.md"]
    _DB_TABLES = ["messages", "sessions", "agents", "usage_log"]

    def validate_source(self) -> List[str]:
        errors = []
        if not self.source_path.is_dir():
            errors.append(f"Not a directory: {self.source_path}")
            return errors
        # nanoclaw has agents/main/ (flat) or agents/global/main/
        has_agents = (
            (self.source_path / "agents" / "main").is_dir()
            or (self.source_path / "agents" / "global" / "main").is_dir()
        )
        has_data = (self.source_path / "data").is_dir()
        if not has_agents and not has_data:
            errors.append("No agents/ or data/ directory found. Not a valid nanoclaw project.")
        return errors

    def discover_components(self) -> Dict[MigrationComponent, bool]:
        p = self.source_path
        has_soul = (
            (p / "agents" / "main").is_dir()
            or (p / "agents" / "global" / "main").is_dir()
        )
        has_yaml_mem = (p / "memory").is_dir() and any(p.glob("memory/*.yaml")) if (p / "memory").is_dir() else False
        return {
            MigrationComponent.SOUL: has_soul,
            MigrationComponent.MEMORY: has_yaml_mem,
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
        # nanoclaw uses flat agents/main/ or agents/global/main/
        for src_base in ("agents/main", "agents/global/main"):
            src_dir = self.source_path / src_base
            if src_dir.is_dir():
                break
        else:
            return

        tgt_dir = self.settings.agents_dir / "global" / "main"
        for f in self._SOUL_FILES:
            self._plan_file(plan, MigrationComponent.SOUL, src_dir / f, tgt_dir / f, f"Soul: {f}", strategy)

    def _plan_memory(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        """nanoclaw stores memory as individual .yaml files."""
        mem_dir = self.source_path / "memory"
        if not mem_dir.is_dir():
            return

        for yaml_file in sorted(mem_dir.glob("*.yaml")):
            slug = yaml_file.stem
            tgt = self.settings.memory_dir / f"{slug}.md"
            conflict = tgt.exists()
            action = "skip" if conflict and strategy == ConflictStrategy.SKIP else "convert"
            plan.items.append(MigrationItem(
                component=MigrationComponent.MEMORY,
                source_path=yaml_file,
                target_path=tgt,
                description=f"Memory: {slug}",
                conflict=conflict,
                action=action,
                details={"format": "yaml"},
            ))

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
                self._plan_file(plan, MigrationComponent.SKILLS, skill_md, tgt, f"Skill: {skill_dir.name}", strategy)

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
                self._plan_file(plan, MigrationComponent.MEDIA, f, tgt_media / f.name, f"Media: {f.name}", strategy)

    # ── Execution overrides ──

    def _migrate_memory_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        """Convert YAML memory file to frontmatter .md."""
        if item.action != "convert" or item.source_path is None or item.target_path is None:
            self._copy_file(item, strategy)
            return
        if item.target_path.exists() and strategy == ConflictStrategy.SKIP:
            return

        try:
            import yaml
        except ImportError:
            # Fallback: parse simple YAML manually
            raw = item.source_path.read_text(encoding="utf-8")
            self._yaml_to_md_simple(raw, item.target_path)
            return

        raw = item.source_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}

        name = data.get("name", item.source_path.stem)
        desc = data.get("description", "")
        mem_type = data.get("type", "project")
        content = data.get("content", "")

        md = (
            f"---\n"
            f"name: {name}\n"
            f"description: {desc}\n"
            f"type: {mem_type}\n"
            f"---\n\n"
            f"{content}\n"
        )
        item.target_path.parent.mkdir(parents=True, exist_ok=True)
        item.target_path.write_text(md, encoding="utf-8")

    def _yaml_to_md_simple(self, raw: str, target: Path) -> None:
        """Fallback YAML->MD without pyyaml dependency."""
        lines = raw.strip().split("\n")
        name = desc = mem_type = ""
        content_lines = []
        in_content = False

        for line in lines:
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
            elif line.startswith("type:"):
                mem_type = line.split(":", 1)[1].strip()
            elif line.startswith("content:"):
                in_content = True
                rest = line.split(":", 1)[1].strip()
                if rest:
                    content_lines.append(rest)
            elif in_content:
                content_lines.append(line)

        md = (
            f"---\n"
            f"name: {name}\n"
            f"description: {desc}\n"
            f"type: {mem_type or 'project'}\n"
            f"---\n\n"
            f"{chr(10).join(content_lines)}\n"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")

    def _migrate_db_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        """Import rows from nanoclaw minimal DB."""
        table = item.details["table"]
        db_path = Path(item.details["db_path"])

        rows = self._import_table_rows(db_path, table)
        if not rows:
            return

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
                    continue
            conn.commit()
        finally:
            conn.close()

    # ── Helpers ──

    def _find_db(self) -> Path | None:
        for name in ("nanoclaw.db", "nano.db", "data.db"):
            p = self.source_path / "data" / name
            if p.exists():
                return p
        return None
