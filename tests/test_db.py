from __future__ import annotations

import time

import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_create_and_get_session(db):
    await db.create_session("sess-1", "main")
    session = await db.get_session("sess-1")
    assert session is not None
    assert session["id"] == "sess-1"
    assert session["agent_name"] == "main"
    assert session["status"] == "active"


@pytest.mark.asyncio
async def test_save_and_get_messages(db):
    await db.create_session("sess-msg", "main")
    msg_id = await db.save_message("user", "Hello", "sess-msg")
    assert msg_id is not None

    await db.save_message("assistant", "Hi there", "sess-msg")

    messages = await db.get_messages("sess-msg")
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"
    assert messages[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_count_messages(db):
    await db.create_session("sess-count", "main")
    for i in range(5):
        await db.save_message("user", f"msg {i}", "sess-count")

    count = await db.count_messages("sess-count")
    assert count == 5


@pytest.mark.asyncio
async def test_save_and_get_agent(db):
    await db.save_agent(
        name="coder",
        scope="ephemeral",
        permissions={"allowed_tools": ["Read", "Write"]},
        skills=["python"],
    )

    agent = await db.get_agent("coder")
    assert agent is not None
    assert agent["name"] == "coder"
    assert agent["scope"] == "ephemeral"
    assert agent["status"] == "active"


@pytest.mark.asyncio
async def test_list_agents(db):
    await db.save_agent(name="a1", scope="global")
    await db.save_agent(name="a2", scope="ephemeral")
    await db.save_agent(name="a3", scope="project", project="myapp")

    all_agents = await db.list_agents()
    assert len(all_agents) == 3

    global_agents = await db.list_agents(scope="global")
    assert len(global_agents) == 1


@pytest.mark.asyncio
async def test_update_agent_status(db):
    await db.save_agent(name="killme", scope="ephemeral")
    await db.update_agent_status("killme", "killed")

    agent = await db.get_agent("killme")
    assert agent["status"] == "killed"

    active = await db.list_agents(status="active")
    assert not any(a["name"] == "killme" for a in active)


@pytest.mark.asyncio
async def test_create_and_get_due_tasks(db):
    past = time.time() - 100
    future = time.time() + 10000

    await db.create_task("due_task", "check disk", "cron", "*/5 * * * *", next_run=past)
    await db.create_task("future_task", "check ram", "cron", "0 * * * *", next_run=future)

    due = await db.get_due_tasks()
    assert len(due) == 1
    assert due[0]["name"] == "due_task"


@pytest.mark.asyncio
async def test_task_run_logging(db):
    task_id = await db.create_task("logged_task", "test", "once", "0")
    await db.log_task_run(task_id, 1500, "success", result="All ok")

    async with db.db.execute(
        "SELECT * FROM task_runs WHERE task_id = ?", (task_id,)
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    assert dict(rows[0])["status"] == "success"


@pytest.mark.asyncio
async def test_approvals(db):
    await db.create_approval("appr-1", "coder", "git push", "confirm_tg", code="ab12")

    approval = await db.get_pending_approval("ab12")
    assert approval is not None
    assert approval["action"] == "git push"

    await db.resolve_approval("appr-1", "approved", "telegram")

    # Should not be pending anymore
    approval = await db.get_pending_approval("ab12")
    assert approval is None


@pytest.mark.asyncio
async def test_usage_logging(db):
    await db.log_usage("main", "sonnet", duration_ms=5000, estimated_percent=0.2)
    await db.log_usage("main", "haiku", duration_ms=1000, estimated_percent=0.05)

    total = await db.get_usage_today()
    assert abs(total - 0.25) < 0.01


@pytest.mark.asyncio
async def test_active_session(db):
    await db.create_session("active-sess", "main")
    session = await db.get_active_session("main")
    assert session is not None
    assert session["id"] == "active-sess"


@pytest.mark.asyncio
async def test_update_session(db):
    await db.create_session("update-sess", "main")
    await db.update_session("update-sess", claude_session_id="claude-123", summary="Test")

    session = await db.get_session("update-sess")
    assert session["claude_session_id"] == "claude-123"
    assert session["summary"] == "Test"
