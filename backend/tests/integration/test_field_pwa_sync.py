# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for the offline field PWA sync surface (TOP-30 #14).

Covers the true Phase-1 delta on top of the existing field-diary module:

    * Punch capture is idempotent on ``client_op_id`` - replaying the same op
      returns the same punch id and does NOT create a second row (the core
      correctness property for an at-least-once offline queue drain).
    * Inspection capture is idempotent the same way.
    * ``sync/batch`` applies many ops in one request and a batch that overlaps a
      prior single replay never double-applies.
    * Project scoping is structural: the punch lands on the session project; a
      photo capture against another project's punch resolves to 404.
    * ``sync/ops`` returns the worker's own applied ops.

Mirrors the PostgreSQL isolation + ASGI-app pattern of ``test_field_diary.py``.
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
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.dependencies import get_session  # noqa: E402
from app.modules.field_diary import models as fd_models  # noqa: E402,F401
from app.modules.field_diary.router import router as fd_router  # noqa: E402
from app.modules.field_diary.service import (  # noqa: E402
    FieldDiaryService,
    clear_sms_log,
)
from app.modules.inspections.models import QualityInspection  # noqa: E402
from app.modules.projects.models import Project  # noqa: E402
from app.modules.punchlist.models import PunchItem  # noqa: E402
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
        owner = User(
            email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="x",
            role="admin",
        )
        s.add(owner)
        await s.flush()
        proj = Project(name=f"P-{uuid.uuid4().hex[:6]}", owner_id=owner.id)
        s.add(proj)
        await s.flush()
        proj_id = proj.id
        await s.commit()
    return proj_id


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
    session_token = r.json()["session_token"]
    return {"Authorization": f"Bearer {session_token}", "X-Field-PIN": pin}


async def _count_punch(SessionFactory, project_id: uuid.UUID) -> int:  # noqa: N803
    async with SessionFactory() as s:
        return (
            await s.execute(select(func.count()).select_from(PunchItem).where(PunchItem.project_id == project_id))
        ).scalar_one()


async def _count_inspections(SessionFactory, project_id: uuid.UUID) -> int:  # noqa: N803
    async with SessionFactory() as s:
        return (
            await s.execute(
                select(func.count()).select_from(QualityInspection).where(QualityInspection.project_id == project_id)
            )
        ).scalar_one()


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_punch_is_idempotent(app_and_client) -> None:
    """Replaying the same client_op_id creates exactly one punch, same result_id."""
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000001")

    op_id = str(uuid.uuid4())
    payload = {
        "client_op_id": op_id,
        "captured_at": "2026-06-05T09:00:00",
        "lat": 52.52,
        "lon": 13.405,
        "title": "Cracked tile in lobby",
        "priority": "high",
        "trade": "finishing",
    }

    r1 = await client.post("/v1/field-diary/capture/punch/", json=payload, headers=headers)
    assert r1.status_code == 201, r1.text
    first = r1.json()
    assert first["status"] == "applied"
    assert first["target_kind"] == "punch_item"
    assert first["result_id"]

    # Replay the identical op (the at-least-once drain firing twice).
    r2 = await client.post("/v1/field-diary/capture/punch/", json=payload, headers=headers)
    assert r2.status_code == 201, r2.text
    second = r2.json()

    # Same downstream id, and exactly ONE punch row in the project.
    assert second["result_id"] == first["result_id"]
    assert await _count_punch(SessionFactory, project_id) == 1

    # The persisted punch carries the geo pin + field-capture metadata.
    async with SessionFactory() as s:
        item = await s.get(PunchItem, uuid.UUID(first["result_id"]))
        assert item is not None
        assert item.project_id == project_id
        assert item.status == "open"
        assert item.geo_lat == pytest.approx(52.52)
        assert item.metadata_["field_capture"]["source"] == "field_pwa"


@pytest.mark.asyncio
async def test_capture_inspection_is_idempotent(app_and_client) -> None:
    """Replaying an inspection op creates one inspection with the geo pin."""
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000002")

    op_id = str(uuid.uuid4())
    payload = {
        "client_op_id": op_id,
        "captured_at": "2026-06-05T10:00:00",
        "lat": 48.137,
        "lon": 11.575,
        "inspection_type": "quality",
        "title": "Rebar spacing check, level 2",
        "location": "Block A / L2",
        "checklist_data": [{"question": "Spacing within tolerance?", "response": None, "critical": True}],
    }

    r1 = await client.post("/v1/field-diary/capture/inspection/", json=payload, headers=headers)
    assert r1.status_code == 201, r1.text
    first = r1.json()
    assert first["target_kind"] == "inspection"

    r2 = await client.post("/v1/field-diary/capture/inspection/", json=payload, headers=headers)
    assert r2.status_code == 201, r2.text
    assert r2.json()["result_id"] == first["result_id"]
    assert await _count_inspections(SessionFactory, project_id) == 1

    async with SessionFactory() as s:
        insp = await s.get(QualityInspection, uuid.UUID(first["result_id"]))
        assert insp is not None
        assert insp.status == "scheduled"
        assert insp.geo_lat == pytest.approx(48.137)
        assert insp.checklist_data and insp.checklist_data[0]["critical"] is True


@pytest.mark.asyncio
async def test_sync_batch_applies_and_dedups(app_and_client) -> None:
    """A batch applies several ops; an op already applied singly does not duplicate."""
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000003")

    op_a = str(uuid.uuid4())
    op_b = str(uuid.uuid4())

    # Apply op_a once via the single endpoint first.
    single = await client.post(
        "/v1/field-diary/capture/punch/",
        json={"client_op_id": op_a, "title": "Punch A", "priority": "low"},
        headers=headers,
    )
    assert single.status_code == 201
    a_id = single.json()["result_id"]

    # Now batch op_a (overlap) + op_b (new).
    batch = await client.post(
        "/v1/field-diary/sync/batch/",
        json={
            "ops": [
                {"client_op_id": op_a, "target_kind": "punch_item", "payload": {"title": "Punch A", "priority": "low"}},
                {
                    "client_op_id": op_b,
                    "target_kind": "punch_item",
                    "payload": {"title": "Punch B", "priority": "high"},
                },
            ]
        },
        headers=headers,
    )
    assert batch.status_code == 200, batch.text
    results = batch.json()
    assert len(results) == 2
    by_op = {r["client_op_id"]: r for r in results}
    # op_a returns the SAME id it got from the single apply (no duplicate).
    assert by_op[op_a]["result_id"] == a_id
    assert by_op[op_b]["result_id"] and by_op[op_b]["result_id"] != a_id

    # Two distinct punch rows total (A and B), not three.
    assert await _count_punch(SessionFactory, project_id) == 2

    # sync/ops lists the worker's applied ops.
    ops = await client.get("/v1/field-diary/sync/ops/", headers=headers)
    assert ops.status_code == 200, ops.text
    op_ids = {o["client_op_id"] for o in ops.json()}
    assert {op_a, op_b} <= op_ids


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_photo_capture_cross_project_is_404(app_and_client) -> None:
    """A photo capture targeting another project's punch resolves to 404 (IDOR)."""
    _app, client, SessionFactory = app_and_client
    project_a = await _seed_project(SessionFactory)
    project_b = await _seed_project(SessionFactory)
    headers_a = await _session_for(client, SessionFactory, project_a, "+491700000004")

    # Create a punch in project B directly (a different project's row).
    async with SessionFactory() as s:
        other = PunchItem(project_id=project_b, title="B punch", status="open", description="")
        s.add(other)
        await s.flush()
        other_id = other.id
        await s.commit()

    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    r = await client.post(
        "/v1/field-diary/capture/photo/",
        headers={**headers_a, "X-Punch-Item-Id": str(other_id), "X-Client-Op-Id": str(uuid.uuid4())},
        files={"file": ("p.jpg", jpeg, "image/jpeg")},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_capture_requires_pin(app_and_client) -> None:
    """A capture without the X-Field-PIN header is 401 (field session deps)."""
    _app, client, SessionFactory = app_and_client
    project_id = await _seed_project(SessionFactory)
    headers = await _session_for(client, SessionFactory, project_id, "+491700000005")

    r = await client.post(
        "/v1/field-diary/capture/punch/",
        json={"client_op_id": str(uuid.uuid4()), "title": "no pin"},
        headers={"Authorization": headers["Authorization"]},  # PIN omitted
    )
    assert r.status_code == 401
