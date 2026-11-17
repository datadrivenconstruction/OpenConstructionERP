# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan room pin registry: targets, locations, validators, idempotent replay, status mirror."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.documents.models import Document, Sheet
from app.modules.plan_room.models import PlanPin
from app.modules.plan_room.permissions import register_plan_room_permissions
from app.modules.plan_room.pin_service import PinService
from app.modules.plan_room.router import router
from app.modules.plan_room.validators import register_plan_room_validation_rules
from app.modules.punchlist.models import PunchItem
from app.modules.rfi.models import RFI
from tests.modules._api_support import api_client, make_project

pytestmark = pytest.mark.asyncio

PREFIX = "/v1/plan-room"


def _client():
    return api_client(router, PREFIX, register_plan_room_permissions, register_plan_room_validation_rules)


async def _doc(session, project_id, pages: int = 2, current: bool = True) -> Document:
    doc = Document(project_id=project_id, name="A-101.pdf", revision_code="B", is_current_revision=True)
    session.add(doc)
    await session.flush()
    for n in range(1, pages + 1):
        session.add(
            Sheet(project_id=project_id, document_id=str(doc.id), page_number=n, is_current=current, created_by="t")
        )
    await session.flush()
    return doc


async def _rfi(session, project_id, user_id, status: str = "open") -> RFI:
    rfi = RFI(
        project_id=project_id,
        rfi_number=f"RFI-{uuid.uuid4().hex[:5]}",
        subject="Slab edge detail",
        question="?",
        raised_by=user_id,
        status=status,
    )
    session.add(rfi)
    await session.flush()
    return rfi


def _body(project_id, doc, rfi=None, **extra):
    body = {
        "project_id": str(project_id),
        "target_kind": "rfi" if rfi else "note",
        "target_id": str(rfi.id) if rfi else None,
        "document_id": str(doc.id),
        "page": 1,
        "x": 0.25,
        "y": 0.75,
        "note": "check",
    }
    body.update(extra)
    return body


async def test_rfi_pin_roundtrip_by_target_and_filters() -> None:
    async with _client() as (client, session, user):
        pid = await make_project(session, user)
        doc, rfi = await _doc(session, pid), await _rfi(session, pid, user.id)
        res = await client.post(f"{PREFIX}/pins/", json=_body(pid, doc, rfi))
        assert res.status_code == 201, res.text
        pin = res.json()
        assert pin["target_kind"] == "rfi" and pin["status"] == "open"
        assert pin["target_label"].startswith("RFI-") and pin["sheet_id"]

        by = await client.get(f"{PREFIX}/pins/by-target/rfi/{rfi.id}", params={"project_id": str(pid)})
        assert by.status_code == 200 and by.json()["total"] == 1

        lst = await client.get(f"{PREFIX}/pins/", params={"project_id": str(pid), "target_kind": "rfi", "page": 1})
        body = lst.json()
        assert set(body) == {"items", "total", "offset", "limit"} and body["total"] == 1
        none = await client.get(f"{PREFIX}/pins/", params={"project_id": str(pid), "target_kind": "ncr"})
        assert none.json()["total"] == 0

        ov = await client.get(f"{PREFIX}/{doc.id}/pages/1/overlays")
        assert [p["target_kind"] for p in ov.json()["pins"]] == ["rfi"]


async def test_idempotent_replay_returns_the_same_pin() -> None:
    async with _client() as (client, session, user):
        pid = await make_project(session, user)
        doc = await _doc(session, pid)
        body = _body(pid, doc, client_op_id="op-replay-0001")
        first = await client.post(f"{PREFIX}/pins/", json=body)
        second = await client.post(f"{PREFIX}/pins/", json=body)
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        count = (await session.execute(select(func.count()).select_from(PlanPin))).scalar_one()
        assert count == 1


async def test_validators_block_bad_pins() -> None:
    async with _client() as (client, session, user):
        pid = await make_project(session, user)
        other = await make_project(session, user)
        doc = await _doc(session, pid, pages=2)
        foreign_rfi = await _rfi(session, other, user.id)

        assert (await client.post(f"{PREFIX}/pins/", json=_body(pid, doc, page=3))).status_code == 422
        assert (await client.post(f"{PREFIX}/pins/", json=_body(pid, doc, x=1.5))).status_code == 422
        assert (await client.post(f"{PREFIX}/pins/", json=_body(pid, doc, foreign_rfi))).status_code == 422
        missing = _body(pid, doc, target_kind="rfi", target_id=None)
        assert (await client.post(f"{PREFIX}/pins/", json=missing)).status_code == 422
        nowhere = {"project_id": str(pid), "target_kind": "note", "note": "x"}
        assert (await client.post(f"{PREFIX}/pins/", json=nowhere)).status_code == 422
        # A document of another project is not found, not pinned.
        foreign_doc = await _doc(session, other)
        assert (await client.post(f"{PREFIX}/pins/", json=_body(pid, foreign_doc))).status_code == 404


async def test_one_location_and_bim_element_of_same_project() -> None:
    async with _client() as (client, session, user):
        pid = await make_project(session, user)
        other = await make_project(session, user)
        doc = await _doc(session, pid)
        models = {}
        for key, proj in (("mine", pid), ("theirs", other)):
            model = BIMModel(project_id=proj, name=key)
            session.add(model)
            await session.flush()
            element = BIMElement(model_id=model.id, stable_id=f"e-{key}")
            session.add(element)
            await session.flush()
            models[key] = (model, element)

        both = _body(pid, doc, bim_element_id=str(models["mine"][1].id))
        assert (await client.post(f"{PREFIX}/pins/", json=both)).status_code == 422
        foreign = {"project_id": str(pid), "bim_element_id": str(models["theirs"][1].id), "note": "x"}
        assert (await client.post(f"{PREFIX}/pins/", json=foreign)).status_code == 422
        ok = {"project_id": str(pid), "bim_element_id": str(models["mine"][1].id), "bim_xyz": [1, 2, 3], "note": "x"}
        res = await client.post(f"{PREFIX}/pins/", json=ok)
        assert res.status_code == 201, res.text
        assert res.json()["bim_model_id"] == str(models["mine"][0].id)
        on_model = await client.get(f"{PREFIX}/bim/{models['mine'][0].id}/pins")
        assert on_model.json()["total"] == 1


async def test_warnings_for_superseded_sheet_and_closed_record() -> None:
    async with _client() as (client, session, user):
        pid = await make_project(session, user)
        doc = await _doc(session, pid, current=False)
        rfi = await _rfi(session, pid, user.id, status="closed")
        res = await client.post(f"{PREFIX}/pins/", json=_body(pid, doc, rfi))
        assert res.status_code == 201, res.text
        rules = {w.get("rule_id") for w in res.json()["validation_warnings"]}
        assert {"plan_room.pin_superseded_revision", "plan_room.pin_closed_record"} <= rules


async def test_move_writes_through_to_punch_item_and_status_mirrors() -> None:
    async with _client() as (client, session, user):
        pid = await make_project(session, user)
        doc = await _doc(session, pid)
        item = PunchItem(project_id=pid, title="Crack", created_by=str(user.id))
        session.add(item)
        await session.flush()
        body = _body(pid, doc, target_kind="punch", target_id=str(item.id))
        pin = (await client.post(f"{PREFIX}/pins/", json=body)).json()
        await session.refresh(item)
        assert (item.page, item.location_x, item.location_y) == (1, 0.25, 0.75)

        moved = await client.patch(f"{PREFIX}/pins/{pin['id']}", json={"x": 0.5, "y": 0.5, "page": 2})
        assert moved.status_code == 200, moved.text
        await session.refresh(item)
        assert (item.page, item.location_x) == (2, 0.5)

        assert await PinService(session).mirror_status("punch", str(item.id), "closed") == 1
        row = await session.get(PlanPin, uuid.UUID(pin["id"]))
        await session.refresh(row)
        assert row.status == "closed"

        reviewed = await client.patch(f"{PREFIX}/pins/{pin['id']}", json={"revision_state": "needs_review"})
        assert reviewed.json()["revision_state"] == "needs_review"
        assert (await client.delete(f"{PREFIX}/pins/{pin['id']}")).status_code == 204
        assert await PinService(session).drop_for_target("punch", str(item.id)) == 0


async def test_carry_forward_marks_old_carried_and_copy_for_review() -> None:
    async with _client() as (client, session, user):
        pid = await make_project(session, user)
        old, new = await _doc(session, pid, pages=2), await _doc(session, pid, pages=1)
        keep = (await client.post(f"{PREFIX}/pins/", json=_body(pid, old))).json()
        gone = (await client.post(f"{PREFIX}/pins/", json=_body(pid, old, page=2))).json()
        res = await client.post(
            f"{PREFIX}/pins/carry-forward/",
            params={"project_id": str(pid), "from_sheet_id": keep["sheet_id"], "to_document_id": str(new.id)},
        )
        assert res.status_code == 201, res.text
        items = res.json()["items"]
        assert len(items) == 1 and items[0]["revision_state"] == "needs_review"
        assert items[0]["carried_from_pin_id"] == keep["id"]
        old_pin = await session.get(PlanPin, uuid.UUID(keep["id"]))
        assert old_pin.revision_state == "carried"
        assert gone["sheet_id"] != keep["sheet_id"]
