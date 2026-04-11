from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Assertion:
    pattern: str
    action: str  # block | warn | require_backup
    reason: str
    compiled: re.Pattern = None  # type: ignore

    def __post_init__(self) -> None:
        self.compiled = re.compile(self.pattern, re.IGNORECASE)


# Ground truth assertions for bash commands
DEFAULT_ASSERTIONS: List[Assertion] = [
    Assertion(
        pattern=r"rm\s+-rf?\s+/[^t]",
        action="block",
        reason="Deletion of root-level directories is blocked",
    ),
    Assertion(
        pattern=r"rm\s+-rf?\s+~",
        action="block",
        reason="Deletion of home directory is blocked",
    ),
    Assertion(
        pattern=r">\s*/etc/",
        action="block",
        reason="Direct write to /etc/ is blocked. Use proper tools.",
    ),
    Assertion(
        pattern=r"chmod\s+777",
        action="warn",
        reason="chmod 777 is a security risk",
    ),
    Assertion(
        pattern=r"curl.*\|\s*(?:ba)?sh",
        action="block",
        reason="Piping curl to shell is blocked for security",
    ),
    Assertion(
        pattern=r"git\s+push.*--force",
        action="warn",
        reason="Force push can destroy remote history",
    ),
    Assertion(
        pattern=r"DROP\s+(?:TABLE|DATABASE)",
        action="block",
        reason="DROP operations are blocked. Use migrations.",
    ),
    Assertion(
        pattern=r"TRUNCATE\s+TABLE",
        action="warn",
        reason="TRUNCATE will delete all data from the table",
    ),
]


class AssertionChecker:
    """Checks commands against ground truth assertions."""

    def __init__(self, assertions: Optional[List[Assertion]] = None):
        self.assertions = assertions or DEFAULT_ASSERTIONS

    def check(self, command: str) -> List[Tuple[str, str]]:
        """Check command against assertions.
        Returns list of (action, reason) tuples for violations."""
        violations = []
        for assertion in self.assertions:
            if assertion.compiled.search(command):
                violations.append((assertion.action, assertion.reason))
        return violations

    def is_blocked(self, command: str) -> Optional[str]:
        """Returns block reason if command should be blocked, else None."""
        for action, reason in self.check(command):
            if action == "block":
                return reason
        return None

    def get_warnings(self, command: str) -> List[str]:
        """Returns list of warning messages for a command."""
        return [reason for action, reason in self.check(command) if action == "warn"]


class ContradictionDetector:
    """Detects contradictions in agent statements about system state."""

    def __init__(self) -> None:
        self._facts: dict[str, Tuple[str, float]] = {}  # key -> (value, timestamp)

    def record_fact(self, key: str, value: str, timestamp: float) -> Optional[str]:
        """Record a fact and return contradiction message if any."""
        if key in self._facts:
            old_value, old_ts = self._facts[key]
            if old_value != value:
                msg = (
                    f"Contradiction detected: '{key}' was '{old_value}' "
                    f"but now '{value}'"
                )
                logger.warning(msg)
                self._facts[key] = (value, timestamp)
                return msg

        self._facts[key] = (value, timestamp)
        return None

    def clear(self) -> None:
        self._facts.clear()


class DryRunFormatter:
    """Formats commands for dry-run preview."""

    @staticmethod
    def format_preview(action: str, details: str, consequences: str = "") -> str:
        lines = [
            "🔍 **Dry Run Preview**",
            f"**Action:** `{action}`",
            f"**Details:** {details}",
        ]
        if consequences:
            lines.append(f"**Consequences:** {consequences}")
        lines.append("\nConfirm to execute.")
        return "\n".join(lines)
