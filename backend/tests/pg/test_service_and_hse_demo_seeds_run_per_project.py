# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The service and HSE demo seeds guard per project, not per table.

A demo project installed after the first boot (for example a full showcase
installed on demand) must still get its contracts and safety records, and a
second run for a project that already has them must add nothing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.hse_advanced.models import JobSafetyAnalysis, PermitToWork, ToolboxTalk, ToolboxTopic
from app.modules.hse_advanced.seed import seed_hse_advanced_demo
from app.modules.projects.models import Project
from app.modules.service.models import ServiceContract, SLADefinition
from app.modules.service.seed import seed_service_demo
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _count(session, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)
    return (await session.execute(stmt)).scalar_one()


async def _project_id(session) -> uuid.UUID:
    owner = User(email=f"seed-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Owner")
    session.add(owner)
    await session.flush()
    project = Project(name="Demo", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id


async def test_service_seed_covers_a_project_installed_later(pg_session) -> None:
    first, second = await _project_id(pg_session), await _project_id(pg_session)

    await seed_service_demo(pg_session, [first])
    tiers = await _count(pg_session, SLADefinition)
    assert await _count(pg_session, ServiceContract, ServiceContract.project_id == first) == 1

    await seed_service_demo(pg_session, [second])
    assert await _count(pg_session, ServiceContract, ServiceContract.project_id == second) == 1
    assert await _count(pg_session, SLADefinition) == tiers

    total = await _count(pg_session, ServiceContract)
    counts = await seed_service_demo(pg_session, [first, second])
    assert counts["contracts"] == 0
    assert await _count(pg_session, ServiceContract) == total


async def test_hse_seed_covers_a_project_installed_later(pg_session) -> None:
    first, second = await _project_id(pg_session), await _project_id(pg_session)

    await seed_hse_advanced_demo(pg_session, [first])
    topics = await _count(pg_session, ToolboxTopic)
    assert await _count(pg_session, JobSafetyAnalysis, JobSafetyAnalysis.project_id == first) > 0

    await seed_hse_advanced_demo(pg_session, [second])
    assert await _count(pg_session, JobSafetyAnalysis, JobSafetyAnalysis.project_id == second) > 0
    assert await _count(pg_session, PermitToWork, PermitToWork.project_id == second) > 0
    assert await _count(pg_session, ToolboxTalk, ToolboxTalk.project_id == second) > 0
    assert await _count(pg_session, ToolboxTopic) == topics

    total = await _count(pg_session, JobSafetyAnalysis)
    await seed_hse_advanced_demo(pg_session, [first, second])
    assert await _count(pg_session, JobSafetyAnalysis) == total
