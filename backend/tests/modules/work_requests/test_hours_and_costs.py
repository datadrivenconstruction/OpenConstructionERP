# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The switchboard tracker's arithmetic: quoted, logged, to-complete,
at-completion, deviation, cost - live off the log rather than typed."""

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
async def test_hours_roll_up_into_cost_to_complete_and_deviation(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(session, depts["workshop"], {"member_ids": [str(fitter.id)], "hourly_rate": "120"})
    req = await raise_request(session, project=proj, user=pm, quoted_hours=40)

    before = await service.payload(session, req)
    assert before["hours_logged"] == 0
    assert before["hours_at_completion"] == 0
    assert before["deviation_hours"] == -40
    assert before["cost_at_completion"] == "0.00"

    await service.log_hours(session, req, day=day(-1), hours=7.5, user_id=str(fitter.id), can_manage=False)
    await service.log_hours(session, req, day=day(0), hours=8, note="wiring", user_id=str(fitter.id), can_manage=False)
    await service.update_request(session, req, {"hours_to_complete": 30}, user_id=str(fitter.id), can_manage=False)

    after = await service.payload(session, req)
    assert after["hours_logged"] == 15.5
    assert after["hours_to_complete"] == 30
    assert after["hours_at_completion"] == 45.5
    assert after["deviation_hours"] == 5.5, "45.5 at completion against 40 quoted"
    assert after["cost_at_completion"] == "5460.00", "45.5h × $120"

    logs = await service.list_hours(session, req)
    assert [entry["hours"] for entry in logs] == [8, 7.5], "newest day first"
    assert logs[0]["user_name"] == "Fitter Example"
    assert logs[0]["note"] == "wiring"


@pytest.mark.asyncio
async def test_no_quote_no_deviation_no_rate_no_cost(session: AsyncSession) -> None:
    pm = await make_user(session)
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    await service.log_hours(session, req, day=day(0), hours=2, user_id=str(pm.id), can_manage=False)
    payload = await service.payload(session, req)
    assert payload["hours_logged"] == 2
    assert payload["deviation_hours"] is None
    assert payload["cost_at_completion"] is None


@pytest.mark.asyncio
async def test_hours_refusals_and_removal(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    stranger = await make_user(session, name="Stranger Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    await service.update_department(session, depts["workshop"], {"member_ids": [str(fitter.id)]})
    req = await raise_request(session, project=proj, user=pm)

    with pytest.raises(service.WorkRequestError):
        await service.log_hours(session, req, day=day(0), hours=0, user_id=str(fitter.id), can_manage=False)
    with pytest.raises(service.WorkRequestError):
        await service.log_hours(session, req, day=day(0), hours=25, user_id=str(fitter.id), can_manage=False)
    with pytest.raises(service.WorkRequestError):
        await service.log_hours(session, req, day="yesterday", hours=1, user_id=str(fitter.id), can_manage=False)
    with pytest.raises(service.NotPermitted):
        await service.log_hours(session, req, day=day(0), hours=1, user_id=str(stranger.id), can_manage=False)
    # The requester logs their own time, but not somebody else's.
    with pytest.raises(service.NotPermitted):
        await service.log_hours(
            session, req, day=day(0), hours=1, for_user_id=str(fitter.id), user_id=str(pm.id), can_manage=False
        )
    # The department logs for a colleague.
    row = await service.log_hours(
        session, req, day=day(0), hours=3, for_user_id=str(pm.id), user_id=str(fitter.id), can_manage=False
    )
    assert row.user_id == str(pm.id)
    with pytest.raises(service.NotPermitted):
        await service.delete_hours(session, req, row.id, user_id=str(stranger.id), can_manage=False)
    await service.delete_hours(session, req, row.id, user_id=str(pm.id), can_manage=False)
    assert await service.list_hours(session, req) == []
    assert (await service.payload(session, req))["hours_logged"] == 0


@pytest.mark.asyncio
async def test_disciplines_are_checked_against_the_request_type(session: AsyncSession) -> None:
    pm = await make_user(session)
    proj = await make_project(session, owner=pm)
    req = await raise_request(
        session,
        project=proj,
        user=pm,
        department="engineering",
        request_type="eng_and_drafting",
        cost_centres={"engineering": "CC-ENG-01", "drafting": "CC-DRF-01"},
        estimated_hours={"engineering": 12, "drafting": "6.5"},
    )
    assert req.estimated_hours == {"engineering": 12, "drafting": 6.5}
    with pytest.raises(service.WorkRequestError):
        await raise_request(
            session,
            project=proj,
            user=pm,
            department="engineering",
            request_type="eng_only",
            estimated_hours={"plumbing": 4},
        )
    with pytest.raises(service.WorkRequestError):
        await raise_request(session, project=proj, user=pm, quoted_hours="forty")
    with pytest.raises(service.WorkRequestError):
        await raise_request(session, project=proj, user=pm, quoted_hours=-1)
