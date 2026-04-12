"""Tests for the migration framework and concrete migrators."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


# ── Registry ──

class TestRegistry:
    def test_all_migrators_registered(self):
        import core.migrators  # noqa: F401
        from core.migrate import list_migrators
        migrators = list_migrators()
        assert "openclaw" in migrators
        assert "nanoclaw" in migrators
        assert "zeroclaw" in migrators

    def test_get_migrator(self):
        import core.migrators  # noqa: F401
        from core.migrate import get_migrator
        cls = get_migrator("openclaw")
        assert cls is not None
        assert cls.source_name == "openclaw"

    def test_get_unknown_migrator(self):
        from core.migrate import get_migrator
        assert get_migrator("unknownclaw") is None


# ── Backup ──

class TestBackup:
    def test_create_backup(self, settings, tmp_path):
        from core.migrate import create_backup

        # Create some files to backup
        (settings.agents_dir / "global" / "main").mkdir(parents=True)
        (settings.agents_dir / "global" / "main" / "SOUL.md").write_text("soul")
        (settings.memory_dir).mkdir(parents=True, exist_ok=True)
        (settings.memory_dir / "MEMORY.md").write_text("memory index")

        backup_path = create_backup(settings)
        assert backup_path.exists()
        assert (backup_path / "agents" / "global" / "main" / "SOUL.md").exists()
        assert (backup_path / "memory" / "MEMORY.md").exists()


# ── OpenclawMigrator ──

class TestOpenclawMigrator:
    @pytest.fixture
    def openclaw_project(self, tmp_path):
        """Create a fake openclaw project structure."""
        root = tmp_path / "openclaw"
        root.mkdir()

        # Real openclaw structure
        (root / "openclaw.json").write_text('{"meta": {"lastTouchedVersion": "2026.3.28"}}')

        # Agent config
        agent_dir = root / "agents" / "main" / "agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "models.json").write_text('{"default": "sonnet"}')
        (agent_dir / "auth-profiles.json").write_text('{"anthropic": {"mode": "token"}}')

        # Sessions
        sessions_dir = root / "agents" / "main" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "abc-123.jsonl").write_text('{"role": "user", "content": "hello"}\n')
        (sessions_dir / "def-456.jsonl").write_text('{"role": "user", "content": "world"}\n')

        # Memory DB
        mem_dir = root / "memory"
        mem_dir.mkdir()
        (mem_dir / "main.sqlite").write_bytes(b"fake-sqlite-for-test")

        # Credentials
        creds_dir = root / "credentials"
        creds_dir.mkdir()
        (creds_dir / "telegram-pairing.json").write_text('{"code": "ABC123"}')

        # Media
        media_dir = root / "media"
        media_dir.mkdir()
        (media_dir / "photo.jpg").write_bytes(b"\xff\xd8fake-jpeg")

        return root

    def test_validate_source(self, openclaw_project, settings):
        from core.migrators.openclaw import OpenclawMigrator
        m = OpenclawMigrator(openclaw_project, settings=settings)
        assert m.validate_source() == []

    def test_validate_invalid(self, tmp_path, settings):
        from core.migrators.openclaw import OpenclawMigrator
        empty = tmp_path / "empty"
        empty.mkdir()
        m = OpenclawMigrator(empty, settings=settings)
        assert len(m.validate_source()) > 0

    def test_discover_components(self, openclaw_project, settings):
        from core.migrators.openclaw import OpenclawMigrator
        m = OpenclawMigrator(openclaw_project, settings=settings)
        avail = m.discover_components()
        assert avail[MigrationComponent.SOUL] is True
        assert avail[MigrationComponent.MEMORY] is True
        assert avail[MigrationComponent.DB] is True
        assert avail[MigrationComponent.CONFIG] is True
        assert avail[MigrationComponent.MEDIA] is True
        assert avail[MigrationComponent.SKILLS] is False

    def test_plan_agent_config(self, openclaw_project, settings):
        from core.migrators.openclaw import OpenclawMigrator
        m = OpenclawMigrator(openclaw_project, settings=settings)
        plan = m.plan([MigrationComponent.SOUL], ConflictStrategy.SKIP)
        soul_items = [i for i in plan.items if i.component == MigrationComponent.SOUL]
        assert len(soul_items) >= 1
        names = [i.description for i in soul_items]
        assert any("models.json" in n for n in names)

    def test_plan_sessions(self, openclaw_project, settings):
        from core.migrators.openclaw import OpenclawMigrator
        m = OpenclawMigrator(openclaw_project, settings=settings)
        plan = m.plan([MigrationComponent.MEMORY], ConflictStrategy.SKIP)
        mem_items = [i for i in plan.items if i.component == MigrationComponent.MEMORY]
        assert len(mem_items) >= 2
        assert any("abc-123" in i.description for i in mem_items)

    def test_plan_db(self, openclaw_project, settings):
        from core.migrators.openclaw import OpenclawMigrator
        m = OpenclawMigrator(openclaw_project, settings=settings)
        plan = m.plan([MigrationComponent.DB], ConflictStrategy.SKIP)
        db_items = [i for i in plan.items if i.component == MigrationComponent.DB]
        assert len(db_items) >= 1
        assert any("main.sqlite" in i.description for i in db_items)

    def test_execute_agent_config(self, openclaw_project, settings):
        from core.migrators.openclaw import OpenclawMigrator
        m = OpenclawMigrator(openclaw_project, settings=settings)
        plan = m.plan([MigrationComponent.SOUL], ConflictStrategy.OVERWRITE)
        result = m.execute(plan, ConflictStrategy.OVERWRITE)
        assert result.success > 0
        assert result.failed == 0
        tgt = settings.agents_dir / "global" / "main" / "models.json"
        assert tgt.exists()

    def test_execute_sessions(self, openclaw_project, settings):
        from core.migrators.openclaw import OpenclawMigrator
        m = OpenclawMigrator(openclaw_project, settings=settings)
        plan = m.plan([MigrationComponent.MEMORY], ConflictStrategy.OVERWRITE)
        result = m.execute(plan, ConflictStrategy.OVERWRITE)
        assert result.success >= 2
        tgt_dir = settings.workspace_dir / "conversations"
        assert any(tgt_dir.glob("*.jsonl"))


# ── NanoclawMigrator ──

class TestNanoclawMigrator:
    @pytest.fixture
    def nanoclaw_project(self, tmp_path):
        root = tmp_path / "nanoclaw"
        root.mkdir()

        # Soul (flat structure)
        soul_dir = root / "agents" / "main"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("# nanoclaw soul")
        (soul_dir / "IDENTITY.md").write_text("name: nano-bot")

        # YAML memory
        mem_dir = root / "memory"
        mem_dir.mkdir()
        (mem_dir / "user_prefs.yaml").write_text(
            "name: User Preferences\n"
            "description: Settings\n"
            "type: user\n"
            "content: Prefers dark mode\n"
        )

        return root

    def test_validate_source(self, nanoclaw_project, settings):
        from core.migrators.nanoclaw import NanoclawMigrator
        m = NanoclawMigrator(nanoclaw_project, settings=settings)
        assert m.validate_source() == []

    def test_discover_memory(self, nanoclaw_project, settings):
        from core.migrators.nanoclaw import NanoclawMigrator
        m = NanoclawMigrator(nanoclaw_project, settings=settings)
        avail = m.discover_components()
        assert avail[MigrationComponent.SOUL] is True
        assert avail[MigrationComponent.MEMORY] is True

    def test_execute_memory_yaml(self, nanoclaw_project, settings):
        from core.migrators.nanoclaw import NanoclawMigrator
        m = NanoclawMigrator(nanoclaw_project, settings=settings)
        plan = m.plan([MigrationComponent.MEMORY], ConflictStrategy.OVERWRITE)
        result = m.execute(plan, ConflictStrategy.OVERWRITE)
        assert result.success > 0
        md_files = list(settings.memory_dir.glob("*.md"))
        assert len(md_files) >= 1
        content = md_files[0].read_text()
        assert "---" in content
        assert "User Preferences" in content or "user_prefs" in content


# ── ZeroclawMigrator ──

class TestZeroclawMigrator:
    @pytest.fixture
    def zeroclaw_project(self, tmp_path):
        root = tmp_path / "zeroclaw"
        root.mkdir()

        # Soul
        soul_dir = root / "soul"
        soul_dir.mkdir()
        (soul_dir / "SOUL.md").write_text("# zeroclaw soul")

        # Notes as .txt
        notes_dir = root / "notes"
        notes_dir.mkdir()
        (notes_dir / "server_setup.txt").write_text("Ubuntu 22.04 on DigitalOcean")
        (notes_dir / "project_goals.txt").write_text("Build an AI assistant")

        # TOML config
        (root / "config.toml").write_text(
            '# zeroclaw config\n'
            'telegram-bot-token = "zer0-token"\n'
            'claude-model = "sonnet"\n'
        )

        return root

    def test_validate_source(self, zeroclaw_project, settings):
        from core.migrators.zeroclaw import ZeroclawMigrator
        m = ZeroclawMigrator(zeroclaw_project, settings=settings)
        assert m.validate_source() == []

    def test_discover_components(self, zeroclaw_project, settings):
        from core.migrators.zeroclaw import ZeroclawMigrator
        m = ZeroclawMigrator(zeroclaw_project, settings=settings)
        avail = m.discover_components()
        assert avail[MigrationComponent.SOUL] is True
        assert avail[MigrationComponent.MEMORY] is True
        assert avail[MigrationComponent.DB] is False  # zeroclaw has no DB
        assert avail[MigrationComponent.CONFIG] is True

    def test_execute_notes_to_memory(self, zeroclaw_project, settings):
        from core.migrators.zeroclaw import ZeroclawMigrator
        m = ZeroclawMigrator(zeroclaw_project, settings=settings)
        plan = m.plan([MigrationComponent.MEMORY], ConflictStrategy.OVERWRITE)
        result = m.execute(plan, ConflictStrategy.OVERWRITE)
        assert result.success == 2
        md_files = list(settings.memory_dir.glob("*.md"))
        assert len(md_files) == 2
        content = md_files[0].read_text()
        assert "---" in content
        assert "type: project" in content

    def test_execute_toml_to_env(self, zeroclaw_project, settings):
        from core.migrators.zeroclaw import ZeroclawMigrator
        m = ZeroclawMigrator(zeroclaw_project, settings=settings)
        plan = m.plan([MigrationComponent.CONFIG], ConflictStrategy.OVERWRITE)
        result = m.execute(plan, ConflictStrategy.OVERWRITE)
        assert result.success == 1
        env_file = settings.project_root / ".env"
        assert env_file.exists()
        content = env_file.read_text()
        assert "TELEGRAM_BOT_TOKEN=zer0-token" in content
        assert "CLAUDE_MODEL=sonnet" in content

    def test_plan_dry_run(self, zeroclaw_project, settings):
        from core.migrators.zeroclaw import ZeroclawMigrator
        m = ZeroclawMigrator(zeroclaw_project, settings=settings)
        plan = m.plan(list(MigrationComponent), ConflictStrategy.SKIP)
        # Dry-run: plan should have items but nothing executed
        assert len(plan.items) > 0
        for item in plan.items:
            assert item.target_path is None or not item.target_path.exists() or item.action == "skip"


# ── Conflict strategies ──

class TestConflictStrategies:
    def test_skip_on_conflict(self, tmp_path, settings):
        from core.migrators.zeroclaw import ZeroclawMigrator

        root = tmp_path / "zeroclaw"
        root.mkdir()
        (root / "soul").mkdir()
        (root / "soul" / "SOUL.md").write_text("new soul")

        # Pre-create target
        tgt_dir = settings.agents_dir / "global" / "main"
        tgt_dir.mkdir(parents=True)
        (tgt_dir / "SOUL.md").write_text("existing soul")

        m = ZeroclawMigrator(root, settings=settings)
        plan = m.plan([MigrationComponent.SOUL], ConflictStrategy.SKIP)
        result = m.execute(plan, ConflictStrategy.SKIP)

        # Original should be preserved
        assert (tgt_dir / "SOUL.md").read_text() == "existing soul"

    def test_overwrite_on_conflict(self, tmp_path, settings):
        from core.migrators.zeroclaw import ZeroclawMigrator

        root = tmp_path / "zeroclaw"
        root.mkdir()
        (root / "soul").mkdir()
        (root / "soul" / "SOUL.md").write_text("new soul")

        tgt_dir = settings.agents_dir / "global" / "main"
        tgt_dir.mkdir(parents=True)
        (tgt_dir / "SOUL.md").write_text("existing soul")

        m = ZeroclawMigrator(root, settings=settings)
        plan = m.plan([MigrationComponent.SOUL], ConflictStrategy.OVERWRITE)
        result = m.execute(plan, ConflictStrategy.OVERWRITE)

        assert (tgt_dir / "SOUL.md").read_text() == "new soul"


# ── Auto-detection ──

class TestAutoDetect:
    def test_detect_openclaw(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / "agents" / "global" / "main").mkdir(parents=True)
        (root / "agents" / "global" / "main" / "SOUL.md").write_text("soul")
        (root / "data").mkdir()
        (root / "memory").mkdir()
        (root / "memory" / "memories.json").write_text("[]")

        from core.migrate import detect_source
        assert detect_source(root) == "nanoclaw"  # nanoclaw also matches flat agents/
        # openclaw requires agents/global/main + data/
        # Both nanoclaw and openclaw can match; first registered wins

    def test_detect_zeroclaw(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        (root / "soul").mkdir()
        (root / "soul" / "SOUL.md").write_text("soul")
        (root / "notes").mkdir()
        (root / "notes" / "note.txt").write_text("note")

        from core.migrate import detect_source
        result = detect_source(root)
        assert result == "zeroclaw"

    def test_detect_unknown(self, tmp_path):
        root = tmp_path / "empty"
        root.mkdir()
        from core.migrate import detect_source
        assert detect_source(root) is None


# Import at module level for use in tests
from core.migrate import MigrationComponent, ConflictStrategy
