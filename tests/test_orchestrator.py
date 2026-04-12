from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from core.agent import AgentPool
from core.orchestrator import Orchestrator, SpawnRequest, SwarmTask, PipelineStage

requires_claude = pytest.mark.requires_claude


@pytest_asyncio.fixture
async def orch(db, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTS_DIR", str(tmp_path / "agents"))
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))

    from core.config import reset_settings, get_settings
    reset_settings()
    settings = get_settings()
    settings.ensure_dirs()

    main_dir = tmp_path / "agents" / "global" / "main"
    main_dir.mkdir(parents=True)
    (main_dir / "SOUL.md").write_text("You are the main agent. Be concise.")

    mem_dir = tmp_path / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "MEMORY.md").write_text("# caliclaw Memory Index\n")

    pool = AgentPool(max_concurrent=3)
    o = Orchestrator(db, pool)
    yield o
    reset_settings()


@pytest.mark.asyncio
async def test_spawn_agent(orch, db):
    request = SpawnRequest(
        name="test-agent",
        role="tester",
        soul="You are a test agent. Reply ONLY: ok",
        identity="name: Tester",
        scope="ephemeral",
    )
    name = await orch.spawn_agent(request)
    assert name == "test-agent"

    agent = await db.get_agent("test-agent")
    assert agent is not None
    assert agent["scope"] == "ephemeral"
    assert agent["status"] == "active"


@pytest.mark.asyncio
async def test_kill_agent(orch, db):
    request = SpawnRequest(
        name="killable",
        role="temp",
        soul="Temp agent.",
        scope="ephemeral",
    )
    await orch.spawn_agent(request)
    await orch.kill_agent("killable", extract_knowledge=False)

    agent = await db.get_agent("killable")
    assert agent["status"] == "killed"


@pytest.mark.asyncio
async def test_promote_agent(orch, db):
    request = SpawnRequest(
        name="promotable",
        role="worker",
        soul="Worker agent.",
        scope="ephemeral",
    )
    await orch.spawn_agent(request)
    await orch.promote_agent("promotable", "global")

    agent = await db.get_agent("promotable")
    assert agent["scope"] == "global"


@requires_claude
@pytest.mark.asyncio
async def test_run_agent_real(orch, db):
    request = SpawnRequest(
        name="real-agent",
        role="responder",
        soul="Reply with ONLY the word 'hello'. Nothing else.",
        scope="ephemeral",
        model="haiku",
    )
    await orch.spawn_agent(request)

    result = await orch.run_agent("real-agent", "say it", model="haiku")

    assert result.exit_code == 0
    assert result.error is None
    assert result.text
    assert "hello" in result.text.lower()


@requires_claude
@pytest.mark.asyncio
async def test_run_nonexistent_agent(orch):
    result = await orch.run_agent("ghost", "hello")
    assert result.error is not None
    assert result.exit_code == 1


@requires_claude
@pytest.mark.asyncio
async def test_swarm_real(orch, db):
    for name, word in [("sw-a", "alpha"), ("sw-b", "beta")]:
        await orch.spawn_agent(SpawnRequest(
            name=name, role="responder",
            soul=f"Reply ONLY: {word}",
            scope="ephemeral", model="haiku",
        ))

    progress_log = []

    async def on_progress(name: str, status: str) -> None:
        progress_log.append((name, status))

    tasks = [
        SwarmTask(agent_name="sw-a", prompt="word?"),
        SwarmTask(agent_name="sw-b", prompt="word?"),
    ]
    results = await orch.run_swarm(tasks, on_progress=on_progress)

    assert results["sw-a"].text
    assert results["sw-b"].text
    assert "alpha" in results["sw-a"].text.lower()
    assert "beta" in results["sw-b"].text.lower()
    assert len(progress_log) >= 2


@requires_claude
@pytest.mark.asyncio
async def test_swarm_with_dependency(orch, db):
    for name in ("dep-1", "dep-2"):
        await orch.spawn_agent(SpawnRequest(
            name=name, role="responder",
            soul="Reply ONLY: done",
            scope="ephemeral", model="haiku",
        ))

    tasks = [
        SwarmTask(agent_name="dep-1", prompt="go"),
        SwarmTask(agent_name="dep-2", prompt="go", depends_on=["dep-1"]),
    ]
    results = await orch.run_swarm(tasks)

    assert results["dep-1"].exit_code == 0
    assert results["dep-2"].exit_code == 0


@requires_claude
@pytest.mark.asyncio
async def test_pipeline_real(orch, db):
    for name in ("p1", "p2"):
        await orch.spawn_agent(SpawnRequest(
            name=name, role="processor",
            soul="Add the word 'processed' to the input. Reply concisely.",
            scope="ephemeral", model="haiku",
        ))

    stages = [
        PipelineStage(agent_name="p1", prompt_template="Process: START"),
        PipelineStage(agent_name="p2", prompt_template="Continue.", depends_on=["p1"]),
    ]
    results = await orch.run_pipeline(stages)

    assert len(results) == 2
    assert results["p1"].text
    assert results["p2"].text
