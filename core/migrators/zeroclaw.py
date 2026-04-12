"""Migrator for zeroclaw projects.

Real zeroclaw layout (~/.zeroclaw/):
  config.toml                            main config (TOML)
  auth-profiles.json                     auth profiles
  workspace/
    SOUL.md, IDENTITY.md, USER.md        soul files
    AGENTS.md, MEMORY.md                 agent rules + memory index
    skills/<name>/SKILL.md               skills
  media/                                 media files

Legacy layout (old zeroclaw):
  soul/SOUL.md, soul/IDENTITY.md         soul files
  notes/*.txt                            flat text memory
  config.toml or config.yaml             config
"""
from __future__ import annotations

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
class ZeroclawMigrator(BaseMigrator):
    source_name = "zeroclaw"
    source_description = "Migrate from zeroclaw (TOML config, workspace layout)"

    _SOUL_FILES = ["SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md"]

    def _workspace(self) -> Path:
        ws = self.source_path / "workspace"
        return ws if ws.is_dir() else self.source_path

    def _soul_dir(self) -> Path:
        ws = self._workspace()
        if any((ws / f).exists() for f in self._SOUL_FILES):
            return ws
        legacy = self.source_path / "soul"
        return legacy if legacy.is_dir() else ws

    def validate_source(self) -> List[str]:
        errors = []
        if not self.source_path.is_dir():
            errors.append(f"Not a directory: {self.source_path}")
            return errors
        has_workspace = (self.source_path / "workspace").is_dir()
        has_soul = (self.source_path / "soul").is_dir()
        has_config = self._find_config() is not None
        if not has_workspace and not has_soul and not has_config:
            errors.append("No workspace/, soul/, or config found. Not a valid zeroclaw project.")
        return errors

    def discover_components(self) -> Dict[MigrationComponent, bool]:
        sd = self._soul_dir()
        ws = self._workspace()
        p = self.source_path

        has_soul = any((sd / f).exists() for f in self._SOUL_FILES)
        has_memory = (
            (ws / "MEMORY.md").exists()
            or ((p / "notes").is_dir() and any((p / "notes").glob("*.txt")))
        )
        has_skills = False
        skills_dir = ws / "skills"
        if skills_dir.is_dir():
            has_skills = any(skills_dir.glob("*/SKILL.md"))
        if not has_skills:
            legacy_skills = p / "skills"
            if legacy_skills.is_dir():
                has_skills = any(legacy_skills.glob("*/SKILL.md"))
        has_config = self._find_config() is not None
        has_media = False
        for media_candidate in [p / "media", ws / "media"]:
            if media_candidate.is_dir() and any(media_candidate.iterdir()):
                has_media = True
                break

        return {
            MigrationComponent.SOUL: has_soul,
            MigrationComponent.MEMORY: has_memory,
            MigrationComponent.SKILLS: has_skills,
            MigrationComponent.DB: False,
            MigrationComponent.CONFIG: has_config,
            MigrationComponent.MEDIA: has_media,
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
        sd = self._soul_dir()
        tgt_dir = self.settings.agents_dir / "global" / "main"
        for md_file in sorted(sd.glob("*.md")):
            self._plan_file(
                plan, MigrationComponent.SOUL,
                md_file, tgt_dir / md_file.name,
                f"Soul: {md_file.name}", strategy,
            )

    def _plan_memory(self, plan: MigrationPlan, strategy: ConflictStrategy) -> None:
        ws = self._workspace()
        # New: MEMORY.md in workspace
        mem_md = ws / "MEMORY.md"
        if mem_md.exists():
            self._plan_file(
                plan, MigrationComponent.MEMORY,
                mem_md, self.settings.memory_dir / "MEMORY.md",
                "Memory: MEMORY.md index", strategy,
            )
        # Legacy: notes/*.txt
        notes_dir = self.source_path / "notes"
        if notes_dir.is_dir():
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
        ws = self._workspace()
        for candidate in [ws / "skills", self.source_path / "skills"]:
            if not candidate.is_dir():
                continue
            for skill_dir in sorted(candidate.iterdir()):
                if not skill_dir.is_dir():
                    continue
                for skill_file in ["SKILL.md", "SKILL.toml"]:
                    src = skill_dir / skill_file
                    if src.exists():
                        tgt = self.settings.skills_dir / skill_dir.name / "SKILL.md"
                        self._plan_file(
                            plan, MigrationComponent.SKILLS,
                            src, tgt, f"Skill: {skill_dir.name}", strategy,
                        )
                        break

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
        for candidate in [self.source_path / "media", self._workspace() / "media"]:
            if not candidate.is_dir():
                continue
            tgt_media = self.settings.workspace_dir / "media"
            for f in sorted(candidate.iterdir()):
                if f.is_file():
                    self._plan_file(
                        plan, MigrationComponent.MEDIA,
                        f, tgt_media / f.name, f"Media: {f.name}", strategy,
                    )
            break

    # ── Execution overrides ──

    def _migrate_memory_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
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
            env_lines = [f"# Imported from {item.source_path.name}", raw]

        item.target_path.parent.mkdir(parents=True, exist_ok=True)
        if item.target_path.exists() and strategy == ConflictStrategy.MERGE:
            existing = item.target_path.read_text(encoding="utf-8")
            content = existing + "\n\n# --- Merged from zeroclaw ---\n" + "\n".join(env_lines) + "\n"
        else:
            content = "\n".join(env_lines) + "\n"
        item.target_path.write_text(content, encoding="utf-8")

    def _migrate_db_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        pass

    # ── Config converters ──

    def _toml_to_env(self, raw: str) -> List[str]:
        lines = ["# Converted from zeroclaw config.toml"]
        section = ""
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("["):
                section = line.strip("[]").strip().replace(".", "_").upper() + "_"
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = section + key.strip().upper().replace("-", "_")
                val = val.strip().strip('"').strip("'")
                if key == "BOT_TOKEN":
                    key = "TELEGRAM_BOT_TOKEN"
                elif key == "DEFAULT_PROVIDER":
                    continue
                elif key == "API_KEY":
                    continue
                lines.append(f"{key}={val}")
        return lines

    def _yaml_to_env(self, raw: str) -> List[str]:
        lines = ["# Converted from zeroclaw config.yaml"]
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip().upper().replace("-", "_")
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
