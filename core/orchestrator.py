from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from core.agent import AgentConfig, AgentPool, AgentResult
from core.config import get_settings
from core.protocols import StorageProtocol, AgentRunnerProtocol
from core.souls import SoulLoader

logger = logging.getLogger(__name__)


@dataclass
class SpawnRequest:
    name: str
    role: str
    soul: str
    identity: str = ""
    scope: str = "ephemeral"
    project: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    model: str = "sonnet"
    allowed_tools: Optional[List[str]] = None
    timeout_seconds: int = 300


@dataclass
class SwarmTask:
    agent_name: str
    prompt: str
    depends_on: List[str] = field(default_factory=list)
    on_fail: str = "report"  # report | retry
    max_retries: int = 2     # only used when on_fail == "retry"


@dataclass
class PipelineStage:
    agent_name: str
    prompt_template: str
    depends_on: List[str] = field(default_factory=list)
    on_fail: str = "stop"    # stop | retry | continue
    max_retries: int = 2     # only used when on_fail == "retry"


_TRANSIENT_PATTERNS = ("rate limit", "could not connect", "timeout", "temporarily")


def _is_transient(result: AgentResult) -> bool:
    """Whether an error looks retryable. Timeouts + network errors = yes."""
    if result.exit_code == -1:
        return True
    err = (result.error or "").lower()
    return any(p in err for p in _TRANSIENT_PATTERNS)


class Orchestrator:
    """Manages agent lifecycle: spawn, kill, promote, swarm, pipelines."""

    def __init__(self, db: StorageProtocol, pool: AgentRunnerProtocol):
        self.db = db
        self.pool = pool
        self.souls = SoulLoader()
        self._results: Dict[str, AgentResult] = {}

    # ── Agent Lifecycle ──

    async def spawn_agent(self, request: SpawnRequest) -> str:
        """Create and register a new agent. Returns agent name."""
        # Create soul files
        self.souls.create_agent_soul(
            agent_name=request.name,
            scope=request.scope,
            project=request.project,
            soul=request.soul,
            identity=request.identity,
            skills=request.skills,
        )

        # Register in DB
        soul_dir = self.souls.get_agent_soul_dir(
            request.name, request.scope, request.project
        )
        await self.db.save_agent(
            name=request.name,
            scope=request.scope,
            project=request.project,
            soul_path=str(soul_dir),
            permissions={"allowed_tools": request.allowed_tools},
            skills=request.skills,
        )

        logger.info(
            "Spawned agent %s (scope=%s, model=%s)",
            request.name, request.scope, request.model,
        )
        return request.name

    async def pause_agent(self, agent_name: str) -> None:
        """Suspend an agent. run_agent will refuse until resume_agent is called."""
        agent = await self.db.get_agent(agent_name)
        if not agent:
            raise ValueError(f"Agent {agent_name} not found")
        if agent["status"] == "killed":
            raise ValueError(f"Cannot pause killed agent {agent_name}")
        await self.db.update_agent_status(agent_name, "paused")
        logger.info("Paused agent %s", agent_name)

    async def resume_agent(self, agent_name: str) -> None:
        """Resume a paused agent to active state."""
        agent = await self.db.get_agent(agent_name)
        if not agent:
            raise ValueError(f"Agent {agent_name} not found")
        if agent["status"] != "paused":
            raise ValueError(
                f"Agent {agent_name} is {agent['status']}, not paused"
            )
        await self.db.update_agent_status(agent_name, "active")
        logger.info("Resumed agent %s", agent_name)

    async def run_agent(
        self,
        agent_name: str,
        prompt: str,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """Run a prompt through a specific agent."""
        agent = await self.db.get_agent(agent_name)
        if not agent:
            return AgentResult(text="", error=f"Agent {agent_name} not found", exit_code=1)

        status = agent.get("status", "active")
        if status == "paused":
            return AgentResult(
                text="",
                error=f"Agent {agent_name} is paused; call resume_agent first",
                exit_code=1,
            )
        if status == "killed":
            return AgentResult(
                text="",
                error=f"Agent {agent_name} has been killed",
                exit_code=1,
            )

        scope = agent["scope"]
        project = agent.get("project")
        system_prompt = self.souls.load_soul(agent_name, scope, project)

        permissions = json.loads(agent.get("permissions", "{}"))
        allowed_tools = permissions.get("allowed_tools")

        config = AgentConfig(
            name=agent_name,
            model=model or get_settings().claude_default_model,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            working_dir=get_settings().workspace_dir,
            continue_session=session_id is not None,
            session_id=session_id,
        )

        result = await self.pool.run(config, prompt)
        await self.db.update_agent_status(agent_name, "active")

        await self.db.log_usage(
            agent_name=agent_name,
            model=config.model,
            duration_ms=result.duration_ms,
        )

        return result

    async def kill_agent(
        self,
        agent_name: str,
        extract_knowledge: bool = True,
    ) -> Optional[str]:
        """Kill an agent. Optionally extract knowledge first. Returns extracted knowledge."""
        agent = await self.db.get_agent(agent_name)
        if not agent:
            return None

        knowledge = None
        if extract_knowledge:
            knowledge = await self._extract_knowledge(agent_name)

        # Update DB status
        await self.db.update_agent_status(agent_name, "killed")

        # Delete soul files
        self.souls.delete_agent_soul(
            agent_name, agent["scope"], agent.get("project")
        )

        logger.info("Killed agent %s (knowledge extracted: %s)", agent_name, bool(knowledge))
        return knowledge

    async def promote_agent(
        self,
        agent_name: str,
        to_scope: str,
        project: Optional[str] = None,
    ) -> None:
        """Promote an agent from ephemeral to project or global."""
        agent = await self.db.get_agent(agent_name)
        if not agent:
            return

        old_scope = agent["scope"]
        old_project = agent.get("project")

        # Read current soul
        old_soul_dir = self.souls.get_agent_soul_dir(agent_name, old_scope, old_project)
        soul_content = ""
        identity_content = ""
        if (old_soul_dir / "SOUL.md").exists():
            soul_content = (old_soul_dir / "SOUL.md").read_text(encoding="utf-8")
        if (old_soul_dir / "IDENTITY.md").exists():
            identity_content = (old_soul_dir / "IDENTITY.md").read_text(encoding="utf-8")

        # Create in new location
        self.souls.create_agent_soul(
            agent_name=agent_name,
            scope=to_scope,
            project=project,
            soul=soul_content,
            identity=identity_content,
        )

        # Delete old
        self.souls.delete_agent_soul(agent_name, old_scope, old_project)

        # Update DB
        new_soul_dir = self.souls.get_agent_soul_dir(agent_name, to_scope, project)
        await self.db.save_agent(
            name=agent_name,
            scope=to_scope,
            project=project,
            soul_path=str(new_soul_dir),
        )

        logger.info("Promoted agent %s: %s -> %s", agent_name, old_scope, to_scope)

    async def _extract_knowledge(self, agent_name: str) -> Optional[str]:
        """Use a quick haiku call to extract knowledge from an agent before killing."""
        try:
            config = AgentConfig(
                name="knowledge-extractor",
                model="haiku",
                system_prompt="Extract key learnings and knowledge from this agent's work. Be concise.",
                timeout_seconds=30,
            )
            soul_dir = self.souls.get_agent_soul_dir(agent_name, "ephemeral")
            soul_file = soul_dir / "SOUL.md"
            if soul_file.exists():
                soul = soul_file.read_text(encoding="utf-8")
                result = await self.pool.run(
                    config,
                    f"Agent '{agent_name}' is being killed. "
                    f"Its soul was:\n{soul}\n\n"
                    f"Summarize what this agent learned in 2-3 bullet points.",
                )
                if result.text:
                    # Save to memory
                    from intelligence.memory import MemoryManager
                    mm = MemoryManager()
                    mm.save(
                        name=f"Agent {agent_name} learnings",
                        description=f"Knowledge extracted from killed agent {agent_name}",
                        mem_type="project",
                        content=result.text,
                    )
                    return result.text
        except (RuntimeError, ValueError, OSError):
            logger.exception("Failed to extract knowledge from %s", agent_name)
        return None

    # ── Swarm ──

    async def run_swarm(
        self,
        tasks: List[SwarmTask],
        on_progress: Optional[Callable[[str, str], Coroutine]] = None,
    ) -> Dict[str, AgentResult]:
        """Run multiple agents in parallel with dependency management."""
        results: Dict[str, AgentResult] = {}
        completed: set[str] = set()
        failed: set[str] = set()

        # Build dependency graph
        pending = {t.agent_name: t for t in tasks}

        while pending:
            # Find tasks with satisfied dependencies
            ready = []
            for name, task in pending.items():
                deps_met = all(d in completed for d in task.depends_on)
                deps_failed = any(d in failed for d in task.depends_on)
                if deps_failed:
                    # Skip if dependency failed
                    results[name] = AgentResult(
                        text="", error=f"Dependency failed: {task.depends_on}", exit_code=1
                    )
                    failed.add(name)
                    continue
                if deps_met:
                    ready.append(task)

            if not ready:
                # Deadlock or all remaining have failed deps
                for name in list(pending.keys()):
                    if name not in results:
                        results[name] = AgentResult(
                            text="", error="Deadlock: unresolvable dependencies", exit_code=1
                        )
                break

            # Remove ready from pending
            for task in ready:
                pending.pop(task.agent_name)

            # Run ready tasks in parallel
            async def _run_task(task: SwarmTask) -> tuple[str, AgentResult]:
                attempts = (
                    task.max_retries + 1 if task.on_fail == "retry" else 1
                )
                result: Optional[AgentResult] = None
                for attempt in range(attempts):
                    if on_progress:
                        label = "started" if attempt == 0 else f"retry {attempt}"
                        await on_progress(task.agent_name, label)
                    result = await self.run_agent(task.agent_name, task.prompt)
                    if not result.error:
                        break
                    if attempt + 1 < attempts and _is_transient(result):
                        await asyncio.sleep(min(2 ** attempt, 30))
                        continue
                    break
                assert result is not None
                if on_progress:
                    status = "completed" if not result.error else "failed"
                    await on_progress(task.agent_name, status)
                return task.agent_name, result

            coros = [_run_task(t) for t in ready]
            batch_results = await asyncio.gather(*coros, return_exceptions=True)

            for item in batch_results:
                if isinstance(item, Exception):
                    logger.error("Swarm task failed: %s", item)
                    continue
                name, result = item
                results[name] = result
                if result.error:
                    failed.add(name)
                else:
                    completed.add(name)

        return results

    # ── Pipelines ──

    async def run_pipeline(
        self,
        stages: List[PipelineStage],
        initial_context: str = "",
        on_progress: Optional[Callable[[str, str], Coroutine]] = None,
    ) -> Dict[str, AgentResult]:
        """Run a sequence of agents, passing results forward."""
        results: Dict[str, AgentResult] = {}
        context = initial_context

        for stage in stages:
            # Check dependencies
            for dep in stage.depends_on:
                if dep in results and results[dep].error:
                    if stage.on_fail == "stop":
                        results[stage.agent_name] = AgentResult(
                            text="", error=f"Pipeline stopped: {dep} failed", exit_code=1
                        )
                        return results

            # Build prompt with context from previous stages
            prompt = stage.prompt_template
            if context:
                prompt = f"Previous context:\n{context}\n\n{prompt}"

            attempts = (
                stage.max_retries + 1 if stage.on_fail == "retry" else 1
            )
            result: Optional[AgentResult] = None
            for attempt in range(attempts):
                if on_progress:
                    label = "started" if attempt == 0 else f"retry {attempt}"
                    await on_progress(stage.agent_name, label)
                result = await self.run_agent(stage.agent_name, prompt)
                if not result.error:
                    break
                if attempt + 1 < attempts and _is_transient(result):
                    await asyncio.sleep(min(2 ** attempt, 30))
                    continue
                break
            assert result is not None
            results[stage.agent_name] = result

            if result.error:
                if on_progress:
                    await on_progress(stage.agent_name, "failed")
                if stage.on_fail == "stop":
                    break
            else:
                context = result.text
                if on_progress:
                    await on_progress(stage.agent_name, "completed")

        return results

    # ── Mailbox (inter-agent messaging) ──

    async def send_message(
        self,
        from_agent: str,
        to_agent: str,
        body: str,
        metadata: Optional[Dict] = None,
    ) -> int:
        """Send a message from one agent to another. Returns message id."""
        return await self.db.send_agent_message(
            from_agent, to_agent, body, metadata=metadata,
        )

    async def get_messages(
        self,
        agent_name: str,
        unread_only: bool = True,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return messages addressed to agent_name, newest first."""
        return await self.db.get_agent_messages(
            agent_name, unread_only=unread_only, limit=limit,
        )

    async def mark_read(self, message_id: int) -> None:
        """Mark a single mailbox message as read."""
        await self.db.mark_agent_message_read(message_id)
