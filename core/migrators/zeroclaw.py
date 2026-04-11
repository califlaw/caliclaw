"""Migrator for zeroclaw projects.

zeroclaw layout (simplest variant, no DB):
  soul/SOUL.md                     <-- single soul file
  soul/IDENTITY.md
  notes/*.txt                       <-- flat text memory files
  skills/*/SKILL.md
  config.toml or config.yaml        <-- not .env
  media/                            <-- flat media directory
"""
from __future__ import annotations

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
class ZeroclawMigrator(BaseMigrator):
    source_name = "zeroclaw"
    source_description = "Migrate from zeroclaw (flat files, no DB)"

    def validate_source(self) -> List[str]:
        errors = []
        if not self.source_path.is_dir():
            errors.append(f"Not a directory: {self.source_path}")
            return errors
        has_soul = (self.source_path / "soul").is_dir() or (self.source_path / "agents").is_dir()
        has_notes = (self.source_path / "notes").is_dir()
        has_config = self._find_config() is not None
        if not has_soul and not has_notes and not has_config:
            errors.append("No soul/, notes/, or config found. Not a valid zeroclaw project.")
        return errors

    def discover_components(self) -> Dict[MigrationComponent, bool]:
        p = self.source_path
        return {
            MigrationComponent.SOUL: (p / "soul").is_dir() or (p / "agents").is_dir(),
            MigrationComponent.MEMORY: (p / "notes").is_dir() and any((p / "notes").glob("*.txt")),
            MigrationComponent.SKILLS: (p / "skills").is_dir() and any((p / "skills").iterdir()),
            MigrationComponent.DB: False,  # zeroclaw has no DB
            MigrationComponent.CONFIG: self._find_config() is not None,
            MigrationComponent.MEDIA: (p / "media").is_dir() and any((p / "media").iterdir()),
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
        if MigrationComponent.CONFIG in components:
            self._plan_config(plan, conflict_strategy)
        if MigrationComponent.MEDIA in components:
            self._plan_media(plan, conflict_strategy)

        return plan

    # ── Planning ──

    def _plan_soul_files(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        # zeroclaw: soul/ or agents/
        src_dir = self.source_path / "soul"
        if not src_dir.is_dir():
            src_dir = self.source_path / "agents"
        if not src_dir.is_dir():
            return

        tgt_dir = self.settings.agents_dir / "global" / "main"
        for md_file in sorted(src_dir.glob("*.md")):
            self._plan_file(
                plan, MigrationComponent.SOUL,
                md_file, tgt_dir / md_file.name,
                f"Soul: {md_file.name}", strategy,
            )

    def _plan_memory(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        """zeroclaw stores notes as plain .txt files."""
        notes_dir = self.source_path / "notes"
        if not notes_dir.is_dir():
            return

        for txt_file in sorted(notes_dir.glob("*.txt")):
            slug = txt_file.stem.lower().replace(" ", "_")[:40]
            tgt = self.settings.memory_dir / f"project_{slug}.md"
            conflict = tgt.exists()
            action = "skip" if conflict and strategy == ConflictStrategy.SKIP else "convert"
            plan.items.append(MigrationItem(
                component=MigrationComponent.MEMORY,
                source_path=txt_file,
                target_path=tgt,
                description=f"Note: {txt_file.name}",
                conflict=conflict,
                action=action,
                details={"format": "txt"},
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
                self._plan_file(
                    plan, MigrationComponent.SKILLS,
                    skill_md, tgt, f"Skill: {skill_dir.name}", strategy,
                )

    def _plan_config(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        config_path = self._find_config()
        if not config_path:
            return
        tgt = self.settings.project_root / ".env"
        conflict = tgt.exists()
        action = "skip" if conflict and strategy == ConflictStrategy.SKIP else "convert"
        plan.items.append(MigrationItem(
            component=MigrationComponent.CONFIG,
            source_path=config_path,
            target_path=tgt,
            description=f"Config: {config_path.name} -> .env",
            conflict=conflict,
            action=action,
            details={"format": config_path.suffix},
        ))

    def _plan_media(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        media_dir = self.source_path / "media"
        if not media_dir.is_dir():
            return
        tgt_media = self.settings.workspace_dir / "media"
        for f in sorted(media_dir.iterdir()):
            if f.is_file():
                self._plan_file(
                    plan, MigrationComponent.MEDIA,
                    f, tgt_media / f.name, f"Media: {f.name}", strategy,
                )

    # ── Execution overrides ──

    def _migrate_memory_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        """Convert .txt note to frontmatter .md."""
        if item.action != "convert" or item.source_path is None or item.target_path is None:
            self._copy_file(item, strategy)
            return
        if item.target_path.exists() and strategy == ConflictStrategy.SKIP:
            return

        raw = item.source_path.read_text(encoding="utf-8").strip()
        name = item.source_path.stem.replace("_", " ").title()

        md = (
            f"---\n"
            f"name: {name}\n"
            f"description: Imported from zeroclaw note {item.source_path.name}\n"
            f"type: project\n"
            f"---\n\n"
            f"{raw}\n"
        )
        item.target_path.parent.mkdir(parents=True, exist_ok=True)
        item.target_path.write_text(md, encoding="utf-8")

    def _migrate_config_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        """Convert TOML/YAML config to .env format."""
        if item.action != "convert" or item.source_path is None or item.target_path is None:
            self._copy_file(item, strategy)
            return
        if item.target_path.exists() and strategy == ConflictStrategy.SKIP:
            return

        raw = item.source_path.read_text(encoding="utf-8")
        fmt = item.details.get("format", "")
        env_lines = []

        if fmt == ".toml":
            env_lines = self._toml_to_env(raw)
        elif fmt in (".yaml", ".yml"):
            env_lines = self._yaml_to_env(raw)
        else:
            # Unknown format — copy as-is with comment
            env_lines = [f"# Imported from {item.source_path.name}", raw]

        item.target_path.parent.mkdir(parents=True, exist_ok=True)
        if item.target_path.exists() and strategy == ConflictStrategy.MERGE:
            existing = item.target_path.read_text(encoding="utf-8")
            content = existing + "\n\n# --- Merged from zeroclaw ---\n" + "\n".join(env_lines) + "\n"
        else:
            content = "\n".join(env_lines) + "\n"
        item.target_path.write_text(content, encoding="utf-8")

    def _migrate_db_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        """zeroclaw has no DB — this should never be called."""
        pass

    # ── Config converters ──

    def _toml_to_env(self, raw: str) -> List[str]:
        """Simple TOML to .env conversion (flat keys only)."""
        lines = ["# Converted from zeroclaw config.toml"]
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip().upper().replace("-", "_").replace(".", "_")
                val = val.strip().strip('"').strip("'")
                lines.append(f"{key}={val}")
        return lines

    def _yaml_to_env(self, raw: str) -> List[str]:
        """Simple YAML to .env conversion (flat keys only)."""
        lines = ["# Converted from zeroclaw config.yaml"]
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip().upper().replace("-", "_").replace(".", "_")
                val = val.strip().strip('"').strip("'")
                if val:
                    lines.append(f"{key}={val}")
        return lines

    # ── Helpers ──

    def _find_config(self) -> Path | None:
        for name in ("config.toml", "config.yaml", "config.yml", ".env"):
            p = self.source_path / name
            if p.exists():
                return p
        return None
