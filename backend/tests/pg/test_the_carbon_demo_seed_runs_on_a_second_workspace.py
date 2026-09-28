# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The carbon demo seed has to run again once its projects are gone.

The seed writes a shared EPD library (``epd_id`` is unique) and then one set of
inventories per project. Enrichment decides whether to run it by counting
inventories, so after a pack switch deletes the previous pack's demo projects
the count is zero again, the seed runs, and re-inserting the library it already
wrote violates the unique index. Enrichment logs "carbon demo seed skipped" and
the new pack's projects open with an empty carbon register.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.carbon.models import CarbonInventory, EPDRecord, MaterialCarbonFactor
from app.modules.carbon.seed import seed_carbon_demo
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _count(session, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)
    return (await session.execute(stmt)).scalar_one()


async def _project_id(session) -> uuid.UUID:
    owner = User(email=f"carbon-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Owner")
    session.add(owner)
    await session.flush()
    project = Project(name="Carbon demo", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id


async def test_a_second_run_reuses_the_library_and_seeds_its_own_projects(pg_session) -> None:
    first, second = await _project_id(pg_session), await _project_id(pg_session)

    await seed_carbon_demo(pg_session, [first])
    library = await _count(pg_session, EPDRecord)
    factors = await _count(pg_session, MaterialCarbonFactor)
    assert library > 0 and factors > 0

    # A pack switch deletes the first project and its inventories, which is
    # what lets enrichment run the seed again; the shared library stays. The
    # first project's rows staying here changes nothing the seed reads.
    counts = await seed_carbon_demo(pg_session, [second])

    assert counts["inventories"] > 0
    assert await _count(pg_session, CarbonInventory, CarbonInventory.project_id == second) > 0
    assert await _count(pg_session, EPDRecord) == library, "the second run wrote the EPD library again"
    assert await _count(pg_session, MaterialCarbonFactor) == factors, "the second run wrote the factors again"
