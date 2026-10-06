# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bounded, context-preserving batches for independent event side effects.

Unlike BOQ's keyed queue, this queue never merges or replaces an event. FIFO
order is preserved, including across request contexts. Only consecutive items
with the *same bindings* can share a batch/session: an async worker inherits
its creator's ContextVars, not the context of later submissions.

At capacity, submitters wait without opening a DB session. Cancellation of a
submitter after admission does not retract its side effect. Workers are tracked
by the event bus shutdown drain; forced shutdown cancels unfinished waiters and
logs dropped work. This is still an in-memory, best-effort queue, not an outbox
or an exactly-once delivery guarantee.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from contextvars import Context, copy_context
from typing import Any

from app.core.events import _log_failures

logger = logging.getLogger(__name__)


def _same_bindings(first: Context, second: Context) -> bool:
    # Identity, not equality: arbitrary ContextVar values may be unhashable or
    # implement surprising equality. A copied context retains binding values.
    return len(first) == len(second) and all(var in second and second[var] is value for var, value in first.items())


class ContextBatchQueue:
    """One worker, at most ``capacity`` admitted items, ``batch_size`` per call.

    Processors must not await another submission to their own queue. The
    timeline writer does not publish events, and application after-commit
    publications are detached; both real nested-publication patterns are
    covered by ``test_event_session_batches``. Adding a synchronous publication
    inside that writer would require revisiting this non-reentrant contract.
    """

    def __init__(
        self,
        name: str,
        process: Callable[[list[Any]], Awaitable[None]],
        *,
        batch_size: int = 200,
        capacity: int = 1000,
    ) -> None:
        if batch_size < 1 or capacity < 1:
            raise ValueError("batch size and capacity must be positive")
        self._name = name
        self._process = process
        self._batch_size = batch_size
        self._capacity = capacity
        self._pending: deque[tuple[Context, Any, asyncio.Future[None]]] = deque()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._slots: asyncio.Semaphore | None = None
        self._worker: asyncio.Task[None] | None = None

    async def submit(self, item: Any) -> None:
        """Wait for admission and processing; never drop an item on overflow."""
        loop = asyncio.get_running_loop()
        if self._worker is not None and self._worker.done():
            # Its done callback may not have run yet. Recover admission slots
            # before waiting for one, and before switching to another loop.
            self._worker_done(self._worker)
        if self._loop is not loop:
            if self._worker is not None and not self._worker.done():
                raise RuntimeError("event batch queue is active on another event loop")
            self._loop = loop
            self._slots = asyncio.Semaphore(self._capacity)
        assert self._slots is not None
        context = copy_context()
        await self._slots.acquire()
        future: asyncio.Future[None] = loop.create_future()
        self._pending.append((context, item, future))
        if self._worker is None or self._worker.done():
            self._worker = _log_failures(self._run(), name=f"{self._name}.batches")
            self._worker.add_done_callback(self._worker_done)
        # A cancelled publisher cannot cancel the shared worker or its peers.
        await asyncio.shield(future)

    def _worker_done(self, worker: asyncio.Task[None]) -> None:
        if worker is not self._worker:
            return  # a late callback must not discard a new worker's items
        # Cancellation before the coroutine's first step never enters _run's
        # try/finally. This fallback owns only the finished worker's queue.
        self._cancel_pending()
        self._worker = None

    def _cancel_pending(self) -> None:
        assert self._slots is not None
        if self._pending:
            logger.warning("%s worker stopped with %d events queued", self._name, len(self._pending))
        while self._pending:
            _, _, waiter = self._pending.popleft()
            self._slots.release()
            waiter.cancel()

    async def _run(self) -> None:
        assert self._slots is not None
        try:
            while self._pending:
                context, item, future = self._pending.popleft()
                batch = [(item, future)]
                while self._pending and len(batch) < self._batch_size and _same_bindings(context, self._pending[0][0]):
                    _, item, future = self._pending.popleft()
                    batch.append((item, future))
                cancelled = False
                try:
                    # Await the child so worker cancellation reaches its session
                    # context manager before shutdown disposes the engine.
                    await asyncio.create_task(self._process([item for item, _ in batch]), context=context)
                except asyncio.CancelledError:
                    cancelled = True
                    logger.warning("%s worker cancelled with %d in-flight events", self._name, len(batch))
                    raise
                except Exception:
                    logger.exception("%s batch of %d failed (not retried)", self._name, len(batch))
                finally:
                    for _, waiter in batch:
                        self._slots.release()
                        if not waiter.done():
                            if cancelled:
                                waiter.cancel()
                            else:
                                waiter.set_result(None)
        finally:
            self._cancel_pending()


async def run_session_batch(
    name: str,
    items: list[Any],
    session_factory: Callable[..., Any],
    process: Callable[[Any, Any], Awaitable[None]],
) -> None:
    """Reuse a session but preserve one transaction/error boundary per event.

    Never retry a failed event: the outcome of a failed commit may be unknown.
    A rollback failure closes the poisoned session and the *next* event gets
    a fresh one, even if closing that session also fails. Context/session setup
    errors propagate to the queue's logged best-effort failure path.
    """
    pending = deque(items)
    while pending:
        poisoned = False
        try:
            async with session_factory() as session:
                while pending:
                    item = pending.popleft()
                    try:
                        await process(session, item)
                        await session.commit()
                    except Exception:
                        logger.exception("%s event failed (not retried)", name)
                        try:
                            await session.rollback()
                        except Exception:
                            logger.exception("%s rollback failed; closing the session", name)
                            poisoned = True
                            break
        except Exception:
            if not poisoned:
                raise
            # Only __aexit__ can fail after marking this session poisoned.
            # The popped event is not retried; unstarted events remain queued.
            logger.exception("%s poisoned session close failed; %d unstarted events remain", name, len(pending))
