from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Coroutine, Optional

from core.agent import AgentConfig, AgentPool, AgentResult
from core.config import get_settings
from core.protocols import StorageProtocol, AgentRunnerProtocol

logger = logging.getLogger(__name__)


@dataclass
class LoopConfig:
    agent_name: str
    task_description: str
    model: str = "sonnet"
    max_iterations: int = 20
    max_duration_minutes: Optional[int] = None  # None = no wall-clock cap
    report_every: int = 5
    system_prompt: str = ""
    working_dir: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class LoopStatus:
    iteration: int = 0
    total_iterations: int = 0
    is_complete: bool = False
    is_stuck: bool = False
    is_cancelled: bool = False
    error: Optional[str] = None
    last_result: str = ""
    accumulated_results: list[str] = field(default_factory=list)
    start_time: float = 0
    total_duration_ms: int = 0


class AgentLoop:
    """Runs an agent in a loop until task is complete or limits hit."""

    def __init__(self, db: StorageProtocol, pool: AgentRunnerProtocol):
        self.db = db
        self.pool = pool
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    async def run(
        self,
        config: LoopConfig,
        on_progress: Optional[Callable[[LoopStatus], Coroutine]] = None,
        on_ask_human: Optional[Callable[[str], Coroutine[..., ..., str]]] = None,
    ) -> LoopStatus:
        status = LoopStatus(
            total_iterations=config.max_iterations,
            start_time=time.time(),
        )

        session_id = config.session_id
        stuck_count = 0

        for i in range(1, config.max_iterations + 1):
            if self._cancelled:
                status.is_cancelled = True
                break

            # Check duration limit (None = unlimited)
            if config.max_duration_minutes is not None:
                elapsed_minutes = (time.time() - status.start_time) / 60
                if elapsed_minutes > config.max_duration_minutes:
                    status.error = f"Duration limit reached: {config.max_duration_minutes}m"
                    break

            status.iteration = i

            # Build loop prompt
            if i == 1:
                prompt = self._build_initial_prompt(config)
            else:
                prompt = self._build_continuation_prompt(config, status, i)

            agent_config = AgentConfig(
                name=config.agent_name,
                model=config.model,
                system_prompt=config.system_prompt,
                working_dir=config.working_dir and __import__("pathlib").Path(config.working_dir) or get_settings().workspace_dir,
                continue_session=session_id is not None,
                session_id=session_id,
            )

            result = await self.pool.run(agent_config, prompt)

            status.total_duration_ms += result.duration_ms
            status.last_result = result.text

            # Log usage
            await self.db.log_usage(
                agent_name=config.agent_name,
                model=config.model,
                duration_ms=result.duration_ms,
            )

            # Update session ID for continuation
            if result.session_id:
                session_id = result.session_id

            if result.error:
                stuck_count += 1
                if stuck_count >= 3:
                    status.is_stuck = True
                    if on_ask_human:
                        human_input = await on_ask_human(
                            f"Agent {config.agent_name} is stuck after {stuck_count} failures.\n"
                            f"Last error: {result.error}\n"
                            f"What should I do?"
                        )
                        if human_input:
                            status.accumulated_results.append(f"[Human input: {human_input}]")
                            stuck_count = 0
                            continue
                    break
                continue
            else:
                stuck_count = 0

            status.accumulated_results.append(result.text)

            # Check if task is complete
            if self._check_completion(result.text):
                status.is_complete = True
                break

            # Progress report
            if i % config.report_every == 0 and on_progress:
                await on_progress(status)

        status.total_duration_ms = int((time.time() - status.start_time) * 1000)

        # Final progress report
        if on_progress:
            await on_progress(status)

        return status

    def _build_initial_prompt(self, config: LoopConfig) -> str:
        return (
            f"You are working in an autonomous loop to complete a task.\n\n"
            f"TASK: {config.task_description}\n\n"
            f"RULES:\n"
            f"- You have up to {config.max_iterations} iterations\n"
            f"- Work step by step, one meaningful action per iteration\n"
            f"- When the task is FULLY COMPLETE, include the exact phrase: TASK_COMPLETE\n"
            f"- If you are stuck and need human input, include: NEED_HUMAN_INPUT: <your question>\n"
            f"- Report what you did and what's next\n\n"
            f"Begin. What is your first step?"
        )

    def _build_continuation_prompt(
        self, config: LoopConfig, status: LoopStatus, iteration: int
    ) -> str:
        return (
            f"Iteration {iteration}/{config.max_iterations}. "
            f"Continue working on the task.\n\n"
            f"When FULLY COMPLETE, say: TASK_COMPLETE\n"
            f"If stuck, say: NEED_HUMAN_INPUT: <question>"
        )

    def _check_completion(self, text: str) -> bool:
        return "TASK_COMPLETE" in text
