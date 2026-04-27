"""Project switching: /project [list|use <name>|new <name>|off].

A project bundles soul (agents/projects/<name>/main/SOUL.md), workspace
(workspace/projects/<name>/), and session (DB agent_name "main:<name>").
Switching is instant — the agent picks up the new scope on the next turn.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

if TYPE_CHECKING:
    from telegram.bot import CaliclawBot

router = Router()


def register(bot: "CaliclawBot") -> None:
    bot.dp.include_router(router)

    @router.message(Command("project"))
    async def cmd_project(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        from core.projects import (
            create_project,
            get_active_project,
            list_projects,
            project_exists,
            set_active_project,
        )

        parts = (message.text or "").split(maxsplit=2)
        action = parts[1].strip().lower() if len(parts) >= 2 else ""
        arg = parts[2].strip() if len(parts) >= 3 else ""

        active = get_active_project()
        projects = list_projects()

        def _project_list_md() -> str:
            if not projects:
                return "_No projects yet — `/project new <name>` to create one._"
            return "\n".join(
                f"{'▶' if p == active else '  '} `{p}`" for p in projects
            )

        # Status (no args)
        if not action:
            current = f"*{active}*" if active else "*global* (no project)"
            await message.answer(
                f"Active: {current}\n\n"
                f"Projects:\n{_project_list_md()}\n\n"
                f"Use:\n"
                f"`/project use <name>` — switch\n"
                f"`/project off` — back to global\n"
                f"`/project new <name>` — scaffold a new project",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if action == "list":
            await message.answer(_project_list_md(), parse_mode=ParseMode.MARKDOWN)
            return

        if action == "off":
            if not active:
                await message.answer("Already on global.")
                return
            set_active_project(None)
            await message.answer(
                "✅ Switched to *global*. Next turn uses the global soul + workspace.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if action == "use":
            if not arg:
                await message.answer(
                    "Need a project name.\n`/project use <name>`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            if not project_exists(arg):
                avail = ", ".join(f"`{p}`" for p in projects) if projects else "_(none)_"
                await message.answer(
                    f"Project `{arg}` not found.\n"
                    f"Available: {avail}\n"
                    f"Create: `/project new {arg}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            set_active_project(arg)
            await message.answer(
                f"✅ Switched to project *{arg}*.\n"
                f"Soul, workspace, and session are project-scoped now.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if action == "new":
            if not arg:
                await message.answer(
                    "Need a project name.\n`/project new <name>`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            if project_exists(arg):
                await message.answer(
                    f"Project `{arg}` already exists. `/project use {arg}` to switch.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            create_project(arg)
            # Don't auto-activate — the new SOUL.md is just a template stub.
            # If we switched now, the agent would lose its global identity
            # and respond as generic Claude until the soul is filled in.
            # User runs `/project use <name>` after editing the soul.
            await message.answer(
                f"✅ Project *{arg}* scaffolded.\n"
                f"Edit `agents/projects/{arg}/main/SOUL.md` to define project context, "
                f"then `/project use {arg}` to activate.\n"
                f"Workspace: `workspace/projects/{arg}/`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await message.answer(
            f"Unknown action: `{action}`. Try `/project`.",
            parse_mode=ParseMode.MARKDOWN,
        )
