from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


def _project_root() -> Path:
    """Resolve project root: env var > cwd > source checkout > user home."""
    env = os.environ.get("CALICLAW_HOME") or os.environ.get("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    # If cwd has .env or agents/, we're in a caliclaw project
    cwd = Path.cwd()
    if (cwd / ".env").exists() or (cwd / "agents").exists():
        return cwd
    # Source checkout: package sits next to agents/ dir
    pkg_parent = Path(__file__).resolve().parent.parent
    if (pkg_parent / "agents").exists() and (pkg_parent / "skills").exists():
        return pkg_parent
    # Pip install — per-user config dir in ~/.caliclaw
    return Path.home() / ".caliclaw"


def bundled_skills_path() -> Path:
    """Return the path to the bundled default skills.

    Works both for source clones (./skills) and pip-installed wheels
    (site-packages/skills).
    """
    # Source checkout — skills are next to the package
    src = Path(__file__).resolve().parent.parent / "skills"
    if src.exists() and any(src.glob("*/SKILL.md")):
        return src
    # Pip install — skills is a subpackage
    try:
        import skills as _skills_pkg
        return Path(_skills_pkg.__file__).resolve().parent
    except ImportError:
        return src


def detect_system_tz() -> str:
    """Auto-detect the IANA timezone name from the host OS. Falls back to UTC."""
    # Debian/Ubuntu
    try:
        tz = Path("/etc/timezone").read_text().strip()
        if tz:
            return tz
    except OSError:
        pass
    # /etc/localtime symlink (most distros, macOS)
    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    # TZ env var as last resort
    env_tz = os.environ.get("TZ", "").strip()
    if env_tz:
        return env_tz
    return "UTC"


class Settings(BaseSettings):
    model_config = {"env_file": str(_project_root() / ".env"), "extra": "ignore"}

    # Telegram
    telegram_bot_token: str = ""
    telegram_allowed_users: List[int] = Field(default_factory=list)

    @field_validator("telegram_allowed_users", mode="before")
    @classmethod
    def parse_allowed_users(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v

    # Engine
    claude_binary: str = "claude"  # legacy alias, kept for backward compat
    claude_default_model: str = "sonnet"
    freedom_mode: bool = False

    @property
    def engine_binary(self) -> str:
        """Path to the caliclaw engine wrapper."""
        wrapper = self.project_root / "bin" / "caliclaw-engine"
        if wrapper.exists():
            return str(wrapper)
        return self.claude_binary

    # Paths
    project_root: Path = Field(default_factory=_project_root)
    data_dir: Path = Field(default_factory=lambda: _project_root() / "data")
    workspace_dir: Path = Field(default_factory=lambda: _project_root() / "workspace")
    agents_dir: Path = Field(default_factory=lambda: _project_root() / "agents")
    skills_dir: Path = Field(default_factory=lambda: _project_root() / "skills")
    memory_dir: Path = Field(default_factory=lambda: _project_root() / "memory")

    # Limits
    max_concurrent_agents: int = 3
    max_loop_iterations: int = 20
    max_loop_duration_minutes: int = 120
    usage_pause_percent: int = 80
    usage_emergency_percent: int = 90
    usage_stop_percent: int = 95

    # Heartbeat cron expressions
    heartbeat_quick_cron: str = "0 */2 * * *"
    heartbeat_review_cron: str = "0 */6 * * *"
    heartbeat_morning_cron: str = "0 9 * * *"
    heartbeat_dream_cron: str = "0 3 * * *"

    # Auto-backup
    backup_enabled: bool = False
    backup_interval_days: int = 7  # weekly by default

    # Whisper
    whisper_cpp_path: str = "/usr/local/bin/whisper-cpp"
    whisper_model_path: str = str(_project_root() / "models" / "ggml-base.bin")

    # Vault
    vault_key_path: Path = Path.home() / ".caliclaw" / "vault.key"

    # Dashboard
    dashboard_port: int = 8080
    dashboard_enabled: bool = True

    # Timezone
    tz: str = "Europe/Moscow"

    # Logging
    log_level: str = "INFO"

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.workspace_dir,
            self.workspace_dir / "conversations",
            self.workspace_dir / "media",
            self.workspace_dir / "ipc",
            self.workspace_dir / "projects",
            self.agents_dir,
            self.skills_dir,
            self.memory_dir,
            self.project_root / "logs",
        ):
            d.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
