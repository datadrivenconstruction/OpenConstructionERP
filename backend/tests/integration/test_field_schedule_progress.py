# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for field-captured schedule progress (T3.4).

Covers the offline field -> T3.2 progress bridge:

    * a field schedule-progress capture updates the activity's progress through
      the progress-rigor engine (percent + status land on the activity);
    * a replay with the same client_op_id is idempotent (no second apply, same
      result id);
    * a cross-project activity id from a field session resolves to 404 (the IDOR
      guard - never trust an activity id outside the session's pinned project);
    * the batch drain routes a ``schedule_progress`` op the same way.

Mirrors the PostgreSQL isolation + magic-link auth pattern of
``test_field_pwa_sync.py``.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

os.environ["EXPOSE_DEV_AUTH_SECRETS"] = "true"  # request-magic-link returns dev_token/dev_pin

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.dependencies import get_session  # noqa: E402
from app.modules.field_diary import models as fd_models  # noqa: E402,F401
from app.modules.field_diary.router import router as fd_router  # noqa: E402
from app.modules.field_diary.service import FieldDiaryService, clear_sms_log  # noqa: E402
from app.modules.projects.models import Project  # noqa: E402
from app.modules.schedule.models import Activity, Schedule, ScheduleProgressEntry  # noqa: E402
from app.modules.users.models import User  # noqa: E402
from tests._pg import isolated_engine  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine_and_session():
    async with isolated_engine() as engine:
        SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
        yield engine, SessionFactory


@pytest_asyncio.fixture
async def app_and_client(engine_and_session) -> AsyncIterator[tuple]:
    _engine, SessionFactory = engine_and_session

    app = FastAPI()
    app.include_router(fd_router, prefix="/v1/field-diary")

    async def _session_override():
        async with SessionFactory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client, SessionFactory


async def _seed_project(SessionFactory) -> uuid.UUID:  # noqa: N803
    async with SessionFactory() as s:
        owner = User(email=f"owner-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
        s.add(owner)
        await s.flush()
        proj = Project(name=f"P-{uuid.uuid4().hex[:6]}", owner_id=owner.id)
        s.add(proj)
        await s.flush()
        proj_id = proj.id
        await s.commit()
    return proj_id


async def _seed_activity(SessionFactory, project_id: uuid.UUID) -> uuid.UUID:  # noqa: N803
    """Create a schedule + one activity in the given project, return activity id."""
    async with SessionFactory() as s:
        sched = Schedule(
            project_id=project_id,
            name="Field schedule",
            start_date="2026-06-01",
            end_date="2026-06-30",
        )
        s.add(sched)
        await s.flush()
        act = Activity(
            schedule_id=sched.id,
            name="Slab pour",
            wbs_code="02.01",
            start_date="2026-06-02",
            end_date="2026-06-12",
            duration_days=10,
            percent_complete_type="duration",
        )
        s.add(act)
        await s.flush()
        act_id = act.id
        await s.commit()
    return act_id


async def _session_for(client, SessionFactory, project_id: uuid.UUID, phone: str) -> dict:  # noqa: N803
    """Drive request-magic-link + grant + consume; return auth headers."""
    clear_sms_log()
    r = await client.post(
        "/v1/field-diary/auth/request-magic-link/",
        json={"phone": phone, "project_id": str(project_id), "module_key": "field_diary"},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    token, pin = body["dev_token"], body["dev_pin"]

    synth = f"field+{phone.lstrip('+')}@field.local"
    async with SessionFactory() as s:
        user_id = (await s.execute(select(User).where(User.email == synth))).scalar_one().id

    async with SessionFactory() as s:
        from app.modules.field_diary.schemas import FieldModuleGrantCreate

        svc = FieldDiaryService(s)
        await svc.create_grant(
            FieldModuleGrantCreate(user_id=user_id, project_id=project_id, module_key="field_diary"),
            granted_by=user_id,
        )
        await s.commit()

    r = await client.post("/v1/field-diary/auth/consume/", json={"token": token, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session_token']}", "X-Field-PIN": pin}


async def _activity(SessionFactory, activity_id: uuid.UUID) -> Activity:  # noqa: N803
    async with SessionFactory() as s:
        return await s.get(Activity, activity_id)


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_field_progress_updates_activity_via_t32(app_and_client) -> None:
    """A field progress capture drives the activity percent + status through T3.2."""
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    activity_id = await _seed_activity(SessionFactory, project_id)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000101")

    op_id = str(uuid.uuid4())
    payload = {
        "client_op_id": op_id,
        "captured_at": "2026-06-07T08:00:00",
        "activity_id": str(activity_id),
        "percent_complete": 40,
    }
    r = await client.post("/v1/field-diary/capture/schedule-progress/", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["target_module"] == "schedule"
    assert body["target_kind"] == "schedule_progress"
    assert body["result_id"] == str(activity_id)

    act = await _activity(SessionFactory, activity_id)
    assert float(act.progress_pct) == pytest.approx(40.0)
    assert act.status == "in_progress"


@pytest.mark.asyncio
async def test_field_progress_replay_is_idempotent(app_and_client) -> None:
    """Replaying the same client_op_id returns the same id and re-applies nothing new."""
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    activity_id = await _seed_activity(SessionFactory, project_id)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000102")

    op_id = str(uuid.uuid4())
    payload = {
        "client_op_id": op_id,
        "activity_id": str(activity_id),
        "percent_complete": 25,
    }
    r1 = await client.post("/v1/field-diary/capture/schedule-progress/", json=payload, headers=headers)
    assert r1.status_code == 201, r1.text

    # A replay returns 200 (already applied) with the same result id.
    r2 = await client.post("/v1/field-diary/capture/schedule-progress/", json=payload, headers=headers)
    assert r2.status_code == 201, r2.text  # FieldCaptureResponse status_code is in the body
    assert r2.json()["result_id"] == r1.json()["result_id"]

    # Exactly one ledger row for this op.
    async with SessionFactory() as s:
        from app.modules.field_diary.models import FieldSyncLedger

        rows = (await s.execute(select(FieldSyncLedger).where(FieldSyncLedger.client_op_id == op_id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].result_type == "schedule_activity_progress"


@pytest.mark.asyncio
async def test_field_progress_finish_completes_activity(app_and_client) -> None:
    """A captured actual_finish drives the activity to 100% / completed (engine rule)."""
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    activity_id = await _seed_activity(SessionFactory, project_id)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000103")

    payload = {
        "client_op_id": str(uuid.uuid4()),
        "activity_id": str(activity_id),
        "actual_finish": "2026-06-11",
    }
    r = await client.post("/v1/field-diary/capture/schedule-progress/", json=payload, headers=headers)
    assert r.status_code == 201, r.text

    act = await _activity(SessionFactory, activity_id)
    assert float(act.progress_pct) == pytest.approx(100.0)
    assert act.status == "completed"
    # The captured actual_finish is recorded in metadata (no Activity column).
    assert act.metadata_["field_actuals"]["actual_finish"] == "2026-06-11"


async def _progress_entries(SessionFactory, activity_id: uuid.UUID) -> list[ScheduleProgressEntry]:  # noqa: N803
    async with SessionFactory() as s:
        rows = (
            (await s.execute(select(ScheduleProgressEntry).where(ScheduleProgressEntry.task_id == activity_id)))
            .scalars()
            .all()
        )
        return list(rows)


@pytest.mark.asyncio
async def test_field_progress_records_actuals_on_progress_entry(app_and_client) -> None:
    """A field capture appends a ScheduleProgressEntry carrying the actual dates.

    This is the table EVM / 4D dashboards and the S-curve actual series read, so
    without the entry a phone-captured actual_start / actual_finish never reached
    earned-value reporting (the activity row has no actual-date columns).
    """
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    activity_id = await _seed_activity(SessionFactory, project_id)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000105")

    op_id = str(uuid.uuid4())
    payload = {
        "client_op_id": op_id,
        "captured_at": "2026-06-07T08:00:00",
        "activity_id": str(activity_id),
        "percent_complete": 60,
        "actual_start": "2026-06-03",
        "lat": 52.5,
        "lon": 13.4,
    }
    r = await client.post("/v1/field-diary/capture/schedule-progress/", json=payload, headers=headers)
    assert r.status_code == 201, r.text

    entries = await _progress_entries(SessionFactory, activity_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actual_start_date == "2026-06-03"
    assert entry.actual_finish_date is None
    assert entry.device == "field"
    assert entry.recorded_by_user_id is not None
    assert entry.geolocation == {"lat": 52.5, "lon": 13.4}

    # A replay (same client_op_id) does not create a second entry.
    r2 = await client.post("/v1/field-diary/capture/schedule-progress/", json=payload, headers=headers)
    assert r2.status_code == 201, r2.text
    assert len(await _progress_entries(SessionFactory, activity_id)) == 1


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_field_progress_cross_project_activity_is_404(app_and_client) -> None:
    """A field session may not move an activity in a project it is not pinned to."""
    _app, client, SessionFactory = app_and_client
    project_a = await _seed_project(SessionFactory)
    project_b = await _seed_project(SessionFactory)
    activity_b = await _seed_activity(SessionFactory, project_b)
    headers_a = await _session_for(client, SessionFactory, project_a, "+491700000104")

    payload = {
        "client_op_id": str(uuid.uuid4()),
        "activity_id": str(activity_b),  # another project's activity
        "percent_complete": 50,
    }
    r = await client.post("/v1/field-diary/capture/schedule-progress/", json=payload, headers=headers_a)
    assert r.status_code == 404, r.text

    # And the cross-project activity was NOT touched.
    act = await _activity(SessionFactory, activity_b)
    assert float(act.progress_pct) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_sync_batch_routes_schedule_progress(app_and_client) -> None:
    """The batch drain applies a schedule_progress op via the same path."""
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    activity_id = await _seed_activity(SessionFactory, project_id)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000105")

    op_id = str(uuid.uuid4())
    batch = await client.post(
        "/v1/field-diary/sync/batch/",
        json={
            "ops": [
                {
                    "client_op_id": op_id,
                    "target_kind": "schedule_progress",
                    "payload": {"activity_id": str(activity_id), "percent_complete": 60},
                }
            ]
        },
        headers=headers,
    )
    assert batch.status_code == 200, batch.text
    results = batch.json()
    assert len(results) == 1
    assert results[0]["target_kind"] == "schedule_progress"
    assert results[0]["result_id"] == str(activity_id)

    act = await _activity(SessionFactory, activity_id)
    assert float(act.progress_pct) == pytest.approx(60.0)
