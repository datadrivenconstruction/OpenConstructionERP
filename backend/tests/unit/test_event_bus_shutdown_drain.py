# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shutdown waits, within a bound, for detached event subscribers.

``EventBus.publish_detached`` hands the request back at once and lets the
subscribers run afterwards. Before :meth:`EventBus.drain` existed nothing ever
awaited those tasks: a restart that landed while one was running disposed the
database engine under it, and whatever the subscriber was about to write was
lost with no trace beyond a "Task was destroyed but it is pending" line.

Every test here uses its own ``EventBus`` instance. The suite's conftest
replaces ``publish_detached`` on the global singleton with a synchronous shim,
so only a fresh instance exercises the production path that fills
``_background_tasks``.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import time

from app.core import events as events_module
from app.core.events import Event, EventBus


async def test_nothing_pending_returns_at_once() -> None:
    bus = EventBus()
    started = time.monotonic()

    result = await bus.drain(timeout=5.0)

    assert (result.finished, result.cancelled) == (0, 0)
    assert time.monotonic() - started < 0.5


async def test_a_slow_subscriber_is_allowed_to_finish() -> None:
    """The write a subscriber was in the middle of is what drain exists to keep."""
    bus = EventBus()
    written: list[str] = []

    async def slow_writer(event: Event) -> None:
        await asyncio.sleep(0.05)
        written.append(event.data["id"])

    bus.subscribe("thing.created", slow_writer)
    bus.publish_detached("thing.created", {"id": "a"})
    bus.publish_detached("thing.created", {"id": "b"})
    assert not written, "the subscriber ran in line, so this test would prove nothing about draining"

    result = await bus.drain(timeout=5.0)

    assert sorted(written) == ["a", "b"]
    assert result.cancelled == 0
    assert result.finished == 2
    assert not bus.pending_tasks()


async def test_events_published_by_a_subscriber_are_drained_too() -> None:
    """A failed inspection becomes a punch suggestion; the second hop must not be dropped."""
    bus = EventBus()
    seen: list[str] = []

    async def first_hop(event: Event) -> None:
        await asyncio.sleep(0.02)
        seen.append("first")
        bus.publish_detached("second.hop", {})

    async def second_hop(event: Event) -> None:
        await asyncio.sleep(0.02)
        seen.append("second")

    bus.subscribe("first.hop", first_hop)
    bus.subscribe("second.hop", second_hop)
    bus.publish_detached("first.hop", {})

    result = await bus.drain(timeout=5.0)

    assert seen == ["first", "second"]
    assert result.finished == 2
    assert result.cancelled == 0


async def test_a_stuck_subscriber_is_cancelled_at_the_deadline() -> None:
    """The wait is bounded: a hung handler cannot hold a restart hostage."""
    bus = EventBus()
    cancelled: list[bool] = []

    async def hangs(event: Event) -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    bus.subscribe("never.ends", hangs)
    task = bus.publish_detached("never.ends", {})
    started = time.monotonic()

    result = await bus.drain(timeout=0.1)

    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"drain took {elapsed:.2f}s against a 0.1s budget"
    assert result.cancelled == 1
    assert result.finished == 0
    assert cancelled == [True]
    assert task.cancelled()


async def test_a_handler_that_swallows_cancellation_still_cannot_block_shutdown() -> None:
    bus = EventBus()
    release = asyncio.Event()

    async def stubborn(event: Event) -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            # Ignores the cancel and keeps waiting.
            await release.wait()

    bus.subscribe("stubborn", stubborn)
    task = bus.publish_detached("stubborn", {})
    started = time.monotonic()

    result = await bus.drain(timeout=0.05)

    assert time.monotonic() - started < 3.0
    assert result.cancelled == 1
    # Tidy up so the session-scoped loop is left clean for the next test.
    release.set()
    await asyncio.wait({task}, timeout=1.0)
    assert task.done()


async def test_a_fast_task_finishes_while_a_slow_one_is_cut_off() -> None:
    """Both counters at once, so neither can be right by accident."""
    bus = EventBus()
    done: list[str] = []

    async def quick(event: Event) -> None:
        await asyncio.sleep(0.01)
        done.append("quick")

    async def slow(event: Event) -> None:
        await asyncio.sleep(60)

    bus.subscribe("quick", quick)
    bus.subscribe("slow", slow)
    bus.publish_detached("quick", {})
    bus.publish_detached("slow", {})

    result = await bus.drain(timeout=0.2)

    assert done == ["quick"]
    assert (result.finished, result.cancelled) == (1, 1)


async def test_log_failures_tasks_are_drained_as_well() -> None:
    """``_log_failures`` keeps its own task set; shutdown must not forget it."""
    bus = EventBus()
    # Wired exactly as the application singleton is wired.
    bus._extra_task_sets.append(events_module._DETACHED_TASKS)
    written: list[int] = []

    async def side_effect() -> None:
        await asyncio.sleep(0.03)
        written.append(1)

    events_module._log_failures(side_effect(), name="test.side_effect")
    assert bus.pending_tasks(), "the detached side effect is not visible to the drain"

    result = await bus.drain(timeout=5.0)

    assert written == [1]
    # At least: the set is process-wide, so a straggler from another test may
    # finish inside the same drain. Ours finishing is what the line above shows.
    assert result.finished >= 1
    assert result.cancelled == 0


def test_the_application_bus_tracks_log_failures_tasks() -> None:
    assert any(s is events_module._DETACHED_TASKS for s in events_module.event_bus._extra_task_sets)


async def test_a_zero_budget_cancels_without_waiting() -> None:
    bus = EventBus()

    async def slow(event: Event) -> None:
        await asyncio.sleep(60)

    bus.subscribe("slow", slow)
    task = bus.publish_detached("slow", {})

    result = await bus.drain(timeout=0)

    assert result.cancelled == 1
    assert task.cancelled()


async def test_drain_called_from_inside_a_detached_task_does_not_wait_on_itself() -> None:
    """A shutdown triggered from a handler must not deadlock on its own task."""
    bus = EventBus()
    outcome: list[tuple[int, int]] = []

    async def shuts_down(event: Event) -> None:
        result = await bus.drain(timeout=0.5)
        outcome.append((result.finished, result.cancelled))

    bus.subscribe("shutdown.requested", shuts_down)
    task = bus.publish_detached("shutdown.requested", {})
    await asyncio.wait_for(task, timeout=3.0)

    assert outcome == [(0, 0)]


def test_application_shutdown_drains_before_disposing_the_engine() -> None:
    """The drain is only useful while the pool still exists to write with.

    Read from the source because running the real shutdown hook would dispose
    the shared test engine and stop the embedded cluster under the rest of the
    suite.
    """
    main_py = pathlib.Path(events_module.__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(main_py.read_text(encoding="utf-8"))

    shutdown = next(
        node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "shutdown"
    )
    calls: list[tuple[int, str]] = []
    for node in ast.walk(shutdown):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            owner_name = owner.id if isinstance(owner, ast.Name) else ""
            calls.append((node.lineno, f"{owner_name}.{node.func.attr}"))
    calls.sort()
    names = [name for _, name in calls]

    assert "event_bus.drain" in names, f"shutdown never drains the event bus: {names}"
    assert "engine.dispose" in names, f"shutdown no longer disposes the engine, update this test: {names}"
    assert names.index("event_bus.drain") < names.index("engine.dispose")
