# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design management against PostgreSQL: number allocation under load, releases into transmittals, scheme change."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.design_management.errors import DesignError
from app.modules.design_management.models import DesignDrawing, DesignNumberCounter
from app.modules.design_management.service import DesignService
from tests._pg import isolated_engine
from tests.pg.design_fixtures import DesignWorld, approved_release, build_design_world, drawing_with_revision

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    from app.modules.design_management import on_startup

    await on_startup()
    async with isolated_engine() as engine:
        yield await build_design_world(async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))


async def test_twenty_parallel_allocations_from_no_counter_row_are_distinct(world: DesignWorld) -> None:
    """Rule 5: the first use of a scope races on the INSERT; on-conflict plus row lock serialises it."""

    async def one() -> str:
        async with world.factory() as s:
            out = await DesignService(s).allocate_number(world.project_id, {"role_id": str(world.roles["ARCH"])})
            await s.commit()
            return out["number"]

    numbers = await asyncio.gather(*(one() for _ in range(20)))
    assert len(set(numbers)) == 20
    async with world.factory() as s:
        counters = (
            (await s.execute(select(DesignNumberCounter).where(DesignNumberCounter.project_id == world.project_id)))
            .scalars()
            .all()
        )
    assert [c.next_value for c in counters] == [21]


async def test_a_release_issues_one_transmittal_per_recipient_with_the_pinned_revisions(world: DesignWorld) -> None:
    from app.modules.transmittals.models import Transmittal

    _d1, rev_a = await drawing_with_revision(world, "ARCH")
    _d2, rev_s = await drawing_with_revision(world, "STRU")
    async with world.factory() as s:
        svc = DesignService(s)
        for role, discipline in (("ARCH", "A"), ("STRU", "S")):
            await svc.create_dist_rule(
                world.project_id,
                {"recipient_role_id": str(world.roles[role]), "discipline_codes": [discipline]},
                actor_id=world.manager,
            )
        await s.commit()
    rel_id = await approved_release(world, [rev_a, rev_s])
    async with world.factory() as s:
        issued = await DesignService(s).issue_release(world.project_id, rel_id, actor_id=world.manager)
        await s.commit()
    assert issued.status == "issued"
    assert len(issued.transmittal_ids) == 2
    by_recipient = {p["recipient_key"]: p["revision_ids"] for p in issued.issue_plan}
    assert by_recipient == {
        f"role:{world.roles['ARCH']}": [str(rev_a)],
        f"role:{world.roles['STRU']}": [str(rev_s)],
    }
    async with world.factory() as s:
        rows = (await s.execute(select(Transmittal).where(Transmittal.project_id == world.project_id))).scalars().all()
    assert len(rows) == 2


async def test_a_work_in_progress_revision_cannot_be_released(world: DesignWorld) -> None:
    _d, rev = await drawing_with_revision(world, "ARCH", suitability="S0")
    async with world.factory() as s:
        svc = DesignService(s)
        rel = await svc.create_release(world.project_id, {"revision_ids": [str(rev)]}, actor_id=world.editor)
        with pytest.raises(DesignError) as err:
            await svc.release_transition(world.project_id, rel.id, "ready", actor_id=world.editor)
    assert err.value.status_code == 422


async def test_a_deleted_drawings_number_is_never_handed_out_again(world: DesignWorld) -> None:
    """Rule 8: a number that was used stays used after its container is gone, typed or generated."""
    from app.modules.cde.models import DocumentContainer

    d, _rev = await drawing_with_revision(world, "ARCH")
    async with world.factory() as s:
        row = await s.get(DesignDrawing, d)
        container = await s.get(DocumentContainer, row.container_id)
        number = container.container_code
        await s.delete(container)
        await s.commit()
    async with world.factory() as s:
        svc = DesignService(s)
        with pytest.raises(DesignError) as typed:
            await svc.create_drawing(
                world.project_id, {"role_id": str(world.roles["ARCH"]), "number": number}, actor_id=world.editor
            )
        assert typed.value.code == "number_taken"
        await s.rollback()
        _fresh, _c = await svc.create_drawing(
            world.project_id, {"role_id": str(world.roles["ARCH"])}, actor_id=world.editor
        )
        await s.commit()
        assert _c.container_code != number


async def test_cde_refuses_a_reserved_number_on_a_container_made_outside_the_register(world: DesignWorld) -> None:
    from fastapi import HTTPException

    from app.modules.cde.models import DocumentContainer
    from app.modules.cde.schemas import ContainerCreate
    from app.modules.cde.service import CDEService

    d, _rev = await drawing_with_revision(world, "ARCH")
    async with world.factory() as s:
        container = await s.get(DocumentContainer, (await s.get(DesignDrawing, d)).container_id)
        number = container.container_code
        await s.delete(container)
        await s.commit()
    async with world.factory() as s:
        with pytest.raises(HTTPException) as exc:
            await CDEService(s).create_container(
                ContainerCreate(project_id=world.project_id, container_code=number, title="x", cde_state="wip"),
                user_id=str(world.editor),
            )
    assert any(v["code"] == "number_reserved" for v in exc.value.detail["violations"])


async def test_a_scheme_change_keeps_numbers_and_flags_them_legacy(world: DesignWorld) -> None:
    """Rule 9: no silent renumbering; numbers that miss the new scheme are flagged."""
    d, _rev = await drawing_with_revision(world, "ARCH")
    async with world.factory() as s:
        out = await DesignService(s).change_scheme(
            world.project_id,
            actor_id=world.manager,
            tenant_id=str(world.manager),
            source="shipped",
            scheme_id="iso19650_generic",
        )
        await s.commit()
    assert out["legacy"] == 1
    async with world.factory() as s:
        row = await s.get(DesignDrawing, d)
    assert row.legacy_scheme is True
