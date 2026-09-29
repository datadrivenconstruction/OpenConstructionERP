"""The schedule Table view: assignee round trip and activities created inside a section.

Two defects reported against the Table view:

* The assignee cell always read "Unassigned". The column existed on the
  model and the grid sent ``assignee_id`` on PATCH, but none of the activity
  schemas declared it, so the write was dropped (``extra="ignore"``) and
  neither the activity nor the Gantt payload the grid reads returned it.
* A new activity created inside a section was appended at the bottom of the
  schedule, and its WBS code had to be typed by hand.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.contacts import models as _contacts_models  # noqa: F401
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _admin_headers(client: AsyncClient, role: str = "admin") -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"sched-table-{uuid.uuid4().hex[:8]}@schedule.io"
    password = f"SchedTable{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Table Owner"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _schedule(client: AsyncClient, headers: dict[str, str]) -> str:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"Table {uuid.uuid4().hex[:6]}", "description": "table view", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    sched = await client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": proj.json()["id"],
            "name": "Table Schedule",
            "start_date": "2026-05-01",
            "end_date": "2026-09-30",
        },
        headers=headers,
    )
    assert sched.status_code == 201, sched.text
    return sched.json()["id"]


async def _activity(client: AsyncClient, headers: dict[str, str], schedule_id: str, **body: object) -> dict:
    payload = {"start_date": "2026-05-04", "end_date": "2026-05-08", **body}
    resp = await client.post(f"/api/v1/schedule/schedules/{schedule_id}/activities/", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _gantt(client: AsyncClient, headers: dict[str, str], schedule_id: str) -> list[dict]:
    resp = await client.get(f"/api/v1/schedule/schedules/{schedule_id}/gantt/", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["activities"]


@pytest.mark.asyncio
async def test_assignee_is_stored_and_read_back_where_the_table_reads_it(http_client):
    headers = await _admin_headers(http_client)
    schedule_id = await _schedule(http_client, headers)
    contact = await http_client.post(
        "/api/v1/contacts/",
        json={"contact_type": "subcontractor", "company_name": "Site Crew GmbH", "first_name": "Ana"},
        headers=headers,
    )
    assert contact.status_code in (200, 201), contact.text
    contact_id = contact.json()["id"]
    act = await _activity(http_client, headers, schedule_id, name="Excavation")

    patched = await http_client.patch(
        f"/api/v1/schedule/activities/{act['id']}", json={"assignee_id": contact_id}, headers=headers
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["assignee_id"] == contact_id

    # The grid renders the Gantt payload, not the activity response. The
    # name travels with it, so a colleague whose own contact list does not
    # hold this contact still sees who is assigned.
    row = next(a for a in await _gantt(http_client, headers, schedule_id) if a["id"] == act["id"])
    assert row["assignee_id"] == contact_id
    assert row["assignee_name"] == "Ana"

    cleared = await http_client.patch(
        f"/api/v1/schedule/activities/{act['id']}", json={"assignee_id": None}, headers=headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["assignee_id"] is None

    unknown = await http_client.patch(
        f"/api/v1/schedule/activities/{act['id']}", json={"assignee_id": str(uuid.uuid4())}, headers=headers
    )
    assert unknown.status_code == 404, unknown.text


@pytest.mark.asyncio
async def test_new_activity_lands_inside_its_section_with_the_next_code(http_client):
    headers = await _admin_headers(http_client)
    schedule_id = await _schedule(http_client, headers)
    s1 = await _activity(http_client, headers, schedule_id, name="Earthworks", wbs_code="1", activity_type="summary")
    await _activity(http_client, headers, schedule_id, name="Strip topsoil", wbs_code="1.1", parent_id=s1["id"])
    await _activity(http_client, headers, schedule_id, name="Excavate", wbs_code="1.2", parent_id=s1["id"])
    await _activity(http_client, headers, schedule_id, name="Structure", wbs_code="2", activity_type="summary")

    suggestion = await http_client.get(
        f"/api/v1/schedule/schedules/{schedule_id}/next-wbs-code/",
        params={"parent_id": s1["id"]},
        headers=headers,
    )
    assert suggestion.status_code == 200, suggestion.text
    assert suggestion.json() == {"wbs_code": "1.3"}

    top = await http_client.get(f"/api/v1/schedule/schedules/{schedule_id}/next-wbs-code/", headers=headers)
    assert top.json() == {"wbs_code": "3"}

    # Left blank, the code is filled in from the section's sequence.
    new = await _activity(http_client, headers, schedule_id, name="Backfill", parent_id=s1["id"])
    assert new["wbs_code"] == "1.3"

    names = [a["name"] for a in await _gantt(http_client, headers, schedule_id)]
    assert names == ["Earthworks", "Strip topsoil", "Excavate", "Backfill", "Structure"]


@pytest.mark.asyncio
async def test_wbs_code_must_be_unique_and_parent_must_be_in_the_schedule(http_client):
    headers = await _admin_headers(http_client)
    schedule_id = await _schedule(http_client, headers)
    other_schedule_id = await _schedule(http_client, headers)
    first = await _activity(http_client, headers, schedule_id, name="A", wbs_code="1")
    second = await _activity(http_client, headers, schedule_id, name="B", wbs_code="2")

    dup = await http_client.post(
        f"/api/v1/schedule/schedules/{schedule_id}/activities/",
        json={"name": "C", "wbs_code": "1", "start_date": "2026-05-04", "end_date": "2026-05-08"},
        headers=headers,
    )
    assert dup.status_code == 409, dup.text

    renamed = await http_client.patch(
        f"/api/v1/schedule/activities/{second['id']}", json={"wbs_code": "1"}, headers=headers
    )
    assert renamed.status_code == 409, renamed.text

    # Resending an activity's own unchanged code is not a conflict.
    same = await http_client.patch(
        f"/api/v1/schedule/activities/{first['id']}", json={"wbs_code": "1", "name": "A2"}, headers=headers
    )
    assert same.status_code == 200, same.text

    foreign = await http_client.post(
        f"/api/v1/schedule/schedules/{other_schedule_id}/activities/",
        json={"name": "X", "parent_id": first["id"], "start_date": "2026-05-04", "end_date": "2026-05-08"},
        headers=headers,
    )
    assert foreign.status_code == 404, foreign.text


async def _contact(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    resp = await client.post(
        "/api/v1/contacts/",
        json={"contact_type": "subcontractor", "company_name": name},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _patch(client: AsyncClient, headers: dict[str, str], activity_id: str, body: dict):
    return await client.patch(f"/api/v1/schedule/activities/{activity_id}", json=body, headers=headers)


@pytest.mark.asyncio
async def test_assignee_must_be_a_live_contact_of_the_callers_tenant(http_client):
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.contacts.models import Contact

    owner = await _admin_headers(http_client, role="manager")
    stranger = await _admin_headers(http_client, role="manager")
    schedule_id = await _schedule(http_client, owner)
    act = await _activity(http_client, owner, schedule_id, name="Pour slab")

    foreign = await _contact(http_client, stranger, "Other Tenant Ltd")
    resp = await _patch(http_client, owner, act["id"], {"assignee_id": foreign})
    assert resp.status_code == 404, resp.text

    own = await _contact(http_client, owner, "Own Crew Ltd")
    async with async_session_factory() as s:
        await s.execute(update(Contact).where(Contact.id == uuid.UUID(own)).values(is_active=False))
        await s.commit()
    resp = await _patch(http_client, owner, act["id"], {"assignee_id": own})
    assert resp.status_code == 422, resp.text

    live = await _contact(http_client, owner, "Live Crew Ltd")
    resp = await _patch(http_client, owner, act["id"], {"assignee_id": live})
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_a_schedule_with_every_sort_order_zero_still_files_the_new_row_in_its_section(http_client):
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.schedule.models import Activity

    headers = await _admin_headers(http_client)
    schedule_id = await _schedule(http_client, headers)
    s1 = await _activity(http_client, headers, schedule_id, name="Phase 1", wbs_code="1", activity_type="summary")
    await _activity(http_client, headers, schedule_id, name="Phase 1 work", wbs_code="1.1", parent_id=s1["id"])
    await _activity(http_client, headers, schedule_id, name="Phase 2", wbs_code="2", activity_type="summary")
    # What seeded and imported schedules look like: the column default everywhere.
    async with async_session_factory() as s:
        await s.execute(update(Activity).where(Activity.schedule_id == uuid.UUID(schedule_id)).values(sort_order=0))
        await s.commit()

    new = await _activity(http_client, headers, schedule_id, name="Phase 1 more", parent_id=s1["id"])
    assert new["wbs_code"] == "1.2"
    names = [a["name"] for a in await _gantt(http_client, headers, schedule_id)]
    assert names == ["Phase 1", "Phase 1 work", "Phase 1 more", "Phase 2"]


@pytest.mark.asyncio
async def test_moving_an_activity_to_another_section_moves_it_in_the_order(http_client):
    headers = await _admin_headers(http_client)
    schedule_id = await _schedule(http_client, headers)
    s1 = await _activity(http_client, headers, schedule_id, name="S1", wbs_code="1", activity_type="summary")
    a = await _activity(http_client, headers, schedule_id, name="A", wbs_code="1.1", parent_id=s1["id"])
    await _activity(http_client, headers, schedule_id, name="A child", wbs_code="1.1.1", parent_id=a["id"])
    s2 = await _activity(http_client, headers, schedule_id, name="S2", wbs_code="2", activity_type="summary")
    await _activity(http_client, headers, schedule_id, name="B", wbs_code="2.1", parent_id=s2["id"])
    await _activity(http_client, headers, schedule_id, name="Tail", wbs_code="3")

    moved = await _patch(http_client, headers, a["id"], {"parent_id": s2["id"]})
    assert moved.status_code == 200, moved.text
    names = [x["name"] for x in await _gantt(http_client, headers, schedule_id)]
    assert names == ["S1", "S2", "B", "A", "A child", "Tail"]

    # Under one of its own children is refused.
    loop = await _patch(http_client, headers, s2["id"], {"parent_id": a["id"]})
    assert loop.status_code == 422, loop.text

    # An explicit null moves it to the top level, at the end.
    top = await _patch(http_client, headers, a["id"], {"parent_id": None})
    assert top.status_code == 200, top.text
    names = [x["name"] for x in await _gantt(http_client, headers, schedule_id)]
    assert names == ["S1", "S2", "B", "Tail", "A", "A child"]


@pytest.mark.asyncio
async def test_a_blank_code_without_a_section_continues_the_top_level(http_client):
    headers = await _admin_headers(http_client)
    schedule_id = await _schedule(http_client, headers)
    first = await _activity(http_client, headers, schedule_id, name="First")
    second = await _activity(http_client, headers, schedule_id, name="Second")
    assert (first["wbs_code"], second["wbs_code"]) == ("1", "2")
