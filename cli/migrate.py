"""CLI integration for `caliclaw migrate` command.

Simple usage:
    caliclaw migrate ~/path/to/project     # auto-detect type, interactive
    caliclaw migrate ~/path -y             # auto-detect, no prompts, migrate all

Advanced:
    caliclaw migrate openclaw ~/path       # explicit type
    caliclaw migrate ~/path --only soul,memory
    caliclaw migrate ~/path --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from core.migrate import (
    ConflictStrategy,
    MigrationComponent,
    MigrationPlan,
    create_backup,
    detect_source,
    get_migrator,
    list_migrators,
)

# Trigger auto-discovery of migrator modules
import core.migrators  # noqa: F401

ALL_COMPONENTS = list(MigrationComponent)

_COMPONENT_LABELS = {
    MigrationComponent.SOUL: "Soul (личность, правила)",
    MigrationComponent.MEMORY: "Memory (память)",
    MigrationComponent.SKILLS: "Skills (навыки)",
    MigrationComponent.DB: "Database (история, сессии)",
    MigrationComponent.CONFIG: "Config (.env настройки)",
    MigrationComponent.MEDIA: "Media (файлы, аудио)",
}


def register_migrate_parser(subparsers) -> None:
    """Register the 'migrate' subcommand in caliclaw CLI."""
    p = subparsers.add_parser(
        "migrate",
        help="Migrate from another *claw project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  caliclaw migrate ~/openclaw-project\n"
            "  caliclaw migrate ~/nanoclaw --only soul,memory\n"
            "  caliclaw migrate openclaw ~/path --dry-run\n"
            "  caliclaw migrate ~/path -y\n"
        ),
    )
    # Positional: either just path (auto-detect) or source + path
    p.add_argument("first", nargs="?", help="Path to project (or source type)")
    p.add_argument("second", nargs="?", help="Path (if first arg is source type)")

    p.add_argument("--only", help="Comma-separated components: soul,memory,skills,db,config,media")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing files on conflict")
    p.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    p.add_argument("--no-backup", action="store_true", help="Skip automatic backup")
    p.add_argument("-y", "--yes", action="store_true", help="Skip all prompts, migrate everything")


def cmd_migrate(args: argparse.Namespace) -> None:
    """Execute the migrate command."""
    # No args — show help
    if not args.first:
        _print_help()
        return

    # Resolve source type and path
    source_name, source_path = _resolve_args(args)

    if source_name is None:
        print(f"Не удалось определить тип проекта в {source_path}")
        print("Укажите тип явно: caliclaw migrate openclaw|nanoclaw|zeroclaw <путь>")
        _print_sources()
        sys.exit(1)

    migrator_cls = get_migrator(source_name)
    if migrator_cls is None:
        print(f"Неизвестный тип: '{source_name}'")
        _print_sources()
        sys.exit(1)

    from core.config import get_settings
    migrator = migrator_cls(source_path, settings=get_settings())

    # Validate
    errors = migrator.validate_source()
    if errors:
        print(f"Ошибка валидации {source_name} в {source_path}:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    # Discover
    available = migrator.discover_components()
    available_list = [c for c, v in available.items() if v]

    print(f"\n  Проект: {source_name}")
    print(f"  Путь:   {source_path}\n")

    if not available_list:
        print("Нечего мигрировать — проект пустой.")
        return

    # Show what's available
    print("Доступно для миграции:")
    for i, comp in enumerate(available_list, 1):
        label = _COMPONENT_LABELS.get(comp, comp.value)
        print(f"  {i}. {label}")

    # Determine what to migrate
    if args.only:
        # Explicit --only
        components = _parse_only(args.only, available_list)
    elif args.yes:
        # -y = migrate everything
        components = available_list
    else:
        # Interactive
        components = _ask_components(available_list)

    if not components:
        print("\nНичего не выбрано.")
        return

    # Conflict strategy
    strategy = ConflictStrategy.OVERWRITE if args.overwrite else ConflictStrategy.SKIP

    # Build plan
    plan = migrator.plan(components, strategy)
    _print_plan(plan)

    if args.dry_run:
        print("\n[DRY RUN] Изменения не внесены.")
        return

    if not plan.items:
        return

    # Confirm
    if not args.yes:
        answer = input("\nМигрировать? (y/n): ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return

    # Backup
    if not args.no_backup:
        print("Бэкап...", end=" ", flush=True)
        backup_path = create_backup()
        print(f"ok -> {backup_path}")

    # Execute
    print("Миграция...")
    result = migrator.execute(plan, strategy)

    print(f"\nГотово: {result.success} перенесено, {result.skipped} пропущено, {result.failed} ошибок")
    if result.errors:
        print("Ошибки:")
        for e in result.errors:
            print(f"  - {e}")


# ── Helpers ──


def _resolve_args(args: argparse.Namespace) -> tuple[Optional[str], Path]:
    """Figure out source_name and source_path from positional args.

    Supports:
      caliclaw migrate ~/path           -> auto-detect type
      caliclaw migrate openclaw ~/path  -> explicit type
    """
    first = args.first
    second = getattr(args, "second", None)

    known_sources = set(list_migrators().keys())

    if first in known_sources:
        # Explicit: caliclaw migrate openclaw ~/path
        path = Path(second).resolve() if second else Path(".").resolve()
        return first, path
    else:
        # Auto-detect: caliclaw migrate ~/path
        path = Path(first).resolve()
        if not path.is_dir():
            print(f"Директория не найдена: {path}")
            sys.exit(1)
        source_name = detect_source(path)
        return source_name, path


def _ask_components(available: List[MigrationComponent]) -> List[MigrationComponent]:
    """Interactive component selection with checkboxes."""
    from cli.ui import ui

    _LABELS = {
        MigrationComponent.SOUL: "Soul (personality, rules)",
        MigrationComponent.MEMORY: "Memory",
        MigrationComponent.SKILLS: "Skills",
        MigrationComponent.DB: "Database (history, sessions)",
        MigrationComponent.CONFIG: "Config (.env)",
        MigrationComponent.MEDIA: "Media (files, audio)",
    }

    options = [(c.value, _LABELS.get(c, c.value), True) for c in available]
    selected_values = ui.checkbox(options, title="What to migrate?")
    return [c for c in available if c.value in selected_values]


def _parse_only(only_str: str, available: List[MigrationComponent]) -> List[MigrationComponent]:
    """Parse --only soul,memory,skills into component list."""
    names = {c.value: c for c in available}
    result = []
    for part in only_str.split(","):
        part = part.strip().lower()
        if part in names:
            result.append(names[part])
        else:
            print(f"Неизвестный компонент: '{part}'. Доступны: {', '.join(names.keys())}")
    return result


def _print_plan(plan: MigrationPlan) -> None:
    if not plan.items:
        print("\nНечего мигрировать.")
        return

    print(f"\nПлан ({len(plan.items)} элементов):")
    for item in plan.items:
        marker = " *" if item.conflict else ""
        print(f"  [{item.action:>9}] {item.description}{marker}")

    if plan.warnings:
        for w in plan.warnings:
            print(f"  ! {w}")
    if plan.errors:
        for e in plan.errors:
            print(f"  X {e}")


def _print_help() -> None:
    print("Миграция из другого *claw проекта в caliclaw\n")
    print("Использование:")
    print("  caliclaw migrate <путь>                  автоопределение типа")
    print("  caliclaw migrate <тип> <путь>            явное указание типа")
    print("  caliclaw migrate <путь> --dry-run        показать план")
    print("  caliclaw migrate <путь> -y               без вопросов")
    print("  caliclaw migrate <путь> --only soul,memory")
    print()
    _print_sources()


def _print_sources() -> None:
    migrators = list_migrators()
    if not migrators:
        return
    print("Поддерживаемые проекты:")
    for name, desc in migrators.items():
        print(f"  {name:<16} {desc}")
