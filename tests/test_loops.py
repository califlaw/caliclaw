from __future__ import annotations

import pytest
import pytest_asyncio

from core.agent import AgentPool
from core.loops import AgentLoop, LoopConfig

requires_claude = pytest.mark.requires_claude


@pytest_asyncio.fixture
async def loop_runner(db):
    pool = AgentPool(max_concurrent=2)
    return AgentLoop(db, pool)


@requires_claude
@pytest.mark.asyncio
async def test_loop_completes(loop_runner, tmp_path):
    """Agent should say TASK_COMPLETE after a simple task."""
    config = LoopConfig(
        agent_name="loop-test",
        task_description="Reply with TASK_COMPLETE immediately. Do nothing else.",
        model="haiku",
        max_iterations=3,
        max_duration_minutes=2,
        system_prompt="When asked, reply with TASK_COMPLETE. Do not use any tools.",
        working_dir=str(tmp_path),
    )
    status = await loop_runner.run(config)

    assert status.is_complete
    assert status.iteration <= 3
    assert status.total_duration_ms > 0


@requires_claude
@pytest.mark.asyncio
async def test_loop_max_iterations(loop_runner, tmp_path):
    """Loop should run exactly max_iterations times (or complete earlier)."""
    config = LoopConfig(
        agent_name="loop-iter",
        task_description="Count from 1. Say the next number each time.",
        model="haiku",
        max_iterations=2,
        max_duration_minutes=2,
        system_prompt="Say the next number. Do not use tools. Do not say TASK_COMPLETE.",
        working_dir=str(tmp_path),
    )
    status = await loop_runner.run(config)

    # Should have run at most 2 iterations
    assert status.iteration <= 2
    assert status.total_duration_ms > 0
    assert len(status.accumulated_results) >= 1


@requires_claude
@pytest.mark.asyncio
async def test_loop_progress_callback(loop_runner, tmp_path):
    """Progress callback should fire."""
    progress_reports = []

    async def on_progress(status):
        progress_reports.append(status.iteration)

    config = LoopConfig(
        agent_name="loop-progress",
        task_description="Say 'working' first time, then TASK_COMPLETE second time.",
        model="haiku",
        max_iterations=5,
        max_duration_minutes=2,
        report_every=1,
        system_prompt="First call: say 'working'. Second call: say TASK_COMPLETE. No tools.",
        working_dir=str(tmp_path),
    )
    status = await loop_runner.run(config, on_progress=on_progress)

    # Should have at least one progress report
    assert len(progress_reports) >= 1


@pytest.mark.asyncio
async def test_loop_cancellation(loop_runner, tmp_path):
    """Cancelled loop should stop immediately without calling claude."""
    loop_runner.cancel()

    config = LoopConfig(
        agent_name="loop-cancel",
        task_description="This should never run.",
        model="haiku",
        max_iterations=10,
        working_dir=str(tmp_path),
    )
    status = await loop_runner.run(config)

    assert status.is_cancelled
    assert status.iteration == 0
