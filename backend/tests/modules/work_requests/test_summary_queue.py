# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The header counts and the personal queue, and the sweep that rings
once a day."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification
from app.modules.work_requests import notifying, service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import day, make_project, make_user, raise_request, seeded


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_summary_counts_per_department(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    other = await make_project(session, owner=pm, code="25407")
    await seeded(session)

    late = await raise_request(session, project=proj, user=pm, title="Late board", due_date=day(-3), quoted_hours=10)
    soon = await raise_request(session, project=proj, user=pm, title="Soon board", due_date=day(3), quoted_hours=20)
    asked = await raise_request(session, project=proj, user=pm, title="Asked board", due_date=day(30))
    await service.needs_info(session, asked, "Which colour?", user_id=str(fitter.id), can_manage=False)
    done = await raise_request(session, project=proj, user=pm, title="Done board")
    await service.move_stage(session, done, "delivered", user_id=str(fitter.id), can_manage=False)
    await raise_request(session, project=other, user=pm, title="Other job's board", due_date=day(-1))
    await raise_request(session, project=proj, user=pm, department="drafting", request_type="drafting_only", title="GA")
    await service.log_hours(session, late, day=day(0), hours=4, user_id=str(fitter.id), can_manage=False)
    await service.log_hours(session, soon, day=day(0), hours=1, user_id=str(fitter.id), can_manage=False)

    out = await service.summary(session, project_ids=None, project_id=proj.id)
    by_key = {d["key"]: d for d in out["departments"]}
    assert list(by_key) == ["engineering", "drafting", "workshop", "automation", "hazardous_area"]
    wks = by_key["workshop"]
    assert wks["open"] == 3, "complete is not open"
    assert wks["overdue"] == 1
    assert wks["due_this_week"] == 1
    assert wks["with_requester"] == 1
    assert wks["hours_quoted"] == 30
    assert wks["hours_logged"] == 5
    assert wks["awaiting_close"] == 1
    assert by_key["drafting"]["open"] == 1
    assert by_key["engineering"]["open"] == 0

    everywhere = await service.summary(session, project_ids={proj.id, other.id})
    assert {d["key"]: d["overdue"] for d in everywhere["departments"]}["workshop"] == 2
    nothing = await service.summary(session, project_ids=set())
    assert all(d["open"] == 0 for d in nothing["departments"]), "an empty visibility set sees nothing"


@pytest.mark.asyncio
async def test_my_queue_buckets(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    me = await make_user(session, name="Me Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    assigned = await raise_request(session, project=proj, user=pm, title="Assigned to me", assignee_ids=[str(me.id)])
    resp = await raise_request(session, project=proj, user=pm, title="I am responsible", responsible_user_id=str(me.id))
    mine = await raise_request(session, project=proj, user=me, title="I raised it")
    await service.needs_info(session, mine, "When?", user_id=str(pm.id), can_manage=False)
    await raise_request(session, project=proj, user=pm, title="Nothing to do with me")

    queue = await service.my_queue(session, user_id=str(me.id), project_ids=None)
    assert [r["id"] for r in queue["assigned"]] == [str(assigned.id)]
    assert [r["id"] for r in queue["responsible"]] == [str(resp.id)]
    assert [r["id"] for r in queue["raised"]] == [str(mine.id)]
    assert [r["id"] for r in queue["needs_my_answer"]] == [str(mine.id)]
    assert queue["needs_my_answer"][0]["needs_info"] == "When?"


@pytest.mark.asyncio
async def test_the_sweep_rings_once_a_day(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    late = await raise_request(
        session, project=proj, user=pm, title="Late", due_date=day(-2), assignee_ids=[str(fitter.id)]
    )
    await raise_request(session, project=proj, user=pm, title="Tomorrow", due_date=day(1))
    await raise_request(session, project=proj, user=pm, title="Next week", due_date=day(7))
    finished = await raise_request(session, project=proj, user=pm, title="Finished but late", due_date=day(-5))
    await service.move_stage(session, finished, "delivered", user_id=str(fitter.id), can_manage=False)

    first = await notifying.sweep(session, project_ids=None)
    assert sorted(first["detail"]) == ["WR-WKS-000001 overdue", "WR-WKS-000002 due tomorrow"]
    assert first["published"] == 2
    second = await notifying.sweep(session, project_ids=None)
    assert second["published"] == 0, "the same day must not ring twice"

    def _sweep_bells(rows: list[Notification]) -> list[str]:
        return [n.title_key for n in rows if "overdue" in n.title_key or "due tomorrow" in n.title_key]

    pm_rows = list((await session.execute(select(Notification).where(Notification.user_id == pm.id))).scalars())
    assert len(_sweep_bells(pm_rows)) == 2, "the requester heard about both"
    assert any("is complete" in n.title_key for n in pm_rows), "and separately about the delivered board"
    fitter_rows = list((await session.execute(select(Notification).where(Notification.user_id == fitter.id))).scalars())
    assert len(_sweep_bells(fitter_rows)) == 1, "the assignee heard about the overdue one"
    assert any("assigned to you" in n.title_key for n in fitter_rows)
    assert late.notified == {"overdue": day(0)}
    assert (await service.payload(session, late))["is_overdue"] is True
    assert (await service.payload(session, late))["days_until_due"] == -2
    assert (await service.payload(session, finished))["is_overdue"] is False, "complete is never overdue"
