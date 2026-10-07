# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule HTTP authorship cannot be supplied by the client."""

import uuid

import pytest

from app.modules.schedule.models import Schedule
from app.modules.schedule.schemas import ScheduleCreate
from app.modules.users.models import User
from tests.integration.test_schedule_archive_lifecycle import api, published  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.tenant_isolation
@pytest.mark.parametrize("submitted_author", ["omitted", "null", "other_user"])
async def test_schedule_author_is_authenticated_user(submitted_author):
    async with api() as (client, session, _service, _schedule, project, payload):
        body = {"project_id": str(project.id), "name": "Authenticated author programme"}
        if submitted_author == "null":
            body["created_by"] = None
        elif submitted_author == "other_user":
            other = User(
                email=f"schedule-author-{uuid.uuid4()}@example.test",
                full_name="Other author",
                hashed_password="x",
                role="editor",
            )
            session.add(other)
            await session.flush()
            body["created_by"] = str(other.id)
        response = await client.post("/schedule/schedules/", json=body)
        assert response.status_code == 201, response.text
        assert response.json()["created_by"] == payload["sub"]
        schedule_id = response.json()["id"]
        fetched = await client.get(f"/schedule/schedules/{schedule_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["created_by"] == payload["sub"]
        row = await session.get(Schedule, uuid.UUID(schedule_id))
        assert row.created_by == uuid.UUID(payload["sub"])
        assert row.project_id == project.id


@pytest.mark.asyncio
async def test_internal_schedule_creation_preserves_explicit_author():
    async with api() as (_client, session, service, _schedule, project, _payload):
        historical = User(
            email=f"historical-author-{uuid.uuid4()}@example.test",
            full_name="Historical author",
            hashed_password="x",
            role="editor",
        )
        session.add(historical)
        await session.flush()
        row = await service.create_schedule(
            ScheduleCreate(project_id=project.id, name="Imported programme", created_by=historical.id)
        )
        assert row.created_by == historical.id
