from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Callable, Dict, List, Optional

from core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    text: str
    session_id: Optional[str] = None
    duration_ms: int = 0
    exit_code: int = 0
    error: Optional[str] = None


@dataclass
class AgentConfig:
    name: str = "main"
    model: str = "sonnet"
    system_prompt: str = ""
    allowed_tools: Optional[List[str]] = None
    working_dir: Optional[Path] = None
    timeout_seconds: int = 900
    continue_session: bool = False
    session_id: Optional[str] = None
    max_turns: Optional[int] = None
    extra_args: List[str] = field(default_factory=list)


class AgentProcess:
    """Wraps a single claude -p invocation."""

    def __init__(self, config: AgentConfig, settings=None):
        self.config = config
        self._settings = settings or get_settings()
        self.process: Optional[asyncio.subprocess.Process] = None
        self._start_time: float = 0
        self._output_chunks: List[str] = []

    def _build_command(self, prompt: str) -> List[str]:
        cfg = self.config
        settings = self._settings
        cmd = [settings.engine_binary]

        # Non-interactive print mode
        cmd.extend(["-p", prompt])

        # Model
        cmd.extend(["--model", cfg.model])

        # Output as JSON for structured parsing
        cmd.extend(["--output-format", "json"])

        # System prompt
        if cfg.system_prompt:
            cmd.extend(["--system-prompt", cfg.system_prompt])

        # Session management
        if cfg.continue_session and cfg.session_id:
            cmd.extend(["--resume", cfg.session_id])
        elif cfg.continue_session:
            cmd.append("--continue")

        # Allowed tools
        if cfg.allowed_tools:
            cmd.extend(["--allowedTools", ",".join(cfg.allowed_tools)])

        # Max turns
        if cfg.max_turns:
            cmd.extend(["--max-turns", str(cfg.max_turns)])

        # Extra args
        cmd.extend(cfg.extra_args)

        return cmd

    async def run(self, prompt: str) -> AgentResult:
        cmd = self._build_command(prompt)
        working_dir = self.config.working_dir or self._settings.workspace_dir

        logger.info(
            "Agent %s running: model=%s, timeout=%ds",
            self.config.name, self.config.model, self.config.timeout_seconds,
        )
        logger.debug("Command: %s", " ".join(cmd[:6]) + "...")

        self._start_time = time.time()

        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(working_dir),
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                self.process.communicate(),
                timeout=self.config.timeout_seconds,
            )

            duration_ms = int((time.time() - self._start_time) * 1000)
            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

            # Parse output first — claude may return valid JSON even with non-zero exit
            result_text, session_id = self._parse_output(stdout)

            if self.process.returncode != 0 and not result_text:
                logger.error("Agent %s failed (exit %d): %s",
                             self.config.name, self.process.returncode, stderr)
                return AgentResult(
                    text="",
                    duration_ms=duration_ms,
                    exit_code=self.process.returncode or 1,
                    error=stderr or stdout or "Unknown error",
                )

            return AgentResult(
                text=result_text,
                session_id=session_id,
                duration_ms=duration_ms,
                exit_code=0,
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.time() - self._start_time) * 1000)
            await self.kill()
            logger.error("Agent %s timed out after %ds", self.config.name, self.config.timeout_seconds)
            return AgentResult(
                text="",
                duration_ms=duration_ms,
                exit_code=-1,
                error=f"Timeout after {self.config.timeout_seconds}s",
            )

    async def run_streaming(
        self, prompt: str, on_chunk: Callable[[str], None] | Callable
    ) -> AgentResult:
        """Run agent and call on_chunk for each line of output."""
        cmd = self._build_command(prompt)
        # For streaming, use stream-json output
        # Replace --output-format json with streaming
        cmd = [c for c in cmd if c not in ("--output-format", "json")]
        cmd.extend(["--output-format", "stream-json", "--verbose"])

        working_dir = self.config.working_dir or self._settings.workspace_dir
        self._start_time = time.time()

        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(working_dir),
            )

            full_text_parts: List[str] = []
            session_id = None

            async def _emit(text: str) -> None:
                result = on_chunk(text)
                if asyncio.iscoroutine(result):
                    await result

            async def read_stream() -> None:
                nonlocal session_id
                assert self.process and self.process.stdout
                async for line_bytes in self.process.stdout:
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        etype = event.get("type", "")
                        if etype == "assistant":
                            # Extract text from content blocks
                            msg = event.get("message", {})
                            content = msg.get("content", []) if isinstance(msg, dict) else []
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text", "")
                                    if text:
                                        full_text_parts.append(text)
                                        await _emit(text)
                        elif etype == "result":
                            session_id = event.get("session_id")
                            text = event.get("result", "")
                            if text and text not in "".join(full_text_parts):
                                full_text_parts.append(text)
                                await _emit(text)
                    except json.JSONDecodeError:
                        # Plain text output
                        full_text_parts.append(line)
                        await _emit(line)

            await asyncio.wait_for(
                read_stream(),
                timeout=self.config.timeout_seconds,
            )
            await self.process.wait()

            duration_ms = int((time.time() - self._start_time) * 1000)
            return AgentResult(
                text="".join(full_text_parts),
                session_id=session_id,
                duration_ms=duration_ms,
                exit_code=self.process.returncode or 0,
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.time() - self._start_time) * 1000)
            await self.kill()
            return AgentResult(
                text="".join(self._output_chunks),
                duration_ms=duration_ms,
                exit_code=-1,
                error=f"Timeout after {self.config.timeout_seconds}s",
            )

    def _parse_output(self, stdout: str) -> tuple[str, Optional[str]]:
        """Parse claude -p JSON output. Returns (text, session_id)."""
        session_id = None
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                result = data.get("result", "")
                session_id = data.get("session_id")
                return result, session_id
            return str(data), None
        except json.JSONDecodeError:
            return stdout, None

    async def kill(self) -> None:
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                await asyncio.sleep(2)
                if self.process.returncode is None:
                    self.process.kill()
            except ProcessLookupError:
                pass


class AgentPool:
    """Manages concurrent agent processes with limits."""

    def __init__(self, max_concurrent: Optional[int] = None, settings=None):
        self._settings = settings or get_settings()
        self._max = max_concurrent or self._settings.max_concurrent_agents
        self._semaphore = asyncio.Semaphore(self._max)
        self._active: Dict[str, AgentProcess] = {}

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def available_slots(self) -> int:
        return self._max - self.active_count

    async def run(self, config: AgentConfig, prompt: str) -> AgentResult:
        agent_id = f"{config.name}-{uuid.uuid4().hex[:8]}"
        async with self._semaphore:
            proc = AgentProcess(config, settings=self._settings)
            self._active[agent_id] = proc
            try:
                result = await proc.run(prompt)
                return result
            finally:
                self._active.pop(agent_id, None)

    async def run_streaming(
        self, config: AgentConfig, prompt: str, on_chunk: Callable[[str], None] | Callable
    ) -> AgentResult:
        agent_id = f"{config.name}-{uuid.uuid4().hex[:8]}"
        async with self._semaphore:
            proc = AgentProcess(config, settings=self._settings)
            self._active[agent_id] = proc
            try:
                result = await proc.run_streaming(prompt, on_chunk)
                return result
            finally:
                self._active.pop(agent_id, None)

    async def kill_all(self) -> None:
        for agent_id, proc in list(self._active.items()):
            await proc.kill()
        self._active.clear()
