"""Manage engine tool permissions.

When skills with `requires_permissions` are toggled, we update the settings.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Set

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def _load_settings() -> dict:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(settings: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def get_allowed_tools() -> Set[str]:
    """Get currently allowed tools."""
    settings = _load_settings()
    perms = settings.get("permissions", {})
    return set(perms.get("allow", []))


def grant_tools(tools: List[str]) -> None:
    """Add tools to the allow list."""
    if not tools:
        return
    settings = _load_settings()
    perms = settings.setdefault("permissions", {})
    allowed = set(perms.get("allow", []))
    allowed.update(tools)
    perms["allow"] = sorted(allowed)
    _save_settings(settings)
    logger.info("Granted tools: %s", tools)


def revoke_tools(tools: List[str]) -> None:
    """Remove tools from the allow list."""
    if not tools:
        return
    settings = _load_settings()
    perms = settings.get("permissions", {})
    if not perms:
        return
    allowed = set(perms.get("allow", []))
    allowed.difference_update(tools)
    perms["allow"] = sorted(allowed)
    _save_settings(settings)
    logger.info("Revoked tools: %s", tools)


# Base permissions required for caliclaw to work autonomously.
# Without these, every bash/file operation triggers a manual approval prompt
# in the underlying engine, which breaks non-interactive (Telegram) usage.
_BASE_PERMISSIONS = [
    "Bash(*)",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
]


def ensure_base_permissions() -> None:
    """Grant base tool permissions if not already present."""
    current = get_allowed_tools()
    missing = [p for p in _BASE_PERMISSIONS if p not in current]
    if missing:
        grant_tools(missing)


def parse_skill_permissions(skill_md_path: Path) -> List[str]:
    """Parse `requires_permissions` field from a skill's frontmatter."""
    if not skill_md_path.exists():
        return []
    content = skill_md_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return []

    # Extract frontmatter
    end = content.find("\n---", 3)
    if end == -1:
        return []
    frontmatter = content[3:end].strip()

    # Simple YAML-like parsing for requires_permissions block
    perms = []
    in_perms = False
    for line in frontmatter.split("\n"):
        stripped = line.strip()
        if stripped.startswith("requires_permissions:"):
            # Inline list: requires_permissions: [a, b]
            rest = stripped[len("requires_permissions:"):].strip()
            if rest.startswith("[") and rest.endswith("]"):
                items = rest[1:-1].split(",")
                return [i.strip().strip('"').strip("'") for i in items if i.strip()]
            in_perms = True
            continue
        if in_perms:
            if stripped.startswith("- "):
                perms.append(stripped[2:].strip().strip('"').strip("'"))
            elif stripped and not line.startswith(" "):
                # Next field — stop
                break
    return perms
