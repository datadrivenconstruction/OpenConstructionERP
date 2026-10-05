# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A schedule milestone falls due on one sales contract, never on all of them.

Milestone names (``foundation_complete``) are free text that every tenant
uses. The handler used to fall back to matching on the name alone when the
event named no contract, which marked other companies' buyers as owing
money. Nothing publishes the event yet; this pins the guard before anything
does.
"""

from __future__ import annotations

import pytest

from app.core.events import Event
from app.modules.property_dev import events as pd_events


class _NoSession:
    def __call__(self):
        raise AssertionError("the handler opened a database session")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"milestone_event": "foundation_complete"}, "no sales_contract_id in payload"),
        ({"milestone_event": "foundation_complete", "sales_contract_id": "not-a-uuid"}, "bad spa_id"),
    ],
)
async def test_a_milestone_without_a_contract_touches_nothing(monkeypatch, payload, reason):
    monkeypatch.setattr(pd_events, "async_session_factory", _NoSession())

    result = await pd_events._on_schedule_milestone_reached(Event(name="schedule.milestone.reached", data=payload))

    assert result == {"status": "ignored", "reason": reason}


def test_no_query_matches_instalments_by_milestone_name_alone():
    from app.modules.property_dev import repository

    assert not hasattr(repository.InstalmentRepository, "list_due_for_milestone")
