from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from core.config import get_settings

logger = logging.getLogger(__name__)


class MemoryEntry:
    def __init__(self, filename: str, name: str, description: str, mem_type: str, content: str):
        self.filename = filename
        self.name = name
        self.description = description
        self.type = mem_type
        self.content = content

    def to_frontmatter(self) -> str:
        return (
            f"---\n"
            f"name: {self.name}\n"
            f"description: {self.description}\n"
            f"type: {self.type}\n"
            f"---\n\n"
            f"{self.content}"
        )

    @classmethod
    def from_file(cls, path: Path) -> Optional[MemoryEntry]:
        try:
            text = path.read_text(encoding="utf-8")
            match = re.match(
                r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL
            )
            if not match:
                return None
            frontmatter, content = match.group(1), match.group(2).strip()
            meta: Dict[str, str] = {}
            for line in frontmatter.split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip()] = val.strip()
            return cls(
                filename=path.name,
                name=meta.get("name", path.stem),
                description=meta.get("description", ""),
                mem_type=meta.get("type", "project"),
                content=content,
            )
        except (OSError, IOError, ValueError) as e:
            logger.warning("Failed to parse memory file %s: %s", path, e)
            return None


class MemoryManager:
    """Manages persistent .md memory files with MEMORY.md index."""

    def __init__(self, memory_dir: Optional[Path] = None):
        self._dir = memory_dir or get_settings().memory_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "MEMORY.md"
        if not self._index_path.exists():
            self._index_path.write_text("# caliclaw Memory Index\n", encoding="utf-8")

    def save(
        self,
        name: str,
        description: str,
        mem_type: str,
        content: str,
        filename: Optional[str] = None,
    ) -> Path:
        if not filename:
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            filename = f"{mem_type}_{slug}.md"

        entry = MemoryEntry(filename, name, description, mem_type, content)
        path = self._dir / filename
        path.write_text(entry.to_frontmatter(), encoding="utf-8")

        self._update_index(filename, name, description)
        logger.info("Saved memory: %s -> %s", name, filename)
        return path

    def load(self, filename: str) -> Optional[MemoryEntry]:
        path = self._dir / filename
        if path.exists():
            return MemoryEntry.from_file(path)
        return None

    def load_all(self) -> List[MemoryEntry]:
        entries = []
        for path in sorted(self._dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            entry = MemoryEntry.from_file(path)
            if entry:
                entries.append(entry)
        return entries

    def search(self, query: str) -> List[MemoryEntry]:
        query_lower = query.lower()
        results = []
        for entry in self.load_all():
            score = 0
            if query_lower in entry.name.lower():
                score += 3
            if query_lower in entry.description.lower():
                score += 2
            if query_lower in entry.content.lower():
                score += 1
            if score > 0:
                results.append((score, entry))
        results.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in results]

    def delete(self, filename: str) -> bool:
        path = self._dir / filename
        if path.exists():
            path.unlink()
            self._rebuild_index()
            logger.info("Deleted memory: %s", filename)
            return True
        return False

    def get_index(self) -> str:
        return self._index_path.read_text(encoding="utf-8")

    def get_context_for_prompt(self, max_chars: int = 4000) -> str:
        """Get memory content suitable for injection into agent prompt."""
        parts = [self.get_index()]
        total = len(parts[0])

        for entry in self.load_all():
            entry_text = f"\n## {entry.name} ({entry.type})\n{entry.content}"
            if total + len(entry_text) > max_chars:
                break
            parts.append(entry_text)
            total += len(entry_text)

        return "\n".join(parts)

    def _update_index(self, filename: str, name: str, description: str) -> None:
        index_text = self._index_path.read_text(encoding="utf-8")
        link_line = f"- [{name}]({filename}) — {description}"

        # Replace existing entry for this file
        lines = index_text.split("\n")
        new_lines = [l for l in lines if f"]({filename})" not in l]
        new_lines.append(link_line)

        self._index_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def _rebuild_index(self) -> None:
        entries = self.load_all()
        lines = ["# caliclaw Memory Index"]
        for entry in entries:
            lines.append(f"- [{entry.name}]({entry.filename}) — {entry.description}")
        self._index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
