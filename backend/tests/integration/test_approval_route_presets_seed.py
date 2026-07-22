# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for the approval-route preset seed (DB-backed).

Confirms the startup seed creates the tenant-wide presets with their steps and
is idempotent: a second run inserts nothing and the table still holds exactly
one route per stable key.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approval_routes.models import Route, Step
from app.modules.approval_routes.seed import PRESETS, seed_approval_route_presets
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _preset_route_count(session: AsyncSession) -> int:
    return (
        await session.execute(select(func.count()).select_from(Route).where(Route.system_key.isnot(None)))
    ).scalar_one()


async def test_seed_creates_all_presets_with_steps(session: AsyncSession) -> None:
    counts = await seed_approval_route_presets(session)
    assert counts["routes_created"] == len(PRESETS)

    rows = (await session.execute(select(Route).where(Route.system_key.isnot(None)))).scalars().all()
    assert {r.system_key for r in rows} == {p.system_key for p in PRESETS}

    for r in rows:
        # Tenant-wide, active, and carrying its declared steps.
        assert r.project_id is None
        assert r.is_active is True
        spec = next(p for p in PRESETS if p.system_key == r.system_key)
        steps = (
            (await session.execute(select(Step).where(Step.route_id == r.id).order_by(Step.ordinal))).scalars().all()
        )
        assert [s.ordinal for s in steps] == [s.ordinal for s in spec.steps]
        assert [s.approver_role for s in steps] == [s.approver_role for s in spec.steps]


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    first = await seed_approval_route_presets(session)
    assert first["routes_created"] == len(PRESETS)

    second = await seed_approval_route_presets(session)
    assert second["routes_created"] == 0

    # Exactly one route per stable key, no duplicates from the second run.
    assert await _preset_route_count(session) == len(PRESETS)
