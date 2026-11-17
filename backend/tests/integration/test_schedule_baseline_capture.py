"""Capture B0, edit the plan, capture B1, approve it, print the Gantt: over HTTP on PostgreSQL.

Only authentication is supplied by the fixture; routes, ownership checks and
SQL run normally in a rollback-isolated database.
"""

from __future__ import annotations

import io
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pypdf
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.dependencies import get_current_user_payload, get_session
from app.modules.projects.models import Project
from app.modules.schedule import router as schedule_router
from app.modules.schedule import service as schedule_service
from app.modules.schedule.models import Activity, ScheduleBaseline
from app.modules.schedule.permissions import register_schedule_permissions
from app.modules.schedule.schemas import ScheduleCreate
from app.modules.schedule.service import ScheduleService
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    register_schedule_permissions()
    monkeypatch.setattr(schedule_service, "_safe_publish", AsyncMock())
    monkeypatch.setattr(schedule_service, "publish_after_commit", lambda *_a, **_k: None)


@asynccontextmanager
async def api():
    async with transactional_session() as session:
        user = User(
            email=f"bl-{uuid.uuid4()}@example.test",
            full_name="Planner",
            hashed_password="x",
            role="editor",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        project = Project(name="Riverside Clinic", owner_id=user.id)
        session.add(project)
        await session.flush()
        service = ScheduleService(session)
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=project.id, name="Contract programme", start_date="2026-01-05")
        )
        payload = {"sub": str(user.id), "role": "editor", "permissions": []}
        app = FastAPI()
        app.include_router(schedule_router.router, prefix="/schedule")

        async def current_session():
            yield session

        app.dependency_overrides[get_session] = current_session
        app.dependency_overrides[get_current_user_payload] = lambda: payload
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session, schedule


@pytest.mark.asyncio
async def test_capture_approve_and_print_without_touching_the_earlier_baseline():
    async with api() as (client, session, schedule):
        base = f"/schedule/schedules/{schedule.id}"
        empty = await client.post(f"{base}/baselines/capture", json={})
        assert empty.status_code == 422, empty.text

        act = Activity(
            schedule_id=schedule.id, name="Excavation", wbs_code="1.1", start_date="2026-01-05", end_date="2026-01-23"
        )
        session.add(act)
        await session.flush()

        b0 = await client.post(f"{base}/baselines/capture", json={"approve": True, "note": "Contract award"})
        assert b0.status_code == 201, b0.text
        b0 = b0.json()
        assert b0["name"] == "B0" and b0["is_active"] is True
        # The response keeps the existing ``metadata_`` key of BaselineResponse.
        assert b0["metadata_"]["approval"]["approved_by"]
        assert b0["snapshot_data"]["activities"][0]["end_date"] == "2026-01-23"
        b0_snapshot = b0["snapshot_data"]

        act.end_date = "2026-01-30"
        await session.flush()
        b1 = (await client.post(f"{base}/baselines/capture", json={})).json()
        assert b1["name"] == "B1" and b1["is_active"] is False

        approved = await client.post(f"{base}/baselines/{b1['id']}/approve")
        assert approved.status_code == 200, approved.text
        rows = {
            str(b.id): b
            for b in (
                await session.execute(select(ScheduleBaseline).where(ScheduleBaseline.schedule_id == schedule.id))
            )
            .scalars()
            .all()
        }
        assert rows[b1["id"]].is_active is True
        assert rows[b0["id"]].is_active is False
        assert rows[b0["id"]].snapshot_data == b0_snapshot

        pdf = await client.get(f"{base}/gantt.pdf", params={"paper": "A4"})
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["content-language"] == "en"
        text = "".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf.content)).pages)
        assert "Riverside Clinic" in text and "Excavation" in text and "B1" in text

        german = await client.get(f"{base}/gantt.pdf", params={"locale": "de", "baseline_id": b0["id"]})
        assert german.headers["content-language"] == "de"


@pytest.mark.asyncio
@pytest.mark.tenant_isolation
async def test_a_baseline_of_another_schedule_cannot_be_approved_here():
    async with api() as (client, session, schedule):
        other = await ScheduleService(session).create_schedule(
            ScheduleCreate(project_id=schedule.project_id, name="Client programme")
        )
        session.add(Activity(schedule_id=other.id, name="Piling", start_date="2026-02-02", end_date="2026-02-06"))
        await session.flush()
        foreign = (await client.post(f"/schedule/schedules/{other.id}/baselines/capture", json={})).json()
        response = await client.post(f"/schedule/schedules/{schedule.id}/baselines/{foreign['id']}/approve")
        assert response.status_code == 404
