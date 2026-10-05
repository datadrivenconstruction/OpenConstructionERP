# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The contracts subscribers that follow the schedule.

They are bound when the module's events file is imported, never raise into
the publisher, ignore a payload they cannot act on, and only refresh
forecasts for an activity edit that moved a date.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.events import Event, event_bus
from app.modules.contracts import events as contract_events

pytestmark = pytest.mark.asyncio


class _FakeService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, Any, dict[str, Any]]] = []

    async def _record(self, name: str, arg: Any, **kwargs: Any) -> int:
        self.calls.append((name, arg, kwargs))
        if self.fail:
            raise RuntimeError("database gone")
        return 1

    async def mark_milestones_reached(self, activity_id, **kwargs):
        return await self._record("reached", activity_id, **kwargs)

    async def reopen_milestones(self, activity_id, **kwargs):
        return await self._record("reopened", activity_id, **kwargs)

    async def refresh_linked_forecasts(self, **kwargs):
        return await self._record("refresh", None, **kwargs)


@pytest.fixture
def fake(monkeypatch) -> _FakeService:
    service = _FakeService()

    async def _run(work):
        return await work(service)

    monkeypatch.setattr(contract_events, "_with_contracts_service", _run)
    return service


def test_every_handler_is_bound_once() -> None:
    contract_events.register_payment_plan_subscribers()
    expected = {
        "schedule.milestone.reached": contract_events._on_schedule_milestone_reached,
        "schedule.milestone.reopened": contract_events._on_schedule_milestone_reopened,
        "schedule.rescheduled": contract_events._on_schedule_dates_moved,
        "schedule.activity.updated": contract_events._on_schedule_dates_moved,
        "schedule.activity.deleted": contract_events._on_schedule_dates_moved,
        "schedule.activities.cleared": contract_events._on_schedule_dates_moved,
    }
    for name, handler in expected.items():
        assert event_bus._handlers[name].count(handler) == 1, name
    assert contract_events._on_schedule_dates_moved not in event_bus._handlers.get("schedule.cpm.calculated", [])


async def test_reached_passes_the_payload_through(fake) -> None:
    activity_id, project_id = uuid.uuid4(), uuid.uuid4()
    result = await contract_events._on_schedule_milestone_reached(
        Event(
            name="schedule.milestone.reached",
            data={
                "activity_id": str(activity_id),
                "project_id": str(project_id),
                "reached_at": "2026-06-08T16:00:00+00:00",
                "actor_id": "u1",
            },
        )
    )
    assert result == {"status": "ok", "moved": 1}
    assert fake.calls == [
        (
            "reached",
            activity_id,
            {"project_id": project_id, "reached_at": "2026-06-08T16:00:00+00:00", "actor_id": "u1"},
        )
    ]


async def test_reopened_passes_the_activity_and_project(fake) -> None:
    activity_id = uuid.uuid4()
    await contract_events._on_schedule_milestone_reopened(
        Event(name="schedule.milestone.reopened", data={"activity_id": str(activity_id)})
    )
    assert fake.calls == [("reopened", activity_id, {"project_id": None})]


@pytest.mark.parametrize(
    "handler",
    [contract_events._on_schedule_milestone_reached, contract_events._on_schedule_milestone_reopened],
)
async def test_a_payload_without_a_usable_activity_is_ignored(fake, handler) -> None:
    result = await handler(Event(name="x", data={"activity_id": "not-a-uuid"}))
    assert result["status"] == "ignored"
    assert fake.calls == []


async def test_a_failure_is_logged_and_never_raised(monkeypatch) -> None:
    service = _FakeService(fail=True)

    async def _run(work):
        return await work(service)

    monkeypatch.setattr(contract_events, "_with_contracts_service", _run)
    result = await contract_events._on_schedule_milestone_reached(
        Event(name="schedule.milestone.reached", data={"activity_id": str(uuid.uuid4())})
    )
    assert result == {"status": "error"}


async def test_a_reschedule_refreshes_the_whole_schedule(fake) -> None:
    schedule_id = uuid.uuid4()
    await contract_events._on_schedule_dates_moved(
        Event(name="schedule.rescheduled", data={"schedule_id": str(schedule_id), "count": 3})
    )
    assert fake.calls == [("refresh", None, {"activity_id": None, "schedule_id": schedule_id})]


async def test_an_activity_edit_refreshes_only_when_its_finish_moved(fake) -> None:
    activity_id = uuid.uuid4()
    renamed = await contract_events._on_schedule_dates_moved(
        Event(
            name="schedule.activity.updated",
            data={"activity_id": str(activity_id), "schedule_id": str(uuid.uuid4()), "fields": ["name"]},
        )
    )
    assert renamed["status"] == "ignored"
    await contract_events._on_schedule_dates_moved(
        Event(
            name="schedule.activity.updated",
            data={"activity_id": str(activity_id), "schedule_id": str(uuid.uuid4()), "fields": ["end_date"]},
        )
    )
    assert fake.calls == [("refresh", None, {"activity_id": activity_id, "schedule_id": None})]
