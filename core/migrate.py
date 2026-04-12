"""Migration framework for importing data from other *claw projects into caliclaw."""
from __future__ import annotations

import abc
import enum
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from core.config import get_settings


# ── Enums ──


class MigrationComponent(enum.Enum):
    SOUL = "soul"
    MEMORY = "memory"
    SKILLS = "skills"
    DB = "db"
    CONFIG = "config"
    MEDIA = "media"


class ConflictStrategy(enum.Enum):
    OVERWRITE = "overwrite"
    SKIP = "skip"
    MERGE = "merge"


# ── Data models ──


@dataclass
class MigrationItem:
    """One unit of migration work."""
    component: MigrationComponent
    source_path: Optional[Path]     # None for DB rows
    target_path: Optional[Path]
    description: str
    conflict: bool = False          # True if target already exists
    action: str = "copy"            # copy, merge, convert, import, skip
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MigrationPlan:
    """Computed before execution; shown in dry-run."""
    source_name: str
    source_path: Path
    items: List[MigrationItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return any(i.conflict for i in self.items)

    def summary(self) -> Dict[MigrationComponent, int]:
        counts: Dict[MigrationComponent, int] = {}
        for item in self.items:
            counts[item.component] = counts.get(item.component, 0) + 1
        return counts


@dataclass
class MigrationResult:
    success: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    backup_path: Optional[Path] = None


# ── Registry (populated after BaseMigrator is defined) ──

_REGISTRY: Dict[str, Type["BaseMigrator"]] = {}


def register_migrator(cls: Type["BaseMigrator"]) -> Type["BaseMigrator"]:
    """Decorator to register a migrator class."""
    _REGISTRY[cls.source_name] = cls
    return cls


def get_migrator(name: str) -> Optional[Type["BaseMigrator"]]:
    return _REGISTRY.get(name)


def list_migrators() -> Dict[str, str]:
    """Return {name: description} of all registered migrators."""
    return {name: cls.source_description for name, cls in sorted(_REGISTRY.items())}


def detect_source(path: Path) -> Optional[str]:
    """Auto-detect which *claw project lives at path.

    Checks for definitive markers first (config files with project name),
    then falls back to trying each migrator's validate_source().
    """
    path = path.resolve()

    # Definitive markers — check first, no ambiguity
    if (path / "openclaw.json").exists():
        return "openclaw"
    if (path / "nanoclaw.yaml").exists() or (path / "nanoclaw.json").exists():
        return "nanoclaw"
    if (path / "zeroclaw.toml").exists() or (path / "zeroclaw.json").exists():
        return "zeroclaw"
    # zeroclaw uses config.toml + workspace/ with SOUL.md
    if (path / "config.toml").exists() and (path / "workspace").is_dir():
        return "zeroclaw"
    # dirname hint: ~/.zeroclaw/
    if path.name == ".zeroclaw" and (path / "workspace").is_dir():
        return "zeroclaw"

    # Fallback: try each migrator's validator
    for name, cls in _REGISTRY.items():
        try:
            m = cls(path)
            if not m.validate_source():
                return name
        except (RuntimeError, ValueError, OSError):
            continue
    return None


# ── Backup ──


def create_backup(settings=None) -> Path:
    """Create a timestamped backup of current caliclaw state before migration."""
    s = settings or get_settings()
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = s.project_root / "backups" / f"pre_migrate_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for src_dir, name in [
        (s.agents_dir, "agents"),
        (s.memory_dir, "memory"),
        (s.skills_dir, "skills"),
        (s.data_dir, "data"),
    ]:
        if src_dir.exists():
            shutil.copytree(src_dir, backup_dir / name, dirs_exist_ok=True)

    env_file = s.project_root / ".env"
    if env_file.exists():
        shutil.copy2(env_file, backup_dir / ".env")

    return backup_dir


# ── Abstract base migrator ──


class BaseMigrator(abc.ABC):
    """Abstract base for all *claw migrators."""

    source_name: str = ""
    source_description: str = ""

    def __init__(self, source_path: Path, settings=None):
        self.source_path = source_path.resolve()
        self.settings = settings or get_settings()

    # ---- Validation ----

    @abc.abstractmethod
    def validate_source(self) -> List[str]:
        """Return list of errors. Empty = valid."""
        ...

    # ---- Discovery ----

    @abc.abstractmethod
    def discover_components(self) -> Dict[MigrationComponent, bool]:
        """Return {component: available} for each type."""
        ...

    # ---- Planning ----

    @abc.abstractmethod
    def plan(
        self,
        components: List[MigrationComponent],
        conflict_strategy: ConflictStrategy,
    ) -> MigrationPlan:
        """Build a plan without executing anything."""
        ...

    # ---- Execution ----

    def execute(
        self,
        plan: MigrationPlan,
        conflict_strategy: ConflictStrategy,
    ) -> MigrationResult:
        """Execute a migration plan."""
        result = MigrationResult()
        for item in plan.items:
            if item.action == "skip":
                result.skipped += 1
                continue
            try:
                handler = self._get_handler(item.component)
                handler(item, conflict_strategy)
                result.success += 1
            except (OSError, IOError, RuntimeError, ValueError) as e:
                result.failed += 1
                result.errors.append(f"{item.description}: {e}")
        return result

    def _get_handler(self, component: MigrationComponent) -> Callable:
        handlers = {
            MigrationComponent.SOUL: self._migrate_soul_item,
            MigrationComponent.MEMORY: self._migrate_memory_item,
            MigrationComponent.SKILLS: self._migrate_skill_item,
            MigrationComponent.DB: self._migrate_db_item,
            MigrationComponent.CONFIG: self._migrate_config_item,
            MigrationComponent.MEDIA: self._migrate_media_item,
        }
        return handlers[component]

    # ---- Default handlers (override if format differs) ----

    def _migrate_soul_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        self._copy_file(item, strategy)

    def _migrate_memory_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        self._copy_file(item, strategy)

    def _migrate_skill_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        self._copy_file(item, strategy)

    def _migrate_config_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        self._copy_file(item, strategy)

    def _migrate_media_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        self._copy_file(item, strategy)

    @abc.abstractmethod
    def _migrate_db_item(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        """DB migration always differs between projects."""
        ...

    # ---- Helpers ----

    def _copy_file(self, item: MigrationItem, strategy: ConflictStrategy) -> None:
        if item.target_path is None or item.source_path is None:
            return
        if item.target_path.exists():
            if strategy == ConflictStrategy.SKIP:
                return
            if strategy == ConflictStrategy.MERGE:
                self._merge_files(item.source_path, item.target_path)
                return
        item.target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.source_path, item.target_path)

    def _merge_files(self, source: Path, target: Path) -> None:
        """Append source content to target with separator."""
        existing = target.read_text(encoding="utf-8")
        new_content = source.read_text(encoding="utf-8")
        merged = f"{existing}\n\n---\n<!-- Merged from migration -->\n\n{new_content}"
        target.write_text(merged, encoding="utf-8")

    def _plan_file(
        self,
        plan: MigrationPlan,
        component: MigrationComponent,
        src: Path,
        tgt: Path,
        description: str,
        strategy: ConflictStrategy,
        action: str = "copy",
        details: Optional[Dict] = None,
    ) -> None:
        """Helper to add a file item to the plan."""
        if not src.exists():
            return
        conflict = tgt.exists()
        effective_action = action
        if conflict and strategy == ConflictStrategy.SKIP:
            effective_action = "skip"
        plan.items.append(MigrationItem(
            component=component,
            source_path=src,
            target_path=tgt,
            description=description,
            conflict=conflict,
            action=effective_action,
            details=details or {},
        ))

    def _import_table_rows(
        self,
        src_db_path: Path,
        table: str,
        column_map: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Read rows from source SQLite table with optional column remapping."""
        import sqlite3
        conn = sqlite3.connect(str(src_db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(f"SELECT * FROM {table}")  # noqa: S608
            rows = [dict(r) for r in cur.fetchall()]
            if column_map:
                mapped = []
                for row in rows:
                    new_row = {}
                    for src_col, tgt_col in column_map.items():
                        if src_col in row:
                            new_row[tgt_col] = row[src_col]
                    mapped.append(new_row)
                return mapped
            return rows
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
