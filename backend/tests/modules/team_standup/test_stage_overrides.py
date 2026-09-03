# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Per-job stage overrides and the client brand colour (PostgreSQL).

1. A job can carry its own stage run: storing one leaves the standard
   set alone, the board serves it under ``stage_overrides``, the job's
   tasks cross by stage NAME, a job without one keeps the standard set,
   and removing the override puts the job (and its tasks) back.
2. A job whose client contact has a brand colour serves it as
   ``client_color``; anything that is not a hex colour is served as ''.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.team_standup import board_service, service
from tests._pg import transactional_session
from tests.modules.team_standup.test_delivery_board import (
    _board,
    _project,
    _stage_named,
)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _stage_of(session: AsyncSession, task_id: str) -> str:
    return str((await board_service.get_task(session, task_id)).stage_id)


@pytest.mark.asyncio
async def test_job_stage_override_is_stored_served_and_falls_back(
    session: AsyncSession,
) -> None:
    user, own, standard = await _board(session)
    other = await _project(session, name="Acme Holdings - Fitout")
    uid = str(user.id)
    pricing = _stage_named(standard, "Pricing")
    ordered = _stage_named(standard, "Ordered")
    [on_pricing, on_ordered, elsewhere] = await board_service.create_tasks(
        session,
        [
            {"title": "Price the switchboard", "project_id": str(own.id), "stage_id": str(pricing.id)},
            {"title": "Order the switchboard", "project_id": str(own.id), "stage_id": str(ordered.id)},
            {"title": "Other job task", "project_id": str(other.id), "stage_id": str(ordered.id)},
        ],
        user_id=uid,
    )

    # A three-column run for this job only: keep "Pricing" by name, add a
    # closing stage. Standard ids echoed back become the job's OWN copies,
    # never edits of the shared rows.
    payload = [
        {
            "id": str(standard[0].id),
            "name": "To do",
            "color": "slate",
            "wip_limit": None,
            "is_done": False,
            "spawn": [],
        },
        {
            "id": str(pricing.id),
            "name": "Pricing",
            "color": "indigo",
            "wip_limit": 2,
            "is_done": False,
            "spawn": ["Chase the quote"],
        },
        {"id": None, "name": "Done", "color": "green", "wip_limit": None, "is_done": True, "spawn": []},
    ]
    own_stages = await board_service.replace_stages(session, payload, user_id=uid, project_id=str(own.id))
    assert [s.name for s in own_stages] == ["To do", "Pricing", "Done"]
    assert all(s.project_id == str(own.id) for s in own_stages)
    assert {str(s.id) for s in own_stages}.isdisjoint({str(s.id) for s in standard})

    # Stored: the standard set is untouched, the override is served.
    assert len(await board_service.stages_ordered(session)) == 10
    served = await board_service.stage_overrides(session)
    assert list(served) == [str(own.id)]
    assert [s.name for s in served[str(own.id)]] == ["To do", "Pricing", "Done"]
    assert _stage_named(served[str(own.id)], "Pricing").spawn == ["Chase the quote"]

    # Resolved per job: the override here, the standard run for the rest.
    assert [s.name for s in await board_service.stages_for(session, str(own.id))] == ["To do", "Pricing", "Done"]
    assert len(await board_service.stages_for(session, str(other.id))) == 10

    # The job's tasks crossed by name; a name with no match landed first.
    own_pricing = _stage_named(own_stages, "Pricing")
    assert await _stage_of(session, str(on_pricing.id)) == str(own_pricing.id)
    assert await _stage_of(session, str(on_ordered.id)) == str(own_stages[0].id)
    assert await _stage_of(session, str(elsewhere.id)) == str(ordered.id), "other job never moved"

    # A standard stage is not a column on this job's board any more.
    with pytest.raises(service.StandupError, match="Unknown stage"):
        await board_service.move_task(session, task_id=str(on_pricing.id), stage_id=str(ordered.id), user_id=uid)
    # Its own closing stage closes the task; a new task lands on ITS first stage.
    res = await board_service.move_task(
        session, task_id=str(on_pricing.id), stage_id=str(own_stages[-1].id), user_id=uid
    )
    assert res["task"].completed_at is not None
    [fresh] = await board_service.create_tasks(session, [{"title": "Later", "project_id": str(own.id)}], user_id=uid)
    assert str(fresh.stage_id) == str(own_stages[0].id)

    # A reset of the STANDARD run leaves the job's own board alone.
    await board_service.reset_stages(session, user_id=uid)
    assert await _stage_of(session, str(fresh.id)) == str(own_stages[0].id)
    assert len(await board_service.stages_for(session, str(own.id))) == 3

    # Back to the standard stages: tasks cross by name, the rows are gone.
    back = await board_service.remove_stage_override(session, project_id=str(own.id), user_id=uid)
    assert len(back) == 10
    assert await board_service.stage_overrides(session) == {}
    assert len(await board_service.stages_for(session, str(own.id))) == 10
    assert await _stage_of(session, str(on_ordered.id)) == str(back[0].id)
    assert await _stage_of(session, str(fresh.id)) == str(back[0].id)
    # "Done" has no standard twin -> the first stage.
    assert await _stage_of(session, str(on_pricing.id)) == str(back[0].id)
    # Removing twice is harmless.
    again = await board_service.remove_stage_override(session, project_id=str(own.id), user_id=uid)
    assert len(again) == 10

    # The rails still hold inside a job's own run.
    with pytest.raises(service.StandupError, match="between 2"):
        await board_service.replace_stages(session, payload[:1], user_id=uid, project_id=str(own.id))
    with pytest.raises(service.StandupError):
        await board_service.replace_stages(session, payload, user_id=uid, project_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_override_pricing_name_survives_the_round_trip(session: AsyncSession) -> None:
    """The name mapping is symmetric: a task on the job's own "Pricing"
    lands on the standard "Pricing" when the override is removed."""
    user, own, standard = await _board(session)
    uid = str(user.id)
    payload = [
        {"id": None, "name": "To do", "color": "slate", "wip_limit": None, "is_done": False, "spawn": []},
        {"id": None, "name": "Pricing", "color": "indigo", "wip_limit": None, "is_done": False, "spawn": []},
    ]
    own_stages = await board_service.replace_stages(session, payload, user_id=uid, project_id=str(own.id))
    [t] = await board_service.create_tasks(
        session,
        [{"title": "Quote it", "project_id": str(own.id), "stage_id": str(own_stages[1].id)}],
        user_id=uid,
    )
    back = await board_service.remove_stage_override(session, project_id=str(own.id), user_id=uid)
    assert await _stage_of(session, str(t.id)) == str(_stage_named(back, "Pricing").id)


@pytest.mark.asyncio
async def test_dropping_an_override_stage_with_tasks_rehomes_them_in_the_override(
    session: AsyncSession,
) -> None:
    """A column removed from a job's own run while tasks sit in it hands
    them to the earlier survivor IN THAT RUN - never to a standard stage
    (which is not a column on the job's board) and never orphaned."""
    user, own, standard = await _board(session)
    uid = str(user.id)
    payload = [
        {"id": None, "name": "To do", "color": "slate", "wip_limit": None, "is_done": False, "spawn": []},
        {"id": None, "name": "Pricing", "color": "indigo", "wip_limit": None, "is_done": False, "spawn": []},
        {"id": None, "name": "Ordered", "color": "blue", "wip_limit": None, "is_done": False, "spawn": []},
    ]
    own_stages = await board_service.replace_stages(session, payload, user_id=uid, project_id=str(own.id))
    [t] = await board_service.create_tasks(
        session,
        [{"title": "Order it", "project_id": str(own.id), "stage_id": str(own_stages[2].id)}],
        user_id=uid,
    )
    # Drop "Ordered" (the task's column); keep the other two by id.
    keep = [
        {"id": str(s.id), "name": s.name, "color": s.color, "wip_limit": None, "is_done": False, "spawn": []}
        for s in own_stages[:2]
    ]
    after = await board_service.replace_stages(session, keep, user_id=uid, project_id=str(own.id))
    assert [s.name for s in after] == ["To do", "Pricing"]
    landed = await _stage_of(session, str(t.id))
    assert landed == str(_stage_named(after, "Pricing").id), "the row above, inside the override"
    assert landed not in {str(s.id) for s in standard}
    # The job's board still has a column for it - the move rail holds.
    res = await board_service.move_task(session, task_id=str(t.id), stage_id=str(after[0].id), user_id=uid)
    assert str(res["task"].stage_id) == str(after[0].id)


@pytest.mark.asyncio
async def test_job_with_client_brand_colour_serves_it(session: AsyncSession) -> None:
    from app.modules.contacts.models import Contact

    branded = Contact(
        contact_type="client",
        company_name="Acme Holdings",
        custom_properties={"brand_color": "#D62828"},
    )
    nested = Contact(
        contact_type="client",
        company_name="Example Nested Pty Ltd",
        custom_properties={"contacts": {"brand_color": "#0af"}},
    )
    plain = Contact(contact_type="client", company_name="Example Plain Pty Ltd")
    junk = Contact(
        contact_type="client",
        company_name="Example Junk Pty Ltd",
        custom_properties={"brand_color": "red; background:url(x)"},
    )
    session.add_all([branded, nested, plain, junk])
    await session.flush()
    projects = []
    for c in (branded, nested, plain, junk):
        p = await _project(session, name="Job")
        p.client_id = str(c.id)
        projects.append(p)
    projects.append(await _project(session, name="Acme Holdings - Unlinked"))
    await session.flush()

    jobs = await board_service.job_payloads(session, projects)
    assert [j["client_color"] for j in jobs] == ["#d62828", "#0af", "", "", ""]
    assert jobs[0]["client"] == "Acme Holdings"
    assert jobs[-1]["client"] == "Acme Holdings", "name-split jobs still resolve, uncoloured"
