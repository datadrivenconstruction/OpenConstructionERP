# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The headcount grid: people per board per day, against the department's
capacity line."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import day, make_project, make_user, raise_request, seeded


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_allocation_upserts_and_zero_clears(session: AsyncSession) -> None:
    pm = await make_user(session)
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    out = await service.set_allocation(session, req, {day(1): 2, day(2): 3}, user_id=str(pm.id), can_manage=False)
    assert out == {day(1): 2.0, day(2): 3.0}
    out = await service.set_allocation(
        session, req, {day(1): 0, day(2): 1.5, day(3): 1}, user_id=str(pm.id), can_manage=False
    )
    assert out == {day(2): 1.5, day(3): 1.0}, "zero clears the day; the rest upserts"
    with pytest.raises(service.WorkRequestError):
        await service.set_allocation(session, req, {"next tuesday": 1}, user_id=str(pm.id), can_manage=False)
    with pytest.raises(service.WorkRequestError):
        await service.set_allocation(session, req, {}, user_id=str(pm.id), can_manage=False)


@pytest.mark.asyncio
async def test_the_grid_sums_allocations_against_capacity(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    a = await make_user(session, name="A Example")
    b = await make_user(session, name="B Example")
    lead = await make_user(session, name="Lead Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(
        session, depts["workshop"], {"lead_user_id": str(lead.id), "member_ids": [str(a.id), str(b.id)]}
    )
    one = await raise_request(session, project=proj, user=pm, title="Board one", due_date=day(20))
    two = await raise_request(session, project=proj, user=pm, title="Board two", due_date=day(10))
    closed = await raise_request(session, project=proj, user=pm, title="Old board")
    await service.update_request(session, closed, {"status": "cancelled"}, user_id=str(pm.id), can_manage=False)

    # Allocation is a department action: the PM who raised it is refused
    # once a roster exists; the lead is not.
    with pytest.raises(service.NotPermitted):
        await service.set_allocation(session, one, {day(1): 2}, user_id=str(pm.id), can_manage=False)
    await service.set_allocation(session, one, {day(1): 2, day(2): 2}, user_id=str(lead.id), can_manage=False)
    await service.set_allocation(session, two, {day(1): 1.5}, user_id=str(lead.id), can_manage=False)
    await service.set_capacity(session, "workshop", {day(2): 1})

    grid = await service.planner(session, department="workshop", from_day=day(0), to_day=day(6))
    assert grid["days"] == [day(i) for i in range(7)]
    assert [m["name"] for m in grid["members"]] == ["Lead Example", "A Example", "B Example"]
    assert [r["title"] for r in grid["rows"]] == ["Board two", "Board one"], "soonest due first; cancelled hidden"
    assert grid["rows"][1]["alloc"] == {day(1): 2.0, day(2): 2.0}
    assert grid["rows"][0]["project_code"] == "25406"
    assert grid["capacity"][day(1)] == {"available": 3.0, "allocated": 3.5, "override": False}
    assert grid["capacity"][day(2)] == {"available": 1.0, "allocated": 2.0, "override": True}
    assert grid["capacity"][day(3)] == {"available": 3.0, "allocated": 0.0, "override": False}

    # Default window is five weeks; the cap is enforced.
    default = await service.planner(session, department="workshop")
    assert len(default["days"]) == service.PLANNER_DEFAULT_DAYS
    with pytest.raises(service.WorkRequestError):
        await service.planner(session, department="workshop", from_day=day(0), to_day=day(200))
    with pytest.raises(service.WorkRequestError):
        await service.planner(session, department="workshop", from_day=day(5), to_day=day(1))
    with pytest.raises(service.NotFoundError):
        await service.planner(session, department="painting")


@pytest.mark.asyncio
async def test_capacity_override_and_removal(session: AsyncSession) -> None:
    await seeded(session)
    out = await service.set_capacity(session, "workshop", {day(1): 4, day(2): 5})
    assert out == {day(1): 4.0, day(2): 5.0}
    out = await service.set_capacity(session, "workshop", {day(1): None})
    assert out == {day(2): 5.0}
    with pytest.raises(service.WorkRequestError):
        await service.set_capacity(session, "workshop", {day(1): -1})
