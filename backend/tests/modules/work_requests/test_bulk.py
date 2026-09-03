# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Bulk update: the same patch over many requests, never all-or-nothing
and never silent - one refusal does not roll the others back."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import service
from app.modules.work_requests.models import MAX_BULK_IDS
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import day, make_project, make_user, raise_request, seeded
from tests.modules.work_requests.conftest import API_BASE


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_the_ones_that_work_land_and_the_ones_that_do_not_say_why(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    hidden = await make_project(session, owner=pm, code="25999", name="Acme Holdings - other job")
    await seeded(session)

    good_a = await raise_request(session, project=proj, user=pm, title="MSB-01 main switchboard")
    good_b = await raise_request(session, project=proj, user=pm, title="MSB-02 main switchboard")
    elsewhere = await raise_request(session, project=hidden, user=pm, title="Not visible here")
    finished = await raise_request(session, project=proj, user=pm, title="Already done")
    await service.update_request(session, finished, {"status": "cancelled"}, user_id=str(pm.id), can_manage=True)

    missing = str(uuid.uuid4())
    out = await service.bulk_update(
        session,
        ids=[str(good_a.id), str(good_b.id), str(elsewhere.id), str(finished.id), missing],
        patch={"assignee_ids": [str(fitter.id)], "due_date": day(21), "priority": "high"},
        user_id=str(pm.id),
        can_manage=True,
        project_ids={proj.id},
    )

    assert out["updated"] == [str(good_a.id), str(good_b.id)]
    assert [r["id"] for r in out["refused"]] == [str(elsewhere.id), str(finished.id), missing]
    assert out["refused"][0]["reason"] == "Work request not found", (
        "a job the caller cannot see answers the same way a missing one does"
    )
    assert "cancelled and cannot be edited" in out["refused"][1]["reason"]
    assert out["refused"][2]["reason"] == "Work request not found"

    for req in (good_a, good_b):
        await session.refresh(req)
        assert req.assignee_ids == [str(fitter.id)]
        assert req.due_date == day(21)
        assert req.priority == "high"
    for req in (elsewhere, finished):
        await session.refresh(req)
    assert elsewhere.assignee_ids == [] and finished.priority == "normal", "a refusal changes nothing"


@pytest.mark.asyncio
async def test_an_illegal_status_move_refuses_only_its_own_row(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    fresh = await raise_request(session, project=proj, user=pm, title="MSB-01 main switchboard")
    started = await raise_request(session, project=proj, user=pm, title="MSB-02 main switchboard")
    await service.update_request(session, started, {"status": "accepted"}, user_id=str(pm.id), can_manage=True)

    out = await service.bulk_update(
        session,
        ids=[str(fresh.id), str(started.id)],
        patch={"status": "in_progress"},
        user_id=str(pm.id),
        can_manage=True,
        project_ids={proj.id},
    )
    assert out["updated"] == [str(started.id)]
    assert out["refused"][0]["id"] == str(fresh.id)
    assert "cannot move to in_progress" in out["refused"][0]["reason"]
    await session.refresh(fresh)
    await session.refresh(started)
    assert fresh.status == "submitted" and started.status == "in_progress"


@pytest.mark.asyncio
async def test_the_shape_of_a_refused_bulk_call(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    req = await raise_request(session, project=proj, user=pm)

    with pytest.raises(service.WorkRequestError, match="No requests given"):
        await service.bulk_update(
            session, ids=[], patch={"priority": "high"}, user_id=str(pm.id), can_manage=True, project_ids=None
        )
    with pytest.raises(service.WorkRequestError, match="Nothing to change"):
        await service.bulk_update(
            session, ids=[str(req.id)], patch={}, user_id=str(pm.id), can_manage=True, project_ids=None
        )
    with pytest.raises(service.WorkRequestError, match="cannot be set in bulk"):
        await service.bulk_update(
            session,
            ids=[str(req.id)],
            patch={"title": "one title for forty boards"},
            user_id=str(pm.id),
            can_manage=True,
            project_ids=None,
        )
    with pytest.raises(service.WorkRequestError, match=f"At most {MAX_BULK_IDS} requests"):
        await service.bulk_update(
            session,
            ids=[str(uuid.uuid4()) for _ in range(MAX_BULK_IDS + 1)],
            patch={"priority": "high"},
            user_id=str(pm.id),
            can_manage=True,
            project_ids=None,
        )


@pytest.mark.asyncio
async def test_bulk_over_http(api) -> None:
    client, pid, _ = api

    async def _raise(title: str) -> str:
        r = await client.post(
            f"{API_BASE}/requests",
            json={"project_id": pid, "department": "workshop", "request_type": "switchboard", "title": title},
        )
        assert r.status_code == 201
        return r.json()["id"]

    a, b = await _raise("MSB-01 main switchboard"), await _raise("MSB-02 main switchboard")
    missing = str(uuid.uuid4())

    r = await client.post(
        f"{API_BASE}/requests/bulk",
        json={"ids": [a, b, missing], "patch": {"priority": "urgent", "stage": "build"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == [a, b]
    assert r.json()["refused"] == [{"id": missing, "reason": "Work request not found"}]
    moved = (await client.get(f"{API_BASE}/requests/{a}")).json()
    assert moved["priority"] == "urgent" and moved["stage"] == "build" and moved["status"] == "in_progress"

    unknown_key = await client.post(f"{API_BASE}/requests/bulk", json={"ids": [a], "patch": {"title": "nope"}})
    assert unknown_key.status_code == 422, "a key bulk cannot set is a schema refusal, never a silent drop"

    empty = await client.post(f"{API_BASE}/requests/bulk", json={"ids": [a], "patch": {}})
    assert empty.status_code == 400 and "Nothing to change" in empty.json()["detail"]
