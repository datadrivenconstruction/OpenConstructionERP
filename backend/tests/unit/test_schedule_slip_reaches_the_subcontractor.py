"""``schedule.activity.slipped`` names a contact; the rating needs the subcontractor."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.events import Event
from app.modules.subcontractors import events as sub_events


@pytest.mark.asyncio
async def test_a_slip_naming_a_subcontractor_directly_bumps_the_schedule_rating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bumped: list[tuple[str, Any]] = []

    async def _bump(kind: str, event: Event) -> None:
        bumped.append((kind, event.data))

    monkeypatch.setattr(sub_events, "_bump", _bump)
    sub = str(uuid.uuid4())

    await sub_events._on_schedule_slipped(Event(name="schedule.activity.slipped", data={"subcontractor_id": sub}))

    assert bumped == [("schedule", {"subcontractor_id": sub})]


@pytest.mark.asyncio
async def test_a_slip_with_no_one_to_charge_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    bumped: list[str] = []

    async def _bump(kind: str, event: Event) -> None:
        bumped.append(kind)

    monkeypatch.setattr(sub_events, "_bump", _bump)

    await sub_events._on_schedule_slipped(Event(name="schedule.activity.slipped", data={"activity_id": "x"}))

    assert bumped == []
