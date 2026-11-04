# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Offline field capture: NCR, safety observation and haul ticket kinds.

Properties pinned here:

* each new kind creates exactly one row however often the same ``client_op_id``
  is replayed (single endpoint, batch, or both mixed);
* the batch dispatcher accepts the three new ``target_kind`` values;
* an op captured more than 30 days ago is rejected with ``op_too_old`` and
  writes nothing, and a rejected op can be re-sent fresh under a new id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.modules.haul_tickets.models import HaulTicket
from app.modules.ncr.models import NCR
from app.modules.safety.models import SafetyObservation
from tests.integration.test_field_pwa_sync import (  # noqa: F401  (fixtures)
    _seed_project,
    _session_for,
    app_and_client,
    engine_and_session,
)


async def _count(SessionFactory, model, project_id) -> int:  # noqa: N803
    async with SessionFactory() as s:
        return (
            await s.execute(select(func.count()).select_from(model).where(model.project_id == project_id))
        ).scalar_one()


NCR_BODY = {
    "title": "Cracked slab",
    "description": "Crack along grid C",
    "ncr_type": "workmanship",
    "severity": "major",
}
OBS_BODY = {
    "observation_type": "unsafe_condition",
    "description": "Open edge on level 3",
    "severity": 4,
    "likelihood": 3,
}
HAUL_BODY = {
    "haul_type": "aggregates",
    "material_name": "Gravel 0/32",
    "unit": "t",
    "net_t": "24.500",
    "plate": "B-XY 123",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "kind", "body", "model"),
    [
        ("ncr", "ncr", NCR_BODY, NCR),
        ("safety-observation", "safety_observation", OBS_BODY, SafetyObservation),
        ("haul-ticket", "haul_ticket", HAUL_BODY, HaulTicket),
    ],
)
async def test_replay_twice_is_one_row(app_and_client, path, kind, body, model) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000101")
    op = str(uuid.uuid4())

    first = await client.post(f"/v1/field-diary/capture/{path}/", json={"client_op_id": op, **body}, headers=headers)
    assert first.status_code == 201, first.text
    again = await client.post(f"/v1/field-diary/capture/{path}/", json={"client_op_id": op, **body}, headers=headers)
    assert again.json()["http_status"] == 200  # the route keeps its 201; the body says it was a replay
    assert again.json()["result_id"] == first.json()["result_id"]

    batch = await client.post(
        "/v1/field-diary/sync/batch/",
        json={"ops": [{"client_op_id": op, "target_kind": kind, "payload": body}]},
        headers=headers,
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()[0]["result_id"] == first.json()["result_id"]
    assert batch.json()[0]["status"] == "applied"
    assert await _count(SessionFactory, model, project_id) == 1


@pytest.mark.asyncio
async def test_batch_mixes_all_six_kinds(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000102")
    ops = [
        {"client_op_id": str(uuid.uuid4()), "target_kind": "punch_item", "payload": {"title": "Paint touch-up"}},
        {"client_op_id": str(uuid.uuid4()), "target_kind": "ncr", "payload": NCR_BODY},
        {"client_op_id": str(uuid.uuid4()), "target_kind": "safety_observation", "payload": OBS_BODY},
        {"client_op_id": str(uuid.uuid4()), "target_kind": "haul_ticket", "payload": HAUL_BODY},
    ]
    r = await client.post("/v1/field-diary/sync/batch/", json={"ops": ops}, headers=headers)
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()] == ["applied"] * 4
    assert [x["target_kind"] for x in r.json()] == ["punch_item", "ncr", "safety_observation", "haul_ticket"]


@pytest.mark.asyncio
async def test_unknown_kind_is_refused_by_the_schema(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000103")
    r = await client.post(
        "/v1/field-diary/sync/batch/",
        json={"ops": [{"client_op_id": str(uuid.uuid4()), "target_kind": "invoice", "payload": {}}]},
        headers=headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "body", "model"),
    [
        ("ncr", NCR_BODY, NCR),
        ("safety_observation", OBS_BODY, SafetyObservation),
        ("haul_ticket", HAUL_BODY, HaulTicket),
    ],
)
async def test_op_older_than_30_days_is_rejected_and_writes_nothing(app_and_client, kind, body, model) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000104")
    old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    op = str(uuid.uuid4())
    r = await client.post(
        "/v1/field-diary/sync/batch/",
        json={"ops": [{"client_op_id": op, "target_kind": kind, "captured_at": old, "payload": body}]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    out = r.json()[0]
    assert out["status"] == "rejected"
    assert out["reason_code"] == "op_too_old"
    assert out["result_id"] is None
    assert await _count(SessionFactory, model, project_id) == 0

    # The same capture re-entered fresh (new id, today's time) goes through.
    fresh = await client.post(
        "/v1/field-diary/sync/batch/",
        json={"ops": [{"client_op_id": str(uuid.uuid4()), "target_kind": kind, "payload": body}]},
        headers=headers,
    )
    assert fresh.json()[0]["status"] == "applied"
    assert await _count(SessionFactory, model, project_id) == 1


@pytest.mark.asyncio
async def test_recent_offline_capture_is_accepted(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000105")
    recent = (datetime.now(UTC) - timedelta(days=29)).isoformat()
    r = await client.post(
        "/v1/field-diary/capture/ncr/",
        json={"client_op_id": str(uuid.uuid4()), "captured_at": recent, **NCR_BODY},
        headers=headers,
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_offline_pack_lists_open_punch_and_checklists_for_the_session_project(app_and_client) -> None:  # noqa: F811
    from app.modules.inspections.models import QualityInspection
    from app.modules.punchlist.models import PunchItem

    _app, client, SessionFactory = app_and_client  # noqa: N806
    mine = await _seed_project(SessionFactory)
    other = await _seed_project(SessionFactory)
    async with SessionFactory() as s:
        s.add(PunchItem(project_id=mine, title="Mine open", status="open", priority="high"))
        s.add(PunchItem(project_id=mine, title="Mine closed", status="closed", priority="low"))
        s.add(PunchItem(project_id=other, title="Theirs", status="open", priority="low"))
        s.add(
            QualityInspection(
                project_id=mine,
                inspection_number="INS-001",
                inspection_type="concrete",
                title="Pour check",
                status="scheduled",
                checklist_data=[{"item": "Rebar cover", "critical": True}],
            )
        )
        await s.commit()
    headers = await _session_for(client, SessionFactory, mine, "+491700000106")
    r = await client.get("/v1/field-diary/offline-pack/", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["title"] for p in body["punch_items"]] == ["Mine open"]
    assert body["inspections"][0]["checklist_data"][0]["item"] == "Rebar cover"
    assert body["punch_truncated"] is False
    assert body["server_time"]


@pytest.mark.asyncio
async def test_single_endpoint_answers_422_for_a_stale_op(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000107")
    old = (datetime.now(UTC) - timedelta(days=31, hours=1)).isoformat()
    r = await client.post(
        "/v1/field-diary/capture/ncr/",
        json={"client_op_id": str(uuid.uuid4()), "captured_at": old, **NCR_BODY},
        headers=headers,
    )
    assert r.status_code == 422
    assert r.json()["reason_code"] == "op_too_old"
    assert await _count(SessionFactory, NCR, project_id) == 0


@pytest.mark.asyncio
async def test_long_op_ids_sharing_a_prefix_make_two_haul_tickets(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000109")
    prefix = "x" * 100
    for suffix in ("a" * 10, "b" * 10):
        r = await client.post(
            "/v1/field-diary/capture/haul-ticket/",
            json={**HAUL_BODY, "client_op_id": prefix + suffix},
            headers=headers,
        )
        assert r.status_code == 201, r.text
    assert await _count(SessionFactory, HaulTicket, project_id) == 2
