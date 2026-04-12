from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    text: str
    sender: str
    timestamp: float = field(default_factory=time.time)
    telegram_message_id: Optional[int] = None
    media_path: Optional[str] = None


class MessageQueue:
    """Per-session message queue with batching.

    When multiple messages arrive while an agent is processing,
    they are batched into a single prompt instead of spawning
    multiple agents.
    """

    def __init__(
        self,
        batch_delay: float = 2.0,
        max_batch_size: int = 10,
    ):
        self._batch_delay = batch_delay
        self._max_batch_size = max_batch_size
        self._queues: Dict[str, List[QueuedMessage]] = {}
        self._processing: Dict[str, bool] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._events: Dict[str, asyncio.Event] = {}

    def cancel(self, session_id: str) -> None:
        """Cancel pending messages for a session."""
        self._queues.pop(session_id, None)
        self._processing[session_id] = False

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def _get_event(self, session_id: str) -> asyncio.Event:
        if session_id not in self._events:
            self._events[session_id] = asyncio.Event()
        return self._events[session_id]

    async def enqueue(
        self,
        session_id: str,
        message: QueuedMessage,
        processor: Callable[[str, List[QueuedMessage]], Coroutine],
    ) -> None:
        """Add a message to the queue. If not currently processing,
        start processing after a batching delay."""
        lock = self._get_lock(session_id)
        should_start = False
        async with lock:
            if session_id not in self._queues:
                self._queues[session_id] = []
            self._queues[session_id].append(message)
            # Atomic check-and-set: only one processor task per session
            if not self._processing.get(session_id, False):
                self._processing[session_id] = True
                should_start = True

        if should_start:
            asyncio.create_task(self._process_batch(session_id, processor))

    async def pipe_to_active(self, session_id: str, message: QueuedMessage) -> bool:
        """Try to pipe a message to an already-active agent session.
        Returns True if piped, False if no active session."""
        if self._processing.get(session_id):
            lock = self._get_lock(session_id)
            async with lock:
                if session_id not in self._queues:
                    self._queues[session_id] = []
                self._queues[session_id].append(message)
            return True
        return False

    async def _process_batch(
        self,
        session_id: str,
        processor: Callable[[str, List[QueuedMessage]], Coroutine],
    ) -> None:
        # Note: _processing[session_id] is set to True by enqueue() before
        # this task is created, ensuring atomic check-and-set.
        try:
            # Wait for batch delay to collect more messages
            await asyncio.sleep(self._batch_delay)

            lock = self._get_lock(session_id)
            while True:
                async with lock:
                    batch = self._queues.pop(session_id, [])
                    if not batch:
                        # Atomic: clear processing flag while holding lock
                        # so concurrent enqueue() sees consistent state
                        self._processing[session_id] = False
                        return

                # Limit batch size
                if len(batch) > self._max_batch_size:
                    async with lock:
                        # Put overflow back at front of queue
                        existing = self._queues.get(session_id, [])
                        self._queues[session_id] = batch[self._max_batch_size:] + existing
                    batch = batch[:self._max_batch_size]

                try:
                    await processor(session_id, batch)
                except (RuntimeError, ValueError, OSError):
                    logger.exception("Error processing batch for session %s", session_id)

                # Small delay before processing next batch
                await asyncio.sleep(0.5)
        except BaseException:
            # On any exception, clear flag so future enqueues can start a new task
            async with self._get_lock(session_id):
                self._processing[session_id] = False
            raise

    def is_processing(self, session_id: str) -> bool:
        return self._processing.get(session_id, False)

    def pending_count(self, session_id: str) -> int:
        return len(self._queues.get(session_id, []))

    def format_batch(self, messages: List[QueuedMessage]) -> str:
        """Format a batch of messages into a single prompt."""
        if len(messages) == 1:
            msg = messages[0]
            if msg.media_path:
                return f"[Audio/Media: {msg.media_path}]\n{msg.text}"
            return msg.text

        parts = []
        for msg in messages:
            ts = time.strftime("%H:%M:%S", time.localtime(msg.timestamp))
            text = msg.text
            if msg.media_path:
                text = f"[Audio/Media: {msg.media_path}]\n{text}"
            parts.append(f"[{ts}] {msg.sender}: {text}")

        return (
            "Multiple messages received while you were processing:\n\n"
            + "\n".join(parts)
            + "\n\nRespond to all of the above."
        )
