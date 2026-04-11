"""Integration tests — end-to-end flows with mock Claude CLI.

These tests simulate the full pipeline:
  message → queue → soul loading → agent (mock) → response → DB save
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio


@pytest.fixture
def mock_claude(tmp_path):
    """Create a mock claude binary that returns JSON responses."""
    mock_bin = tmp_path / "claude"
    mock_bin.write_text(
        '#!/bin/bash\n'
        'echo \'{"result": "Mock response from Claude", "session_id": "mock-sess-001"}\'\n'
    )
    mock_bin.chmod(mock_bin.stat().st_mode | stat.S_IEXEC)
    return str(mock_bin)


@pytest.fixture
def mock_claude_streaming(tmp_path):
    """Create a mock claude binary that returns stream-json output."""
    mock_bin = tmp_path / "claude-stream"
    mock_bin.write_text(
        '#!/bin/bash\n'
        'echo \'{"type": "assistant", "message": {"content": [{"type": "text", "text": "Streaming response"}]}}\'\n'
        'echo \'{"type": "result", "result": "Streaming response", "session_id": "mock-sess-002"}\'\n'
    )
    mock_bin.chmod(mock_bin.stat().st_mode | stat.S_IEXEC)
    return str(mock_bin)


@pytest.fixture
def mock_claude_error(tmp_path):
    """Mock claude that fails."""
    mock_bin = tmp_path / "claude-err"
    mock_bin.write_text('#!/bin/bash\nexit 1\n')
    mock_bin.chmod(mock_bin.stat().st_mode | stat.S_IEXEC)
    return str(mock_bin)


@pytest.fixture
def mock_claude_timeout(tmp_path):
    """Mock claude that hangs."""
    mock_bin = tmp_path / "claude-timeout"
    mock_bin.write_text('#!/bin/bash\nsleep 999\n')
    mock_bin.chmod(mock_bin.stat().st_mode | stat.S_IEXEC)
    return str(mock_bin)


# ── Agent E2E ──

class TestAgentE2E:
    @pytest.mark.asyncio
    async def test_agent_run_mock(self, mock_claude, settings, monkeypatch):
        """Full agent run: config → process → result."""
        monkeypatch.setenv("CLAUDE_BINARY", mock_claude)

        from core.config import reset_settings
        reset_settings()

        from core.agent import AgentProcess, AgentConfig
        config = AgentConfig(
            name="test-agent",
            model="sonnet",
            system_prompt="You are a test agent.",
            timeout_seconds=10,
        )
        proc = AgentProcess(config)
        # Override the binary path
        proc.config.working_dir = Path(settings.workspace_dir)
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)

        result = await proc.run("Hello test")
        assert result.text == "Mock response from Claude"
        assert result.session_id == "mock-sess-001"
        assert result.exit_code == 0
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_agent_timeout(self, mock_claude_timeout, settings, monkeypatch):
        """Agent should timeout and return error."""
        monkeypatch.setenv("CLAUDE_BINARY", mock_claude_timeout)

        from core.config import reset_settings
        reset_settings()

        from core.agent import AgentProcess, AgentConfig
        config = AgentConfig(
            name="timeout-agent",
            model="sonnet",
            timeout_seconds=2,  # short timeout
        )
        proc = AgentProcess(config)
        proc.config.working_dir = Path(settings.workspace_dir)
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)

        result = await proc.run("This will timeout")
        assert result.exit_code == -1
        assert "Timeout" in (result.error or "")

    @pytest.mark.asyncio
    async def test_agent_error(self, mock_claude_error, settings, monkeypatch):
        """Agent should handle claude process failure."""
        monkeypatch.setenv("CLAUDE_BINARY", mock_claude_error)

        from core.config import reset_settings
        reset_settings()

        from core.agent import AgentProcess, AgentConfig
        config = AgentConfig(name="error-agent", model="sonnet", timeout_seconds=10)
        proc = AgentProcess(config)
        proc.config.working_dir = Path(settings.workspace_dir)
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)

        result = await proc.run("This will fail")
        assert result.exit_code != 0


# ── Pool E2E ──

class TestPoolE2E:
    @pytest.mark.asyncio
    async def test_pool_run(self, mock_claude, settings, monkeypatch):
        """Pool manages agent lifecycle."""
        monkeypatch.setenv("CLAUDE_BINARY", mock_claude)

        from core.config import reset_settings
        reset_settings()

        from core.agent import AgentPool, AgentConfig
        pool = AgentPool(max_concurrent=2)

        config = AgentConfig(name="pool-test", model="sonnet", timeout_seconds=10)
        config.working_dir = Path(settings.workspace_dir)
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)

        result = await pool.run(config, "Pool test message")
        assert result.text == "Mock response from Claude"
        assert pool.active_count == 0  # should be released

    @pytest.mark.asyncio
    async def test_pool_concurrent(self, mock_claude, settings, monkeypatch):
        """Pool handles concurrent agents."""
        monkeypatch.setenv("CLAUDE_BINARY", mock_claude)

        from core.config import reset_settings
        reset_settings()

        from core.agent import AgentPool, AgentConfig
        pool = AgentPool(max_concurrent=3)

        configs = [
            AgentConfig(name=f"concurrent-{i}", model="sonnet", timeout_seconds=10,
                       working_dir=Path(settings.workspace_dir))
            for i in range(3)
        ]
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)

        results = await asyncio.gather(*[
            pool.run(c, f"Message {i}") for i, c in enumerate(configs)
        ])
        assert all(r.text == "Mock response from Claude" for r in results)
        assert pool.active_count == 0


# ── Soul + Agent E2E ──

class TestSoulAgentE2E:
    @pytest.mark.asyncio
    async def test_soul_loaded_into_agent(self, mock_claude, settings, monkeypatch):
        """Soul files are loaded and passed to agent."""
        monkeypatch.setenv("CLAUDE_BINARY", mock_claude)

        from core.config import reset_settings
        reset_settings()

        # Create soul files
        soul_dir = settings.agents_dir / "global" / "main"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("You are a test soul.")
        (soul_dir / "IDENTITY.md").write_text("name: test\nrole: tester")

        from core.souls import SoulLoader
        loader = SoulLoader()
        prompt = loader.load_soul("main")
        assert "test soul" in prompt
        assert "test" in prompt

        # Use soul as system prompt in agent
        from core.agent import AgentProcess, AgentConfig
        config = AgentConfig(
            name="soul-test", model="sonnet",
            system_prompt=prompt, timeout_seconds=10,
        )
        proc = AgentProcess(config)
        proc.config.working_dir = Path(settings.workspace_dir)
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)

        cmd = proc._build_command("Hello")
        assert "--system-prompt" in cmd
        # System prompt should contain soul content
        sp_idx = cmd.index("--system-prompt")
        assert "test soul" in cmd[sp_idx + 1]


# ── Queue + DB E2E ──

class TestQueueDBE2E:
    @pytest.mark.asyncio
    async def test_message_queue_to_db(self, db):
        """Message queued → processed → saved to DB."""
        await db.create_session("e2e-sess", "main")

        # Simulate what bot does
        await db.save_message(
            role="user", content="Hello from e2e test",
            session_id="e2e-sess", telegram_message_id=12345,
        )

        # Simulate agent response
        await db.save_message(
            role="assistant", content="Mock response from Claude",
            session_id="e2e-sess",
        )

        messages = await db.get_messages("e2e-sess")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello from e2e test"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Mock response from Claude"

    @pytest.mark.asyncio
    async def test_session_continuation(self, db):
        """Session tracks claude_session_id for continuation."""
        await db.create_session("e2e-cont", "main")
        await db.update_session("e2e-cont", claude_session_id="claude-abc-123")

        session = await db.get_session("e2e-cont")
        assert session["claude_session_id"] == "claude-abc-123"

    @pytest.mark.asyncio
    async def test_usage_tracking_e2e(self, db):
        """Usage logged after agent run."""
        await db.log_usage(
            agent_name="main", model="sonnet",
            duration_ms=1500, session_id="e2e-sess",
            estimated_percent=0.2,
        )

        usage = await db.get_usage_today()
        assert usage >= 0.2


# ── Loop E2E ──

class TestLoopE2E:
    @pytest.mark.asyncio
    async def test_loop_cancel(self, db):
        """Loop responds to cancel signal."""
        from core.agent import AgentPool
        from core.loops import AgentLoop, LoopConfig

        pool = AgentPool()
        loop_runner = AgentLoop(db, pool)

        config = LoopConfig(
            agent_name="cancel-test",
            task_description="This will be cancelled",
            max_iterations=10,
        )

        # Cancel immediately
        loop_runner.cancel()

        status = await loop_runner.run(config)
        assert status.is_cancelled
        assert status.iteration == 0


# ── Orchestrator E2E ──

class TestOrchestratorE2E:
    @pytest.mark.asyncio
    async def test_spawn_kill_flow(self, db, settings):
        """Spawn agent → verify in DB → kill → verify killed."""
        from core.agent import AgentPool
        from core.orchestrator import Orchestrator, SpawnRequest

        pool = AgentPool()
        orch = Orchestrator(db, pool)

        # Spawn
        req = SpawnRequest(
            name="e2e-agent", role="tester",
            soul="You are a test agent.", identity="name: e2e-agent",
            scope="ephemeral",
        )
        await orch.spawn_agent(req)

        # Verify alive
        agent = await db.get_agent("e2e-agent")
        assert agent is not None
        assert agent["status"] == "active"
        assert agent["scope"] == "ephemeral"

        # Kill
        await orch.kill_agent("e2e-agent", extract_knowledge=False)

        # Verify killed
        agent = await db.get_agent("e2e-agent")
        assert agent["status"] == "killed"

    @pytest.mark.asyncio
    async def test_promote_flow(self, db, settings):
        """Spawn ephemeral → promote to global."""
        from core.agent import AgentPool
        from core.orchestrator import Orchestrator, SpawnRequest

        pool = AgentPool()
        orch = Orchestrator(db, pool)

        req = SpawnRequest(
            name="promote-test", role="researcher",
            soul="Research agent.", identity="name: promote-test",
            scope="ephemeral",
        )
        await orch.spawn_agent(req)
        await orch.promote_agent("promote-test", "global")

        agent = await db.get_agent("promote-test")
        assert agent["scope"] == "global"
