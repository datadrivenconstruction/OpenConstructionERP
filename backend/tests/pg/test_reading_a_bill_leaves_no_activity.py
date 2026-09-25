"""PG: opening a bill writes nothing to its activity feed, and the feed reads as prose.

``get_cost_breakdown`` published ``boq.cost_breakdown.computed`` on every GET.
The activity handler logs every ``boq.*`` event, and it had no sentence for this
one, so each load of the editor added a Recent Activity row whose text was the
dotted event name itself. A read is not an action on the bill, and a raw event
name is not something a reader should ever see.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest

from app.modules.boq import service as service_mod
from app.modules.boq.models import BOQ, BOQActivityLog, Position
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User


async def _bill(session) -> BOQ:
    owner = User(email="activity-read@example.test", hashed_password="x", full_name="Reader")
    session.add(owner)
    await session.flush()
    project = Project(name="Activity", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Read me")
    session.add(boq)
    await session.flush()
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="01.001",
            description="Wall",
            unit="m2",
            quantity="2",
            unit_rate="10",
            total="20",
        )
    )
    await session.flush()
    return boq


@pytest.mark.asyncio
async def test_the_cost_breakdown_publishes_nothing(pg_session, monkeypatch) -> None:
    boq = await _bill(pg_session)
    published: list[str] = []

    async def _spy(name, *args, **kwargs):
        published.append(name)

    monkeypatch.setattr(service_mod, "_safe_publish", _spy)

    await BOQService(pg_session).get_cost_breakdown(boq.id)

    assert published == []


@pytest.mark.asyncio
async def test_the_feed_hides_old_read_rows_and_never_shows_an_event_name(pg_session) -> None:
    boq = await _bill(pg_session)
    common = {"project_id": boq.project_id, "boq_id": boq.id, "changes": {}, "metadata_": {}}
    pg_session.add_all(
        [
            # Written by the old cost-breakdown GET, before the publish was removed.
            BOQActivityLog(
                action="cost_breakdown.computed",
                target_type="cost_breakdown",
                description="boq.cost_breakdown.computed",
                **common,
            ),
            # Written by the old fallback for an event with no sentence.
            BOQActivityLog(
                action="quantity_link.created",
                target_type="quantity_link",
                description="boq.quantity_link.created",
                **common,
            ),
            BOQActivityLog(
                action="position.created",
                target_type="position",
                description="Added position 01.001",
                **common,
            ),
        ]
    )
    await pg_session.flush()

    service = BOQService(pg_session)
    for listing in (
        await service.get_activity_for_boq(boq.id),
        await service.get_activity_for_project(boq.project_id),
    ):
        assert listing.total == 2
        texts = sorted(item.description for item in listing.items)
        assert texts == ["Added position 01.001", "Quantity link created"]
