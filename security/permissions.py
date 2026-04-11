from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class PermissionLevel:
    auto: Set[str] = field(default_factory=lambda: {
        "Read", "Glob", "Grep", "WebSearch",
        "git status", "git diff", "git log",
        "systemctl status", "ps aux", "df -h", "free -m",
        "which", "type", "cat", "ls", "head", "tail",
    })
    confirm_tg: Set[str] = field(default_factory=lambda: {
        "Write", "Edit", "git commit", "git push",
        "pip install", "apt install", "npm install",
        "docker start", "docker stop", "docker restart",
        "cron create", "cron delete",
        "mkdir", "touch", "cp", "mv",
    })
    confirm_terminal: Set[str] = field(default_factory=lambda: {
        "rm -rf", "rm -r",
        "git push --force", "git reset --hard",
        "drop database", "DROP TABLE",
        "systemctl restart", "systemctl stop",
        "iptables", "ufw",
        "passwd", "chmod", "chown",
        "vault access",
        "deploy production",
        "ssh",
        "reboot", "shutdown",
    })


# Dangerous patterns that should ALWAYS require confirmation
DANGEROUS_PATTERNS = [
    re.compile(r"rm\s+-rf?\s+/(?!tmp)"),          # rm on non-tmp root paths
    re.compile(r">\s*/dev/sd"),                     # write to block devices
    re.compile(r"dd\s+if=.*of=/dev/"),              # dd to devices
    re.compile(r"mkfs"),                            # format filesystems
    re.compile(r":(){ :|:& };:"),                   # fork bomb
    re.compile(r"curl.*\|\s*(?:ba)?sh"),            # pipe to shell
    re.compile(r"wget.*\|\s*(?:ba)?sh"),
]


class PermissionChecker:
    """Check if an action requires approval."""

    def __init__(self, levels: Optional[PermissionLevel] = None):
        self.levels = levels or PermissionLevel()

    def check(self, action: str, agent_name: str = "main") -> str:
        """Returns permission level: 'auto', 'confirm_tg', 'confirm_terminal', 'blocked'."""
        action_lower = action.lower().strip()

        # Check dangerous patterns first
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(action):
                return "confirm_terminal"

        # Check terminal-level actions
        for term_action in self.levels.confirm_terminal:
            if term_action.lower() in action_lower:
                return "confirm_terminal"

        # Check TG-level actions
        for tg_action in self.levels.confirm_tg:
            if tg_action.lower() in action_lower:
                return "confirm_tg"

        # Check auto actions
        for auto_action in self.levels.auto:
            if auto_action.lower() in action_lower:
                return "auto"

        # Default: require TG confirmation for unknown actions
        return "confirm_tg"

    def check_bash_command(self, command: str) -> str:
        """Specifically check bash commands."""
        # Extract the base command
        parts = command.strip().split()
        if not parts:
            return "auto"

        base_cmd = parts[0]

        # Always dangerous
        if base_cmd in ("rm", "rmdir") and any(f in parts for f in ("-rf", "-r", "--recursive")):
            return "confirm_terminal"
        if base_cmd in ("reboot", "shutdown", "halt", "poweroff"):
            return "confirm_terminal"
        if base_cmd in ("iptables", "ufw", "firewall-cmd"):
            return "confirm_terminal"

        # Needs TG confirmation
        if base_cmd in ("apt", "apt-get", "yum", "dnf", "pacman"):
            if any(a in parts for a in ("install", "remove", "purge", "upgrade")):
                return "confirm_tg"
        if base_cmd in ("pip", "pip3", "npm", "yarn"):
            if "install" in parts or "uninstall" in parts:
                return "confirm_tg"
        if base_cmd in ("docker", "docker-compose", "podman"):
            if any(a in parts for a in ("rm", "stop", "restart", "down", "prune")):
                return "confirm_tg"
        if base_cmd == "git":
            if "push" in parts:
                return "confirm_tg"
            if "reset" in parts and "--hard" in parts:
                return "confirm_terminal"

        # Check dangerous patterns
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(command):
                return "confirm_terminal"

        # Safe by default for read-only commands
        safe_commands = {
            "ls", "cat", "head", "tail", "grep", "find", "which", "type",
            "echo", "pwd", "whoami", "hostname", "date", "uptime", "df",
            "free", "top", "ps", "id", "env", "printenv", "wc", "sort",
            "uniq", "diff", "file", "stat", "du", "dig", "nslookup",
            "curl", "wget", "ping", "traceroute", "ss", "netstat",
        }
        if base_cmd in safe_commands:
            return "auto"

        return "confirm_tg"
