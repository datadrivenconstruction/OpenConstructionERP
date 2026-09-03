# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Per-request checklist overrides: a one-off job adds "Client witness
test" or drops an item that does not apply, WITHOUT rewriting the request
type every other job uses.

The whole point of storing a DIFFERENCE rather than a copy is the last
test in this file: an item nobody has overridden here still reads its
label off the type after the type is edited.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import make_project, make_user, raise_request, seeded
from tests.modules.work_requests.conftest import API_BASE, API_EDITOR, API_MANAGER, API_USER_ID

CHECKLIST = [
    {"key": "drawings", "label": "Drawings signed off", "required": True},
    {"key": "fat_booked", "label": "FAT booked", "required": True},
    {"key": "photos", "label": "Photos on file"},
]


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _workshop(session: AsyncSession, checklist=None):
    dept = (await seeded(session))["workshop"]
    await service.update_request_type(
        session, dept, "switchboard", {"checklist": list(CHECKLIST if checklist is None else checklist)}
    )
    return dept


async def _a_request(session: AsyncSession):
    """``(request, department, lead, pm)`` - the lead is the one person
    besides a manager who may change the shape of the list."""
    pm = await make_user(session, name="PM Example")
    lead = await make_user(session, name="Lead Example")
    proj = await make_project(session, owner=pm)
    dept = await _workshop(session)
    await service.update_department(session, dept, {"lead_user_id": str(lead.id)})
    req = await raise_request(session, project=proj, user=pm)
    return req, dept, lead, pm


def _keys(payload: dict) -> list[str]:
    return [i["key"] for i in payload["checklist"]]


@pytest.mark.asyncio
async def test_an_item_added_here_shows_as_a_request_item(session: AsyncSession) -> None:
    req, dept, lead, _pm = await _a_request(session)
    await service.add_checklist_item(
        session, req, label="Client witness test", required=True, user_id=str(lead.id), can_manage=False
    )
    p = await service.payload(session, req)
    assert _keys(p) == ["drawings", "fat_booked", "photos", "client_witness_test"]
    added = p["checklist"][-1]
    assert added["label"] == "Client witness test" and added["required"] is True
    assert added["source"] == "request", "the UI must be able to tell a one-off from what is inherited"
    assert all(i["source"] == "type" for i in p["checklist"][:3])
    assert p["checklist_total"] == 4 and p["checklist_is_overridden"] is True

    # ``after_key`` puts it where it belongs rather than at the end.
    await service.add_checklist_item(
        session, req, label="Megger test", after_key="drawings", user_id=str(lead.id), can_manage=False
    )
    assert _keys(await service.payload(session, req)) == [
        "drawings",
        "megger_test",
        "fat_booked",
        "photos",
        "client_witness_test",
    ]

    with pytest.raises(service.ConflictError, match="already has a checklist item"):
        await service.add_checklist_item(session, req, label="Megger Test", user_id=str(lead.id), can_manage=False)
    with pytest.raises(service.WorkRequestError, match="to add this one after"):
        await service.add_checklist_item(
            session, req, label="Paint", after_key="nope", user_id=str(lead.id), can_manage=False
        )


@pytest.mark.asyncio
async def test_an_inherited_item_is_reworded_and_re_required_here_only(session: AsyncSession) -> None:
    req, dept, lead, _pm = await _a_request(session)
    await service.update_checklist_item(
        session, req, "photos", label="Photos to the client", required=True, user_id=str(lead.id), can_manage=False
    )
    await service.update_checklist_item(
        session, req, "fat_booked", required=False, user_id=str(lead.id), can_manage=False
    )
    p = await service.payload(session, req)
    photos = next(i for i in p["checklist"] if i["key"] == "photos")
    assert photos["label"] == "Photos to the client" and photos["required"] is True
    assert photos["source"] == "type", "an override does not turn an inherited item into a one-off"
    assert next(i for i in p["checklist"] if i["key"] == "fat_booked")["required"] is False

    spec = service.request_type_spec(dept, "switchboard")
    assert [i["label"] for i in spec["checklist"]] == ["Drawings signed off", "FAT booked", "Photos on file"], (
        "the TYPE every other job uses is untouched"
    )

    # A request-added item is edited in place, and keeps its key so the
    # tick already against it survives the rename.
    await service.add_checklist_item(session, req, label="Witness test", user_id=str(lead.id), can_manage=False)
    await service.set_checklist_item(session, req, "witness_test", True, user_id=str(lead.id), can_manage=False)
    await service.update_checklist_item(
        session, req, "witness_test", label="Client witness test", user_id=str(lead.id), can_manage=False
    )
    item = next(i for i in (await service.payload(session, req))["checklist"] if i["key"] == "witness_test")
    assert item["label"] == "Client witness test" and item["done"] is True


@pytest.mark.asyncio
async def test_hiding_an_inherited_item_and_deleting_an_added_one(session: AsyncSession) -> None:
    req, dept, lead, _pm = await _a_request(session)
    await service.add_checklist_item(session, req, label="Witness test", user_id=str(lead.id), can_manage=False)

    await service.remove_checklist_item(session, req, "fat_booked", user_id=str(lead.id), can_manage=False)
    assert _keys(await service.payload(session, req)) == ["drawings", "photos", "witness_test"]
    assert service.overrides_of(req)["hidden"] == ["fat_booked"], "an inherited item is HIDDEN, never deleted"
    assert [i["key"] for i in service.request_type_spec(dept, "switchboard")["checklist"]] == [
        "drawings",
        "fat_booked",
        "photos",
    ], "the type still declares it, so a later type change brings it back"

    await service.remove_checklist_item(session, req, "witness_test", user_id=str(lead.id), can_manage=False)
    p = await service.payload(session, req)
    assert _keys(p) == ["drawings", "photos"]
    assert service.overrides_of(req)["added"] == [], "one added here is removed outright"

    # Adding a label that slugs to the SAME key un-hides the inherited
    # item rather than refusing over a row nobody can see.
    await service.add_checklist_item(
        session, req, label="FAT Booked", required=True, user_id=str(lead.id), can_manage=False
    )
    p = await service.payload(session, req)
    back = next((i for i in p["checklist"] if i["key"] == "fat_booked"), None)
    assert back is not None and back["source"] == "type", "it is the type's item again, not a one-off"
    assert back["label"] == "FAT Booked" and back["required"] is True, "under the label just asked for"
    assert service.overrides_of(req)["hidden"] == []


@pytest.mark.asyncio
async def test_a_ticked_item_is_not_deleted_out_from_under_the_tick(session: AsyncSession) -> None:
    req, dept, lead, _pm = await _a_request(session)
    await service.set_checklist_item(session, req, "photos", True, user_id=str(lead.id), can_manage=False)

    with pytest.raises(service.ConflictError) as exc:
        await service.remove_checklist_item(session, req, "photos", user_id=str(lead.id), can_manage=False)
    assert "untick it first" in str(exc.value) and "Photos on file" in str(exc.value)
    assert "photos" in _keys(await service.payload(session, req)), "the refusal left the list alone"

    await service.set_checklist_item(session, req, "photos", False, user_id=str(lead.id), can_manage=False)
    await service.remove_checklist_item(session, req, "photos", user_id=str(lead.id), can_manage=False)
    assert "photos" not in _keys(await service.payload(session, req))


@pytest.mark.asyncio
async def test_reorder_keeps_what_was_left_out_in_relative_order(session: AsyncSession) -> None:
    req, dept, lead, _pm = await _a_request(session)
    await service.add_checklist_item(session, req, label="Witness test", user_id=str(lead.id), can_manage=False)

    await service.reorder_checklist(
        session, req, ["photos", "witness_test", "ghost"], user_id=str(lead.id), can_manage=False
    )
    assert _keys(await service.payload(session, req)) == ["photos", "witness_test", "drawings", "fat_booked"], (
        "the keys named lead, in that order; the rest keep their order at the end"
    )
    assert service.overrides_of(req)["order"] == ["photos", "witness_test"], "a key not on the list is ignored"


@pytest.mark.asyncio
async def test_reset_drops_every_override_but_keeps_the_ticks_that_still_apply(session: AsyncSession) -> None:
    req, dept, lead, _pm = await _a_request(session)
    await service.add_checklist_item(session, req, label="Witness test", user_id=str(lead.id), can_manage=False)
    await service.update_checklist_item(
        session, req, "photos", label="Photos to the client", user_id=str(lead.id), can_manage=False
    )
    await service.remove_checklist_item(session, req, "fat_booked", user_id=str(lead.id), can_manage=False)
    await service.reorder_checklist(session, req, ["photos"], user_id=str(lead.id), can_manage=False)
    await service.set_checklist_item(session, req, "drawings", True, user_id=str(lead.id), can_manage=False)

    await service.reset_checklist(session, req, user_id=str(lead.id), can_manage=False)
    p = await service.payload(session, req)
    assert _keys(p) == ["drawings", "fat_booked", "photos"]
    assert [i["label"] for i in p["checklist"]] == ["Drawings signed off", "FAT booked", "Photos on file"]
    assert all(i["source"] == "type" for i in p["checklist"])
    assert p["checklist_overrides"] == {"added": [], "hidden": [], "edits": {}, "order": []}
    assert p["checklist_is_overridden"] is False
    assert next(i for i in p["checklist"] if i["key"] == "drawings")["done"] is True, "the tick survives the reset"


@pytest.mark.asyncio
async def test_only_the_lead_or_a_manager_changes_the_shape_of_the_list(session: AsyncSession) -> None:
    req, dept, lead, pm = await _a_request(session)
    fitter = await make_user(session, name="Fitter Example")
    await service.update_department(session, dept, {"member_ids": [str(fitter.id)]})

    for who in (fitter, pm):
        with pytest.raises(service.NotPermitted) as exc:
            await service.add_checklist_item(session, req, label="Paint", user_id=str(who.id), can_manage=False)
        assert str(exc.value) == "Only the Workshop lead or a manager can change this checklist."
    with pytest.raises(service.NotPermitted):
        await service.remove_checklist_item(session, req, "photos", user_id=str(fitter.id), can_manage=False)
    with pytest.raises(service.NotPermitted):
        await service.reset_checklist(session, req, user_id=str(fitter.id), can_manage=False)

    # A member still TICKS - that rail is unchanged and stays department-side.
    await service.set_checklist_item(session, req, "photos", True, user_id=str(fitter.id), can_manage=False)

    await service.add_checklist_item(session, req, label="Paint", user_id=str(lead.id), can_manage=False)
    await service.add_checklist_item(session, req, label="Labels", user_id=str(pm.id), can_manage=True)
    assert _keys(await service.payload(session, req))[-2:] == ["paint", "labels"]


@pytest.mark.asyncio
async def test_an_added_required_item_blocks_completion_and_a_hidden_one_stops_blocking(
    session: AsyncSession,
) -> None:
    req, dept, lead, pm = await _a_request(session)
    for key in ("drawings", "fat_booked"):
        await service.set_checklist_item(session, req, key, True, user_id=str(lead.id), can_manage=False)

    await service.add_checklist_item(
        session, req, label="Client witness test", required=True, user_id=str(lead.id), can_manage=False
    )
    with pytest.raises(service.ConflictError) as exc:
        await service.move_stage(session, req, "delivered", user_id=str(lead.id), can_manage=False)
    assert "Client witness test" in str(exc.value), "the gate runs on the DERIVED list, one-offs included"
    assert req.stage == "requested"

    # Hide it instead of ticking it: it must stop gating immediately.
    await service.remove_checklist_item(session, req, "client_witness_test", user_id=str(lead.id), can_manage=False)
    await service.move_stage(session, req, "delivered", user_id=str(lead.id), can_manage=False)
    assert req.stage == "delivered" and req.status == "complete"


@pytest.mark.asyncio
async def test_hiding_an_inherited_required_item_lifts_the_gate(session: AsyncSession) -> None:
    req, dept, lead, _pm = await _a_request(session)
    await service.set_checklist_item(session, req, "drawings", True, user_id=str(lead.id), can_manage=False)

    with pytest.raises(service.ConflictError, match="FAT booked"):
        await service.move_stage(session, req, "delivered", user_id=str(lead.id), can_manage=False)

    await service.remove_checklist_item(session, req, "fat_booked", user_id=str(lead.id), can_manage=False)
    await service.move_stage(session, req, "delivered", user_id=str(lead.id), can_manage=False)
    assert req.status == "complete", "an item that does not apply to this job no longer holds it open"


@pytest.mark.asyncio
async def test_a_later_edit_of_the_type_still_shows_through_where_nobody_overrode_it(session: AsyncSession) -> None:
    """The override is a DIFFERENCE, not a copy of the list."""
    req, dept, lead, _pm = await _a_request(session)
    await service.update_checklist_item(
        session, req, "photos", label="Photos to the client", user_id=str(lead.id), can_manage=False
    )
    await service.add_checklist_item(session, req, label="Witness test", user_id=str(lead.id), can_manage=False)

    await service.update_request_type(
        session,
        dept,
        "switchboard",
        {
            "checklist": [
                {"key": "drawings", "label": "Drawings approved by the client", "required": True},
                {"key": "fat_booked", "label": "FAT booked", "required": False},
                {"key": "photos", "label": "Photos filed", "required": True},
                {"key": "torque", "label": "Torque check", "required": True},
            ]
        },
    )
    p = await service.payload(session, req)
    by_key = {i["key"]: i for i in p["checklist"]}
    assert by_key["drawings"]["label"] == "Drawings approved by the client", "a re-worded type item shows through"
    assert by_key["fat_booked"]["required"] is False, "so does a required flag the type dropped"
    assert "torque" in by_key and by_key["torque"]["source"] == "type", "a NEW type item arrives on this request"
    assert by_key["photos"]["label"] == "Photos to the client", "the one item overridden here keeps its override"
    assert by_key["photos"]["required"] is True, "and un-overridden halves still follow the type"
    assert by_key["witness_test"]["source"] == "request"
    assert _keys(p) == ["drawings", "fat_booked", "photos", "torque", "witness_test"]


@pytest.mark.asyncio
async def test_a_closed_request_refuses_every_checklist_edit(session: AsyncSession) -> None:
    req, dept, lead, pm = await _a_request(session)
    await service.update_request(session, req, {"status": "cancelled"}, user_id=str(pm.id), can_manage=True)

    with pytest.raises(service.ConflictError, match="can no longer be changed"):
        await service.add_checklist_item(session, req, label="Paint", user_id=str(lead.id), can_manage=True)
    with pytest.raises(service.ConflictError, match="can no longer be changed"):
        await service.reset_checklist(session, req, user_id=str(lead.id), can_manage=True)


@pytest.mark.asyncio
async def test_checklist_overrides_over_http(api) -> None:
    client, pid, state = api
    base = API_BASE
    state["payload"] = dict(API_MANAGER)
    assert (await client.get(f"{base}/departments")).status_code == 200
    assert (
        await client.patch(f"{base}/departments/workshop/request-types/switchboard", json={"checklist": CHECKLIST})
    ).status_code == 200
    # The caller is the workshop LEAD from here on, not a manager.
    assert (await client.patch(f"{base}/departments/workshop", json={"lead_user_id": API_USER_ID})).status_code == 200
    made = await client.post(
        f"{base}/requests",
        json={"project_id": pid, "department": "workshop", "request_type": "switchboard", "title": "MSB-01"},
    )
    assert made.status_code == 201
    rid = made.json()["id"]
    state["payload"] = dict(API_EDITOR)

    r = await client.post(
        f"{base}/requests/{rid}/checklist/items", json={"label": "Client witness test", "required": True}
    )
    assert r.status_code == 201, r.text
    assert [i["key"] for i in r.json()["checklist"]][-1] == "client_witness_test"
    assert r.json()["checklist"][-1]["source"] == "request" and r.json()["checklist_total"] == 4

    dup = await client.post(f"{base}/requests/{rid}/checklist/items", json={"label": "Client Witness Test"})
    assert dup.status_code == 409 and "already has a checklist item" in dup.json()["detail"]["error"]

    r = await client.patch(
        f"{base}/requests/{rid}/checklist/items/photos", json={"label": "Photos to the client", "required": True}
    )
    assert r.status_code == 200
    assert next(i for i in r.json()["checklist"] if i["key"] == "photos")["label"] == "Photos to the client"

    r = await client.post(f"{base}/requests/{rid}/checklist", json={"key": "photos", "done": True})
    assert r.status_code == 200
    stuck = await client.delete(f"{base}/requests/{rid}/checklist/items/photos")
    assert stuck.status_code == 409 and "untick it first" in stuck.json()["detail"]["error"]
    await client.post(f"{base}/requests/{rid}/checklist", json={"key": "photos", "done": False})

    r = await client.delete(f"{base}/requests/{rid}/checklist/items/fat_booked")
    assert r.status_code == 200 and "fat_booked" not in [i["key"] for i in r.json()["checklist"]]

    r = await client.put(f"{base}/requests/{rid}/checklist/order", json={"keys": ["client_witness_test", "photos"]})
    assert r.status_code == 200
    assert [i["key"] for i in r.json()["checklist"]] == ["client_witness_test", "photos", "drawings"]

    # An ordinary editor who is not the lead is refused, by name.
    state["payload"] = {"role": "viewer", "permissions": ["work_requests.read", "work_requests.update"]}
    assert (await client.patch(f"{base}/departments/workshop", json={"lead_user_id": None})).status_code == 403
    state["payload"] = dict(API_MANAGER)
    assert (await client.patch(f"{base}/departments/workshop", json={"lead_user_id": None})).status_code == 200
    state["payload"] = dict(API_EDITOR)
    nope = await client.post(f"{base}/requests/{rid}/checklist/items", json={"label": "Paint"})
    assert nope.status_code == 403
    assert nope.json()["detail"] == "Only the Workshop lead or a manager can change this checklist."

    state["payload"] = dict(API_MANAGER)
    r = await client.post(f"{base}/requests/{rid}/checklist/reset")
    assert r.status_code == 200
    assert [i["key"] for i in r.json()["checklist"]] == ["drawings", "fat_booked", "photos"]
    assert r.json()["checklist_is_overridden"] is False
