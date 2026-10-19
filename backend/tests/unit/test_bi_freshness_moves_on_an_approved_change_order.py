"""An approved change order tells the BI dashboards their EVM figures moved.

Approving a change order writes a budget delta row, which EVM reads as BAC, so
every KPI built on budget is stale the moment it lands. The BI layer keeps a
freshness watermark per project that the frontend polls to refetch, and its
invalidation list named ``variations.completed`` for this. Nothing publishes
that name; the change order module publishes ``changeorder.approved``. A
dashboard open during an approval kept showing the old BAC until reloaded.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

import app.modules.bi_dashboards.events as bi_events
from app.core.events import EventBus


@pytest.fixture
def bi_bus(monkeypatch: pytest.MonkeyPatch) -> EventBus:
    bus = EventBus()
    monkeypatch.setattr(bi_events, "event_bus", bus)
    monkeypatch.setattr(bi_events, "_KPI_WATERMARKS", {})
    bi_events.register_subscribers()
    return bus


async def _settle() -> None:
    # The invalidation handler re-broadcasts through publish_detached, so the
    # watermark moves one task later.
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_an_approved_change_order_advances_its_projects_watermark(bi_bus: EventBus) -> None:
    project_id = str(uuid.uuid4())
    assert bi_events.get_kpi_freshness(project_id)["invalidated_at"] is None

    # The payload keys changeorders/service.py publishes on approval.
    await bi_bus.publish(
        "changeorder.approved",
        {"change_order_id": str(uuid.uuid4()), "project_id": project_id, "cost_impact": "1250.00"},
        source_module="changeorders",
    )
    await _settle()

    freshness = bi_events.get_kpi_freshness(project_id)
    assert freshness["invalidated_at"] is not None
    assert freshness["source_event"] == "changeorder.approved"


def test_the_invalidation_list_names_only_events_that_exist() -> None:
    """The two names nothing publishes are gone from the list."""
    assert "variations.completed" not in bi_events._PROJECTION_INVALIDATING_EVENTS
    assert "schedule_advanced.task.completed" not in bi_events._PROJECTION_INVALIDATING_EVENTS
