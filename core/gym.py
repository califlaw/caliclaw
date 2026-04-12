"""caliclaw-gym — community skill marketplace via GitHub.

Skills live in github.com/califlaw/caliclaw-gym repository.
Users can install/publish skills with simple CLI commands.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import List, Optional

from core.config import get_settings

logger = logging.getLogger(__name__)

GYM_REPO = "califlaw/caliclaw-gym"
GYM_RAW_URL = f"https://raw.githubusercontent.com/{GYM_REPO}/main"
GYM_API_URL = f"https://api.github.com/repos/{GYM_REPO}"


def list_remote_skills() -> List[dict]:
    """Fetch list of available skills from caliclaw-gym repo with ratings.

    Returns list of {name, description, url, stars, author} sorted by stars desc.
    """
    try:
        url = f"{GYM_API_URL}/contents/skills"
        with urllib.request.urlopen(url, timeout=10) as resp:
            entries = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to fetch gym skills: %s", e)
        return []

    # Fetch all skill issues with ratings (one API call vs N)
    ratings = _fetch_skill_ratings()

    skills = []
    for entry in entries:
        if entry.get("type") != "dir":
            continue
        name = entry["name"]
        info = ratings.get(name, {})
        skills.append({
            "name": name,
            "description": _fetch_skill_description(name),
            "url": entry.get("html_url", ""),
            "stars": info.get("stars", 0),
            "author": info.get("author", "anonymous"),
            "issue_url": info.get("issue_url", ""),
        })

    # Sort by stars descending, then alphabetically
    skills.sort(key=lambda s: (-s["stars"], s["name"]))
    return skills


def _fetch_skill_ratings() -> dict:
    """Fetch all skill issues from caliclaw-gym and parse ratings.

    Convention: each skill has a GitHub issue titled "skill: <name>" with label 'skill'.
    Returns dict {skill_name: {stars, author, issue_url}}.
    """
    ratings: dict = {}
    try:
        url = f"{GYM_API_URL}/issues?labels=skill&state=open&per_page=100"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            issues = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to fetch skill ratings: %s", e)
        return ratings

    for issue in issues:
        title = issue.get("title", "")
        if not title.startswith("skill:"):
            continue
        skill_name = title[len("skill:"):].strip()
        reactions = issue.get("reactions", {})
        ratings[skill_name] = {
            "stars": reactions.get("+1", 0),
            "author": (issue.get("user") or {}).get("login", "anonymous"),
            "issue_url": issue.get("html_url", ""),
        }
    return ratings


def _fetch_skill_description(skill_name: str) -> str:
    """Fetch the description field from a remote skill's frontmatter."""
    try:
        url = f"{GYM_RAW_URL}/skills/{skill_name}/SKILL.md"
        with urllib.request.urlopen(url, timeout=10) as resp:
            content = resp.read().decode("utf-8")
        # Parse description from frontmatter
        import re
        m = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
        return m.group(1).strip() if m else ""
    except (urllib.error.URLError, OSError):
        return ""


def install_skill(skill_name: str) -> bool:
    """Download a skill from caliclaw-gym and install locally.

    Returns True on success.
    """
    settings = get_settings()
    target_dir = settings.skills_dir / skill_name

    if target_dir.exists():
        logger.warning("Skill already installed locally: %s", skill_name)
        return False

    # Fetch SKILL.md
    try:
        url = f"{GYM_RAW_URL}/skills/{skill_name}/SKILL.md"
        with urllib.request.urlopen(url, timeout=15) as resp:
            content = resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as e:
        logger.error("Failed to download skill %s: %s", skill_name, e)
        return False

    # Save it
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "SKILL.md").write_text(content, encoding="utf-8")

    # Auto-enable
    config_file = settings.project_root / "data" / "enabled_skills.txt"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    enabled = set()
    if config_file.exists():
        enabled = {l.strip() for l in config_file.read_text().split("\n") if l.strip()}
    enabled.add(skill_name)
    config_file.write_text("\n".join(sorted(enabled)) + "\n")

    logger.info("Installed skill from gym: %s", skill_name)
    return True


def publish_skill(skill_name: str) -> str:
    """Generate instructions for publishing a local skill to caliclaw-gym.

    Returns markdown instructions.
    """
    settings = get_settings()
    skill_path = settings.skills_dir / skill_name / "SKILL.md"
    if not skill_path.exists():
        return f"Skill not found locally: {skill_name}"

    return f"""To publish '{skill_name}' to caliclaw-gym:

1. Fork: https://github.com/{GYM_REPO}
2. Clone your fork
3. Copy your skill:
   cp -r {skill_path.parent} <fork>/skills/{skill_name}
4. Commit and push
5. Open a Pull Request

Or use GitHub CLI (one-liner):
   gh repo fork {GYM_REPO} --clone
   cp -r {skill_path.parent} caliclaw-gym/skills/
   cd caliclaw-gym && git add . && git commit -m "Add {skill_name} skill" && gh pr create

Your skill content (SKILL.md):
---
{skill_path.read_text(encoding='utf-8')[:500]}
---
"""
