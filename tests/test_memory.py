from __future__ import annotations

import pytest
from pathlib import Path

from intelligence.memory import MemoryManager, MemoryEntry


@pytest.fixture
def memory(tmp_path):
    return MemoryManager(memory_dir=tmp_path / "memory")


def test_save_and_load(memory):
    path = memory.save(
        name="Test Fact",
        description="A test memory entry",
        mem_type="project",
        content="This is important information.",
    )
    assert path.exists()

    entry = memory.load(path.name)
    assert entry is not None
    assert entry.name == "Test Fact"
    assert entry.type == "project"
    assert "important information" in entry.content


def test_save_updates_index(memory):
    memory.save("Fact 1", "desc 1", "user", "content 1")
    memory.save("Fact 2", "desc 2", "project", "content 2")

    index = memory.get_index()
    assert "Fact 1" in index
    assert "Fact 2" in index


def test_search(memory):
    memory.save("Python tips", "Tips about Python", "reference", "Use list comprehensions")
    memory.save("Docker setup", "How to setup Docker", "project", "Install docker-ce")
    memory.save("User prefers dark mode", "UI preference", "user", "Dark theme preferred")

    results = memory.search("Python")
    assert len(results) >= 1
    assert results[0].name == "Python tips"

    results = memory.search("Docker")
    assert len(results) >= 1
    assert results[0].name == "Docker setup"


def test_delete(memory):
    memory.save("To delete", "Will be removed", "project", "Temporary", filename="temp.md")

    assert memory.delete("temp.md")
    assert memory.load("temp.md") is None

    index = memory.get_index()
    assert "To delete" not in index


def test_load_all(memory):
    memory.save("Entry 1", "desc", "user", "content 1")
    memory.save("Entry 2", "desc", "project", "content 2")
    memory.save("Entry 3", "desc", "reference", "content 3")

    entries = memory.load_all()
    assert len(entries) == 3


def test_context_for_prompt(memory):
    memory.save("Short", "short desc", "user", "Short content")
    memory.save("Long", "long desc", "project", "A" * 5000)

    context = memory.get_context_for_prompt(max_chars=1000)
    assert len(context) <= 1500  # some overhead from headers


def test_frontmatter_parsing():
    from tempfile import NamedTemporaryFile

    content = "---\nname: Test\ndescription: A test\ntype: user\n---\n\nBody content here."
    path = Path("/tmp/test_memory_entry.md")
    path.write_text(content)

    entry = MemoryEntry.from_file(path)
    assert entry is not None
    assert entry.name == "Test"
    assert entry.type == "user"
    assert entry.content == "Body content here."

    path.unlink()


def test_duplicate_index_entry(memory):
    memory.save("Same Entry", "v1", "user", "version 1", filename="same.md")
    memory.save("Same Entry", "v2", "user", "version 2", filename="same.md")

    index = memory.get_index()
    # Should have only one entry for this file
    assert index.count("same.md") == 1
