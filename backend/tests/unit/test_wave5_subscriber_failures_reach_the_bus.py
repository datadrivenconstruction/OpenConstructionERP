# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A wave-5 subscriber that fails says so on the bus.

Every handler in ``_wave5_cross_module_subscribers`` used to wrap its whole
body in ``except Exception`` and report the failure at ``logger.debug``. The
bus already does better than that: ``EventBus.publish`` isolates each handler
in its own ``try``, logs the traceback at exception level, and records the
failure in ``EventResult.errors`` while the remaining handlers still run. The
inner catch therefore bought no isolation - it only discarded the record.

The consequence was not a crash but a silence. A subscriber that failed
produced a missing side effect and one debug line, and a caller holding the
``EventResult`` was told the publish had succeeded.

This test breaks a handler from the inside rather than standing in for it.
Replacing the handler with a stand-in that raises would pass identically
whether or not the catch is present, because the stand-in has no catch of its
own; the exception would reach the bus either way. So the real handler runs,
and the session it opens is what fails.
"""

from __future__ import annotations

import pytest

from app.core.events import EventBus
from app.modules.notifications import _wave5_cross_module_subscribers as w5


class _SessionThatCannotBeOpened:
    """Stands in for ``async_session_factory`` and fails where it is used.

    ``_on_cert_expiring`` calls this inside its ``try``, after every early
    return has been passed, so a handler that reaches it has committed to
    doing work. Raising here is the closest thing to a real infrastructure
    failure that a unit test can arrange, and it is the failure the handler
    used to hide.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> _SessionThatCannotBeOpened:
        self.calls += 1
        raise RuntimeError("the database session could not be opened")


@pytest.mark.asyncio
async def test_a_failing_subscriber_is_recorded_on_the_event_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure reaches ``EventResult.errors`` and names the handler.

    The bus is a fresh ``EventBus`` rather than the application's, and that
    is load-bearing. Two handlers are registered on ``"*"`` on the global
    bus - ``boq._log_boq_activity`` and ``timeline._record_event`` - and they
    run for every event. Either of them raising would fill ``errors`` for a
    reason that has nothing to do with this subscriber, and the test would be
    green before the catch was removed. A fresh bus has no wildcard handlers,
    so the only failure it can record is the one this test arranges.
    """
    factory = _SessionThatCannotBeOpened()
    monkeypatch.setattr(w5, "async_session_factory", factory)

    bus = EventBus()
    bus.subscribe("resources.cert_expiring", w5._on_cert_expiring)

    result = await bus.publish(
        "resources.cert_expiring",
        {
            "resource_id": "0f5a1f1e-1f2a-4c3b-9d4e-5a6b7c8d9e0f",
            "cert_type": "scaffolding",
            "valid_until": "2026-09-01",
            "window_days": 7,
        },
        source_module="resources",
    )

    # Measured before anything is concluded about the errors. A handler that
    # returned early never reached the session and never raised, and its
    # empty error list would otherwise read as a swallow.
    assert factory.calls == 1, (
        "the handler did not reach the session it opens, so it cannot have "
        "failed there and this test is measuring nothing. Check the guards "
        "above the try in _on_cert_expiring against the payload above."
    )

    assert not result.success, f"the publish reported success despite a failing handler; errors={result.errors}"
    assert any(entry["handler"] == "_on_cert_expiring" for entry in result.errors), (
        f"the failure was not recorded against the handler that caused it; errors={result.errors}"
    )
    recorded = next(entry for entry in result.errors if entry["handler"] == "_on_cert_expiring")
    assert recorded["type"] == "RuntimeError"
    assert "could not be opened" in recorded["error"]


@pytest.mark.asyncio
async def test_one_failing_subscriber_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """The isolation the removed catch appeared to provide belongs to the bus.

    This is the assertion that makes the removal safe rather than merely
    tidier, and it is written from the other side: the neighbour must still
    run, and its result must still be recorded, while the failing handler is
    reported. If ``EventBus.publish`` ever stopped isolating handlers, this
    fails and the catches would have to come back.
    """
    factory = _SessionThatCannotBeOpened()
    monkeypatch.setattr(w5, "async_session_factory", factory)

    ran: list[str] = []

    async def _neighbour(event) -> str:
        ran.append(event.name)
        return "neighbour ok"

    bus = EventBus()
    bus.subscribe("resources.cert_expiring", w5._on_cert_expiring)
    bus.subscribe("resources.cert_expiring", _neighbour)

    result = await bus.publish("resources.cert_expiring", {"resource_id": "not-a-uuid-but-truthy"})

    assert factory.calls == 1
    assert ran == ["resources.cert_expiring"], "the neighbour did not run after the first handler failed"
    assert any(entry["handler"] == "_on_cert_expiring" for entry in result.errors)
    assert any(entry["result"] == "neighbour ok" for entry in result.handler_results)
