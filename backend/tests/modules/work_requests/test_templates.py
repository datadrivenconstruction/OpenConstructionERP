# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Duplicating a request, and the template flag that keeps the copy-from
rows out of every register, board, planner, summary and sweep."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import notifying, service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import day, make_project, make_user, raise_request, seeded
from tests.modules.work_requests.conftest import API_BASE


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_a_duplicate_carries_the_shape_and_none_of_the_history(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    proj = await make_project(session, owner=pm)
    dept = (await seeded(session))["workshop"]
    await service.update_request_type(
        session, dept, "switchboard", {"checklist": [{"key": "fat_booked", "label": "FAT booked", "required": True}]}
    )
    src = await raise_request(
        session,
        project=proj,
        user=pm,
        quoted_hours=40,
        due_date=day(10),
        fields={"custom_plinth": "Yes - stand", "factory_cost_centre": "CC-100"},
        links=[{"label": "SLD", "url": "https://example.com/sld.pdf"}],
        assignee_ids=[str(fitter.id)],
        responsible_user_id=str(fitter.id),
    )
    await service.set_checklist_item(session, src, "fat_booked", True, user_id=str(pm.id), can_manage=False)
    await service.log_hours(session, src, day=day(0), hours=6, user_id=str(pm.id), can_manage=True)
    await service.add_comment(session, src, body="Ordered the gear", mention_ids=[], user_id=str(pm.id))
    await service.move_stage(session, src, "build", user_id=str(pm.id), can_manage=False)

    copy = await service.duplicate_request(session, src, user_id=str(pm.id))
    p = await service.payload(session, copy)

    assert copy.id != src.id and copy.reference != src.reference
    assert p["status"] == "draft" and p["is_template"] is False
    assert p["title"] == src.title and p["request_types"] == ["switchboard"]
    assert p["quoted_hours"] == 40
    assert p["fields"]["custom_plinth"] == "Yes - stand"
    assert [x["url"] for x in p["links"]] == ["https://example.com/sld.pdf"]
    assert [a["id"] for a in p["assignees"]] == [str(fitter.id)]
    assert p["responsible"]["id"] == str(fitter.id)
    assert p["checklist_total"] == 1 and p["checklist_done"] == 0, "the list travels, the ticks do not"

    assert p["hours_logged"] == 0
    assert p["comment_count"] == 0
    assert p["attachments"] == []
    assert p["depends_on"] == [] and p["parent_id"] is None
    assert p["stage"] == "requested", "a copy starts at the front of the board, not where the original got to"
    assert [h["stage"] for h in p["stage_history"]] == ["requested"]
    assert p["due_date"] is None, "a deadline belongs to the request that was raised"


@pytest.mark.asyncio
async def test_a_duplicate_can_be_retitled_and_moved_to_another_job(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    other = await make_project(session, owner=pm, code="25407", name="Acme Holdings - stage 2")
    await seeded(session)
    src = await raise_request(session, project=proj, user=pm)
    copy = await service.duplicate_request(
        session, src, title="MSB-02 main switchboard", project_id=str(other.id), user_id=str(pm.id)
    )
    assert copy.title == "MSB-02 main switchboard"
    assert str(copy.project_id) == str(other.id)
    with pytest.raises(service.WorkRequestError, match="must be a job id"):
        await service.duplicate_request(session, src, project_id="not-a-uuid", user_id=str(pm.id))


@pytest.mark.asyncio
async def test_a_template_is_kept_out_of_everything_normal(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    live = await raise_request(session, project=proj, user=pm, title="MSB-01 main switchboard", due_date=day(-2))
    tmpl = await raise_request(session, project=proj, user=pm, title="Standard switchboard", due_date=day(-2))
    await service.update_request(session, tmpl, {"is_template": True}, user_id=str(pm.id), can_manage=True)

    listed = await service.list_requests(session, project_ids=None, project_id=proj.id)
    assert [r.id for r in listed] == [live.id]
    only = await service.list_requests(session, project_ids=None, project_id=proj.id, is_template=True)
    assert [r.id for r in only] == [tmpl.id]

    summary = await service.summary(session, project_ids=None, project_id=proj.id)
    workshop = next(d for d in summary["departments"] if d["key"] == "workshop")
    assert workshop["open"] == 1 and workshop["overdue"] == 1

    grid = await service.planner(session, department="workshop", from_day=day(0), to_day=day(3))
    assert [r["request_id"] for r in grid["rows"]] == [str(live.id)]

    queue = await service.my_queue(session, user_id=str(pm.id), project_ids=None)
    assert [r["id"] for r in queue["raised"]] == [str(live.id)]

    swept = await notifying.sweep(session, project_ids=None)
    assert swept["published"] == 1 and swept["detail"] == [f"{live.reference} overdue"]


@pytest.mark.asyncio
async def test_duplicate_and_templates_over_http(api) -> None:
    client, pid, _ = api
    made = await client.post(
        f"{API_BASE}/requests",
        json={
            "project_id": pid,
            "department": "workshop",
            "request_type": "switchboard",
            "title": "Standard switchboard",
        },
    )
    assert made.status_code == 201
    rid = made.json()["id"]

    flagged = await client.patch(f"{API_BASE}/requests/{rid}", json={"is_template": True})
    assert flagged.status_code == 200 and flagged.json()["is_template"] is True
    assert (await client.get(f"{API_BASE}/requests", params={"project_id": pid})).json()["items"] == []
    templates = await client.get(f"{API_BASE}/requests", params={"project_id": pid, "is_template": True})
    assert [x["id"] for x in templates.json()["items"]] == [rid]

    copy = await client.post(f"{API_BASE}/requests/{rid}/duplicate", json={"title": "MSB-07"})
    assert copy.status_code == 201
    body = copy.json()
    assert body["title"] == "MSB-07" and body["status"] == "draft" and body["is_template"] is False
    assert body["reference"] != made.json()["reference"]
    register = await client.get(f"{API_BASE}/requests", params={"project_id": pid})
    assert [x["id"] for x in register.json()["items"]] == [body["id"]], "the copy is live, the template is not"

    activity = (await client.get(f"{API_BASE}/requests/{body['id']}/activity")).json()["items"]
    assert any(a["what"] == "Copied from" for a in activity)
