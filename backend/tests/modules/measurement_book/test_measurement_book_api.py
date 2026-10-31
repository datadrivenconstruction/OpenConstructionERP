# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book API on real PostgreSQL: entries, check, running bill, progress hand-off, rules."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.boq.models import BOQ, Position
from app.modules.measurement_book.router import router as mb_router
from app.modules.measurement_book.validators import register_measurement_book_rules
from app.modules.progress.models import ProgressEntry
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

BASE = "/v1/measurement-book"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_measurement_book_rules()
    async with transactional_session() as s:
        yield s


async def _setup(session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user = User(email=f"mb-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
    session.add(user)
    await session.flush()
    project = Project(name="Measurement book test", owner_id=user.id, currency="PKR")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Main")
    session.add(boq)
    await session.flush()
    pos = Position(
        boq_id=boq.id,
        ordinal="02.010",
        description="Brick masonry",
        unit="m3",
        quantity="10",
        unit_rate="1500",
        total="15000",
    )
    session.add(pos)
    await session.flush()
    return user.id, project.id, pos.id


def _app(session, caller: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(mb_router, prefix=BASE)

    async def _session():
        yield session

    async def _uid() -> str:
        return str(caller)

    async def _payload() -> dict:
        return {"sub": str(caller), "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _uid
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_entries_check_running_bill_and_progress(db_session) -> None:
    uid, pid, pos = await _setup(db_session)
    async with _http(_app(db_session, uid)) as c:
        a = await c.post(
            f"{BASE}/entries/",
            json={
                "project_id": str(pid),
                "boq_position_id": str(pos),
                "entry_date": "2026-10-01",
                "location": "Ground floor, grid A-C",
                "length": "10",
                "breadth": "0.23",
                "height": "3",
                "number": "1",
                "measured_by": "Site engineer",
            },
        )
        assert a.status_code == 201, a.text
        assert a.json()["quantity"] == "6.9000"
        b = await c.post(
            f"{BASE}/entries/",
            json={
                "project_id": str(pid),
                "boq_position_id": str(pos),
                "entry_date": "2026-10-08",
                "direct_quantity": "5",
            },
        )
        assert b.status_code == 201, b.text

        # Over the BOQ quantity and unchecked: warning plus a blocking error.
        v = (await c.get(f"{BASE}/validation/", params={"project_id": str(pid)})).json()
        ids = {r["rule_id"] for r in v["results"]}
        assert {"measurement_book.measured_within_boq", "measurement_book.checked_before_certification"} <= ids
        assert v["status"] == "errors"

        blocked = await c.post(
            f"{BASE}/running-bill/post-to-progress", params={"project_id": str(pid)}, json={"period_label": "2026-10"}
        )
        assert blocked.status_code == 409

        ok = await c.post(f"{BASE}/entries/{a.json()['id']}/check", json={"status": "checked", "check_quantity": "6.5"})
        assert ok.status_code == 200, ok.text
        assert (await c.delete(f"{BASE}/entries/{a.json()['id']}")).status_code == 409
        await c.post(f"{BASE}/entries/{b.json()['id']}/check", json={"status": "checked"})

        v = (await c.get(f"{BASE}/validation/", params={"project_id": str(pid), "deviation_threshold_pct": "2"})).json()
        assert "measurement_book.check_deviation" in {r["rule_id"] for r in v["results"]}

        bill = (await c.get(f"{BASE}/running-bill/", params={"project_id": str(pid)})).json()
        assert bill["can_certify"] is True
        assert bill["currency"] == "PKR"
        assert bill["lines"][0]["checked_quantity"] == "11.5000"
        assert bill["total_value"] == "17250.00"

        posted = await c.post(
            f"{BASE}/running-bill/post-to-progress", params={"project_id": str(pid)}, json={"period_label": "2026-10"}
        )
        assert posted.status_code == 200, posted.text
        assert posted.json() == {"recorded": 1, "skipped": 0}
    progress = (
        (await db_session.execute(select(ProgressEntry).where(ProgressEntry.boq_position_id == pos))).scalars().all()
    )
    assert len(progress) == 1
    assert float(progress[0].percent_complete) == 100.0
    assert progress[0].metadata_["source"] == "measurement_book"


async def test_position_from_another_project_is_refused(db_session) -> None:
    uid, pid, _pos = await _setup(db_session)
    _uid2, _pid2, foreign = await _setup(db_session)
    async with _http(_app(db_session, uid)) as c:
        r = await c.post(
            f"{BASE}/entries/",
            json={"project_id": str(pid), "boq_position_id": str(foreign), "entry_date": "2026-10-01", "length": "1"},
        )
    assert r.status_code == 422
