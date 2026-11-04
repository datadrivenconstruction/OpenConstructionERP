# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Field capture hardening: the op ledger is per project, and capture age is judged on every kind.

* the same ``client_op_id`` replayed against another project neither returns the
  first project's row nor is blocked by it;
* a punch, inspection or schedule-progress capture older than 30 days is refused;
* a capture with no readable ``captured_at`` is treated as captured now and
  carries a warning code instead of silently skipping the freshness rule.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.modules.inspections.models import QualityInspection
from app.modules.punchlist.models import PunchItem
from tests.integration.test_field_pwa_sync import (  # noqa: F401  (fixtures)
    _seed_project,
    _session_for,
    app_and_client,
    engine_and_session,
)
from tests.integration.test_field_schedule_progress import _seed_activity

PUNCH = {"title": "Cracked tile", "priority": "high", "trade": "finishing"}
INSPECTION = {"inspection_type": "quality", "title": "Rebar check", "location": "L2", "checklist_data": []}


def _old(days: int = 45) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


@pytest.mark.asyncio
async def test_same_op_id_in_two_projects_makes_two_rows(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    a = await _seed_project(SessionFactory)
    b = await _seed_project(SessionFactory)
    ha = await _session_for(client, SessionFactory, a, "+491700000201")
    hb = await _session_for(client, SessionFactory, b, "+491700000202")
    op = str(uuid.uuid4())
    ra = await client.post("/v1/field-diary/capture/punch/", json={"client_op_id": op, **PUNCH}, headers=ha)
    rb = await client.post("/v1/field-diary/capture/punch/", json={"client_op_id": op, **PUNCH}, headers=hb)
    assert ra.status_code == 201 and rb.status_code == 201, rb.text
    assert rb.json()["result_id"] != ra.json()["result_id"]
    async with SessionFactory() as s:
        item = await s.get(PunchItem, uuid.UUID(rb.json()["result_id"]))
        assert item is not None and item.project_id == b
        n = (await s.execute(select(func.count()).select_from(PunchItem))).scalar_one()
        assert n == 2

    # Each project still dedups its own replay.
    again = await client.post("/v1/field-diary/capture/punch/", json={"client_op_id": op, **PUNCH}, headers=hb)
    assert again.json()["result_id"] == rb.json()["result_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "body", "model"),
    [("punch", PUNCH, PunchItem), ("inspection", INSPECTION, QualityInspection)],
)
async def test_stale_punch_and_inspection_are_refused(app_and_client, path, body, model) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000203")
    r = await client.post(
        f"/v1/field-diary/capture/{path}/",
        json={"client_op_id": str(uuid.uuid4()), "captured_at": _old(), **body},
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["reason_code"] == "op_too_old"
    async with SessionFactory() as s:
        assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == 0


@pytest.mark.asyncio
async def test_stale_schedule_progress_is_refused(app_and_client) -> None:  # noqa: F811
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    activity_id = await _seed_activity(SessionFactory, project_id)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000204")
    r = await client.post(
        "/v1/field-diary/capture/schedule-progress/",
        json={
            "client_op_id": str(uuid.uuid4()),
            "captured_at": _old(),
            "activity_id": str(activity_id),
            "percent_complete": 40,
        },
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["reason_code"] == "op_too_old"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("captured", "warning"), [(None, "captured_at_missing"), ("not a date", "captured_at_unreadable")]
)
async def test_missing_or_unreadable_capture_time_counts_as_now_with_a_warning(
    app_and_client,  # noqa: F811
    captured,
    warning,
) -> None:
    _app, client, SessionFactory = app_and_client  # noqa: N806
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000205")
    body = {"client_op_id": str(uuid.uuid4()), **PUNCH}
    if captured is not None:
        body["captured_at"] = captured
    r = await client.post("/v1/field-diary/capture/punch/", json=body, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "applied"
    assert r.json()["warning_code"] == warning

    fresh = await client.post(
        "/v1/field-diary/capture/punch/",
        json={"client_op_id": str(uuid.uuid4()), "captured_at": _old(1), **PUNCH},
        headers=headers,
    )
    assert fresh.json()["warning_code"] is None
