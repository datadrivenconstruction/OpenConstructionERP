# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The programme tie-in: a workshop build points at the activity it feeds
and the estimate lines it draws on - and only ever on its OWN job."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.schedule.models import Activity, Schedule
from app.modules.work_requests import service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import make_project, make_user, raise_request, seeded
from tests.modules.work_requests.conftest import API_BASE


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _activity(session: AsyncSession, project) -> Activity:
    schedule = Schedule(project_id=project.id, name="Construction programme")
    session.add(schedule)
    await session.flush()
    row = Activity(
        schedule_id=schedule.id,
        name="Install MCC",
        start_date="2026-09-01",
        end_date="2026-09-11",
    )
    session.add(row)
    await session.flush()
    return row


async def _position(session: AsyncSession, project, ordinal: str = "1.1") -> Position:
    boq = BOQ(project_id=project.id, name="Estimate")
    session.add(boq)
    await session.flush()
    row = Position(boq_id=boq.id, ordinal=ordinal, description="Main switchboard", unit="ea")
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_a_request_points_at_its_own_activity_and_lines(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    req = await raise_request(session, project=proj, user=pm)
    activity = await _activity(session, proj)
    line = await _position(session, proj)

    await service.update_request(
        session,
        req,
        {"schedule_activity_id": str(activity.id), "boq_position_ids": [str(line.id)]},
        user_id=str(pm.id),
        can_manage=True,
    )
    p = await service.payload(session, req)
    assert p["schedule_activity_id"] == str(activity.id)
    assert p["boq_position_ids"] == [str(line.id)]

    await service.update_request(
        session, req, {"schedule_activity_id": None, "boq_position_ids": []}, user_id=str(pm.id), can_manage=True
    )
    p = await service.payload(session, req)
    assert p["schedule_activity_id"] is None and p["boq_position_ids"] == []


@pytest.mark.asyncio
async def test_an_unknown_activity_or_line_is_a_404(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    req = await raise_request(session, project=proj, user=pm)

    with pytest.raises(service.NotFoundError, match="Unknown programme activity"):
        await service.update_request(
            session, req, {"schedule_activity_id": str(uuid.uuid4())}, user_id=str(pm.id), can_manage=True
        )
    with pytest.raises(service.NotFoundError, match="Unknown estimate line"):
        await service.update_request(
            session, req, {"boq_position_ids": [str(uuid.uuid4())]}, user_id=str(pm.id), can_manage=True
        )
    with pytest.raises(service.WorkRequestError, match="must be an activity id"):
        await service.update_request(
            session, req, {"schedule_activity_id": "not-a-uuid"}, user_id=str(pm.id), can_manage=True
        )
    with pytest.raises(service.WorkRequestError, match="must be an estimate line id"):
        await service.update_request(
            session, req, {"boq_position_ids": ["not-a-uuid"]}, user_id=str(pm.id), can_manage=True
        )


@pytest.mark.asyncio
async def test_another_jobs_activity_or_line_is_refused(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    other = await make_project(session, owner=pm, code="25407", name="Acme Holdings - stage 2")
    await seeded(session)
    req = await raise_request(session, project=proj, user=pm)
    foreign_activity = await _activity(session, other)
    foreign_line = await _position(session, other)

    with pytest.raises(service.WorkRequestError, match="is on another job"):
        await service.update_request(
            session, req, {"schedule_activity_id": str(foreign_activity.id)}, user_id=str(pm.id), can_manage=True
        )
    with pytest.raises(service.WorkRequestError, match="is on another job"):
        await service.update_request(
            session, req, {"boq_position_ids": [str(foreign_line.id)]}, user_id=str(pm.id), can_manage=True
        )
    assert req.schedule_activity_id is None and req.boq_position_ids == []


@pytest.mark.asyncio
async def test_programme_links_over_http(api) -> None:
    client, pid, _ = api
    made = await client.post(
        f"{API_BASE}/requests",
        json={"project_id": pid, "department": "workshop", "request_type": "switchboard", "title": "MSB-01"},
    )
    rid = made.json()["id"]
    assert made.json()["schedule_activity_id"] is None and made.json()["boq_position_ids"] == []

    bad = await client.patch(f"{API_BASE}/requests/{rid}", json={"schedule_activity_id": str(uuid.uuid4())})
    assert bad.status_code == 404 and "Unknown programme activity" in bad.json()["detail"]
    bad_line = await client.patch(f"{API_BASE}/requests/{rid}", json={"boq_position_ids": [str(uuid.uuid4())]})
    assert bad_line.status_code == 404 and "Unknown estimate line" in bad_line.json()["detail"]
