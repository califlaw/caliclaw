from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


class FileWatcher:
    """Watches files for changes and triggers actions."""

    def __init__(self):
        self._watches: Dict[str, dict] = {}
        self._running = False

    def add_watch(
        self,
        name: str,
        path: str,
        pattern: Optional[str] = None,
        callback: Optional[Callable[[str, str], Coroutine]] = None,
    ) -> None:
        self._watches[name] = {
            "path": path,
            "pattern": re.compile(pattern) if pattern else None,
            "callback": callback,
            "last_size": 0,
            "last_mtime": 0,
        }

    def remove_watch(self, name: str) -> None:
        self._watches.pop(name, None)

    async def start(self) -> None:
        self._running = True
        logger.info("File watcher started with %d watches", len(self._watches))
        while self._running:
            for name, watch in list(self._watches.items()):
                try:
                    await self._check_file(name, watch)
                except (OSError, IOError):
                    logger.exception("File watch error: %s", name)
            await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False

    async def _check_file(self, name: str, watch: dict) -> None:
        path = Path(watch["path"])
        if not path.exists():
            return

        stat = path.stat()
        if stat.st_mtime <= watch["last_mtime"]:
            return

        # File changed
        watch["last_mtime"] = stat.st_mtime

        if watch["pattern"]:
            # Read new content (tail)
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                # Only check last 4KB for pattern
                tail = content[-4096:]
                if not watch["pattern"].search(tail):
                    return
                matched_text = tail
            except (OSError, IOError):
                return
        else:
            matched_text = f"File {path} changed"

        if watch["callback"]:
            await watch["callback"](name, matched_text)


class WebhookServer:
    """Simple HTTP server for incoming webhooks."""

    def __init__(self, port: int = 8081):
        self.port = port
        self._handlers: Dict[str, Callable[[dict], Coroutine]] = {}
        self._app = None

    def register(self, path: str, handler: Callable[[dict], Coroutine]) -> None:
        self._handlers[path] = handler

    async def start(self) -> None:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        import uvicorn

        async def handle_webhook(request: Request) -> JSONResponse:
            path = request.path_params.get("path", "")
            handler = self._handlers.get(f"/{path}")
            if not handler:
                return JSONResponse({"error": "not found"}, status_code=404)

            try:
                body = await request.json()
            except (json.JSONDecodeError, ValueError):
                body = {}

            try:
                await handler(body)
                return JSONResponse({"ok": True})
            except (RuntimeError, ValueError, OSError) as e:
                logger.exception("Webhook handler error")
                return JSONResponse({"error": str(e)}, status_code=500)

        app = Starlette(
            routes=[Route("/hook/{path:path}", handle_webhook, methods=["POST"])],
        )

        config = uvicorn.Config(app, host="0.0.0.0", port=self.port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()


class HookRunner:
    """Pre/post hooks for agent actions."""

    def __init__(self):
        self._hooks: Dict[str, List[dict]] = {}  # event -> list of hooks

    def register(self, event: str, command: str, description: str = "") -> None:
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append({"command": command, "description": description})

    async def run(self, event: str, context: dict = {}) -> List[dict]:
        """Run all hooks for an event. Returns list of results."""
        hooks = self._hooks.get(event, [])
        results = []

        for hook in hooks:
            cmd = hook["command"]
            # Substitute context variables
            for key, value in context.items():
                cmd = cmd.replace(f"{{{key}}}", str(value))

            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash", "-c", cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                results.append({
                    "hook": hook["description"] or cmd[:50],
                    "exit_code": proc.returncode,
                    "stdout": stdout.decode()[:1000],
                    "stderr": stderr.decode()[:500],
                })
            except asyncio.TimeoutError:
                results.append({
                    "hook": hook["description"] or cmd[:50],
                    "exit_code": -1,
                    "error": "timeout",
                })
            except OSError as e:
                results.append({
                    "hook": hook["description"] or cmd[:50],
                    "exit_code": -1,
                    "error": str(e),
                })

        return results
