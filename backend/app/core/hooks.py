"""Hook system for data transformation and action injection.

Two types:
- **Filters**: transform data through a chain of handlers (like WordPress filters).
  Each handler receives data, modifies it, returns it. Chain order = priority.
- **Actions**: fire-and-forget side effects at specific points (like WordPress actions).

Usage:
    # Register a filter (in a module):
    @hooks.filter("boq.position.before_save", priority=10)
    async def auto_classify_position(position: dict) -> dict:
        position["classification"]["din276"] = classify(position["description"])
        return position

    # Apply filter (in core):
    position_data = await hooks.apply_filters("boq.position.before_save", position_data)

    # Register an action:
    @hooks.action("boq.export.completed")
    async def log_export(data: dict) -> None:
        logger.info("BOQ exported: %s", data["boq_id"])
"""

import asyncio
import inspect
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

HookHandler = Callable[..., Any]


@dataclass
class HookEntry:
    """A registered hook handler with priority."""

    handler: HookHandler
    priority: int
    module: str | None = None


class HookRegistry:
    """Central registry for filters and actions."""

    def __init__(self) -> None:
        self._filters: dict[str, list[HookEntry]] = defaultdict(list)
        self._actions: dict[str, list[HookEntry]] = defaultdict(list)

    # ── Registration ────────────────────────────────────────────────────

    def filter(self, hook_name: str, priority: int = 10, module: str | None = None) -> Callable:
        """Decorator: register a filter handler."""

        def decorator(func: HookHandler) -> HookHandler:
            entry = HookEntry(handler=func, priority=priority, module=module)
            self._filters[hook_name].append(entry)
            self._filters[hook_name].sort(key=lambda e: e.priority)
            return func

        return decorator

    def action(self, hook_name: str, priority: int = 10, module: str | None = None) -> Callable:
        """Decorator: register an action handler."""

        def decorator(func: HookHandler) -> HookHandler:
            entry = HookEntry(handler=func, priority=priority, module=module)
            self._actions[hook_name].append(entry)
            self._actions[hook_name].sort(key=lambda e: e.priority)
            return func

        return decorator

    def add_filter(
        self,
        hook_name: str,
        handler: HookHandler,
        priority: int = 10,
        module: str | None = None,
    ) -> None:
        """Programmatic filter registration."""
        entry = HookEntry(handler=handler, priority=priority, module=module)
        self._filters[hook_name].append(entry)
        self._filters[hook_name].sort(key=lambda e: e.priority)

    def add_action(
        self,
        hook_name: str,
        handler: HookHandler,
        priority: int = 10,
        module: str | None = None,
    ) -> None:
        """Programmatic action registration."""
        entry = HookEntry(handler=handler, priority=priority, module=module)
        self._actions[hook_name].append(entry)
        self._actions[hook_name].sort(key=lambda e: e.priority)

    # ── Execution ───────────────────────────────────────────────────────

    async def apply_filters(self, hook_name: str, data: Any, **context: Any) -> Any:
        """Run data through all registered filter handlers in priority order.

        Each handler receives the output of the previous one.
        """
        entries = self._filters.get(hook_name, [])
        result = data

        for entry in entries:
            try:
                if inspect.iscoroutinefunction(entry.handler):
                    result = await entry.handler(result, **context)
                else:
                    result = await asyncio.to_thread(entry.handler, result, **context)
            except Exception:
                logger.exception(
                    "Error in filter '%s' handler %s (module=%s)",
                    hook_name,
                    entry.handler.__qualname__,
                    entry.module,
                )
                raise  # Filters are critical — propagate errors

        return result

    async def do_actions(self, hook_name: str, **kwargs: Any) -> None:
        """Execute all registered action handlers. Errors are logged, not propagated."""
        entries = self._actions.get(hook_name, [])

        for entry in entries:
            try:
                if inspect.iscoroutinefunction(entry.handler):
                    await entry.handler(**kwargs)
                else:
                    await asyncio.to_thread(entry.handler, **kwargs)
            except Exception:
                logger.exception(
                    "Error in action '%s' handler %s (module=%s)",
                    hook_name,
                    entry.handler.__qualname__,
                    entry.module,
                )

    # ── Introspection ───────────────────────────────────────────────────

    def list_filters(self) -> dict[str, list[str]]:
        return {
            name: [f"{e.handler.__qualname__} (p={e.priority})" for e in entries]
            for name, entries in self._filters.items()
        }

    def list_actions(self) -> dict[str, list[str]]:
        return {
            name: [f"{e.handler.__qualname__} (p={e.priority})" for e in entries]
            for name, entries in self._actions.items()
        }

    def clear(self) -> None:
        """Remove all hooks. Used in testing."""
        self._filters.clear()
        self._actions.clear()


# Global singleton
hooks = HookRegistry()
