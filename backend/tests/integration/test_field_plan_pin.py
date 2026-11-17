# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Offline field capture of a location pin: it follows the record raised earlier in the same queue."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.documents.models import Document, Sheet
from app.modules.plan_room.models import PlanPin
from app.modules.punchlist.models import PunchItem
from tests.integration.test_field_pwa_sync import (  # noqa: F401  (fixtures)
    _seed_project,
    _session_for,
    app_and_client,
    engine_and_session,
)


async def _drawing(SessionFactory, project_id) -> Document:  # noqa: N803
    async with SessionFactory() as s:
        doc = Document(project_id=project_id, name="A-101.pdf", mime_type="application/pdf")
        s.add(doc)
        await s.flush()
        s.add(Sheet(project_id=project_id, document_id=str(doc.id), page_number=1, created_by="t"))
        await s.commit()
        return doc


async def _pins(SessionFactory, project_id) -> list[PlanPin]:  # noqa: N803
    async with SessionFactory() as s:
        return list((await s.execute(select(PlanPin).where(PlanPin.project_id == project_id))).scalars().all())


@pytest.mark.asyncio
async def test_pin_follows_the_punch_raised_in_the_same_batch_and_replays_once(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000201")
    doc = await _drawing(SessionFactory, project_id)
    punch_op, pin_op = str(uuid.uuid4()), str(uuid.uuid4())
    ops = [
        {"client_op_id": punch_op, "target_kind": "punch_item", "payload": {"title": "Cracked sill"}},
        {
            "client_op_id": pin_op,
            "target_kind": "plan_pin",
            "payload": {
                "record_kind": "punch",
                "record_client_op_id": punch_op,
                "document_id": str(doc.id),
                "page": 1,
                "x": 0.4,
                "y": 0.6,
            },
        },
    ]
    for _ in range(2):  # the second drain replays the same ops
        res = await client.post("/v1/field-diary/sync/batch/", json={"ops": ops}, headers=headers)
        assert res.status_code == 200, res.text
        assert [r["status"] for r in res.json()] == ["applied", "applied"]

    pins = await _pins(SessionFactory, project_id)
    assert len(pins) == 1 and pins[0].target_kind == "punch" and pins[0].client_op_id == pin_op
    async with SessionFactory() as s:
        item = await s.get(PunchItem, uuid.UUID(pins[0].target_id))
        assert (item.page, item.location_x, item.location_y) == (1, 0.4, 0.6)


@pytest.mark.asyncio
async def test_pin_without_its_record_is_rejected_and_writes_nothing(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000202")
    doc = await _drawing(SessionFactory, project_id)
    body = {
        "client_op_id": str(uuid.uuid4()),
        "record_kind": "punch",
        "record_client_op_id": str(uuid.uuid4()),
        "document_id": str(doc.id),
        "x": 0.1,
        "y": 0.1,
    }
    res = await client.post("/v1/field-diary/capture/plan-pin/", json=body, headers=headers)
    assert res.json()["status"] == "rejected" and res.json()["reason_code"] == "record_not_synced"
    assert await _pins(SessionFactory, project_id) == []


@pytest.mark.asyncio
async def test_sheet_list_is_scoped_to_the_session_project(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    mine = await _seed_project(SessionFactory)
    theirs = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, mine, "+491700000203")
    own = await _drawing(SessionFactory, mine)
    other = await _drawing(SessionFactory, theirs)
    res = await client.get("/v1/field-diary/sheets/", headers=headers)
    body = res.json()
    assert set(body) == {"items", "total", "offset", "limit"}
    assert [i["document_id"] for i in body["items"]] == [str(own.id)]
    foreign = await client.get(f"/v1/field-diary/sheets/{other.id}/pages/1/image/", headers=headers)
    assert foreign.status_code == 404
    async with SessionFactory() as s:
        assert (await s.execute(select(func.count()).select_from(Document))).scalar_one() >= 2
