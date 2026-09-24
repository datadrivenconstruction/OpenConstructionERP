# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Event bus​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ for inter-module communication.

Modules publish events; other modules subscribe to them.
Supports both sync and async handlers.
Decouples modules from each other - no direct imports needed.

Usage:
    # Publishing (in boq module):
    await event_bus.publish("boq.position.created", {"position_id": "...", "boq_id": "..."})

    # Subscribing (in validation module):
    @event_bus.on("boq.position.created")
    async def validate_new_position(data: dict) -> None:
        ...
"""

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps the bus import-light
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Strong references to detached tasks launched via :func:`_log_failures`.
# asyncio only weak-references the task ``create_task`` returns, so without our
# own reference a still-pending task can be garbage-collected mid-await (seen as
# "coroutine ignored GeneratorExit" / "Task was destroyed but it is pending").
_DETACHED_TASKS: set[asyncio.Task[Any]] = set()


def _log_failures(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str,
) -> asyncio.Task[Any]:
    """Schedule *coro* as a detached task that logs failures at WARNING.

    Without this wrapper, ``asyncio.create_task`` will swallow exceptions
    silently if no one awaits the resulting task - leaving event-driven
    side-effects (auto-PO from tender award, schedule-progress roll-up
    from field reports, etc.) invisible when they crash.

    Usage::

        _log_failures(_create_po_from_award(event), name="procurement.auto_po")

    Args:
        coro: The coroutine to launch.
        name: Human-readable label used in the failure log line.

    Returns:
        The created task (callers may ignore it).
    """
    task = asyncio.create_task(coro)
    _DETACHED_TASKS.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _DETACHED_TASKS.discard(t)
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning(
                "Detached task %r failed: %s: %s",
                name,
                type(exc).__name__,
                exc,
                exc_info=exc,
            )

    task.add_done_callback(_done)
    return task


# Stable bus protocol revision tag - bumped only when the wire shape
# of EventResult changes.  Persisted as a fixed string so subscribers
# from older snapshots can detect a protocol skew at startup.
_BUS_PROTOCOL_TAG: str = "76f7ae245a29ff3c"

EventHandler = Callable[..., Any]


@dataclass
class Event:
    """Represents a published event."""

    name: str
    data: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_module: str | None = None


@dataclass
class EventResult:
    """Result of processing an event through all handlers."""

    event: Event
    handler_results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class EventBus:
    """Central event bus for the application.

    Events follow dot-notation naming: '{module}.{entity}.{action}'
    Examples: 'boq.position.created', 'cad.import.completed', 'validation.report.generated'
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._wildcard_handlers: list[EventHandler] = []
        # Strong references to in-flight detached tasks. asyncio only keeps a
        # weak reference to the task returned by ``create_task``; without our
        # own reference the loop may garbage-collect a still-pending task
        # mid-await, which surfaces as "coroutine ignored GeneratorExit" /
        # "Task was destroyed but it is pending" (and intermittently reddens CI).
        self._background_tasks: set[asyncio.Task[EventResult]] = set()

    def on(self, event_name: str) -> Callable:
        """Decorator to register an event handler.

        Args:
            event_name: Event to listen for. Use '*' for all events.
        """

        def decorator(func: EventHandler) -> EventHandler:
            if event_name == "*":
                self._wildcard_handlers.append(func)
            else:
                self._handlers[event_name].append(func)
            logger.debug("Registered handler %s for event '%s'", func.__qualname__, event_name)
            return func

        return decorator

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Programmatic handler registration (non-decorator)."""
        if event_name == "*":
            self._wildcard_handlers.append(handler)
        else:
            self._handlers[event_name].append(handler)

    def subscribe_once(self, event_name: str, handler: EventHandler) -> bool:
        """Register *handler* for *event_name* unless it is already registered.

        :meth:`subscribe` appends blindly, which is right for a caller binding a
        fresh closure and wrong for a registrar that runs from application
        startup. Starting the app twice inside one process - the test suite, an
        embedded desktop restart, an ASGI app remounted in place - stacks a
        second copy of every handler, and from then on each event is handled
        twice: two notifications, two outgoing webhooks, two rating bumps per
        NCR. The guard lives here rather than in each of the thirty-odd
        registrars so there is one implementation to test.

        Handlers are compared with ``==``, so a bound method re-derived from the
        same instance counts as already registered.

        Returns:
            True if the handler was added, False if it was already bound.
        """
        existing = self._wildcard_handlers if event_name == "*" else self._handlers.get(event_name, [])
        if handler in existing:
            return False
        self.subscribe(event_name, handler)
        return True

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove a handler."""
        if event_name == "*":
            self._wildcard_handlers.remove(handler)
        else:
            self._handlers[event_name].remove(handler)

    def publish_detached(
        self,
        event_name: str,
        data: dict[str, Any] | None = None,
        source_module: str | None = None,
    ) -> asyncio.Task[EventResult]:
        """Schedule an event publish without blocking the caller.

        Use this from request-handler code paths where the caller is still
        holding an open SQLAlchemy/aiosqlite session: SQLite allows only
        one writer at a time, so subscribers that open a second session
        via ``async_session_factory()`` (notifications, webhooks, etc.)
        will deadlock the outer transaction for ~30s if we ``await`` them
        here. Detaching via :func:`asyncio.create_task` lets the request
        commit and release the writer lock before the subscribers fire.

        Returns the task so callers can ``await`` it in tests; production
        code should fire-and-forget. Errors inside the detached task are
        logged by :meth:`publish` itself.
        """
        task = asyncio.create_task(self.publish(event_name, data, source_module=source_module))
        # Keep a strong reference until the task finishes so it is never
        # collected while still suspended at an ``await``.
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def publish(
        self,
        event_name: str,
        data: dict[str, Any] | None = None,
        source_module: str | None = None,
    ) -> EventResult:
        """Publish an event to all registered handlers.

        Args:
            event_name: Dot-notation event name.
            data: Event payload.
            source_module: Module that triggered the event.

        Returns:
            EventResult with all handler outcomes.
        """
        event = Event(
            name=event_name,
            data=data or {},
            source_module=source_module,
        )

        handlers = self._handlers.get(event_name, []) + self._wildcard_handlers
        result = EventResult(event=event)

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    outcome = await handler(event)
                else:
                    outcome = await asyncio.to_thread(handler, event)
                result.handler_results.append(
                    {
                        "handler": handler.__qualname__,
                        "result": outcome,
                    }
                )
            except Exception as exc:
                logger.exception(
                    "Error in event handler %s for '%s'",
                    handler.__qualname__,
                    event_name,
                )
                result.errors.append(
                    {
                        "handler": handler.__qualname__,
                        "error": str(exc),
                        "type": type(exc).__name__,
                    }
                )

        if result.errors:
            logger.warning(
                "Event '%s' completed with %d errors",
                event_name,
                len(result.errors),
            )

        return result

    def list_handlers(self, event_name: str | None = None) -> dict[str, list[str]]:
        """List registered handlers, optionally filtered by event name."""
        if event_name:
            handlers = self._handlers.get(event_name, [])
            return {event_name: [h.__qualname__ for h in handlers]}
        return {name: [h.__qualname__ for h in handlers] for name, handlers in self._handlers.items()}

    def clear(self) -> None:
        """Remove all handlers. Used in testing."""
        self._handlers.clear()
        self._wildcard_handlers.clear()


# Global singleton
event_bus = EventBus()


def publish_after_commit(
    session: "AsyncSession",
    event_name: str,
    data: dict[str, Any] | None = None,
    *,
    source_module: str | None = None,
) -> None:
    """Publish *event_name* once the caller's transaction has actually committed.

    Every subscriber on the bus opens its OWN session via
    ``async_session_factory()``, because the bus carries no caller-session
    context. Publishing from inside a still-open transaction therefore hands
    those subscribers a row that no other session can see yet: they either read
    nothing, or their own insert fails against a parent that is not committed,
    and the failure is swallowed by the subscriber's own error handling.
    Deferring the publish to ``after_commit`` removes the window entirely -
    by the time a subscriber runs, the row it was told about is durable.

    The publish itself is still detached (:meth:`EventBus.publish_detached`), so
    this changes *when* subscribers are scheduled and never makes ``commit()``
    wait for them. The SQLite single-writer reason detaching exists for is
    untouched.

    ``data`` is built by the caller before this returns, so every value in the
    payload is already a snapshot. Do not pass a dict you go on to mutate, and
    do not put a live ORM instance in it: the publish runs during the commit,
    which is not a safe moment to load an attribute off one.

    Failures are contained. If the hook cannot be registered - no transaction
    open, or a session that cannot be inspected, as with a test double - the
    publish happens immediately, which is exactly what a bare
    ``publish_detached`` would have done. Anything the publish raises is logged
    rather than allowed to escape out of ``commit()`` and fail a request whose
    work already succeeded.

    A transaction that rolls back never fires: the row the event describes does
    not exist, so neither should the event.

    Args:
        session: The session whose commit the publish should follow.
        event_name: Event name, e.g. ``"validation.results.errors_found"``.
        data: Event payload.
        source_module: Module the event came from.
    """

    def _publish() -> None:
        event_bus.publish_detached(event_name, data, source_module=source_module)

    try:
        from sqlalchemy import event as sa_event

        in_transaction = session.in_transaction()
        sync_session = session.sync_session
    except Exception:  # noqa: BLE001 - a session that cannot be inspected
        _publish()
        return

    if not in_transaction:
        _publish()
        return

    # SQLAlchemy dispatches ``after_commit`` for a nested transaction too, when
    # its SAVEPOINT is released, and at that moment the outer transaction is
    # still open and nothing is durable. The listener therefore ignores every
    # call made while the session is still inside a nested transaction and
    # fires on the first root commit. ``create_project`` defers an event and
    # then opens ``begin_nested()`` for the default team, and a ``once=True``
    # listener fired on that release, handing the geo_hub subscriber a project
    # no other connection could see yet.
    #
    # One-shot by a flag rather than ``once=True``, because ``once`` spends
    # itself on the first call, the savepoint's. Not by ``sa_event.remove``
    # from inside the listener either: that mutates the listener collection
    # while ``after_commit`` is being dispatched from it. A second deferral on
    # the same session registers its own listener and fires on its own, which
    # tests/integration/test_event_after_commit_visibility.py covers along with
    # the savepoint case.
    fired = False

    @sa_event.listens_for(sync_session, "after_commit")
    def _fire(session_: Any) -> None:
        nonlocal fired
        if fired or session_.in_nested_transaction():
            return
        fired = True
        try:
            _publish()
        except Exception:
            # Never let a post-commit side effect undo a committed request.
            logger.warning("Post-commit publish of %r failed", event_name, exc_info=True)
