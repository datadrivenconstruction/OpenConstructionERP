# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Process building blocks: the ``ManagedProcess`` contract and ready-made shapes.

A managed process owns whatever it starts (an asyncio task, a thread, a loaded
model) so the registry can stop and restart it without leaking anything. The
three helpers cover almost every background job in the platform:

* :class:`LoopProcess` - an async ``tick`` every ``interval_s`` seconds.
* :class:`OneShotProcess` - an async job that runs once (prewarm, backfill).
* :class:`ThreadLoopProcess` - a blocking ``work`` callable on its own thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import threading
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class ProcessReporter(Protocol):
    """Callbacks a running process uses to tell the registry what happened."""

    def tick_ok(self) -> None:
        """Report a healthy iteration (clears a degraded state)."""

    def tick_failed(self, exc: BaseException) -> None:
        """Report a failed iteration; the process keeps running."""

    def finished(self) -> None:
        """Report that a one-shot job completed successfully."""

    def crashed(self, exc: BaseException) -> None:
        """Report that the process died; the restart policy decides what next."""

    def ready(self) -> None:
        """Report that a process with ``reports_ready`` finished loading."""


class _NullReporter:
    def tick_ok(self) -> None:
        return None

    def tick_failed(self, exc: BaseException) -> None:
        return None

    def finished(self) -> None:
        return None

    def crashed(self, exc: BaseException) -> None:
        return None

    def ready(self) -> None:
        return None


@dataclass
class HealthReport:
    """Result of :meth:`ManagedProcess.health`."""

    ok: bool
    detail: str | None = None


class ManagedProcess(ABC):
    """Base class for anything the process registry can start and stop.

    ``start`` must return quickly: long work belongs in a task or thread the
    process owns. ``stop`` must be idempotent and must wait until everything
    the process started is gone.
    """

    process_id: str = ""
    reporter: ProcessReporter = _NullReporter()
    #: True when ``start`` returns before the process is usable and the
    #: process calls ``reporter.ready()`` later; the status stays ``starting``
    #: until then, and the start queue waits for it.
    reports_ready: bool = False

    def bind(self, process_id: str, reporter: ProcessReporter) -> None:
        """Attach the registry's id and reporter before ``start`` is called."""
        self.process_id = process_id
        self.reporter = reporter

    @abstractmethod
    async def start(self) -> None:
        """Start the process. Raise to signal a failed start."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the process and release what it holds. Idempotent."""

    async def health(self) -> HealthReport:
        """Return a cheap health probe. Defaults to healthy."""
        return HealthReport(ok=True)


class _TaskProcess(ManagedProcess):
    """Shared plumbing for processes backed by one asyncio task."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        """The task backing this process, if any."""
        return self._task

    def _spawn(self, coro: Awaitable[None]) -> None:
        self._task = asyncio.create_task(coro, name=f"process:{self.process_id}")  # type: ignore[arg-type]

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


class LoopProcess(_TaskProcess):
    """Run ``tick`` every ``interval_s`` seconds until stopped.

    A failing tick is reported and the loop carries on, so one bad night of a
    daily sweeper does not switch the sweeper off.

    Args:
        interval_s: Pause between ticks, in seconds.
        tick: Coroutine function called on each iteration.
        initial_delay_s: Pause before the first tick.
    """

    def __init__(self, interval_s: float, tick: Callable[[], Awaitable[None]], initial_delay_s: float = 0) -> None:
        super().__init__()
        self.interval_s = interval_s
        self.tick = tick
        self.initial_delay_s = initial_delay_s

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._spawn(self._run())

    async def _run(self) -> None:
        if self.initial_delay_s:
            await asyncio.sleep(self.initial_delay_s)
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.reporter.tick_failed(exc)
            else:
                self.reporter.tick_ok()
            await asyncio.sleep(self.interval_s)


class OneShotProcess(_TaskProcess):
    """Run ``run`` once in the background.

    Args:
        run: Coroutine function doing the job.
        initial_delay_s: Pause before the job starts.
    """

    def __init__(self, run: Callable[[], Awaitable[None]], initial_delay_s: float = 0) -> None:
        super().__init__()
        self.run = run
        self.initial_delay_s = initial_delay_s

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._spawn(self._run())

    async def _run(self) -> None:
        try:
            if self.initial_delay_s:
                await asyncio.sleep(self.initial_delay_s)
            await self.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.reporter.crashed(exc)
        else:
            self.reporter.finished()


class ResidentProcess(_TaskProcess):
    """Load something that then stays resident (a model, an open store).

    The status is ``starting`` while ``load`` runs and stays ``running`` after
    it returns, because the thing is
    still in memory. ``unload`` runs on stop and should drop every reference
    so the garbage collector can reclaim it; the OS may not see the memory
    back at once.

    Args:
        load: Coroutine function that loads the resource.
        unload: Optional callable (sync or async) that releases it.
    """

    reports_ready = True

    def __init__(
        self,
        load: Callable[[], Awaitable[None]],
        unload: Callable[[], object] | None = None,
    ) -> None:
        super().__init__()
        self.load = load
        self.unload = unload

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._spawn(self._run())

    async def _run(self) -> None:
        try:
            await self.load()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.reporter.crashed(exc)
        else:
            self.reporter.ready()

    async def stop(self) -> None:
        await super().stop()
        if self.unload is not None:
            result = self.unload()
            if inspect.isawaitable(result):
                await result


class ThreadLoopProcess(ManagedProcess):
    """Call blocking ``work`` every ``interval_s`` seconds on a daemon thread.

    Stop sets an event and joins the thread, so a restart never leaves the old
    thread behind.

    Args:
        interval_s: Pause between calls, in seconds.
        work: Blocking callable.
        join_timeout_s: How long ``stop`` waits for the thread.
    """

    def __init__(self, interval_s: float, work: Callable[[], None], join_timeout_s: float = 10) -> None:
        self.interval_s = interval_s
        self.work = work
        self.join_timeout_s = join_timeout_s
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._loop = asyncio.get_running_loop()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"process:{self.process_id}", daemon=True)
        self._thread.start()

    def _report(self, fn: Callable[..., None], *args: object) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(fn, *args)

    def _run(self) -> None:
        stop = self._stop
        while not stop.is_set():
            try:
                self.work()
            except Exception as exc:
                self._report(self.reporter.tick_failed, exc)
            else:
                self._report(self.reporter.tick_ok)
            stop.wait(self.interval_s)

    async def stop(self) -> None:
        thread, self._thread = self._thread, None
        self._stop.set()
        if thread is not None and thread.is_alive():
            await asyncio.to_thread(thread.join, self.join_timeout_s)
