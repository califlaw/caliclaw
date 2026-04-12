from __future__ import annotations

import pytest
from pathlib import Path

from core.souls import SoulLoader


@pytest.fixture
def souls(tmp_path):
    agents_dir = tmp_path / "agents"
    # Create main agent soul
    main_dir = agents_dir / "global" / "main"
    main_dir.mkdir(parents=True)
    (main_dir / "SOUL.md").write_text("You are caliclaw, the main coordinator.")
    (main_dir / "IDENTITY.md").write_text("name: caliclaw\nrole: coordinator")

    return SoulLoader(agents_dir=agents_dir)


def test_load_main_soul(souls):
    soul = souls.load_soul("main")
    assert "caliclaw" in soul
    assert "coordinator" in soul


def test_create_and_load_ephemeral(souls):
    souls.create_agent_soul(
        agent_name="test-agent",
        scope="ephemeral",
        soul="You are a test agent.",
        identity="name: Tester",
    )

    soul = souls.load_soul("test-agent", scope="ephemeral")
    assert "test agent" in soul
    # Should also include main soul as base
    assert "caliclaw" in soul


def test_delete_agent_soul(souls):
    souls.create_agent_soul("to-delete", scope="ephemeral", soul="Temporary")
    soul_dir = souls.get_agent_soul_dir("to-delete", "ephemeral")
    assert soul_dir.exists()

    souls.delete_agent_soul("to-delete", "ephemeral")
    assert not soul_dir.exists()


def test_list_agents(souls):
    souls.create_agent_soul("agent-a", scope="ephemeral", soul="A")
    souls.create_agent_soul("agent-b", scope="ephemeral", soul="B")

    agents = souls.list_agents()
    assert "main" in agents["global"]
    assert "agent-a" in agents["ephemeral"]
    assert "agent-b" in agents["ephemeral"]


def test_project_scoped_agent(souls):
    souls.create_agent_soul(
        "proj-agent", scope="project", project="myapp",
        soul="You work on myapp.",
    )

    soul = souls.load_soul("proj-agent", scope="project", project="myapp")
    assert "myapp" in soul


def test_empty_soul_files(souls):
    # Agent with no soul files should still return something (from main)
    agent_dir = souls.get_agent_soul_dir("empty-agent", "ephemeral")
    agent_dir.mkdir(parents=True)
    (agent_dir / "SOUL.md").write_text("")

    soul = souls.load_soul("empty-agent", scope="ephemeral")
    # Should at least have the main soul
    assert "caliclaw" in soul
