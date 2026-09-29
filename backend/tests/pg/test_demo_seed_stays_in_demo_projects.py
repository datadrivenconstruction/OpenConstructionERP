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


async def test_two_restarts_write_no_demo_rows_into_a_real_project(boot_factory) -> None:
    from app.core.demo_enrichment import enrich_all

    ids = await _estate(boot_factory)

    await enrich_all()
    await enrich_all()

    leaked = {m.__name__: n for m in _PROJECT_SCOPED if (n := await _rows(boot_factory, m, ids["real"]))}
    assert leaked == {}, f"demo rows written into a real project: {leaked}"

    into_deleted = {m.__name__: n for m in _PROJECT_SCOPED if (n := await _rows(boot_factory, m, ids["deleted_demo"]))}
    assert into_deleted == {}, f"demo rows written into a deleted demo project: {into_deleted}"

    # The discriminating half: the same boot run did fill the live demo project,
    # so an empty real project above is the gate working and not the seed dead.
    assert await _rows(boot_factory, ITPPlan, ids["demo"]) == 1
    assert await _rows(boot_factory, DailyDiary, ids["demo"]) > 0
    assert await _rows(boot_factory, RosterMember, ids["demo"]) > 0


async def test_the_equipment_rentals_land_on_demo_projects_only(boot_factory) -> None:
    from app.modules.equipment.seed import seed_equipment_demo

    # The real project first, so "the first projects in the table" is exactly
    # the project a selection by position would pick.
    async with boot_factory() as s:
        owner_id = await _owner(s)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        demo = await _project(s, owner_id, "Residential Berlin (demo)", demo_id=_DEMO_ID)
        await s.commit()

    async with boot_factory() as s:
        await seed_equipment_demo(s)
        await s.commit()

    assert await _rows(boot_factory, EquipmentRental, real) == 0
    assert await _rows(boot_factory, EquipmentRental, demo) > 0


async def test_the_subcontract_demo_is_attached_to_a_demo_project(boot_factory) -> None:
    from app.core.demo_marker import first_live_demo_project_id

    async with boot_factory() as s:
        owner_id = await _owner(s)
        await _project(s, owner_id, "Warehouse Extension Leipzig")
        await s.commit()
        assert await first_live_demo_project_id(s) is None

        demo = await _project(s, owner_id, "Residential Berlin (demo)", demo_id=_DEMO_ID)
        await _project(s, owner_id, "Office Frankfurt (demo)", demo_id="office-frankfurt", status="archived")
        await s.commit()
        assert await first_live_demo_project_id(s) == demo


async def test_the_portfolio_overview_leaves_out_a_deleted_project(boot_factory) -> None:
    from app.modules.projects.router import analytics_overview

    ids = await _estate(boot_factory)
    async with boot_factory() as s:
        overview = await analytics_overview(session=s, _user_id=str(uuid.uuid4()), payload={"role": "admin"})

    listed = {str(p["id"]) for p in overview["projects"]}
    assert str(ids["deleted_demo"]) not in listed
    assert {str(ids["demo"]), str(ids["real"])} <= listed
    assert overview["total_projects"] == len(listed)


async def test_deleting_a_demo_project_records_that_it_was_retired(boot_factory) -> None:
    from app.core.demo_marker import retired_demo_ids
    from app.modules.projects.service import ProjectService

    ids = await _estate(boot_factory)
    async with boot_factory() as s:
        await ProjectService(s, get_settings()).delete_project(ids["demo"])
        await s.commit()

    async with boot_factory() as s:
        assert _DEMO_ID in await retired_demo_ids(s)


async def test_a_purged_demo_is_not_reinstalled_by_the_next_boot(boot_factory) -> None:
    from app.core.demo_marker import retired_demo_ids
    from app.core.demo_projects import install_demo_projects_at_boot
    from app.modules.projects.service import ProjectService

    ids = await _estate(boot_factory)
    async with boot_factory() as s:
        await ProjectService(s, get_settings()).purge_demo_projects()
        await s.commit()

    async with boot_factory() as s:
        assert {_DEMO_ID, "office-frankfurt"} <= await retired_demo_ids(s)

    # Two boots, the way a restart after the purge and one after an upgrade
    # would each reach the installer.
    for _ in range(2):
        await install_demo_projects_at_boot([_DEMO_ID, "office-frankfurt"])

    async with boot_factory() as s:
        demo_rows = [
            p
            for p in (await s.execute(select(Project))).scalars().all()
            if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id")
        ]
        assert demo_rows == []
        assert (await s.get(Project, ids["real"])) is not None


async def test_an_explicit_install_brings_a_retired_demo_back(boot_factory) -> None:
    from app.core.demo_marker import retire_demo_ids, retired_demo_ids
    from app.core.demo_projects import install_demo_project

    async with boot_factory() as s:
        await _owner(s)
        await retire_demo_ids(s, {_DEMO_ID: None}, reason="purged")
        await s.commit()

    # A person asking for the demo is the one thing that overrides the record
    # of them removing it, and it clears the record so later boots keep it.
    async with boot_factory() as s:
        result = await install_demo_project(s, _DEMO_ID)
        await s.commit()
    assert not result.get("already_installed")

    async with boot_factory() as s:
        assert _DEMO_ID not in await retired_demo_ids(s)


async def test_the_cleanup_removes_only_seed_marked_rows_from_real_projects(boot_factory) -> None:
    from app.core.demo_cleanup import clean_leaked_demo_rows

    ids = await _estate(boot_factory)
    async with boot_factory() as s:
        # What the old boot seeding left in the real project, next to a diary a
        # person wrote in it, and the demo project's own seeded diary.
        s.add(DailyDiary(project_id=ids["real"], diary_date="2026-09-01", metadata_={"seed": True}))
        s.add(DailyDiary(project_id=ids["real"], diary_date="2026-09-02", metadata_={}))
        s.add(DailyDiary(project_id=ids["demo"], diary_date="2026-09-01", metadata_={"seed": True}))
        await s.commit()

    async with boot_factory() as s:
        dry = await clean_leaked_demo_rows(s)
        await s.rollback()
    assert dry.marked["daily_diary"] == 1
    assert await _rows(boot_factory, DailyDiary, ids["real"]) == 2

    async with boot_factory() as s:
        done = await clean_leaked_demo_rows(s, apply=True)
        await s.commit()
    assert done.marked["daily_diary"] == 1

    async with boot_factory() as s:
        left = (await s.execute(select(DailyDiary.metadata_).where(DailyDiary.project_id == ids["real"]))).scalars()
        assert list(left) == [{}]
    assert await _rows(boot_factory, DailyDiary, ids["demo"]) == 1
