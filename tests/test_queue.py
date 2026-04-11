from __future__ import annotations

import asyncio
import time

import pytest

from core.queue import MessageQueue, QueuedMessage


@pytest.fixture
def queue():
    return MessageQueue(batch_delay=0.1, max_batch_size=5)


@pytest.mark.asyncio
async def test_single_message(queue):
    processed = []

    async def processor(session_id, batch):
        processed.append((session_id, [m.text for m in batch]))

    msg = QueuedMessage(text="Hello", sender="User")
    await queue.enqueue("sess-1", msg, processor)

    await asyncio.sleep(0.5)
    assert len(processed) == 1
    assert processed[0][0] == "sess-1"
    assert processed[0][1] == ["Hello"]


@pytest.mark.asyncio
async def test_message_batching(queue):
    processed = []

    async def processor(session_id, batch):
        processed.append((session_id, [m.text for m in batch]))

    # Send multiple messages quickly
    for i in range(3):
        msg = QueuedMessage(text=f"msg-{i}", sender="User")
        await queue.enqueue("sess-batch", msg, processor)

    await asyncio.sleep(0.5)
    # Should be batched into one call
    assert len(processed) == 1
    assert len(processed[0][1]) == 3


@pytest.mark.asyncio
async def test_format_single_message(queue):
    messages = [QueuedMessage(text="Hello world", sender="User")]
    result = queue.format_batch(messages)
    assert result == "Hello world"


@pytest.mark.asyncio
async def test_format_multiple_messages(queue):
    messages = [
        QueuedMessage(text="First", sender="User"),
        QueuedMessage(text="Second", sender="User"),
    ]
    result = queue.format_batch(messages)
    assert "Multiple messages" in result
    assert "First" in result
    assert "Second" in result


@pytest.mark.asyncio
async def test_format_with_media(queue):
    messages = [QueuedMessage(text="Check this", sender="User", media_path="/tmp/audio.ogg")]
    result = queue.format_batch(messages)
    assert "/tmp/audio.ogg" in result


def test_is_processing(queue):
    assert not queue.is_processing("sess-x")


def test_pending_count(queue):
    assert queue.pending_count("sess-x") == 0


@pytest.mark.asyncio
async def test_concurrent_enqueue_no_double_processing():
    """Race condition test: concurrent enqueue() must not start two processor tasks."""
    q = MessageQueue(batch_delay=0.1, max_batch_size=20)
    process_starts = []

    async def processor(session_id, batch):
        process_starts.append(len(batch))
        await asyncio.sleep(0.2)

    # Fire concurrent enqueues — all should be in ONE batch
    tasks = [
        q.enqueue("race-sess", QueuedMessage(text=f"m{i}", sender="U"), processor)
        for i in range(10)
    ]
    await asyncio.gather(*tasks)

    await asyncio.sleep(1.5)
    assert len(process_starts) == 1, f"Expected 1 batch, got {len(process_starts)}"
    assert process_starts[0] == 10


@pytest.mark.asyncio
async def test_processing_flag_cleared_on_empty(queue):
    """Verify _processing flag is cleared after queue empties so new tasks can start."""
    processed = []

    async def processor(session_id, batch):
        processed.append(len(batch))

    # First batch
    await queue.enqueue("clear-sess", QueuedMessage(text="a", sender="U"), processor)
    await asyncio.sleep(1.0)  # wait for batch + cleanup
    assert len(processed) == 1
    assert not queue.is_processing("clear-sess")

    # Second batch should also process (flag was properly cleared)
    await queue.enqueue("clear-sess", QueuedMessage(text="b", sender="U"), processor)
    await asyncio.sleep(1.0)
    assert len(processed) == 2
