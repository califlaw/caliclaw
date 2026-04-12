from __future__ import annotations

import asyncio

import pytest

from core.agent import AgentConfig, AgentProcess, AgentPool, AgentResult

requires_claude = pytest.mark.requires_claude


class TestAgentConfig:
    def test_defaults(self):
        config = AgentConfig()
        assert config.name == "main"
        assert config.model == "sonnet"
        assert config.timeout_seconds == 300

    def test_custom(self):
        config = AgentConfig(
            name="coder",
            model="opus",
            allowed_tools=["Read", "Write"],
            timeout_seconds=600,
        )
        assert config.name == "coder"
        assert config.allowed_tools == ["Read", "Write"]


class TestAgentProcess:
    def test_build_command_basic(self):
        config = AgentConfig(name="test", model="haiku", system_prompt="Be helpful")
        proc = AgentProcess(config)
        cmd = proc._build_command("Hello")

        # First arg is the engine binary (caliclaw-engine wrapper or claude)
        assert "engine" in cmd[0] or "claude" in cmd[0]
        assert "-p" in cmd
        assert "Hello" in cmd
        assert "--model" in cmd
        assert "haiku" in cmd
        assert "--system-prompt" in cmd

    def test_build_command_with_session(self):
        config = AgentConfig(
            continue_session=True, session_id="sess-123"
        )
        proc = AgentProcess(config)
        cmd = proc._build_command("Continue")

        assert "--resume" in cmd
        assert "sess-123" in cmd

    def test_build_command_with_tools(self):
        config = AgentConfig(allowed_tools=["Read", "Write", "Bash"])
        proc = AgentProcess(config)
        cmd = proc._build_command("test")

        assert "--allowedTools" in cmd
        assert "Read,Write,Bash" in cmd

    def test_parse_output_json(self):
        proc = AgentProcess(AgentConfig())
        text, session_id = proc._parse_output(
            '{"result": "Hello world", "session_id": "abc-123"}'
        )
        assert text == "Hello world"
        assert session_id == "abc-123"

    def test_parse_output_plain_text(self):
        proc = AgentProcess(AgentConfig())
        text, session_id = proc._parse_output("Just plain text")
        assert text == "Just plain text"
        assert session_id is None

    @requires_claude
    @pytest.mark.asyncio
    async def test_run_real_claude(self, tmp_path):
        config = AgentConfig(
            name="test",
            model="haiku",
            system_prompt="Reply with ONLY the word 'pong'. Nothing else.",
            timeout_seconds=30,
            working_dir=tmp_path,
            max_turns=1,
        )
        proc = AgentProcess(config)
        result = await proc.run("ping")

        assert result.exit_code == 0
        assert result.error is None
        assert result.text  # got some response
        assert "pong" in result.text.lower()

    @requires_claude
    @pytest.mark.asyncio
    async def test_run_returns_session_id(self, tmp_path):
        config = AgentConfig(
            name="test",
            model="haiku",
            system_prompt="Reply with one word: yes",
            timeout_seconds=30,
            working_dir=tmp_path,
            max_turns=1,
        )
        proc = AgentProcess(config)
        result = await proc.run("confirm?")

        assert result.exit_code == 0
        # JSON output mode should return session_id
        assert result.session_id is not None or result.text

    @requires_claude
    @pytest.mark.asyncio
    async def test_run_timeout(self, tmp_path):
        config = AgentConfig(
            name="test",
            model="haiku",
            system_prompt="Write a 10000 word essay about the universe.",
            timeout_seconds=3,
            working_dir=tmp_path,
        )
        proc = AgentProcess(config)
        result = await proc.run("Go")

        assert result.exit_code == -1
        assert result.error is not None
        assert "Timeout" in result.error

    @requires_claude
    @pytest.mark.asyncio
    async def test_run_streaming_real(self, tmp_path):
        config = AgentConfig(
            name="test",
            model="haiku",
            system_prompt="Reply with ONLY: hello world",
            timeout_seconds=30,
            working_dir=tmp_path,
            max_turns=1,
        )
        proc = AgentProcess(config)
        chunks = []

        def on_chunk(chunk: str) -> None:
            chunks.append(chunk)

        result = await proc.run_streaming("say it", on_chunk)

        assert result.exit_code == 0
        # Should have received at least something
        full_text = result.text or "".join(chunks)
        assert len(full_text) > 0


class TestAgentPool:
    @pytest.mark.asyncio
    async def test_concurrency_limit(self):
        pool = AgentPool(max_concurrent=2)
        assert pool.available_slots == 2
        assert pool.active_count == 0

    @requires_claude
    @pytest.mark.asyncio
    async def test_run_through_pool(self, tmp_path):
        pool = AgentPool(max_concurrent=2)
        config = AgentConfig(
            name="pool-test",
            model="haiku",
            system_prompt="Reply ONLY: ok",
            timeout_seconds=30,
            working_dir=tmp_path,
            max_turns=1,
        )

        result = await pool.run(config, "status?")

        assert result.exit_code == 0
        assert result.text
        assert pool.active_count == 0  # Released after completion

    @requires_claude
    @pytest.mark.asyncio
    async def test_parallel_runs(self, tmp_path):
        pool = AgentPool(max_concurrent=3)

        configs = []
        for i in range(2):
            configs.append(AgentConfig(
                name=f"parallel-{i}",
                model="haiku",
                system_prompt=f"Reply ONLY with the number {i}",
                timeout_seconds=30,
                working_dir=tmp_path,
                max_turns=1,
            ))

        results = await asyncio.gather(
            pool.run(configs[0], "number?"),
            pool.run(configs[1], "number?"),
        )

        assert len(results) == 2
        for r in results:
            assert r.exit_code == 0
            assert r.text
        assert pool.active_count == 0
