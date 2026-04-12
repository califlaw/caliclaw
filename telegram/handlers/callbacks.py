"""Callback query handlers — single router for all inline button callbacks."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from telegram.bot import CaliclawBot

logger = logging.getLogger(__name__)
router = Router()


def register(bot: CaliclawBot) -> None:
    bot.dp.include_router(router)

    @router.callback_query()
    async def handle_callback(callback: CallbackQuery) -> None:
        data = callback.data or ""

        if data.startswith("approve:"):
            await _handle_approve(bot, callback, data)
        elif data.startswith("deny:"):
            await _handle_deny(bot, callback, data)
        elif data.startswith("reset:"):
            await _handle_reset(bot, callback, data)
        elif data.startswith("model:"):
            await _handle_model(bot, callback, data)
        elif data.startswith("skill_view:"):
            await _handle_skill_view(bot, callback, data)
        elif data == "skill_back":
            await _handle_skill_back(bot, callback)
        elif data.startswith("skill:"):
            await _handle_skill(bot, callback, data)
        elif data.startswith("kill:"):
            await _handle_kill(bot, callback, data)
        elif data.startswith("task:"):
            await _handle_task(bot, callback, data)
        elif data.startswith("access:"):
            await _handle_access(bot, callback, data)


async def _handle_approve(bot, callback, data):
    code = data.split(":", 1)[1]
    approval = await bot.db.get_pending_approval(code)
    if approval:
        await bot.db.resolve_approval(approval["id"], "approved", "telegram")
        await callback.answer("Approved!")
        if callback.message:
            await callback.message.edit_text(f"✅ Approved: {approval['action']}")
    else:
        await callback.answer("Code not found.")


async def _handle_deny(bot, callback, data):
    code = data.split(":", 1)[1]
    approval = await bot.db.get_pending_approval(code)
    if approval:
        await bot.db.resolve_approval(approval["id"], "denied", "telegram")
        await callback.answer("Denied.")
        if callback.message:
            await callback.message.edit_text(f"❌ Denied: {approval['action']}")


async def _handle_reset(bot, callback, data):
    target = data.split(":", 1)[1]
    msg_map = {
        "session": ("UPDATE sessions SET status = 'archived' WHERE status = 'active'", "Sessions archived."),
        "agents": ("UPDATE agents SET status = 'killed' WHERE scope = 'ephemeral' AND status = 'active'", "Ephemeral agents killed."),
        "tasks": ("UPDATE tasks SET status = 'paused'", "All tasks paused."),
    }
    if target == "all":
        for sql, _ in msg_map.values():
            await bot.db.db.execute(sql)
        await bot.db.db.commit()
        msg = "Full reset done."
    elif target in msg_map:
        await bot.db.db.execute(msg_map[target][0])
        await bot.db.db.commit()
        msg = msg_map[target][1]
    else:
        msg = "Unknown target."
    await callback.answer(msg)
    if callback.message:
        await callback.message.edit_text(f"🔄 {msg}")


async def _handle_model(bot, callback, data):
    model = data.split(":", 1)[1]
    if model not in ("haiku", "sonnet", "opus"):
        return
    if model == bot._current_model:
        await callback.answer(f"Already on {model}")
        return
    bot._current_model = model
    await callback.answer(f"Switched to {model}")
    if callback.message:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"{'> ' if model == m else ''}{m}", callback_data=f"model:{m}")
            for m in ("haiku", "sonnet", "opus")
        ]])
        await callback.message.edit_text(
            f"Current model: `{model}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )


async def _handle_skill(bot, callback, data):
    """Toggle a skill on/off (called from detail view)."""
    skill_name = data.split(":", 1)[1]
    config_file = bot.settings.project_root / "data" / "enabled_skills.txt"
    enabled = set()
    if config_file.exists():
        enabled = {l.strip() for l in config_file.read_text().split("\n") if l.strip()}
    if skill_name in enabled:
        enabled.discard(skill_name)
        action = "off"
    else:
        enabled.add(skill_name)
        action = "on"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("\n".join(sorted(enabled)) + "\n")

    # Apply permission side-effects
    from security.engine_permissions import parse_skill_permissions, grant_tools, revoke_tools
    skill_md = bot.settings.skills_dir / skill_name / "SKILL.md"
    perms = parse_skill_permissions(skill_md)
    if perms:
        if action == "on":
            grant_tools(perms)
        else:
            revoke_tools(perms)

    await callback.answer(f"{skill_name}: {action}")
    # Refresh the detail view (toggle button changes label)
    if callback.message:
        text, keyboard = bot._build_skill_detail(skill_name)
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def _handle_skill_view(bot, callback, data):
    """Show skill detail panel (full content + Enable/Disable + Back)."""
    skill_name = data.split(":", 1)[1]
    text, keyboard = bot._build_skill_detail(skill_name)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def _handle_skill_back(bot, callback):
    """Return to skills list view."""
    text, keyboard = bot._build_skills_message()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def _handle_kill(bot, callback, data):
    name = data.split(":", 1)[1]
    if name == "main":
        await callback.answer("Cannot kill main agent.")
        return
    from core.orchestrator import Orchestrator
    orch = Orchestrator(bot.db, bot.pool)
    await orch.kill_agent(name, extract_knowledge=False)
    await callback.answer(f"Agent {name} killed.")
    if callback.message:
        await callback.message.edit_text(f"🔴 Agent `{name}` killed.", parse_mode=ParseMode.MARKDOWN)


async def _handle_task(bot, callback, data):
    parts = data.split(":")
    if len(parts) != 3:
        return
    action, task_id_str = parts[1], parts[2]
    try:
        task_id = int(task_id_str)
    except ValueError:
        await callback.answer("Invalid task ID.")
        return
    if action == "pause":
        await bot.db.db.execute("UPDATE tasks SET status = 'paused' WHERE id = ?", (task_id,))
        await bot.db.db.commit()
        await callback.answer(f"Task #{task_id} paused.")
    elif action == "resume":
        await bot.db.db.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (task_id,))
        await bot.db.db.commit()
        await callback.answer(f"Task #{task_id} resumed.")
    if callback.message:
        await callback.message.edit_text(
            f"{'🟡' if action == 'pause' else '🟢'} Task `#{task_id}` {action}d.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _handle_access(bot, callback, data):
    parts = data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    if action == "grant" and len(parts) == 3:
        path = Path(parts[2])
        bot._working_dir = path
        session = await bot.db.get_active_session("main")
        if session and session.get("claude_session_id"):
            await bot.db.update_session(session["id"], claude_session_id=None)
        bot._inject_context = True
        await callback.answer("Unleashed")
        logger.info("Unleashed on %s", path)
        if callback.message:
            await callback.message.edit_text(f"🔓 Unleashed on `{path}`", parse_mode=ParseMode.MARKDOWN)
    elif action == "cancel":
        await callback.answer("Cancelled")
        if callback.message:
            await callback.message.edit_text("🔒 Still in the cage.")
