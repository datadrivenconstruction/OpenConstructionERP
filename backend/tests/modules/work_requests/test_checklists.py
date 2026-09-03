# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Checklists: the definition on the type, the ticks on the request, and
the gate a closing stage runs into while a required item is outstanding."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import make_project, make_user, raise_request, seeded
from tests.modules.work_requests.conftest import API_BASE, API_MANAGER, API_USER_ID

CHECKLIST = [
    {"label": "Drawings signed off", "required": True},
    {"key": "fat_booked", "label": "FAT booked", "required": True},
    {"key": "photos", "label": "Photos on file"},
]


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _workshop_with_checklist(session: AsyncSession, checklist=None):
    depts = await seeded(session)
    dept = depts["workshop"]
    await service.update_request_type(
        session, dept, "switchboard", {"checklist": list(CHECKLIST if checklist is None else checklist)}
    )
    return dept


@pytest.mark.asyncio
async def test_a_checklist_is_validated_the_way_fields_are(session: AsyncSession) -> None:
    dept = (await seeded(session))["workshop"]
    spec = await service.update_request_type(
        session, dept, "switchboard", {"checklist": [{"label": "Drawings signed off", "required": True}]}
    )
    assert spec["checklist"] == [{"key": "drawings_signed_off", "label": "Drawings signed off", "required": True}], (
        "the key is slugged from the label, exactly like a request type's own key"
    )

    with pytest.raises(service.WorkRequestError, match="appears twice"):
        await service.update_request_type(
            session, dept, "switchboard", {"checklist": [{"key": "a1", "label": "One"}, {"key": "a1", "label": "Two"}]}
        )
    with pytest.raises(service.WorkRequestError, match="lowercase letters"):
        await service.update_request_type(
            session, dept, "switchboard", {"checklist": [{"key": "Not A Key", "label": "One"}]}
        )
    with pytest.raises(service.WorkRequestError, match="must be a list"):
        await service.update_request_type(session, dept, "switchboard", {"checklist": {"key": "a"}})


@pytest.mark.asyncio
async def test_the_request_reads_its_checklist_back_resolved(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await _workshop_with_checklist(session)
    req = await raise_request(session, project=proj, user=pm)

    p = await service.payload(session, req)
    assert [i["key"] for i in p["checklist"]] == ["drawings_signed_off", "fat_booked", "photos"]
    assert [i["required"] for i in p["checklist"]] == [True, True, False]
    assert p["checklist_done"] == 0 and p["checklist_total"] == 3

    await service.set_checklist_item(session, req, "photos", True, user_id=str(pm.id), can_manage=False)
    p = await service.payload(session, req)
    ticked = next(i for i in p["checklist"] if i["key"] == "photos")
    assert ticked["done"] is True and ticked["by"] == str(pm.id) and ticked["at"]
    assert p["checklist_done"] == 1 and p["checklist_total"] == 3

    await service.set_checklist_item(session, req, "photos", False, user_id=str(pm.id), can_manage=False)
    assert (await service.payload(session, req))["checklist_done"] == 0, "unticking is a first-class move"


@pytest.mark.asyncio
async def test_an_unknown_item_is_refused_by_name(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await _workshop_with_checklist(session)
    req = await raise_request(session, project=proj, user=pm)
    with pytest.raises(service.WorkRequestError, match="no checklist item"):
        await service.set_checklist_item(session, req, "paint_colour", True, user_id=str(pm.id), can_manage=False)


@pytest.mark.asyncio
async def test_only_the_department_side_ticks(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    fitter = await make_user(session, name="Fitter Example")
    stranger = await make_user(session, name="Stranger Example")
    proj = await make_project(session, owner=pm)
    dept = await _workshop_with_checklist(session)
    await service.update_department(session, dept, {"member_ids": [str(fitter.id)]})
    req = await raise_request(session, project=proj, user=pm)

    with pytest.raises(service.NotPermitted):
        await service.set_checklist_item(session, req, "photos", True, user_id=str(stranger.id), can_manage=False)
    with pytest.raises(service.NotPermitted):
        await service.set_checklist_item(session, req, "photos", True, user_id=str(pm.id), can_manage=False)
    await service.set_checklist_item(session, req, "photos", True, user_id=str(fitter.id), can_manage=False)
    assert (await service.payload(session, req))["checklist_done"] == 1


@pytest.mark.asyncio
async def test_a_closing_stage_refuses_while_a_required_item_is_unticked(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await _workshop_with_checklist(session)
    req = await raise_request(session, project=proj, user=pm)
    await service.set_checklist_item(session, req, "drawings_signed_off", True, user_id=str(pm.id), can_manage=False)

    with pytest.raises(service.ConflictError) as exc:
        await service.move_stage(session, req, "delivered", user_id=str(pm.id), can_manage=False)
    assert "FAT booked" in str(exc.value)
    assert "Drawings signed off" not in str(exc.value), "only what is actually outstanding is named"
    assert "Photos on file" not in str(exc.value), "an optional item never gates the close"
    assert req.stage == "requested", "the board does not move and then refuse behind itself"
    assert req.status == "submitted"

    await service.set_checklist_item(session, req, "fat_booked", True, user_id=str(pm.id), can_manage=False)
    await service.move_stage(session, req, "delivered", user_id=str(pm.id), can_manage=False)
    assert req.stage == "delivered" and req.status == "complete"


@pytest.mark.asyncio
async def test_the_gate_holds_on_the_status_path_too(session: AsyncSession) -> None:
    """A rail enforced in one code path is not a rail: completing by
    status must refuse for the same reason a closing stage does."""
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await _workshop_with_checklist(session)
    req = await raise_request(session, project=proj, user=pm)
    await service.update_request(session, req, {"status": "accepted"}, user_id=str(pm.id), can_manage=True)
    await service.update_request(session, req, {"status": "in_progress"}, user_id=str(pm.id), can_manage=True)

    with pytest.raises(service.ConflictError) as exc:
        await service.update_request(session, req, {"status": "complete"}, user_id=str(pm.id), can_manage=True)
    assert "Drawings signed off" in str(exc.value) and "FAT booked" in str(exc.value)
    assert req.status == "in_progress"


@pytest.mark.asyncio
async def test_two_types_union_their_checklists_and_required_wins(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    depts = await seeded(session)
    dept = depts["workshop"]
    await service.update_request_type(
        session, dept, "switchboard", {"checklist": [{"key": "sign_off", "label": "Sign off", "required": False}]}
    )
    await service.update_request_type(
        session,
        dept,
        "gear_tray",
        {"checklist": [{"key": "sign_off", "label": "Sign off", "required": True}, {"key": "tray", "label": "Tray"}]},
    )
    req = await raise_request(session, project=proj, user=pm, request_types=["switchboard", "gear_tray"])
    p = await service.payload(session, req)
    assert [i["key"] for i in p["checklist"]] == ["sign_off", "tray"]
    assert p["checklist"][0]["required"] is True, "required in ANY chosen type is required on the request"


@pytest.mark.asyncio
async def test_a_type_with_no_checklist_reads_back_empty(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    req = await raise_request(session, project=proj, user=pm)
    p = await service.payload(session, req)
    assert p["checklist"] == [] and p["checklist_total"] == 0
    await service.move_stage(session, req, "delivered", user_id=str(pm.id), can_manage=False)
    assert req.status == "complete", "no checklist is no gate"


@pytest.mark.asyncio
async def test_checklist_over_http(api) -> None:
    client, pid, state = api
    state["payload"] = dict(API_MANAGER)
    base = API_BASE
    assert (await client.get(f"{base}/departments")).status_code == 200, "first read plants the seeds"
    r = await client.patch(
        f"{base}/departments/workshop/request-types/switchboard",
        json={"checklist": [{"key": "fat_booked", "label": "FAT booked", "required": True}]},
    )
    assert r.status_code == 200
    assert r.json()["request_type"]["checklist"][0]["required"] is True

    made = await client.post(
        f"{base}/requests",
        json={"project_id": pid, "department": "workshop", "request_type": "switchboard", "title": "MSB-01"},
    )
    assert made.status_code == 201
    rid = made.json()["id"]
    assert made.json()["checklist_total"] == 1 and made.json()["checklist_done"] == 0

    bad = await client.post(f"{base}/requests/{rid}/checklist", json={"key": "nope", "done": True})
    assert bad.status_code == 400 and "no checklist item" in bad.json()["detail"]

    blocked = await client.post(f"{base}/requests/{rid}/stage", json={"stage": "delivered"})
    assert blocked.status_code == 409 and "FAT booked" in blocked.json()["detail"]["error"]

    ok = await client.post(f"{base}/requests/{rid}/checklist", json={"key": "fat_booked", "done": True})
    assert ok.status_code == 200 and ok.json()["checklist_done"] == 1
    assert ok.json()["checklist"][0]["by"] == API_USER_ID

    closed = await client.post(f"{base}/requests/{rid}/stage", json={"stage": "delivered"})
    assert closed.status_code == 200 and closed.json()["status"] == "complete"
