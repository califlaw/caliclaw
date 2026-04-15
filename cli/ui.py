"""CLI UI module — Rich output, ASCII art, loading messages.

Usage:
    from cli.ui import ui
    ui.banner()
    ui.ok("Connected")
    ui.fail("Token invalid")
    with ui.spin("Flexing the claws..."):
        install_deps()
    ui.table(["Name", "Status"], rows)
"""
from __future__ import annotations

import random
import time
from contextlib import contextmanager
from typing import List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

# ── ASCII Art ──

LOGO = r"""
   ╔══╗     ╔══╗   ╔══╗     ╔══╗   ╔══╗     ╔══╗
   ║██║     ║██║   ║██║     ║██║   ║██║     ║██║
   ║██╠═════╣██║   ║██╠═════╣██║   ║██╠═════╣██║
   ║██╠═════╣██║   ║██╠═════╣██║   ║██╠═════╣██║
   ║██║     ║██║   ║██║     ║██║   ║██║     ║██║
   ╚══╝     ╚══╝   ╚══╝     ╚══╝   ╚══╝     ╚══╝
                 C A L I C L A W
"""

LOGO_SMALL = r"""  ╔█╗══{ CALICLAW }══╔█╗"""

LOGO_BANNER = r"""
        ╔══╗     ╔══╗   ╔══╗     ╔══╗   ╔══╗     ╔══╗   ╔══╗     ╔══╗
        ║██║     ║██║   ║██║     ║██║   ║██║     ║██║   ║██║     ║██║
        ║██╠═════╣██║   ║██╠═════╣██║   ║██╠═════╣██║   ║██╠═════╣██║
        ║██╠═════╣██║   ║██╠═════╣██║   ║██╠═════╣██║   ║██╠═════╣██║
        ║██║     ║██║   ║██║     ║██║   ║██║     ║██║   ║██║     ║██║
        ╚══╝     ╚══╝   ╚══╝     ╚══╝   ╚══╝     ╚══╝   ╚══╝     ╚══╝
        ██████╗  █████╗ ██╗     ██╗ ██████╗██╗      █████╗ ██╗    ██╗
        ██╔════╝██╔══██╗██║     ██║██╔════╝██║     ██╔══██╗██║    ██║
        ██║     ███████║██║     ██║██║     ██║     ███████║██║ █╗ ██║
        ██║     ██╔══██║██║     ██║██║     ██║     ██╔══██║██║███╗██║
        ╚██████╗██║  ██║███████╗██║╚██████╗███████╗██║  ██║╚███╔███╔╝
         ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
"""

# ── Gym-themed loading messages ──

MESSAGES_INIT = [
    "Flexing the claws...",
    "Loading the bar...",
    "Chalking up...",
    "Stretching before the lift...",
    "Setting up the rack...",
]

MESSAGES_START = [
    "Warming up...",
    "Entering the gym...",
    "Cracking knuckles...",
    "Pre-workout kicking in...",
    "Lacing up...",
]

MESSAGES_PROCESSING = [
    "Crunching reps...",
    "Lifting heavy thoughts...",
    "No pain no gain...",
    "Grinding it out...",
    "In the zone...",
    "One more rep...",
    "Beast mode...",
]

MESSAGES_DONE = [
    "Racked.",
    "Clean lift.",
    "PR achieved.",
    "Set complete.",
    "No spotter needed.",
]

MESSAGES_STOP = [
    "Racked the weights.",
    "Cooldown initiated.",
    "Rest day earned.",
    "Dropped the bar.",
]

MESSAGES_ERROR = [
    "Failed the rep.",
    "Bad form detected.",
    "Need a spotter.",
    "Missed the lift.",
]

MESSAGES_FLUSH = [
    "Brain day off.",
    "Mind-muscle disconnect.",
    "Reset the gains.",
]

MESSAGES_SQUEEZE = [
    "Squeezing it out...",
    "Compressing the pump...",
    "Cutting weight...",
]


def _pick(messages: list[str]) -> str:
    return random.choice(messages)


# ── UI Class ──


class UI:
    """Rich-based CLI output helpers."""

    def __init__(self):
        self.c = console

    # ── Banner ──

    def banner(self, subtitle: str = "") -> None:
        """Show the full branded banner."""
        text = Text()
        text.append(LOGO_BANNER, style="bold red")
        if subtitle:
            text.append(f"\n  {subtitle}", style="dim")
        self.c.print(text)

    def banner_small(self, subtitle: str = "") -> None:
        """Compact banner for smaller contexts."""
        self.c.print(f"[bold red]🔱 caliclaw[/bold red]  [dim]{subtitle}[/dim]")

    def logo(self) -> None:
        """Show ASCII art logo."""
        self.c.print(LOGO, style="red")

    # ── BIOS-style boot sequence ──

    def boot(
        self,
        modules: List[Tuple[str, str]],
        version: Optional[str] = None,
        animate: bool = True,
    ) -> None:
        """Print a BIOS-style boot sequence.

        Args:
            modules: list of (module_name, status) tuples in load order
            version: BIOS version string (defaults to installed package version)
            animate: pause briefly between lines (off in tests / non-tty)
        """
        import sys as _sys

        if version is None:
            from core import get_version
            version = f"v{get_version()}"

        tick = 0.06 if (animate and _sys.stdout.isatty()) else 0.0

        self.c.print()
        self.c.print(f"[bold yellow]CALICLAW BIOS {version}[/bold yellow]")
        self.c.print("[dim yellow]Copyright (C) 2026 caliclaw project[/dim yellow]")
        self.c.print("[dim]Press DEL to enter setup (just kidding)[/dim]")
        self.c.print()
        if tick: time.sleep(tick * 2)

        self.c.print("[yellow]>> Initializing boot sequence...[/yellow]")
        self.c.print()
        if tick: time.sleep(tick)

        width = max((len(n) for n, _ in modules), default=16) + 2
        for name, status in modules:
            if tick: time.sleep(tick)
            name_padded = f"{name}.module".ljust(width + 7)
            self.c.print(
                f"  [bold green][  OK  ][/bold green]  "
                f"[bold white]{name_padded}[/bold white] "
                f"[dim]{status}[/dim]"
            )

        if tick: time.sleep(tick)
        self.c.print()

        # Orange progress bar (mimics the BIOS screenshot)
        bar_full = "█" * 32
        self.c.print(
            f"  [bold #ff8c1a][ 100% ][/bold #ff8c1a]  "
            f"[#ff8c1a]{bar_full}[/#ff8c1a]"
        )
        self.c.print()
        self.c.print(
            "  [bold green]>>[/bold green] [bold white]caliclaw ready.[/bold white] "
            "[dim]type 'caliclaw --help' to begin.[/dim]"
        )
        self.c.print()

    def boot_fail(self, module: str, reason: str) -> None:
        """Print a BIOS-style [FAIL] line."""
        self.c.print(
            f"  [bold red][ FAIL ][/bold red]  "
            f"[bold white]{module}.module[/bold white] "
            f"[red]{reason}[/red]"
        )

    # ── Status messages ──

    def ok(self, msg: str) -> None:
        self.c.print(f"  [green]✓[/green] {msg}")

    def fail(self, msg: str) -> None:
        self.c.print(f"  [red]✗[/red] {msg}")

    def warn(self, msg: str) -> None:
        self.c.print(f"  [yellow]![/yellow] {msg}")

    def info(self, msg: str) -> None:
        self.c.print(f"  [dim]→[/dim] {msg}")

    def step(self, n: int, total: int, msg: str) -> None:
        self.c.print(f"\n  [bold red][{n}/{total}][/bold red] {msg}")

    def done(self, msg: str = "") -> None:
        text = msg or _pick(MESSAGES_DONE)
        self.c.print(f"\n  [bold green]✓ {text}[/bold green]")

    def vibe(self, category: str = "processing") -> str:
        """Get a themed message for the given category."""
        msgs = {
            "init": MESSAGES_INIT,
            "start": MESSAGES_START,
            "processing": MESSAGES_PROCESSING,
            "done": MESSAGES_DONE,
            "stop": MESSAGES_STOP,
            "error": MESSAGES_ERROR,
            "flush": MESSAGES_FLUSH,
            "squeeze": MESSAGES_SQUEEZE,
        }
        return _pick(msgs.get(category, MESSAGES_PROCESSING))

    # ── Spinner ──

    @contextmanager
    def spin(self, msg: str = "", category: str = "processing"):
        """Context manager that shows a spinner during long operations."""
        text = msg or _pick(MESSAGES_PROCESSING)
        status = self.c.status(f"[red]{text}[/red]", spinner="dots")
        status.start()
        try:
            yield status
        finally:
            status.stop()

    # ── Tables ──

    def table(
        self,
        columns: List[str],
        rows: List[Tuple],
        title: str = "",
        style: str = "red",
    ) -> None:
        t = Table(
            title=title or None,
            box=box.SIMPLE,
            header_style=f"bold {style}",
            show_edge=False,
            pad_edge=False,
            padding=(0, 2),
        )
        for col in columns:
            t.add_column(col)
        for row in rows:
            t.add_row(*[str(c) for c in row])
        self.c.print(t)

    # ── Panels ──

    def panel(self, content: str, title: str = "", style: str = "red") -> None:
        self.c.print(Panel(content, title=title or None, border_style=style, padding=(0, 1)))

    # ── Next steps ──

    def next_steps(self, steps: List[str]) -> None:
        """Show actionable next steps after a command."""
        self.c.print()
        self.c.print("  [bold]Next:[/bold]")
        for s in steps:
            self.c.print(f"    [dim]$[/dim] {s}")
        self.c.print()

    # ── Separator ──

    def sep(self) -> None:
        self.c.print("[dim]─[/dim]" * 50)

    # ── Interactive widgets ──

    def _run_dialog(self, fn):
        """Run a prompt_toolkit dialog, safely handling both sync and async contexts.

        prompt_toolkit's .run() calls asyncio.run() internally, which fails if
        there's already a running loop. Detect the running loop and run the
        dialog in a dedicated thread (with its own loop). The main loop blocks
        on the thread — acceptable during an interactive wizard where nothing
        else is running concurrently.
        """
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return fn()

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(fn).result()

    def checkbox(
        self,
        options: List[Tuple[str, str, bool]],
        title: str = "Select options",
    ) -> List[str]:
        """Interactive checkbox — pure keyboard, no buttons.

        Args:
            options: [(value, label, default_checked), ...]
            title: header text
        Returns:
            list of selected values
        """
        import sys
        if not sys.stdin.isatty():
            return [v for v, _, checked in options if checked]

        try:
            from prompt_toolkit.application import Application
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import Layout
            from prompt_toolkit.layout.containers import Window
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.formatted_text import FormattedText
        except ImportError:
            return [v for v, _, checked in options if checked]

        # Row 0 is a synthetic "Select all" toggle, rows 1..N are real options
        state = {
            "idx": 1,
            "checked": {v for v, _, c in options if c},
        }
        total_rows = len(options) + 1

        def get_text():
            lines = []
            if title:
                lines.append(("bold", f"  {title}\n\n"))

            # Synthetic Select-all row
            all_checked = len(state["checked"]) == len(options)
            is_cursor = state["idx"] == 0
            cursor = "▶" if is_cursor else " "
            label_style = "fg:#ff3b30 bold" if is_cursor else "bold"
            mark = "[x]" if all_checked else "[ ]"
            mark_style = "fg:#ff3b30 bold" if all_checked else "fg:#666"
            lines.append((label_style, f"  {cursor} "))
            lines.append((mark_style, f"{mark} "))
            lines.append((label_style, "Select all\n"))
            lines.append(("fg:#333", "  ─────────────────\n"))

            for i, (value, label, _) in enumerate(options):
                row_idx = i + 1
                is_cursor = row_idx == state["idx"]
                is_checked = value in state["checked"]
                mark = "[x]" if is_checked else "[ ]"
                cursor = "▶" if is_cursor else " "
                style = "fg:#ff3b30 bold" if is_cursor else ""
                mark_style = "fg:#ff3b30 bold" if is_checked else "fg:#666"
                lines.append((style, f"  {cursor} "))
                lines.append((mark_style, f"{mark} "))
                lines.append((style, f"{label}\n"))
            lines.append(("", "\n"))
            lines.append(("fg:#666", "  space = toggle   enter = confirm   esc = cancel\n"))
            return FormattedText(lines)

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _(event):
            state["idx"] = (state["idx"] - 1) % total_rows

        @kb.add("down")
        @kb.add("j")
        def _(event):
            state["idx"] = (state["idx"] + 1) % total_rows

        @kb.add("space")
        def _(event):
            if state["idx"] == 0:
                # Toggle all: if everything is selected → clear, else → select all
                if len(state["checked"]) == len(options):
                    state["checked"] = set()
                else:
                    state["checked"] = {v for v, _, _ in options}
                return
            v = options[state["idx"] - 1][0]
            if v in state["checked"]:
                state["checked"].discard(v)
            else:
                state["checked"].add(v)

        @kb.add("enter")
        def _(event):
            event.app.exit(result=[v for v, _, _ in options if v in state["checked"]])

        @kb.add("escape")
        @kb.add("c-c")
        def _(event):
            event.app.exit(result=None)

        app = Application(
            layout=Layout(Window(FormattedTextControl(get_text), always_hide_cursor=True)),
            key_bindings=kb,
            full_screen=False,
        )

        try:
            result = self._run_dialog(app.run)
        except (EOFError, KeyboardInterrupt):
            result = None

        if result is None:
            return [v for v, _, checked in options if checked]
        return result

    def radio(
        self,
        options: List[Tuple[str, str]],
        title: str = "Select one",
        default: str = "",
    ) -> str:
        """Interactive radio — pure keyboard, no buttons.

        Args:
            options: [(value, label), ...]
            title: header text
            default: pre-selected value
        Returns:
            selected value
        """
        import sys
        if not sys.stdin.isatty():
            return default or options[0][0]

        try:
            from prompt_toolkit.application import Application
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import Layout
            from prompt_toolkit.layout.containers import Window
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.formatted_text import FormattedText
        except ImportError:
            return default or options[0][0]

        state = {"idx": 0}
        if default:
            for i, (v, _) in enumerate(options):
                if v == default:
                    state["idx"] = i
                    break

        def get_text():
            lines = []
            if title:
                lines.append(("bold", f"  {title}\n\n"))
            for i, (_, label) in enumerate(options):
                is_cursor = i == state["idx"]
                cursor = "▶" if is_cursor else " "
                style = "fg:#ff3b30 bold" if is_cursor else ""
                lines.append((style, f"  {cursor} {label}\n"))
            lines.append(("", "\n"))
            lines.append(("fg:#666", "  ↑↓ = move   enter = confirm   esc = cancel\n"))
            return FormattedText(lines)

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _(event):
            state["idx"] = (state["idx"] - 1) % len(options)

        @kb.add("down")
        @kb.add("j")
        def _(event):
            state["idx"] = (state["idx"] + 1) % len(options)

        @kb.add("enter")
        def _(event):
            event.app.exit(result=options[state["idx"]][0])

        @kb.add("escape")
        @kb.add("c-c")
        def _(event):
            event.app.exit(result=None)

        app = Application(
            layout=Layout(Window(FormattedTextControl(get_text), always_hide_cursor=True)),
            key_bindings=kb,
            full_screen=False,
        )

        try:
            result = self._run_dialog(app.run)
        except (EOFError, KeyboardInterrupt):
            result = None

        return result if result is not None else (default or options[0][0])


# Singleton
ui = UI()
