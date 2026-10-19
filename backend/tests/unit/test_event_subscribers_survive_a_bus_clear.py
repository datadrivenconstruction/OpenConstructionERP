# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A module's subscribers must come back when its registrar runs on an emptied bus.

Registrars used to guard themselves with a flag, either set on ``event_bus``
(``setattr(event_bus, "_x_subscribers_registered", True)``) or held in a module
global. The handlers live in the bus registries and the flag lived somewhere
else, so anything that emptied the registries without the flag - ``EventBus.clear()``,
a test restoring a snapshot of ``_handlers``, an in-process restart over a fresh
bus - left the module deaf for the rest of the process: the next call to the
registrar returned at its first line. Nothing logged and nothing raised.

Every registrar subscribes through ``EventBus.subscribe_once``, which compares
handlers and skips one already bound. That makes the registrar idempotent by
itself, so the flags were never needed for idempotency and are gone. These
tests pin both halves: a second call adds nothing, and a call after the bus was
emptied subscribes again.
"""

from __future__ import annotations

import importlib
import re
import uuid
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.events import event_bus

# (module, registrar). Every registrar that carried a flag guard.
REGISTRARS: list[tuple[str, str]] = [
    ("app.modules.bi_dashboards.events", "register_subscribers"),
    ("app.modules.closeout.events", "register_closeout_subscribers"),
    ("app.modules.daily_diary.events", "register_subscribers"),
    ("app.modules.geo_hub.events", "register_subscribers"),
    ("app.modules.hse_advanced.events", "register_subscribers"),
    ("app.modules.moc.events", "register_subscribers"),
    ("app.modules.ncr.events", "register_subscribers"),
    ("app.modules.property_dev.events", "register_subscribers"),
    ("app.modules.property_dev.events", "register_task_139_subscribers"),
    ("app.modules.property_dev.events", "register_warranty_bridge_subscribers"),
    ("app.modules.property_dev.events", "register_portal_message_subscribers"),
    ("app.modules.punchlist.events", "register_punchlist_event_subscribers"),
    ("app.modules.qms.events", "register_subscribers"),
    ("app.modules.rfi.approval_subscribers", "register_rfi_approval_subscribers"),
    ("app.modules.safety.events", "register_subscribers"),
    ("app.modules.submittals.approval_subscribers", "register_submittal_approval_subscribers"),
    ("app.modules.supplier_catalogs.events", "register_subscribers"),
    ("app.modules.timeline.events", "register_timeline_subscribers"),
    ("app.modules.schedule.realtime_router", "register_schedule_realtime_subscribers"),
]


@pytest.fixture
def restored_bus() -> Iterator[None]:
    """Give the test the bus to empty, and put every registration back afterwards."""
    saved_named = {name: list(handlers) for name, handlers in event_bus._handlers.items()}
    saved_wildcard = list(event_bus._wildcard_handlers)
    try:
        yield
    finally:
        event_bus._handlers.clear()
        event_bus._handlers.update(saved_named)
        event_bus._wildcard_handlers[:] = saved_wildcard


def _bound() -> Counter:
    """Every (event, handler) pair on the bus, counted."""
    pairs: Counter = Counter()
    for name, handlers in event_bus._handlers.items():
        for handler in handlers:
            pairs[(name, handler)] += 1
    for handler in event_bus._wildcard_handlers:
        pairs[("*", handler)] += 1
    return pairs


@pytest.mark.parametrize(("module_name", "registrar_name"), REGISTRARS, ids=[f"{m}.{r}" for m, r in REGISTRARS])
def test_a_registrar_subscribes_again_after_the_bus_was_cleared(restored_bus, module_name, registrar_name) -> None:
    registrar = getattr(importlib.import_module(module_name), registrar_name)

    event_bus.clear()
    registrar()
    first = _bound()
    assert first, f"{module_name}.{registrar_name} subscribed nothing on an empty bus"

    event_bus.clear()
    registrar()
    assert _bound() == first, (
        f"{module_name}.{registrar_name} did not subscribe again after EventBus.clear(): the module is deaf"
    )

    registrar()
    assert _bound() == first, f"{module_name}.{registrar_name} stacked a second copy of its handlers"


async def test_a_cleared_and_re_registered_module_still_receives_its_events(restored_bus) -> None:
    """Delivery through the bus, not a handler called by hand.

    bi_dashboards turns ``bi_dashboards.kpi_recompute`` into an in-process
    freshness watermark, which makes the effect observable without a database.
    """
    from app.modules.bi_dashboards import events as bi_events

    bi_events.register_subscribers()
    event_bus.clear()
    bi_events.register_subscribers()

    project_id = str(uuid.uuid4())
    assert project_id not in bi_events._KPI_WATERMARKS

    result = await event_bus.publish(
        "bi_dashboards.kpi_recompute",
        {"project_id": project_id, "reason": "test", "source_event": "test.event"},
        source_module="tests",
    )

    assert result.success
    assert project_id in bi_events._KPI_WATERMARKS, "the re-registered subscriber never ran"
    bi_events._KPI_WATERMARKS.pop(project_id, None)


def test_no_registrar_guards_its_subscriptions_with_a_flag() -> None:
    """A new flag guard brings the deaf-bus defect back; ``subscribe_once`` is the guard."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    offenders = [
        str(path.relative_to(app_dir.parent))
        for path in app_dir.rglob("*.py")
        if re.search(r"setattr\(\s*event_bus\s*,", path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"subscriptions guarded by a flag on event_bus: {offenders}"
