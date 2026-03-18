"""Event bus for inter-module communication.

Modules publish events; other modules subscribe to them.
Supports both sync and async handlers.
Decouples modules from each other — no direct imports needed.

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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

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

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove a handler."""
        if event_name == "*":
            self._wildcard_handlers.remove(handler)
        else:
            self._handlers[event_name].remove(handler)

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
        return {
            name: [h.__qualname__ for h in handlers] for name, handlers in self._handlers.items()
        }

    def clear(self) -> None:
        """Remove all handlers. Used in testing."""
        self._handlers.clear()
        self._wildcard_handlers.clear()


# Global singleton
event_bus = EventBus()
