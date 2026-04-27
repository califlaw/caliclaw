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


def test_project_main_includes_global_as_base(souls):
    """When `main` is loaded under project scope, the global main SOUL must
    still be loaded as base — otherwise activating an empty project soul
    would erase the agent's identity (regression caught on 2026-04-27:
    `/project new ai-marketplace` made the bot represent as generic Claude
    because the stub project soul replaced the global Йоичи soul)."""
    project_main = souls._agents_dir / "projects" / "myapp" / "main"
    project_main.mkdir(parents=True)
    (project_main / "SOUL.md").write_text("Working on myapp specifically.")

    soul = souls.load_soul("main", scope="project", project="myapp")
    # Project context layered ON TOP of global identity
    assert "myapp" in soul
    assert "caliclaw" in soul, "global main SOUL must remain as base"


def test_global_main_does_not_duplicate_itself(souls):
    """Global main loading itself shouldn't include the global main soul
    twice (once as base + once as agent-specific)."""
    soul = souls.load_soul("main")
    # "caliclaw" appears once in SOUL.md content; ensure no duplicate
    assert soul.count("caliclaw, the main coordinator") == 1


def test_project_main_with_empty_project_soul_falls_back_to_global(souls):
    """If a project main has an empty SOUL.md (template stub), global
    identity must still come through from the base."""
    project_main = souls._agents_dir / "projects" / "ai-marketplace" / "main"
    project_main.mkdir(parents=True)
    (project_main / "SOUL.md").write_text("")  # empty template

    soul = souls.load_soul("main", scope="project", project="ai-marketplace")
    # Even with empty project soul, agent keeps its base identity
    assert "caliclaw" in soul
