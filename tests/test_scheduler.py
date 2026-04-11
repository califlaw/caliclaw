from __future__ import annotations

import time

import pytest
import pytest_asyncio

from automation.scheduler import HeartbeatManager, TaskScheduler
from core.agent import AgentPool


@pytest.mark.asyncio
async def test_setup_default_heartbeats(db):
    hm = HeartbeatManager(db)
    await hm.setup_default_heartbeats()

    # Should create 3 default heartbeats
    async with db.db.execute("SELECT COUNT(*) FROM tasks") as cur:
        row = await cur.fetchone()
    assert row[0] == 3


@pytest.mark.asyncio
async def test_heartbeats_not_duplicated(db):
    hm = HeartbeatManager(db)
    await hm.setup_default_heartbeats()
    await hm.setup_default_heartbeats()  # Call again

    async with db.db.execute("SELECT COUNT(*) FROM tasks") as cur:
        row = await cur.fetchone()
    assert row[0] == 3  # Still 3, not 6


@pytest.mark.asyncio
async def test_due_tasks_detected(db):
    past = time.time() - 100
    await db.create_task("due", "check", "cron", "* * * * *", next_run=past)

    due = await db.get_due_tasks()
    assert len(due) == 1
    assert due[0]["name"] == "due"


@pytest.mark.asyncio
async def test_task_update_after_run(db):
    task_id = await db.create_task("test", "check", "cron", "*/5 * * * *", next_run=time.time() - 10)

    future = time.time() + 300
    await db.update_task_after_run(task_id, next_run=future, result="All ok", status="active")

    # Should not be due anymore
    due = await db.get_due_tasks()
    assert len(due) == 0


def test_cron_next_run_respects_timezone():
    """0 9 * * * should fire at 9 AM in user's TZ, not UTC."""
    from automation.scheduler import cron_next_run
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Moscow is UTC+3 in summer / UTC+3 always (doesn't observe DST since 2014)
    ts_moscow = cron_next_run("0 9 * * *", "Europe/Moscow")
    ts_utc = cron_next_run("0 9 * * *", "UTC")

    # Convert back to verify
    moscow_dt = datetime.fromtimestamp(ts_moscow, tz=ZoneInfo("Europe/Moscow"))
    utc_dt = datetime.fromtimestamp(ts_utc, tz=ZoneInfo("UTC"))

    # Both should be 9 AM in their respective timezones
    assert moscow_dt.hour == 9, f"Expected 9 AM Moscow, got {moscow_dt}"
    assert utc_dt.hour == 9, f"Expected 9 AM UTC, got {utc_dt}"

    # And they should be different timestamps (3 hours apart for Moscow)
    assert ts_moscow != ts_utc


def test_cron_next_run_invalid_timezone_falls_back_to_utc():
    """Invalid timezone shouldn't crash, should fall back to UTC."""
    from automation.scheduler import cron_next_run
    # Should not raise
    ts = cron_next_run("0 12 * * *", "Invalid/Nowhere")
    assert ts > 0


def test_cron_next_run_invalid_expression_raises():
    """Invalid cron expression should raise ValueError."""
    from automation.scheduler import cron_next_run
    with pytest.raises((ValueError, KeyError)):
        cron_next_run("not a cron", "UTC")
