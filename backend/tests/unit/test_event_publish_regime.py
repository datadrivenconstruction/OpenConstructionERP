# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Guard the synchronous-publish contract unit tests are written against.

``tests/conftest.py`` replaces ``event_bus.publish_detached`` so a test can call
a service and assert on its own recorder on the very next line, with no await in
between. That shim picks its regime from what is on the bus: one subscriber
doing real async I/O pushes the whole publish onto the event loop, and every
pure recorder goes with it.

The first bug this file guards: an earlier test subscribed such a handler and
never unsubscribed, so from that point on every unit test relying on the
synchronous contract asserted against an empty recorder. The symptom appeared in
an unrelated module, hundreds of tests away from the cause, and vanished
whenever that file was run on its own.

The second, worse one: the guard classified handlers against a hand-kept set of
three names, which covered the ``"*"`` subscribers and none of the 150-odd
per-event ones. A leaked ``boq.position.created`` subscriber therefore looked
pure, was stepped by hand, suspended inside a live asyncpg read and corrupted
the session-scoped loop; every later test in the process died in ``selectors.py``
without reaching application code. So the assertions below are written over real
application subscribers from *both* registries, and none of them depends on a
handler's name.

Importing an events module registers its subscribers on the process-global bus -
that is how the module loader wires the app, and it is also the leak class under
test here. The deliberate leaks are removed again at module teardown.
"""

import asyncio

import pytest

import app.modules.boq.events as boq_events
from app.core.event_handlers import _dispatch_to_webhooks
from app.core.events import event_bus
from app.modules.punchlist.events import _on_clash_high_severity
from app.modules.timeline.events import _record_event

PROBE = "regime.probe"

# Every real application subscriber below opens its own database session, so
# each must be kept out of an in-line publish. Two registries, five modules,
# and not one of them named in the harness.
REAL_IO_SUBSCRIBERS = [
    _dispatch_to_webhooks,
    _record_event,
    boq_events._log_boq_activity,
    boq_events._on_position_created,
    _on_clash_high_severity,
]


@pytest.fixture(scope="module", autouse=True)
def _leaked_io_subscribers():
    """Leave real application subscribers on the bus, the way the bug did.

    One in each registry: the timeline bridge on ``"*"``, the punch-list bridge
    on a named event. Module scope on purpose - they are registered once and stay
    registered across the tests below, which is what makes this a leak rather
    than a setup step. Both are removed at the end so this file is a better
    citizen than the bug it describes, and that removal doubles as the check that
    the harness borrowed nothing: ``unsubscribe`` raises ``ValueError`` if the
    handler is not still on the bus, so a guard that confiscated it instead of
    stepping around it would error here rather than pass quietly.
    """
    event_bus.subscribe("*", _record_event)
    event_bus.subscribe(PROBE, _on_clash_high_severity)
    yield
    event_bus.unsubscribe("*", _record_event)
    event_bus.unsubscribe(PROBE, _on_clash_high_severity)


async def test_recorder_runs_in_line_despite_a_leaked_wildcard_io_handler():
    seen: list[str] = []

    async def recorder(event):
        seen.append(event.name)

    event_bus.subscribe("*", recorder)
    try:
        event_bus.publish_detached(PROBE, {"n": 1})
        # Deliberately no await before the assertion. That gap is the whole
        # contract: a sleep here would make this test pass with the guard
        # removed, which is exactly what it must not do.
        assert seen == [PROBE]
    finally:
        event_bus.unsubscribe("*", recorder)


async def test_recorder_runs_in_line_despite_a_leaked_per_event_io_handler():
    """The half the old guard missed.

    ``_on_clash_high_severity`` is subscribed to a named event, not to ``"*"``,
    so it lives in ``_handlers`` rather than ``_wildcard_handlers``. The previous
    guard looked only at the wildcard list, so a subscriber like this one both
    ran and decided the regime.
    """
    seen: list[str] = []

    async def recorder(event):
        seen.append(event.name)

    event_bus.subscribe(PROBE, recorder)
    try:
        pending = event_bus.publish_detached(PROBE, {})
        assert seen == [PROBE]
    finally:
        event_bus.unsubscribe(PROBE, recorder)

    # The publish finished in line, and the leaked subscriber was not part of it.
    assert pending.done()
    ran = [entry["handler"] for entry in pending.result().handler_results]
    assert "_on_clash_high_severity" not in ran


@pytest.mark.parametrize("handler", REAL_IO_SUBSCRIBERS, ids=lambda h: h.__name__)
async def test_a_real_application_subscriber_is_never_stepped_in_line(handler):
    """State the rule, over the handlers it has to cover.

    A subscriber defined in the application package may open its own database
    session, so an in-line publish must skip it. This is the assertion that the
    structural rule is a superset of the three names the harness used to keep by
    hand: those three are in the list below, and so are two per-event
    subscribers the old list had no way to know about.

    If one of them were classified as pure it would be hand-stepped, suspend on
    its first ``await``, and the shim would raise rather than return - so the
    plain fact that this publish completes in line is itself part of the check.
    """
    seen: list[str] = []

    async def recorder(event):
        seen.append(event.name)

    event_bus.subscribe(PROBE, handler)
    event_bus.subscribe(PROBE, recorder)
    try:
        pending = event_bus.publish_detached(PROBE, {})
    finally:
        event_bus.unsubscribe(PROBE, recorder)
        event_bus.unsubscribe(PROBE, handler)

    assert pending.done(), "publish did not complete in line"
    ran = [entry["handler"] for entry in pending.result().handler_results]
    assert handler.__name__ not in ran, f"{handler.__name__} was stepped in line"
    # The control: a recorder defined by the test is not skipped, so the
    # assertion above is about the handler and not about an empty fan-out.
    assert seen == [PROBE]
    assert any(entry.endswith("recorder") for entry in ran)


async def test_the_leaked_subscribers_stay_on_the_bus():
    """The harness steps around leaked subscribers; it does not confiscate them.

    Tests that assert on event wiring - ``test_doc_assistant_wiring``,
    ``test_subs_rating_event_wiring`` - read the registries directly. A guard
    that deleted handlers would make those pass alone and fail in a chunk,
    which is the same order-dependent shape as the bug being guarded against.
    """
    assert _record_event in event_bus._wildcard_handlers
    assert _on_clash_high_severity in event_bus._handlers.get(PROBE, [])


async def test_delivery_happens_once_not_twice():
    seen: list[str] = []

    async def recorder(event):
        seen.append(event.name)

    event_bus.subscribe("*", recorder)
    try:
        event_bus.publish_detached("regime.probe.solo", {})
        assert seen == ["regime.probe.solo"]
    finally:
        event_bus.unsubscribe("*", recorder)

    await asyncio.sleep(0)
    assert seen == ["regime.probe.solo"]
