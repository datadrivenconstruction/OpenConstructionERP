# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Demo data belongs to demo projects, and a demo the user removed stays removed.

A self-hosted install reported three things after deleting the demo projects:
the deleted projects kept showing up on the dashboard and answered "Project not
found" when opened, and every restart wrote demo records - a daily diary, bid
packages, service contracts, quality plans with inspections and NCRs, site
photos, a team roster - into the real projects the user had created since.

The seeding ran over every project in the database. Each seeder asked "does
this project already hold rows of my kind", and a real project that has not
reached that module yet answers no, so the first boot after an upgrade is the
one that writes into it. Nothing marks those rows afterwards: the quality plan
the seed writes into a live project is indistinguishable from one a person
typed, which is why this is pinned at the gate rather than cleaned up later.

The tests drive the boot path itself, twice, the way two restarts would, and
count rows per module through each project. Every assertion that the real
project stays empty is paired with one that the live demo project was filled,
because an enrichment that silently did nothing would pass the first half.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database as app_database
from app.config import get_settings
from app.modules.accommodation.models import Accommodation
from app.modules.bid_management.models import BidPackage
from app.modules.bim_hub.models import BIMFederation
from app.modules.clash.models import ClashRun
from app.modules.daily_diary.models import DailyDiary
from app.modules.documents.models import ProjectPhoto
from app.modules.equipment.models import EquipmentRental
from app.modules.field_time.models import FieldTimesheet
from app.modules.hse_advanced.models import JobSafetyAnalysis, PermitToWork
from app.modules.projects.models import Project
from app.modules.qms.models import QMSNCR, ITPPlan, QMSAudit, QMSInspection, QMSPunchItem
from app.modules.service.models import ServiceContract
from app.modules.teams.models import RosterMember
from app.modules.users.models import User
from app.modules.variations.models import Notice

pytestmark = pytest.mark.asyncio

# Every model the report named, plus the ones the audit of the boot list found
# receiving the same unfiltered project list. Counted per project, never per
# table: a table count is satisfied by the demo project alone.
_PROJECT_SCOPED = (
    DailyDiary,
    BidPackage,
    ServiceContract,
    JobSafetyAnalysis,
    PermitToWork,
    ITPPlan,
    QMSInspection,
    QMSNCR,
    QMSPunchItem,
    QMSAudit,
    ProjectPhoto,
    Accommodation,
    RosterMember,
    FieldTimesheet,
    ClashRun,
    BIMFederation,
    Notice,
    EquipmentRental,
)

# One of the curated showcase ids, so the seeders that fill only the curated set
# (accommodation, markups, the cost model) reach the demo project as well.
_DEMO_ID = "residential-berlin"


@pytest_asyncio.fixture
async def boot_factory(pg_session, monkeypatch, no_detached_subscribers):
    """The session factory the boot seeding opens, bound to this test's cluster.

    Each session joins the test's outer transaction through a savepoint, so what
    one seeder commits the next one reads, and the whole run rolls back after.
    """
    factory = async_sessionmaker(
        bind=pg_session.bind,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    monkeypatch.setattr(app_database, "async_session_factory", factory)
    return factory


async def _owner(session) -> uuid.UUID:
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"owner-{owner_id.hex[:8]}@example.test",
            hashed_password="x",
            full_name="Site Owner",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    return owner_id


async def _project(session, owner_id: uuid.UUID, name: str, *, demo_id: str | None = None, status="active"):
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Demo seed boundary fixture",
            currency="EUR",
            status=status,
            owner_id=owner_id,
            metadata_={"demo_id": demo_id} if demo_id else {},
        )
    )
    await session.flush()
    return project_id


async def _rows(factory, model, project_id: uuid.UUID) -> int:
    async with factory() as s:
        return int(
            (
                await s.execute(select(func.count()).select_from(model).where(model.project_id == project_id))
            ).scalar_one()
        )


async def _estate(factory) -> dict[str, uuid.UUID]:
    """A live demo project, a demo project the user deleted, and a real one."""
    async with factory() as s:
        owner_id = await _owner(s)
        ids = {
            "demo": await _project(s, owner_id, "Residential Berlin (demo)", demo_id=_DEMO_ID),
            "deleted_demo": await _project(
                s, owner_id, "Office Frankfurt (demo)", demo_id="office-frankfurt", status="archived"
            ),
            "real": await _project(s, owner_id, "Warehouse Extension Leipzig"),
        }
        await s.commit()
    return ids


# What the boot enrichment fills in a live demo project of the curated set.
# Asserted on the demo project in the same run that must leave the real one
# empty, so a seeder that silently stopped writing fails here instead of
# passing the "nothing leaked" half by writing nothing anywhere.
_FILLED_IN_A_DEMO = (
    DailyDiary,
    BidPackage,
    ServiceContract,
    JobSafetyAnalysis,
    PermitToWork,
    ITPPlan,
    QMSInspection,
    QMSNCR,
    QMSPunchItem,
    QMSAudit,
    ProjectPhoto,
    Accommodation,
    RosterMember,
    Notice,
)


async def _invitations(factory, project_id: uuid.UUID) -> int:
    from app.modules.bid_management.models import BidInvitation

    async with factory() as s:
        return int(
            (
                await s.execute(
                    select(func.count())
                    .select_from(BidInvitation)
                    .join(BidPackage, BidInvitation.package_id == BidPackage.id)
                    .where(BidPackage.project_id == project_id)
                )
            ).scalar_one()
        )


async def test_two_restarts_write_no_demo_rows_into_a_real_project(boot_factory) -> None:
    from app.core.demo_enrichment import enrich_all

    ids = await _estate(boot_factory)

    await enrich_all()
    await enrich_all()

    leaked = {m.__name__: n for m in _PROJECT_SCOPED if (n := await _rows(boot_factory, m, ids["real"]))}
    assert leaked == {}, f"demo rows written into a real project: {leaked}"
    assert await _invitations(boot_factory, ids["real"]) == 0

    # The discriminating half: the same boot run did fill the live demo project,
    # so an empty real project above is the gate working and not the seed dead.
    empty = [m.__name__ for m in _FILLED_IN_A_DEMO if not await _rows(boot_factory, m, ids["demo"])]
    assert empty == [], f"the boot left these empty in the live demo project: {empty}"
    assert await _invitations(boot_factory, ids["demo"]) > 0


async def test_a_project_made_after_the_demo_was_deleted_gets_nothing_on_restart(boot_factory) -> None:
    """The tester's order of events: demos seeded, demo deleted, own project, restart.

    The first boot fills the live demo. The person then deletes it and starts
    a project of their own, which has no rows in any module yet, so to a seeder
    that only asks "is my table empty for this project" it looks exactly like a
    project waiting for its demo content. The next boot must leave it alone.
    """
    from app.core.demo_enrichment import enrich_all
    from app.modules.projects.service import ProjectService

    async with boot_factory() as s:
        owner_id = await _owner(s)
        demo = await _project(s, owner_id, "Residential Berlin (demo)", demo_id=_DEMO_ID)
        await s.commit()
    await enrich_all()
    assert await _rows(boot_factory, ITPPlan, demo) == 1, "the first boot did not fill the demo"

    async with boot_factory() as s:
        await ProjectService(s, get_settings()).delete_project(demo)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        await s.commit()
    before = {m.__name__: await _rows(boot_factory, m, demo) for m in _PROJECT_SCOPED}

    await enrich_all()

    leaked = {m.__name__: n for m in _PROJECT_SCOPED if (n := await _rows(boot_factory, m, real))}
    assert leaked == {}, f"demo rows written into a project made after the demo was deleted: {leaked}"
    after = {m.__name__: await _rows(boot_factory, m, demo) for m in _PROJECT_SCOPED}
    assert after == before, "the restart wrote into the deleted demo project"
