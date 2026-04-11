"""Agents handlers: /agents, /spawn, /kill, /promote."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

if TYPE_CHECKING:
    from telegram.bot import CaliclawBot

logger = logging.getLogger(__name__)
router = Router()


def register(bot: CaliclawBot) -> None:
    bot.dp.include_router(router)

    @router.message(Command("agents"))
    async def cmd_agents(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        agents = await bot.db.list_agents()
        if not agents:
            await message.answer("No agents.")
            return
        lines = ["🤖 **Agents:**\n"]
        buttons = []
        for a in agents:
            status_icon = {"active": "🟢", "paused": "🟡", "killed": "🔴"}.get(a["status"], "⚪")
            lines.append(f"{status_icon} `{a['name']}` ({a['scope']}) — {a['status']}")
            if a["name"] != "main" and a["status"] == "active":
                buttons.append(InlineKeyboardButton(text=f"Kill {a['name']}", callback_data=f"kill:{a['name']}"))
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[buttons[i:i+2] for i in range(0, len(buttons), 2)]
        ) if buttons else None
        await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    @router.message(Command("spawn"))
    async def cmd_spawn(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split(maxsplit=2)
        if len(args) < 3:
            await message.answer(
                "Usage: /spawn `<name>` `<role description>`\n"
                "Example: /spawn researcher Research topics and gather info",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        name = args[1].strip()
        description = args[2].strip()

        from core.orchestrator import Orchestrator, SpawnRequest
        orch = Orchestrator(bot.db, bot.pool)
        request = SpawnRequest(
            name=name, role=description,
            soul=f"You are {name}. Your role: {description}.\nBe focused and concise.",
            identity=f"name: {name}\nrole: {description}",
            scope="ephemeral",
        )
        await orch.spawn_agent(request)
        await message.answer(f"🤖 Agent `{name}` created (ephemeral)", parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("kill"))
    async def cmd_kill(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Usage: /kill `<agent name>`", parse_mode=ParseMode.MARKDOWN)
            return
        name = args[1].strip()
        if name == "main":
            await message.answer("Cannot kill the main agent.")
            return
        from core.orchestrator import Orchestrator
        orch = Orchestrator(bot.db, bot.pool)
        await orch.kill_agent(name, extract_knowledge=False)
        await message.answer(f"🔴 Agent `{name}` killed.", parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("promote"))
    async def cmd_promote(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split()
        if len(args) < 3:
            await message.answer("Usage: /promote `<name>` `<global|project>`", parse_mode=ParseMode.MARKDOWN)
            return
        name, scope = args[1], args[2]
        if scope not in ("global", "project"):
            await message.answer("Scope must be: global or project")
            return
        from core.orchestrator import Orchestrator
        orch = Orchestrator(bot.db, bot.pool)
        await orch.promote_agent(name, scope)
        await message.answer(f"⬆️ Agent `{name}` promoted to `{scope}`", parse_mode=ParseMode.MARKDOWN)
