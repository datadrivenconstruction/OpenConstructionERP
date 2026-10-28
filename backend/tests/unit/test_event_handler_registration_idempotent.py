# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Starting the application twice in one process must not double every handler.

``register_event_handlers`` runs from the lifespan, which is once per process in
production and more often anywhere the app is started again in place: the test
suite does it, and so does any embedded run that stops and restarts the ASGI app
without a new interpreter. ``EventBus.subscribe`` appends blindly, so before the
guard below a second lifespan left two copies of all twenty-five handlers on the
bus - the same notification delivered twice, and every event pushed to every
configured outgoing webhook twice.

The bus is a process-global singleton, so each test here snapshots both
registries and puts them back verbatim: registering the real cross-module
handlers leaves subscribers that open their own database session, and leaking
those into the rest of the run is the pollution class this file exists to
describe.
"""

from __future__ import annotations

import pytest

from app.core.event_handlers import (
    _dispatch_to_webhooks,
    _notify_ncr_created,
    register_event_handlers,
)
from app.core.events import event_bus


@pytest.fixture
def restored_bus():
    """Snapshot both bus registries and put them back after the test."""
    saved = {name: list(handlers) for name, handlers in event_bus._handlers.items()}
    saved_wildcard = list(event_bus._wildcard_handlers)
    try:
        yield event_bus
    finally:
        event_bus._handlers.clear()
        for name, handlers in saved.items():
            event_bus._handlers[name] = handlers
        event_bus._wildcard_handlers[:] = saved_wildcard


def _snapshot() -> tuple[dict[str, list], list]:
    return (
        {name: list(handlers) for name, handlers in event_bus._handlers.items()},
        list(event_bus._wildcard_handlers),
    )


# ── subscribe_once ─────────────────────────────────────────────────────────


def test_subscribe_once_binds_a_new_handler(restored_bus) -> None:
    async def handler(event) -> None:  # type: ignore[no-untyped-def]
        return None

    assert event_bus.subscribe_once("probe.once", handler) is True
    assert event_bus._handlers["probe.once"] == [handler]


def test_subscribe_once_refuses_the_same_handler_twice(restored_bus) -> None:
    async def handler(event) -> None:  # type: ignore[no-untyped-def]
        return None

    event_bus.subscribe_once("probe.once", handler)
    assert event_bus.subscribe_once("probe.once", handler) is False
    assert event_bus._handlers["probe.once"] == [handler]


def test_subscribe_once_still_binds_a_different_handler(restored_bus) -> None:
    """The guard is per handler, not per event: two handlers still both bind."""

    async def first(event) -> None:  # type: ignore[no-untyped-def]
        return None

    async def second(event) -> None:  # type: ignore[no-untyped-def]
        return None

    event_bus.subscribe_once("probe.once", first)
    event_bus.subscribe_once("probe.once", second)
    assert event_bus._handlers["probe.once"] == [first, second]


def test_subscribe_once_guards_the_wildcard_registry_too(restored_bus) -> None:
    """``"*"`` lives in a second list, and that is where the webhook fan-out is."""

    async def handler(event) -> None:  # type: ignore[no-untyped-def]
        return None

    assert event_bus.subscribe_once("*", handler) is True
    assert event_bus.subscribe_once("*", handler) is False
    assert event_bus._wildcard_handlers.count(handler) == 1


def test_subscribe_once_recognises_a_re_derived_bound_method(restored_bus) -> None:
    """``self.method`` is a fresh object each time but compares equal."""

    class Sink:
        async def handle(self, event) -> None:  # type: ignore[no-untyped-def]
            return None

    sink = Sink()
    event_bus.subscribe_once("probe.once", sink.handle)
    assert event_bus.subscribe_once("probe.once", sink.handle) is False
    assert len(event_bus._handlers["probe.once"]) == 1


# ── the cross-module registrar ─────────────────────────────────────────────


def test_registering_the_cross_module_handlers_twice_changes_nothing(restored_bus) -> None:
    """A second lifespan in the same process must leave the bus as it was."""
    register_event_handlers()
    after_first = _snapshot()

    register_event_handlers()
    register_event_handlers()

    assert _snapshot() == after_first


def test_a_second_registration_does_not_double_a_notification(restored_bus) -> None:
    """Named case: the NCR notification, one handler however often we register."""
    register_event_handlers()
    register_event_handlers()

    assert event_bus._handlers["ncr.created"].count(_notify_ncr_created) == 1


def test_a_second_registration_does_not_double_the_webhook_fan_out(restored_bus) -> None:
    """Named case: the wildcard dispatcher, which would post every event twice."""
    register_event_handlers()
    register_event_handlers()

    assert event_bus._wildcard_handlers.count(_dispatch_to_webhooks) == 1
