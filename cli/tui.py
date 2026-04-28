"""caliclaw TUI — interactive terminal chat."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.live import Live
    from rich.text import Text
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:
    print("Install dependencies: pip install rich prompt_toolkit")
    sys.exit(1)

from cli.mic import MicRecorder

console = Console()


class TUI:
    def __init__(self):
        self.session_id: str | None = None
        self.claude_session_id: str | None = None
        history_path = _ROOT / "data" / "tui_history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self._mic = MicRecorder()
        self.prompt_session = PromptSession(
            history=FileHistory(str(history_path)),
            key_bindings=self._build_keybindings(),
            bottom_toolbar=self._toolbar,
            refresh_interval=0.5,  # so the REC timer ticks
        )

    def _build_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("escape", "c-n")
        def _toggle_mic(event):
            buf = event.app.current_buffer
            if self._mic.is_recording():
                # Block briefly while whisper runs — better than splitting
                # the UI flow with an async callback.
                text = self._mic.stop_and_transcribe()
                if text:
                    buf.insert_text(text + " ")
                # If transcribe failed, _toolbar surfaces the reason.
            else:
                if not self._mic.start():
                    # Toolbar will show last_error; nothing else to do.
                    pass

        return kb

    def _toolbar(self):
        if self._mic.is_recording():
            return f" 🔴 REC {self._mic.elapsed():.0f}s — Ctrl+Alt+N to stop+transcribe"
        err = self._mic.last_error()
        if err:
            return f" 🎙 Ctrl+Alt+N to record · last: {err}"
        return " 🎙 Ctrl+Alt+N to record"

    async def start(self) -> None:
        from core.config import get_settings
        from core.db import Database
        from core.agent import AgentConfig, AgentProcess
        from core.souls import SoulLoader

        settings = get_settings()
        settings.ensure_dirs()

        db = Database()
        await db.connect()

        souls = SoulLoader()

        # Get or create session
        session = await db.get_active_session("main")
        if session:
            self.session_id = session["id"]
            self.claude_session_id = session.get("claude_session_id")
        else:
            self.session_id = f"tui-{uuid.uuid4().hex[:12]}"
            await db.create_session(self.session_id, "main")

        console.print(Panel.fit(
            "[bold red]caliclaw TUI[/bold red]\n"
            "Type your message. Commands:\n"
            "  [dim]/new[/dim]     — new session\n"
            "  [dim]/status[/dim]  — system status\n"
            "  [dim]/memory[/dim]  — show memory\n"
            "  [dim]/agents[/dim]  — list agents\n"
            "  [dim]/model X[/dim] — switch model (haiku/sonnet/opus)\n"
            "  [dim]/quit[/dim]    — exit\n"
            "[dim]Ctrl+Alt+N[/dim] — push-to-talk (toggle mic → whisper → prompt)",
            title="🔱",
        ))

        model = settings.claude_default_model

        # ANSI-coloured prompt for prompt_toolkit: cyan bold "you" + dim chevron
        user_prompt = ANSI("\n\x1b[1;36myou\x1b[0m \x1b[2m›\x1b[0m ")

        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.prompt_session.prompt(user_prompt),
                )
            except (EOFError, KeyboardInterrupt):
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                handled = await self._handle_command(user_input, db, model)
                if handled == "quit":
                    break
                if handled == "new":
                    self.session_id = f"tui-{uuid.uuid4().hex[:12]}"
                    self.claude_session_id = None
                    await db.create_session(self.session_id, "main")
                    console.print("[dim]New session started.[/dim]")
                    continue
                if isinstance(handled, str) and handled.startswith("model:"):
                    model = handled.split(":")[1]
                    console.print(f"[dim]Model: {model}[/dim]")
                    continue
                if handled:
                    continue

            # Save user message
            await db.save_message("user", user_input, self.session_id)

            # Build agent config
            system_prompt = souls.load_soul("main")

            config = AgentConfig(
                name="main",
                model=model,
                system_prompt=system_prompt,
                continue_session=self.claude_session_id is not None,
                session_id=self.claude_session_id,
                working_dir=settings.workspace_dir,
            )

            # Run with streaming
            proc = AgentProcess(config)
            console.print()
            console.print(
                f"[bold green]bot[/bold green] [dim]› {model}[/dim]",
                highlight=False,
            )

            accumulated = []
            start_time = time.time()

            def on_chunk(chunk: str) -> None:
                accumulated.append(chunk)
                console.print(chunk, end="", highlight=False)

            try:
                result = await proc.run_streaming(user_input, on_chunk)
            except (KeyboardInterrupt, asyncio.CancelledError):
                # Kill subprocess so its stdout pipe / asyncio reader thread
                # don't deadlock during interpreter shutdown.
                await proc.kill()
                console.print()
                console.print("[dim]interrupted — type your next message or Ctrl+C again to quit[/dim]")
                console.rule(style="dim grey30")
                continue

            if not accumulated and result.text:
                try:
                    console.print(Markdown(result.text))
                except (ValueError, TypeError):
                    console.print(result.text)
            else:
                console.print()  # newline after streaming

            if result.error:
                console.print(f"[red]Error: {result.error}[/red]")

            # Subtle divider between turns
            console.rule(style="dim grey30")

            # Update session
            if result.session_id:
                self.claude_session_id = result.session_id
                await db.update_session(
                    self.session_id, claude_session_id=result.session_id
                )

            # Save assistant message
            text = result.text or "".join(accumulated)
            if text:
                await db.save_message("assistant", text, self.session_id)

            # Log usage
            duration = int((time.time() - start_time) * 1000)
            await db.log_usage("main", model, duration_ms=duration, session_id=self.session_id)

            elapsed = duration / 1000
            console.print(f"[dim]({model}, {elapsed:.1f}s)[/dim]")

        await db.close()
        console.print("[dim]Bye.[/dim]")

    async def _handle_command(self, cmd: str, db, current_model: str) -> str | bool:
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command == "/quit" or command == "/exit":
            return "quit"

        if command == "/new":
            return "new"

        if command == "/model":
            if arg in ("haiku", "sonnet", "opus"):
                return f"model:{arg}"
            console.print("[dim]Usage: /model haiku|sonnet|opus[/dim]")
            return True

        if command == "/status":
            from monitoring.tracking import UsageTracker
            tracker = UsageTracker(db)
            summary = await tracker.get_today_summary()
            agents = await db.list_agents()
            console.print(f"  Requests: {summary['total_requests']}  |  Agents: {len(agents)}")
            return True

        if command == "/memory":
            from intelligence.memory import MemoryManager
            mm = MemoryManager()
            index = mm.get_index()
            console.print(Markdown(index))
            return True

        if command == "/agents":
            agents = await db.list_agents()
            if not agents:
                console.print("[dim]No agents.[/dim]")
            else:
                for a in agents:
                    console.print(f"  {a['name']} ({a['scope']}) — {a['status']}")
            return True

        if command == "/help":
            console.print(
                "/new — new session\n"
                "/status — system status\n"
                "/memory — show memory\n"
                "/agents — list agents\n"
                "/model X — switch model\n"
                "/quit — exit\n"
                "Ctrl+Alt+N — push-to-talk (mic → whisper → prompt)"
            )
            return True

        console.print(f"[dim]Unknown command: {command}. Type /help[/dim]")
        return True


def run_tui() -> None:
    tui = TUI()
    try:
        asyncio.run(tui.start())
    except (KeyboardInterrupt, EOFError):
        from cli.ui import ui
        ui.c.print()
        ui.c.print("[dim]bye 🔱[/dim]")
    finally:
        # Force-exit so daemon threads (rich live spinner, prompt_toolkit
        # input reader, asyncio subprocess pipe readers) don't deadlock
        # during interpreter _shutdown waiting on locks. atexit handlers
        # we care about (DB writes) have already flushed by this point.
        import os
        os._exit(0)
