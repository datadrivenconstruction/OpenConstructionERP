# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Manual bar bending schedule API on real PostgreSQL: entry, totals, rules, CSV."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.rebar_schedule.bbs_validators import register_bbs_rules
from app.modules.rebar_schedule.router import router as rebar_router
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

BASE = "/v1/rebar-schedule"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_bbs_rules()
    async with transactional_session() as s:
        yield s


def _app(session, caller: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(rebar_router, prefix=BASE)

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


async def test_manual_schedule_totals_rules_and_csv(db_session) -> None:
    user = User(email=f"bbs-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
    db_session.add(user)
    await db_session.flush()
    project = Project(name="BBS test", owner_id=user.id, currency="PKR")
    db_session.add(project)
    await db_session.flush()
    boq = BOQ(project_id=project.id, name="Main")
    db_session.add(boq)
    await db_session.flush()
    steel = Position(boq_id=boq.id, ordinal="05.010", description="Reinforcement", unit="kg", quantity="200")
    db_session.add(steel)
    await db_session.flush()

    async with _http(_app(db_session, user.id)) as c:
        codes = (await c.get(f"{BASE}/shape-codes/")).json()
        assert any(s["standard"] == "IS2502" and s["code"] == "F" for s in codes)

        base = {"project_id": str(project.id), "shape_standard": "BS8666", "boq_position_id": str(steel.id)}
        r = await c.post(
            f"{BASE}/bbs/",
            json={
                **base,
                "member": "Beam B1",
                "bar_mark": "01",
                "diameter_mm": "12",
                "shape_code": "00",
                "dim_a": "6000",
                "members_count": 4,
                "bars_per_member": 10,
                "lap_length_mm": "400",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["weight_kg"] == "213.336"

        missing = await c.post(
            f"{BASE}/bbs/",
            json={
                **base,
                "member": "Beam B1",
                "bar_mark": "02",
                "diameter_mm": "10",
                "shape_code": "21",
                "dim_a": "300",
            },
        )
        assert missing.status_code == 422

        dup = await c.post(
            f"{BASE}/bbs/",
            json={**base, "member": "Beam B1", "bar_mark": "01", "diameter_mm": "12", "shape_code": "00", "dim_a": "1"},
        )
        assert dup.status_code == 409

    async with _http(_app(db_session, user.id)) as c:
        schedule = (await c.get(f"{BASE}/bbs/", params={"project_id": str(project.id)})).json()
        assert schedule["totals_by_diameter"][0]["bar_count"] == 40
        assert schedule["total_weight_kg"] == "213.336"

        v = (await c.get(f"{BASE}/bbs/validation/", params={"project_id": str(project.id)})).json()
        ids = {x["rule_id"] for x in v["results"]}
        # 400 mm lap is under 50 x 12 = 600; 213 kg against 200 kg is 6.7 percent over 5.
        assert ids == {"bar_bending_schedule.lap_length_min", "bar_bending_schedule.total_vs_boq"}

        csv = await c.get(f"{BASE}/bbs/export.csv", params={"project_id": str(project.id)})
        assert csv.status_code == 200
        assert "Beam B1,01,BS8666,00,12" in csv.text
