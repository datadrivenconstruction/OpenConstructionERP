# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board API on real PostgreSQL: board, conflicts, scheduled moves, copy, plan, prefill, utilisation."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.dispatch.permissions import register_dispatch_permissions
from app.modules.dispatch.router import router as dispatch_router
from app.modules.dispatch.validators import register_dispatch_validation_rules
from app.modules.equipment.models import Equipment, MaintenanceWorkOrder
from app.modules.field_time.models import FieldTimesheet
from app.modules.projects.models import Project
from app.modules.resources.models import AvailabilityWindow, Resource
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

TODAY = datetime.now(UTC).date()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_dispatch_permissions()
    register_dispatch_validation_rules()
    async with transactional_session() as s:
        yield s


def _app(session, caller: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(dispatch_router, prefix="/v1/dispatch")

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


async def _setup(session):
    tag = uuid.uuid4().hex[:6]
    user = User(email=f"disp-{tag}@example.com", hashed_password="x", role="admin")
    session.add(user)
    await session.flush()
    project = Project(name="Dispatch test", owner_id=user.id, currency="EUR")
    w1 = Resource(code=f"W1-{tag}", name="Anna Mason", resource_type="person")
    w2 = Resource(code=f"W2-{tag}", name="Ben Fixer", resource_type="person")
    w3 = Resource(code=f"W3-{tag}", name="Carl Op", resource_type="person")
    ex = Equipment(code=f"EX-{tag}", name="Excavator", metadata_={"required_certificates": ["excavator"]})
    session.add_all([project, w1, w2, w3, ex])
    await session.flush()
    await session.commit()
    return user.id, project.id, w1, w2, w3, ex


async def _loc(c, name, kind="project", project_id=None) -> str:
    body = {"name": name, "kind": kind}
    if project_id:
        body["project_id"] = str(project_id)
    r = await c.post("/v1/dispatch/locations", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_board_conflicts_and_validation(db_session):
    uid, project, w1, w2, w3, ex = await _setup(db_session)
    db_session.add(MaintenanceWorkOrder(equipment_id=ex.id, scheduled_for=TODAY.isoformat(), status="scheduled"))
    db_session.add(
        AvailabilityWindow(
            resource_id=w2.id,
            window_type="holiday",
            start_at=datetime.now(UTC) - timedelta(hours=1),
            end_at=datetime.now(UTC) + timedelta(hours=2),
        )
    )
    await db_session.commit()
    async with _http(_app(db_session, uid)) as c:
        site = await _loc(c, "Site A", project_id=project)
        site_b = await _loc(c, "Site B", project_id=project)
        r = await c.post(
            "/v1/dispatch/crews", json={"name": "Gang 1", "member_ids": [str(w1.id), str(w2.id)], "min_size": 2}
        )
        crew = r.json()["id"]
        day = TODAY.isoformat()
        r = await c.post(
            "/v1/dispatch/placements",
            json={
                "day": day,
                "location_id": site,
                "cards": [{"card_kind": "crew", "card_ref": crew}, {"card_kind": "equipment", "card_ref": str(ex.id)}],
                "operator_ref": str(w3.id),
            },
        )
        assert r.json()["created"] == 2, r.text
        await c.post(
            "/v1/dispatch/placements",
            json={"day": day, "location_id": site_b, "cards": [{"card_kind": "worker", "card_ref": str(w1.id)}]},
        )
        board = (await c.get(f"/v1/dispatch/board?day={day}")).json()
        kinds = {x["kind"] for x in board["conflicts"]}
        assert {
            "double_booked",
            "maintenance_block",
            "missing_certificate",
            "worker_absent",
            "crew_under_minimum",
        } <= kinds
        unit = next(p for p in board["placements"] if p["card_kind"] == "equipment")
        assert unit["status"] == "maintenance"
        crew_card = next(p for p in board["placements"] if p["card_kind"] == "crew")
        assert [m["name"] for m in crew_card["members"]] == ["Anna Mason", "Ben Fixer"]

        v = (await c.get(f"/v1/dispatch/validate?day={day}")).json()
        assert v["status"] == "errors"
        assert "dispatch.no_double_booking" in {x["rule_id"] for x in v["results"]}


async def test_scheduled_move_applies_on_its_day_and_copy_yesterday(db_session):
    uid, project, w1, _w2, _w3, _ex = await _setup(db_session)
    async with _http(_app(db_session, uid)) as c:
        site = await _loc(c, "Site A", project_id=project)
        yard = await _loc(c, "Yard", kind="yard")
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        await c.post(
            "/v1/dispatch/placements",
            json={"day": yesterday, "location_id": site, "cards": [{"card_kind": "worker", "card_ref": str(w1.id)}]},
        )
        r = await c.post("/v1/dispatch/copy-day", json={"from_day": yesterday, "to_day": TODAY.isoformat()})
        assert r.json()["copied"] == 1
        r = await c.post("/v1/dispatch/copy-day", json={"from_day": yesterday, "to_day": TODAY.isoformat()})
        assert r.json()["copied"] == 0

        r = await c.post(
            "/v1/dispatch/moves",
            json={
                "card_kind": "worker",
                "card_ref": str(w1.id),
                "to_location_id": yard,
                "effective_date": TODAY.isoformat(),
            },
        )
        assert r.status_code == 201, r.text
        board = (await c.get(f"/v1/dispatch/board?day={TODAY.isoformat()}")).json()
        assert board["applied_moves"] == 1
        assert [p["location_id"] for p in board["placements"]] == [yard]
        assert board["placements"][0]["source"] == "scheduled"
        again = (await c.get(f"/v1/dispatch/board?day={TODAY.isoformat()}")).json()
        assert again["applied_moves"] == 0
        assert len(again["placements"]) == 1

        r = await c.post(
            "/v1/dispatch/moves",
            json={
                "card_kind": "worker",
                "card_ref": str(w1.id),
                "to_location_id": yard,
                "effective_date": yesterday,
            },
        )
        assert r.status_code == 422


async def test_timesheet_prefill_plan_and_utilisation(db_session):
    uid, project, w1, w2, w3, ex = await _setup(db_session)
    async with _http(_app(db_session, uid)) as c:
        site = await _loc(c, "Site A", project_id=project)
        crew = (
            await c.post(
                "/v1/dispatch/crews",
                json={
                    "name": "Gang 1",
                    "member_ids": [str(w1.id), str(w2.id)],
                    "foreman_resource_id": str(w1.id),
                    "foreman_user_id": str(uid),
                },
            )
        ).json()["id"]
        day = TODAY.isoformat()
        await c.post(
            "/v1/dispatch/placements",
            json={
                "day": day,
                "location_id": site,
                "start_time": "06:30",
                "cards": [{"card_kind": "crew", "card_ref": crew}, {"card_kind": "equipment", "card_ref": str(ex.id)}],
            },
        )
        r = await c.post("/v1/dispatch/timesheet-prefill", json={"location_id": site, "day": day, "hours": "8"})
        assert r.status_code == 200, r.text
        first = r.json()
        assert first["created"] is True
        assert first["lines_added"] == 3
        sheet = (
            await db_session.execute(
                select(FieldTimesheet).where(FieldTimesheet.id == uuid.UUID(first["timesheet_id"]))
            )
        ).scalar_one()
        assert {str(ln.resource_id) for ln in sheet.lines if ln.resource_id} == {str(w1.id), str(w2.id)}

        await c.post(
            "/v1/dispatch/placements",
            json={"day": day, "location_id": site, "cards": [{"card_kind": "worker", "card_ref": str(w3.id)}]},
        )
        second = (
            await c.post("/v1/dispatch/timesheet-prefill", json={"location_id": site, "day": day, "hours": "8"})
        ).json()
        assert second["created"] is False
        assert second["timesheet_id"] == first["timesheet_id"]
        assert second["lines_added"] == 1

        plan = (await c.get(f"/v1/dispatch/plan?day={day}")).json()
        assert plan["plans"][0]["foreman"] == "Anna Mason"
        assert plan["plans"][0]["lines"][0]["start_time"] == "06:30"
        pdf = await c.get(f"/v1/dispatch/plan/pdf?day={day}")
        assert pdf.status_code == 200
        assert pdf.content[:4] == b"%PDF"
        share = (await c.post(f"/v1/dispatch/plan/share?day={day}")).json()
        assert share["notified"] == 1

        util = (await c.get(f"/v1/dispatch/utilisation?start={day}&end={day}")).json()
        row = next(x for x in util["items"] if x["unit_ref"] == str(ex.id))
        assert row["days_assigned"] == (1 if TODAY.weekday() < 5 else 0)

        r = await c.put("/v1/dispatch/preferences", json={"card_density": "compact"})
        assert r.status_code == 200
        assert (await c.get("/v1/dispatch/preferences")).json()["card_density"] == "compact"
