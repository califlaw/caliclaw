"""Tasks handlers: /tasks, /loop, /cron, /pause, /resume."""
from __future__ import annotations

import asyncio
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

    @router.message(Command("tasks"))
    async def cmd_tasks(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        async with bot.db.db.execute("SELECT * FROM tasks ORDER BY status, next_run") as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        if not rows:
            await message.answer("No tasks.")
            return
        lines = ["📋 **Tasks:**\n"]
        buttons = []
        for r in rows:
            icon = {"active": "🟢", "paused": "🟡", "completed": "✅", "failed": "🔴"}.get(r["status"], "⚪")
            lines.append(f"{icon} `#{r['id']}` **{r['name']}** — {r['schedule_type']}:{r['schedule_value']} ({r['status']})")
            if r["status"] == "active":
                buttons.append(InlineKeyboardButton(text=f"⏸ #{r['id']}", callback_data=f"task:pause:{r['id']}"))
            elif r["status"] == "paused":
                buttons.append(InlineKeyboardButton(text=f"▶ #{r['id']}", callback_data=f"task:resume:{r['id']}"))
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[buttons[i:i+3] for i in range(0, len(buttons), 3)]
        ) if buttons else None
        await message.answer("\n".join(lines)[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    @router.message(Command("cron"))
    async def cmd_cron(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split(maxsplit=2)
        if len(args) < 3:
            await message.answer(
                "Usage: /cron `<expression>` `<task>`\nExample: /cron `*/30 * * * *` Check server load",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        schedule, prompt = args[1], args[2]
        from automation.scheduler import cron_next_run
        try:
            next_run = cron_next_run(schedule, bot.settings.tz)
        except (ValueError, KeyError):
            await message.answer("Invalid cron format.")
            return
        task_id = await bot.db.create_task(
            name=prompt[:30], prompt=prompt, schedule_type="cron",
            schedule_value=schedule, next_run=next_run, notify=True, model="haiku",
        )
        await message.answer(f"📋 Task `#{task_id}` created: `{schedule}`", parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("pause"))
    async def cmd_pause(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split()
        if len(args) < 2:
            await message.answer("Usage: /pause `<id>`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            task_id = int(args[1])
        except ValueError:
            await message.answer("ID must be a number.")
            return
        await bot.db.db.execute("UPDATE tasks SET status = 'paused' WHERE id = ?", (task_id,))
        await bot.db.db.commit()
        await message.answer(f"🟡 Task `#{task_id}` paused.", parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("resume"))
    async def cmd_resume(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split()
        if len(args) < 2:
            await message.answer("Usage: /resume `<id>`", parse_mode=ParseMode.MARKDOWN)
            return
        try:
            task_id = int(args[1])
        except ValueError:
            await message.answer("ID must be a number.")
            return
        await bot.db.db.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (task_id,))
        await bot.db.db.commit()
        await message.answer(f"🟢 Task `#{task_id}` resumed.", parse_mode=ParseMode.MARKDOWN)

    @router.message(Command("loop"))
    async def cmd_loop(message: Message) -> None:
        if not bot._check_allowed(message):
            return
        args = (message.text or "").split(maxsplit=1)
        chat_id = message.chat.id

        if len(args) < 2:
            await message.answer(
                "Usage:\n"
                "/loop `<task description>` — start a loop\n"
                "/loop stop — cancel the loop running in this chat\n"
                "/loop status — show current loop state",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        sub = args[1].strip()
        sub_lower = sub.lower()

        if sub_lower == "stop":
            loop_runner = bot._active_loops.get(chat_id)
            if not loop_runner:
                await message.answer("No loop running in this chat.")
                return
            loop_runner.cancel()
            await message.answer("🛑 Loop cancel requested.")
            return

        if sub_lower == "status":
            loop_runner = bot._active_loops.get(chat_id)
            if not loop_runner:
                await message.answer("No loop running in this chat.")
                return
            await message.answer("🔄 Loop active. Use `/loop stop` to cancel.")
            return

        task_desc = sub
        await message.answer(
            f"🔄 Starting loop: _{task_desc}_\n\nSend `/loop stop` to cancel.",
            parse_mode=ParseMode.MARKDOWN,
        )

        async def run_loop() -> None:
            from core.loops import AgentLoop, LoopConfig
            loop_runner = AgentLoop(bot.db, bot.pool)
            bot._active_loops[chat_id] = loop_runner
            system_prompt = bot.souls.load_soul("main")

            config = LoopConfig(
                agent_name="main", task_description=task_desc,
                model=bot._current_model, system_prompt=system_prompt, report_every=3,
            )

            async def on_progress(status) -> None:
                label = (
                    f"{status.iteration}/{status.total_iterations}"
                    if status.total_iterations
                    else f"{status.iteration}"
                )
                await bot.bot.send_message(chat_id, f"🔄 Iteration {label}")

            try:
                status = await loop_runner.run(config, on_progress=on_progress)
                if status.is_cancelled:
                    await bot.bot.send_message(chat_id, "🛑 Loop stopped by user.")
                elif status.is_complete:
                    await bot.bot.send_message(chat_id, f"✅ Loop completed in {status.iteration} iterations.")
                elif status.is_stuck:
                    await bot.bot.send_message(chat_id, f"⚠️ Loop stuck at iteration {status.iteration}.")
                elif status.error:
                    await bot.bot.send_message(chat_id, f"🔴 Loop stopped: {status.error}")
                if status.last_result and not status.is_cancelled:
                    await bot.bot.send_message(chat_id, status.last_result[:4000])
            finally:
                bot._active_loops.pop(chat_id, None)

        asyncio.create_task(run_loop())
