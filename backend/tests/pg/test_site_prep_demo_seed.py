# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The site prep demo seed must fill the register, attach it, and fill it once.

Site prep shipped complete and unseeded, so the readiness rollup, the category
breakdown and the commencement gate all opened empty on every project. The
seeder that fixes that has four ways to be wrong that a green exit code cannot
show, so each is pinned here against a real database:

* it writes rows the module itself would refuse. Every row goes through
  ``SitePrepService`` with a real ``SitePrepItemCreate``, but the seeder holds
  each project in its own SAVEPOINT and logs the failure rather than raising -
  which is right for a boot-time seeder and means a rejected row shows up here
  as an empty register, not as an exception. So the counts are asserted, not
  just the absence of an error.
* it writes items that belong to no plan. An unattached item still renders in
  the list and still counts in the rollup, so nothing looks broken; what breaks
  is the countdown, because the target start date lives on the plan.
* it doubles the register on the second boot, because idempotency in this
  codebase is per loop rather than per seeder.
* it produces a register the readiness engine cannot say anything interesting
  about - every project identical, no gate ever blocking, nothing ever overdue.

The last one is asserted through ``get_readiness`` and ``get_gate_status``
themselves rather than by restating their rules, so a change to what counts as
ready, blocked or overdue fails here.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.projects.models import Project
from app.modules.site_prep.models import SitePrepItem, SitePrepPlan
from app.modules.site_prep.seed import seed_site_prep_demo
from app.modules.site_prep.service import SitePrepService
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

# Five, so every stage in the seeder's rotation is exercised at least once.
_PROJECT_COUNT = 5


async def _make_project(session, name: str) -> uuid.UUID:
    """A project and its owner. Site prep needs nothing else on the project."""
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.lower()}@example.test",
            hashed_password="x",
            full_name=f"{name} Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    # Flushed on its own: the project's owner FK has no ORM relationship behind
    # it, so nothing orders the two inserts for us.
    await session.flush()
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Site prep seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()
    return project_id


async def _seeded(session) -> list[uuid.UUID]:
    """Seed a handful of projects and return their ids in seeding order."""
    ids = [await _make_project(session, f"SitePrep{i}") for i in range(_PROJECT_COUNT)]
    totals = await seed_site_prep_demo(session, ids)
    # The seeder swallows a per-project failure by design, so an empty register
    # is what a refused row looks like from here. Assert it wrote something
    # before asserting anything about what it wrote.
    assert totals["projects"] == _PROJECT_COUNT, totals
    assert totals["plans"] == _PROJECT_COUNT, totals
    assert totals["items"] > 0, totals
    assert totals["gates"] > 0, totals
    return ids


async def test_every_item_hangs_off_its_own_projects_plan(pg_session) -> None:
    """No orphan items, and no item pointing at another project's plan."""
    ids = await _seeded(pg_session)

    for project_id in ids:
        plan = (
            (await pg_session.execute(select(SitePrepPlan).where(SitePrepPlan.project_id == project_id)))
            .scalars()
            .one()
        )
        assert plan.target_start_date is not None, "the register has nothing to count down to"

        items = (
            (await pg_session.execute(select(SitePrepItem).where(SitePrepItem.project_id == project_id)))
            .scalars()
            .all()
        )
        assert items, f"project {project_id} got a plan and no items"
        assert all(item.plan_id == plan.id for item in items), "an item is not attached to its project's plan"

    # And nothing anywhere is attached to a plan belonging to a different
    # project, which a per-project loop cannot see.
    crossed = (
        await pg_session.execute(
            select(func.count())
            .select_from(SitePrepItem)
            .join(SitePrepPlan, SitePrepPlan.id == SitePrepItem.plan_id)
            .where(SitePrepPlan.project_id != SitePrepItem.project_id)
        )
    ).scalar_one()
    assert crossed == 0


async def test_the_readiness_engine_answers_from_the_seeded_register(pg_session) -> None:
    """The rollup and the gate say something, and say it about real items."""
    ids = await _seeded(pg_session)
    service = SitePrepService(pg_session)

    reports = [await service.get_readiness(pid) for pid in ids]
    gates = [await service.get_gate_status(pid) for pid in ids]

    # A register the engine can actually work on: applicable items, a percentage
    # that is defined, and a denominator the not-applicable items have moved.
    assert all(r["applicable_items"] > 0 for r in reports)
    assert all(r["readiness_percent"] is not None for r in reports)
    assert any(r["applicable_items"] < r["total_items"] for r in reports), "nothing was marked not applicable"

    # The estate has to show both answers, or the gate screen never demonstrates
    # the thing it exists for.
    assert any(g["gate_ready"] for g in gates), "no project ever closes its gates"
    assert any(not g["gate_ready"] for g in gates), "no project ever has a gate still open"

    # Overdue is derived from dates, not seeded as a status, so it has to appear
    # somewhere without any item ever being given an "overdue" state.
    assert any(r["overdue"] for r in (rep["overall"] for rep in reports)), "nothing is ever late"

    # Whatever the gate reports as blocking must be a real gate item that is
    # genuinely unresolved - a list built from something else would still render.
    for project_id, gate in zip(ids, gates, strict=True):
        for ref in gate["gate_blocking"]:
            item = (
                (
                    await pg_session.execute(
                        select(SitePrepItem).where(
                            SitePrepItem.project_id == project_id,
                            SitePrepItem.id == uuid.UUID(ref["item_id"]),
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert item.is_gate is True
            assert item.status not in ("ready", "not_applicable")


async def test_a_second_pass_adds_nothing(pg_session) -> None:
    """Re-running the seeder must not double the register."""
    ids = await _seeded(pg_session)

    def _count(model):
        return pg_session.execute(select(func.count()).select_from(model))

    plans_before = (await _count(SitePrepPlan)).scalar_one()
    items_before = (await _count(SitePrepItem)).scalar_one()

    again = await seed_site_prep_demo(pg_session, ids)
    assert again == {"projects": 0, "plans": 0, "items": 0, "gates": 0}

    assert (await _count(SitePrepPlan)).scalar_one() == plans_before
    assert (await _count(SitePrepItem)).scalar_one() == items_before


async def test_no_two_projects_show_the_same_register(pg_session) -> None:
    """Two demo projects must not open on the same picture."""
    ids = await _seeded(pg_session)
    service = SitePrepService(pg_session)

    fingerprints = []
    for project_id in ids:
        report = await service.get_readiness(project_id)
        fingerprints.append(
            (
                report["target_start_date"],
                report["ready_items"],
                report["overall"]["blocked"],
                report["overall"]["overdue"],
                report["gate_ready"],
            )
        )

    assert len(set(fingerprints)) == len(fingerprints), f"two projects render identically: {fingerprints}"
