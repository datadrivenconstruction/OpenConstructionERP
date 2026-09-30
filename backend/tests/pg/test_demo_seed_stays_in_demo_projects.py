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


_FLAGSHIP_PROJECT_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")


async def _boot_pass(owner_id: uuid.UUID) -> None:
    """Everything a boot does with demo content, in boot order.

    A restart and an upgrade run this same pass. The only thing an upgrade
    changes is the version marker, and the marker only decides whether the
    backfill half runs at all; after an upgrade it always does, so running the
    pass is running the upgrade.
    """
    from app.core.demo_enrichment import enrich_all
    from app.core.demo_projects import install_demo_projects_at_boot, install_flagship_at_boot

    await install_demo_projects_at_boot([_DEMO_ID])
    await install_flagship_at_boot(owner_id)
    await enrich_all()


async def _listed_ids(factory, owner_id: uuid.UUID) -> tuple[set[str], set[str]]:
    """Project ids in the top-left switcher and in the dashboard project cards."""
    from app.modules.projects.router import dashboard_cards, list_projects
    from app.modules.projects.service import ProjectService

    payload = {"role": "admin", "sub": str(owner_id)}
    async with factory() as s:
        dropdown = await list_projects(
            user_id=str(owner_id),
            payload=payload,
            service=ProjectService(s, get_settings()),
            offset=0,
            limit=500,
            status=None,
        )
        cards = await dashboard_cards(session=s, user_id=str(owner_id), payload=payload)
    # Called directly, the card endpoint hands back plain dicts, not the response model.
    return {str(p.id) for p in dropdown}, {str(c["id"] if isinstance(c, dict) else c.id) for c in cards}


async def test_deleted_demos_stay_deleted_through_restart_and_upgrade(boot_factory) -> None:
    from app.core.demo_projects import install_demo_project
    from app.modules.projects.service import ProjectService

    async with boot_factory() as s:
        owner_id = await _owner(s)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        # A stand-in for the flagship at its fixed id: the boot installer finds
        # its project by that id, which is what makes a purge undo itself.
        s.add(
            Project(
                id=_FLAGSHIP_PROJECT_ID,
                name="Flagship (demo)",
                description="Demo seed boundary fixture",
                currency="USD",
                status="active",
                owner_id=owner_id,
                metadata_={"demo_id": "flagship-house"},
            )
        )
        await s.commit()
    async with boot_factory() as s:
        installed = await install_demo_project(s, _DEMO_ID)
        await s.commit()
    demo = uuid.UUID(installed["project_id"])

    # The tester's case: both demos deleted from the project list.
    async with boot_factory() as s:
        await ProjectService(s, get_settings()).delete_project(demo)
        await ProjectService(s, get_settings()).delete_project(_FLAGSHIP_PROJECT_ID)
        await s.commit()

    for _ in ("restart", "upgrade"):
        await _boot_pass(owner_id)

    async with boot_factory() as s:
        demos = [
            (p.id, p.status)
            for p in (await s.execute(select(Project))).scalars().all()
            if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id")
        ]
    assert sorted(demos) == sorted([(demo, "archived"), (_FLAGSHIP_PROJECT_ID, "archived")])

    dropdown, cards = await _listed_ids(boot_factory, owner_id)
    assert dropdown == cards
    assert str(real) in dropdown
    assert not {str(demo), str(_FLAGSHIP_PROJECT_ID)} & dropdown

    leaked = {m.__name__: n for m in _PROJECT_SCOPED if (n := await _rows(boot_factory, m, real))}
    assert leaked == {}, f"demo rows written into a real project: {leaked}"

    # Then "Remove demo data", which deletes the rows outright, and the same
    # two boots. Nothing may come back, not even under a fresh id.
    async with boot_factory() as s:
        await ProjectService(s, get_settings()).purge_demo_projects()
        await s.commit()

    for _ in ("restart", "upgrade"):
        await _boot_pass(owner_id)

    async with boot_factory() as s:
        back = [
            p.id
            for p in (await s.execute(select(Project))).scalars().all()
            if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id")
        ]
    assert back == []
    dropdown, cards = await _listed_ids(boot_factory, owner_id)
    assert dropdown == cards
    assert str(real) in dropdown


async def test_the_cleanup_undoes_what_the_old_boot_wrote_and_keeps_user_records(boot_factory) -> None:
    """An install polluted the way the tester's was, then ``demo-cleanup --apply``.

    The seeders are called directly with the real project, which is exactly
    what the old enrichment did. The user's own diary sits next to the leaked
    rows and must survive.
    """
    from app.core.demo_cleanup import clean_leaked_demo_rows
    from app.modules.bid_management.seed import seed_bid_management_demo
    from app.modules.daily_diary.seed import seed_daily_diary_demo
    from app.modules.documents.photos_seed import seed_photos
    from app.modules.qms.seed import seed_qms

    async with boot_factory() as s:
        owner_id = await _owner(s)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        # Written before the seed, the way the tester's own work was.
        s.add(DailyDiary(project_id=real, diary_date="2000-01-03", metadata_={}, notes="Poured the east footing"))
        await s.commit()

    async with boot_factory() as s:
        # The diary seed stops at a project that already holds a real diary,
        # so it runs against a second real project to reproduce the leak.
        leaked_into = await _project(s, owner_id, "Depot Refurbishment Halle")
        await s.commit()
    for seed in (
        lambda s: seed_daily_diary_demo(s, [leaked_into]),
        lambda s: seed_bid_management_demo(s, [real]),
        lambda s: seed_photos(s, [real]),
        lambda s: seed_qms(s, project_id=real),
    ):
        async with boot_factory() as s:
            await seed(s)
            await s.commit()

    before = {m: await _rows(boot_factory, m, real) for m in (BidPackage, ProjectPhoto, ITPPlan)}
    assert before[BidPackage] > 0 and before[ProjectPhoto] > 0 and before[ITPPlan] == 1
    assert await _rows(boot_factory, DailyDiary, leaked_into) > 0

    async with boot_factory() as s:
        report = await clean_leaked_demo_rows(s, apply=True)
        await s.commit()

    assert report.marked["bid_management"] == before[BidPackage]
    assert report.marked["photos"] == before[ProjectPhoto]
    assert await _rows(boot_factory, BidPackage, real) == 0
    assert await _rows(boot_factory, ProjectPhoto, real) == 0
    assert await _rows(boot_factory, DailyDiary, leaked_into) == 0
    # The diary seed's rows that hang off the project rather than the diary.
    from app.modules.daily_diary.models import DroneSurvey, RealityCaptureDataset, WeatherRecord

    for model in (WeatherRecord, DroneSurvey, RealityCaptureDataset):
        assert await _rows(boot_factory, model, leaked_into) == 0, model.__name__
    assert report.marked["daily_diary_weather"] > 0
    assert report.marked["daily_diary_drone_surveys"] > 0
    assert report.marked["daily_diary_reality_captures"] > 0

    # The user's diary is untouched.
    async with boot_factory() as s:
        kept = (await s.execute(select(DailyDiary.notes).where(DailyDiary.project_id == real))).scalars().all()
    assert kept == ["Poured the east footing"]

    # The quality plan carries no mark; its content is the seed's, so it goes too.
    assert report.marked["qms_itp_plans"] == 1
    assert await _rows(boot_factory, ITPPlan, real) == 0


# Company-wide groups: which of their rows may go depends on what stays.
_COMPANY_GROUPS = {
    "hse_ppe_issues",
    "service_sla_definitions",
    "service_checklists",
    "service_customers",
    "demo_contacts",
}


# Groups every old seeding run fills. The field-time side effects (reversals,
# the worker-days and daywork it books on approval) depend on the dice and on
# rates, so they are checked for removal below but not required to exist.
_FINGERPRINT_GROUPS = (
    "qms_ncrs",
    "qms_inspections",
    "qms_itp_plans",
    "qms_punch_items",
    "qms_audits",
    "teams_roster",
    "hse_permits_to_work",
    "hse_job_safety_analyses",
    "hse_ppe_issues",
    "variation_site_measurements",
    "variation_orders",
    "variation_requests",
    "variation_notices",
    "variation_daywork_sheets",
    "variation_disruption_claims",
    "variation_eot_claims",
    "variation_final_accounts",
    "service_contracts",
    "field_timesheets",
)


async def _crew_and_bill(factory, project_id: uuid.UUID) -> None:
    """What the timesheet seed needs before it books anything: a crew and a priced bill."""
    from decimal import Decimal

    from app.modules.boq.models import BOQ, Position
    from app.modules.resources.models import Resource

    async with factory() as s:
        for name, kind in (("Marta Nowak", "person"), ("Jonas Weber", "person"), ("Formwork crew A", "crew")):
            s.add(
                Resource(
                    code=f"FT-{uuid.uuid4().hex[:6]}",
                    name=name,
                    resource_type=kind,
                    home_project_id=project_id,
                    default_cost_rate=Decimal("42"),
                    currency="EUR",
                    status="active",
                    metadata_={},
                )
            )
        boq = BOQ(project_id=project_id, name="Main bill")
        s.add(boq)
        await s.flush()
        for n, description in enumerate(("Excavation", "Blinding concrete", "Strip footings", "Blockwork"), start=1):
            s.add(
                Position(
                    boq_id=boq.id,
                    ordinal=f"01.{n:02d}",
                    description=description,
                    unit="m3",
                    quantity="10",
                    unit_rate="50",
                    total="500",
                )
            )
        await s.commit()


async def _look_alike(factory, model, seeded_id: uuid.UUID, **changes) -> uuid.UUID:
    """A person's own row: a copy of a seeded one that differs in the fields given."""
    from sqlalchemy import inspect as sa_inspect

    async with factory() as s:
        row = await s.get(model, seeded_id)
        values = {attr.key: getattr(row, attr.key) for attr in sa_inspect(model).column_attrs}
        values.update(id=uuid.uuid4(), **changes)
        s.add(model(**values))
        await s.commit()
    return values["id"]


async def _present(factory, model, ids) -> int:
    if not ids:
        return 0
    async with factory() as s:
        return int((await s.execute(select(func.count()).select_from(model).where(model.id.in_(ids)))).scalar_one())


async def test_the_cleanup_removes_every_unmarked_seed_by_its_content(boot_factory) -> None:
    """The seeds that left no mark are recognised by what they wrote, and only by that.

    Every seeder the old boot handed a real project runs against one here. Next
    to each group sits a person's own row that shares the seed's title but not
    a second field, the way a user who copied a demo record and changed it
    would have it. The dry run lists the seed's rows and deletes nothing, the
    apply removes every group on PostgreSQL's foreign keys, the look-alikes
    survive, and a second pass finds nothing left.
    """
    from datetime import timedelta

    from app.core.demo_cleanup import clean_leaked_demo_rows
    from app.modules.costmodel.models import LabourWorkerDay
    from app.modules.field_time.seed import seed_field_time_demo
    from app.modules.hse_advanced.models import PPEIssue
    from app.modules.hse_advanced.seed import seed_hse_advanced_demo
    from app.modules.qms.seed import seed_qms
    from app.modules.service.seed import seed_service_demo
    from app.modules.teams.seed import seed_teams_roster
    from app.modules.variations.models import (
        DayworkSheet,
        DisruptionClaim,
        ExtensionOfTimeClaim,
        FinalAccount,
        SiteMeasurement,
        VariationOrder,
        VariationRequest,
    )
    from app.modules.variations.seed import seed_variations_demo

    async with boot_factory() as s:
        owner_id = await _owner(s)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        await s.commit()
    await _crew_and_bill(boot_factory, real)

    # The old boot's order: variations before field time, so hours can be
    # booked against an open variation order.
    #
    # An approved timesheet publishes its hours to the cost model, whose
    # subscriber opens a session of its own. Here that session shares this
    # test's one connection with the seeding session and unwinds its
    # savepoints, so the two labour subscribers sit this out, the way
    # ``no_detached_subscribers`` does for the budget-line ones.
    from app.core.events import event_bus
    from app.modules.costmodel.service import _on_labour_logged, _on_labour_reversed

    detached = [
        ("fieldreports.labour.logged", _on_labour_logged),
        ("fieldreports.labour.reversed", _on_labour_reversed),
    ]
    removed = [(name, fn) for name, fn in detached if fn in event_bus._handlers.get(name, [])]
    for name, fn in removed:
        event_bus.unsubscribe(name, fn)
    try:
        for seed in (
            lambda s: seed_qms(s, project_id=real),
            lambda s: seed_teams_roster(s, project_id=real),
            lambda s: seed_hse_advanced_demo(s, [real]),
            lambda s: seed_variations_demo(s, [real]),
            lambda s: seed_service_demo(s, [real]),
            lambda s: seed_field_time_demo(s, [real]),
        ):
            async with boot_factory() as s:
                await seed(s)
                await s.commit()
    finally:
        for name, fn in removed:
            event_bus.subscribe(name, fn)

    async with boot_factory() as s:
        dry = await clean_leaked_demo_rows(s)
        await s.rollback()
    empty = [g for g in _FINGERPRINT_GROUPS if not dry.rows.get(g)]
    assert empty == [], f"seeded groups the fingerprint did not recognise: {empty}; found {dry.marked}"
    assert dry.ppe_kept_reason == ""

    models = {
        "qms_ncrs": QMSNCR,
        "qms_inspections": QMSInspection,
        "qms_itp_plans": ITPPlan,
        "qms_punch_items": QMSPunchItem,
        "qms_audits": QMSAudit,
        "teams_roster": RosterMember,
        "hse_permits_to_work": PermitToWork,
        "hse_job_safety_analyses": JobSafetyAnalysis,
        "hse_ppe_issues": PPEIssue,
        "variation_site_measurements": SiteMeasurement,
        "variation_orders": VariationOrder,
        "variation_requests": VariationRequest,
        "variation_notices": Notice,
        "variation_daywork_sheets": DayworkSheet,
        "variation_disruption_claims": DisruptionClaim,
        "variation_eot_claims": ExtensionOfTimeClaim,
        "variation_final_accounts": FinalAccount,
        "service_contracts": ServiceContract,
        "field_timesheets": FieldTimesheet,
        "field_time_reversals": FieldTimesheet,
        "field_time_labour_worker_days": LabourWorkerDay,
        "field_time_daywork_sheets": DayworkSheet,
    }
    # A dry run lists and leaves: every listed row is still there.
    for group, model in models.items():
        listed = dry.rows.get(group, [])
        assert await _present(boot_factory, model, listed) == len(listed), group

    # A person's rows: the seed's title, a different second field.
    first = {group: ids[0] for group, ids in dry.rows.items() if ids}
    async with boot_factory() as s:
        signed = (
            await s.execute(
                select(FieldTimesheet.id, FieldTimesheet.submitted_at).where(
                    FieldTimesheet.id.in_(dry.rows["field_timesheets"]), FieldTimesheet.submitted_at.is_not(None)
                )
            )
        ).first()
    assert signed is not None, "the seed signed none of its timesheets"
    keep = {
        QMSNCR: await _look_alike(
            boot_factory, QMSNCR, first["qms_ncrs"], description="Found by our site engineer on the east wall."
        ),
        QMSPunchItem: await _look_alike(
            boot_factory, QMSPunchItem, first["qms_punch_items"], description="Logged on our handover walk."
        ),
        ITPPlan: await _look_alike(boot_factory, ITPPlan, first["qms_itp_plans"], wbs_ref="WBS-OWN-01"),
        QMSAudit: await _look_alike(boot_factory, QMSAudit, first["qms_audits"], audit_scope="Our own audit scope"),
        RosterMember: await _look_alike(boot_factory, RosterMember, first["teams_roster"], company_name="Own Crew Ltd"),
        JobSafetyAnalysis: await _look_alike(
            boot_factory, JobSafetyAnalysis, first["hse_job_safety_analyses"], location="Basement B2"
        ),
        PermitToWork: await _look_alike(
            boot_factory, PermitToWork, first["hse_permits_to_work"], description="Hot work on our own boiler."
        ),
        PPEIssue: await _look_alike(boot_factory, PPEIssue, first["hse_ppe_issues"], recipient_company="Own Crew Ltd"),
        # Codes are unique per project, so the person's copy carries its own.
        Notice: await _look_alike(boot_factory, Notice, first["variation_notices"], code="NOT-OWN-1"),
        VariationOrder: await _look_alike(boot_factory, VariationOrder, first["variation_orders"], code="VO-OWN-1"),
        ServiceContract: await _look_alike(
            boot_factory, ServiceContract, first["service_contracts"], contract_number="SC-OWN-1"
        ),
        # The seed's note and hours, signed when it was really signed.
        FieldTimesheet: await _look_alike(
            boot_factory,
            FieldTimesheet,
            signed.id,
            reference=f"TS-OWN-{uuid.uuid4().hex[:6]}",
            submitted_at=signed.submitted_at + timedelta(minutes=7),
            approved_at=None,
            status="submitted",
        ),
    }

    async with boot_factory() as s:
        again = await clean_leaked_demo_rows(s)
        await s.rollback()
    in_projects = lambda marked: {g: n for g, n in marked.items() if g not in _COMPANY_GROUPS}  # noqa: E731
    assert in_projects(again.marked) == in_projects(dry.marked), "a person's look-alike was taken for the seed's"
    # The person's contract keeps the SLA tier and the customer it names.
    kept_company = {r.table for r in again.kept}
    assert {"oe_service_sla_definition", "oe_contacts_contact"} <= kept_company, again.kept
    assert len(again.rows["service_sla_definitions"]) == len(dry.rows["service_sla_definitions"]) - 1

    async with boot_factory() as s:
        done = await clean_leaked_demo_rows(s, apply=True)
        await s.commit()
    assert done.marked == again.marked

    gone = {
        group: n for group, model in models.items() if (n := await _present(boot_factory, model, done.rows.get(group)))
    }
    assert gone == {}, f"groups the apply left behind: {gone}"

    survived = {model.__name__: await _present(boot_factory, model, [rid]) for model, rid in keep.items()}
    assert survived == dict.fromkeys(survived, 1), f"a person's row was removed: {survived}"

    # Nothing of the seed's kind is left in the real project but the person's rows.
    per_project = {model: 1 for model in keep if model is not PPEIssue}
    per_project.update(
        dict.fromkeys(
            (
                QMSInspection,
                VariationRequest,
                SiteMeasurement,
                DisruptionClaim,
                ExtensionOfTimeClaim,
                FinalAccount,
                DayworkSheet,
            ),
            0,
        )
    )
    left = {m.__name__: n for m, want in per_project.items() if (n := await _rows(boot_factory, m, real)) != want}
    assert left == {}, f"seed rows still in the real project: {left}"

    async with boot_factory() as s:
        second = await clean_leaked_demo_rows(s, apply=True)
        await s.commit()
    assert second.total == 0, second.marked


async def test_a_second_removal_racing_the_first_does_not_fail(boot_factory, monkeypatch) -> None:
    """Two removals of one demo, the second reading before the first wrote.

    The losing request sees no record, exactly as if it had read a moment
    earlier, and must still not fail on the unique demo id.
    """
    import app.core.demo_marker as demo_marker
    from app.modules.projects.models import DemoProjectTombstone

    async with boot_factory() as s:
        await demo_marker.retire_demo_ids(s, {_DEMO_ID: uuid.uuid4()}, reason="archived")
        await s.commit()

    async def nothing_yet(_session):
        return set()

    monkeypatch.setattr(demo_marker, "retired_demo_ids", nothing_yet)
    async with boot_factory() as s:
        added = await demo_marker.retire_demo_ids(s, {_DEMO_ID: uuid.uuid4()}, reason="purged")
        await s.commit()
    assert added == 0

    async with boot_factory() as s:
        rows = (await s.execute(select(DemoProjectTombstone.reason))).scalars().all()
    assert rows == ["archived"]


# ── The boot itself (``_seed_demo_account``) ────────────────────────────────


def _boot_as_a_desktop_install(monkeypatch, *, pack=None) -> None:
    """Run the real boot seeding with only the parts that are not under test stood in.

    The seed-demo switch reads the environment and a choice file on the
    machine running the suite, the backfill marker lives in its data dir, and
    the demo passwords would otherwise be generated and written to its home
    directory. None of that decides these tests.
    """
    import app.core.demo_seed as demo_seed
    import app.core.partner_pack.discovery as discovery
    import app.main as main

    for var in ("OE_TEST_FAST_STARTUP", "OE_SKIP_SHOWCASE", "SEED_DEMO"):
        monkeypatch.delenv(var, raising=False)
    for var in ("DEMO_USER_PASSWORD", "DEMO_ESTIMATOR_PASSWORD", "DEMO_MANAGER_PASSWORD"):
        monkeypatch.setenv(var, "demo-password-for-tests")
    monkeypatch.setattr(demo_seed, "seed_demo_enabled", lambda: True)
    monkeypatch.setattr(demo_seed, "read_demo_seed_choice", lambda data_dir=None: None)
    # A marker from the previous release: the demos were seeded here before.
    monkeypatch.setattr(main, "_read_demo_backfill_version", lambda: "18.2.0")
    monkeypatch.setattr(main, "_write_demo_backfill_version", lambda version: None)
    monkeypatch.setattr(discovery, "get_active_pack", lambda: pack)


async def _demo_projects(factory) -> list[tuple[uuid.UUID, str, str]]:
    from app.core.demo_marker import demo_id_of

    async with factory() as s:
        rows = (await s.execute(select(Project.id, Project.status, Project.metadata_))).all()
    return sorted((pid, demo_id_of(meta), status) for pid, status, meta in rows if demo_id_of(meta))


@pytest.mark.parametrize("pack_mode", [False, True], ids=["showcase", "partner-pack"])
async def test_an_install_that_removed_its_demos_before_the_record_existed_gets_none_back(
    boot_factory, monkeypatch, caplog, pack_mode
) -> None:
    """The state a pre-18.2.1 removal left: marker present, no demo project, no record.

    That is the tester's install. The first boot on the new version must see
    the removal and write it down before any installer runs, in showcase mode
    and in partner-pack mode alike, and a second boot must agree.
    """
    from types import SimpleNamespace

    import app.main as main
    from app.core.demo_marker import retired_demo_ids

    pack = SimpleNamespace(slug="test-pack", demo_template_ids=[_DEMO_ID]) if pack_mode else None
    _boot_as_a_desktop_install(monkeypatch, pack=pack)
    async with boot_factory() as s:
        owner_id = await _owner(s)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        await s.commit()

    with caplog.at_level("INFO"):
        for _ in ("first boot on the new version", "restart"):
            await main._seed_demo_account()

    assert "Failed to seed demo account" not in caplog.text
    assert await _demo_projects(boot_factory) == []
    async with boot_factory() as s:
        assert set(main._boot_demo_ids(pack)) <= await retired_demo_ids(s)
        # The boot really ran: it created the demo account it always creates.
        assert (await s.execute(select(User.id).where(User.email == "demo@openconstructionerp.com"))).first()
    leaked = {m.__name__: n for m in _PROJECT_SCOPED if (n := await _rows(boot_factory, m, real))}
    assert leaked == {}


async def test_a_fresh_install_is_not_mistaken_for_one_that_removed_its_demos(boot_factory, monkeypatch) -> None:
    """No marker and no choice: the demos were never seeded, so nothing is recorded."""
    import app.main as main
    from app.core.demo_marker import backfill_removed_demo_records, retired_demo_ids

    async with boot_factory() as s:
        written = await backfill_removed_demo_records(s, main._boot_demo_ids(None), seeded_before=False)
        await s.commit()
    assert written == 0
    async with boot_factory() as s:
        assert await retired_demo_ids(s) == set()


async def test_the_boot_keeps_deleted_and_then_purged_demos_away(boot_factory, monkeypatch, caplog) -> None:
    """Soft delete every demo the boot installs, boot twice; purge, boot twice.

    Stand-in projects carry each boot demo id, the flagship at its fixed id,
    and belong to the demo account, so the boot runs its every branch: the
    showcase loop (once the purge leaves the account with no project), the
    flagship, the Heilbronn backfill and the company-wide seeds after them.
    """
    import app.main as main
    from app.modules.projects.service import ProjectService
    from app.modules.users.service import hash_password

    _boot_as_a_desktop_install(monkeypatch)
    async with boot_factory() as s:
        # A real hash: the boot checks the stored one against the env password.
        demo_user = User(
            email="demo@openconstructionerp.com",
            hashed_password=hash_password("demo-password-for-tests"),
            full_name="Demo",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
        s.add(demo_user)
        await s.flush()
        ids = []
        for did in main._boot_demo_ids(None):
            pid = _FLAGSHIP_PROJECT_ID if did == "flagship-house" else uuid.uuid4()
            s.add(
                Project(
                    id=pid,
                    name=f"{did} (demo)",
                    description="Demo seed boundary fixture",
                    currency="EUR",
                    status="active",
                    owner_id=demo_user.id,
                    metadata_={"demo_id": did},
                )
            )
            ids.append(pid)
        await s.commit()

    async with boot_factory() as s:
        for pid in ids:
            await ProjectService(s, get_settings()).delete_project(pid)
        await s.commit()
    deleted = await _demo_projects(boot_factory)

    with caplog.at_level("INFO"):
        for _ in ("restart", "upgrade"):
            await main._seed_demo_account()
    assert await _demo_projects(boot_factory) == deleted
    assert {status for _pid, _did, status in deleted} == {"archived"}

    async with boot_factory() as s:
        await ProjectService(s, get_settings()).purge_demo_projects()
        await s.commit()
    with caplog.at_level("INFO"):
        for _ in ("restart", "upgrade"):
            await main._seed_demo_account()
    assert await _demo_projects(boot_factory) == []
    assert "Failed to seed demo account" not in caplog.text


# ── The demo endpoints ─────────────────────────────────────────────────────


def _admin_app(user_id: str, role: str = "admin"):
    from app.dependencies import get_current_user_id, get_current_user_payload
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": user_id, "role": role, "permissions": []}
    return app


async def test_the_demo_endpoints_record_what_they_remove_and_take_the_flagship_too(boot_factory) -> None:
    """``/api/demo/uninstall`` and ``/api/demo/clear-all`` over HTTP.

    The flagship carries ``demo_id`` and not ``is_demo``, which is the tag
    clear-all used to select by, so it survived. A contact the demo installer
    wrote goes with its demo.
    """
    import httpx

    from app.core.demo_marker import retired_demo_ids
    from app.modules.contacts.models import Contact

    async with boot_factory() as s:
        owner_id = await _owner(s)
        single = await _project(s, owner_id, "Office Frankfurt (demo)", demo_id="office-frankfurt")
        showcase = uuid.uuid4()
        s.add(
            Project(
                id=showcase,
                name="Residential Berlin (demo)",
                description="Demo seed boundary fixture",
                currency="EUR",
                status="active",
                owner_id=owner_id,
                metadata_={"demo_id": _DEMO_ID, "is_demo": True},
            )
        )
        s.add(
            Project(
                id=_FLAGSHIP_PROJECT_ID,
                name="Flagship (demo)",
                description="Demo seed boundary fixture",
                currency="USD",
                status="active",
                owner_id=owner_id,
                metadata_={"demo_id": "flagship-house"},
            )
        )
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        s.add(Contact(contact_type="client", company_name="Flagship Client", metadata_={"demo_id": "flagship-house"}))
        s.add(Contact(contact_type="client", company_name="Our Own Client", metadata_={}))
        await s.commit()

    app = _admin_app(str(owner_id))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        one = await client.delete("/api/demo/uninstall/office-frankfurt")
        assert one.status_code == 200, one.text
        async with boot_factory() as s:
            assert "office-frankfurt" in await retired_demo_ids(s)
            assert await s.get(Project, single) is None

        everything = await client.delete("/api/demo/clear-all")
        assert everything.status_code == 200, everything.text
    assert everything.json()["deleted_projects"] == 2

    async with boot_factory() as s:
        assert {_DEMO_ID, "flagship-house", "office-frankfurt"} <= await retired_demo_ids(s)
        assert await s.get(Project, showcase) is None
        assert await s.get(Project, _FLAGSHIP_PROJECT_ID) is None
        assert await s.get(Project, real) is not None
        names = set((await s.execute(select(Contact.company_name))).scalars().all())
    assert names == {"Our Own Client"}


async def test_the_demo_endpoints_are_admin_only(boot_factory) -> None:
    import httpx

    async with boot_factory() as s:
        owner_id = await _owner(s)
        demo = await _project(s, owner_id, "Office Frankfurt (demo)", demo_id="office-frankfurt")
        await s.commit()
    app = _admin_app(str(owner_id), role="editor")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.delete("/api/demo/clear-all")).status_code == 403
        assert (await client.delete("/api/demo/uninstall/office-frankfurt")).status_code == 403
    async with boot_factory() as s:
        assert await s.get(Project, demo) is not None


# ── Purge and restore ─────────────────────────────────────────────────────


async def test_the_demo_purge_takes_the_demos_own_contacts(boot_factory) -> None:
    from app.modules.contacts.models import Contact
    from app.modules.projects.service import ProjectService

    async with boot_factory() as s:
        owner_id = await _owner(s)
        await _project(s, owner_id, "Residential Berlin (demo)", demo_id=_DEMO_ID)
        s.add(Contact(contact_type="subcontractor", company_name="Demo Roofing", metadata_={"demo_id": _DEMO_ID}))
        s.add(Contact(contact_type="subcontractor", company_name="Our Roofer", metadata_={}))
        await s.commit()
    async with boot_factory() as s:
        await ProjectService(s, get_settings()).purge_demo_projects()
        await s.commit()
    async with boot_factory() as s:
        names = set((await s.execute(select(Contact.company_name))).scalars().all())
    assert names == {"Our Roofer"}


async def test_a_project_restored_from_a_backup_is_not_a_demo(boot_factory) -> None:
    """A restore makes a new project, and like a copy it must not carry the demo tag."""
    from app.core.demo_marker import demo_id_of, retired_demo_ids
    from app.modules.projects.service import ProjectService

    async with boot_factory() as s:
        owner_id = await _owner(s)
        demo = await _project(s, owner_id, "Residential Berlin (demo)", demo_id=_DEMO_ID)
        await s.commit()
    async with boot_factory() as s:
        service = ProjectService(s, get_settings())
        restored = await service.restore_project_from_backup(await service.backup_project(demo), owner_id)
        await s.commit()
    async with boot_factory() as s:
        copy = await s.get(Project, restored.project_id)
        original = await s.get(Project, demo)
        assert demo_id_of(copy.metadata_) == ""
        assert demo_id_of(original.metadata_) == _DEMO_ID
        # Deleting the restored project is deleting a real one: no demo is retired.
        await ProjectService(s, get_settings()).delete_project(restored.project_id)
        await s.commit()
    async with boot_factory() as s:
        assert await retired_demo_ids(s) == set()


# ── Cleanup: what it keeps, the CLI, the API ────────────────────────────────


async def test_the_cleanup_keeps_seed_rows_somebody_worked_on(boot_factory) -> None:
    """A seeded punch item a person edited later, and a plan a person inspected against."""
    from datetime import timedelta

    from sqlalchemy import update

    from app.core.demo_cleanup import clean_leaked_demo_rows
    from app.modules.qms.models import ITPItem
    from app.modules.qms.seed import seed_qms

    async with boot_factory() as s:
        owner_id = await _owner(s)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        await s.commit()
    async with boot_factory() as s:
        await seed_qms(s, project_id=real)
        await s.commit()

    async with boot_factory() as s:
        punches = (
            (await s.execute(select(QMSPunchItem).where(QMSPunchItem.project_id == real).order_by(QMSPunchItem.title)))
            .scalars()
            .all()
        )
        edited = punches[0]
        await s.execute(
            update(QMSPunchItem)
            .where(QMSPunchItem.id == edited.id)
            .values(updated_at=edited.created_at + timedelta(days=2))
        )
        item = (
            await s.execute(
                select(ITPItem.id).join(ITPPlan, ITPItem.itp_plan_id == ITPPlan.id).where(ITPPlan.project_id == real)
            )
        ).first()[0]
        own = QMSInspection(
            project_id=real, itp_item_id=item, location_ref="Core B, level 2", notes="Our own rebar check"
        )
        s.add(own)
        await s.commit()

    async with boot_factory() as s:
        report = await clean_leaked_demo_rows(s, apply=True)
        await s.commit()

    kept = {r.id: r.reason for r in report.kept}
    assert edited.id in kept and "changed" in kept[edited.id]
    assert any("inspection" in reason for reason in kept.values()), kept
    assert await _rows(boot_factory, ITPPlan, real) == 1
    assert await _present(boot_factory, QMSPunchItem, [edited.id]) == 1
    assert await _present(boot_factory, QMSInspection, [own.id]) == 1
    # Everything else the seed wrote went.
    assert await _rows(boot_factory, QMSPunchItem, real) == 1
    assert await _rows(boot_factory, QMSNCR, real) == 0
    assert await _rows(boot_factory, QMSAudit, real) == 0


async def test_the_cleanup_removes_the_contacts_of_a_removed_demo(boot_factory) -> None:
    from app.core.demo_cleanup import clean_leaked_demo_rows
    from app.modules.contacts.models import Contact

    async with boot_factory() as s:
        owner_id = await _owner(s)
        await _project(s, owner_id, "Warehouse Extension Leipzig")
        s.add(Contact(contact_type="client", company_name="Leftover Demo Client", metadata_={"demo_id": _DEMO_ID}))
        s.add(Contact(contact_type="client", company_name="Our Own Client", metadata_={}))
        await s.commit()
    async with boot_factory() as s:
        report = await clean_leaked_demo_rows(s, apply=True)
        await s.commit()
    assert report.marked["demo_contacts"] == 1
    async with boot_factory() as s:
        names = set((await s.execute(select(Contact.company_name))).scalars().all())
    assert names == {"Our Own Client"}


async def test_the_cli_changes_nothing_without_apply_and_commits_with_it(boot_factory) -> None:
    """``openconstructionerp demo-cleanup`` and ``demo-cleanup --apply``, through the command's own code."""
    from app.cli import run_demo_cleanup

    async with boot_factory() as s:
        owner_id = await _owner(s)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        s.add(DailyDiary(project_id=real, diary_date="2026-09-01", metadata_={"seed": True}))
        s.add(DailyDiary(project_id=real, diary_date="2026-09-02", metadata_={}))
        await s.commit()

    dry: list[str] = []
    await run_demo_cleanup(False, write=dry.append)
    assert await _rows(boot_factory, DailyDiary, real) == 2
    text = "\n".join(dry)
    assert "Warehouse Extension Leipzig" in text
    assert "daily_diary" in text
    assert "Dry run, nothing changed" in text

    applied: list[str] = []
    await run_demo_cleanup(True, write=applied.append)
    assert "Removed 1 demo row(s)." in "\n".join(applied)
    assert await _rows(boot_factory, DailyDiary, real) == 1

    again: list[str] = []
    await run_demo_cleanup(False, write=again.append)
    assert "No demo rows found in real projects." in "\n".join(again)


def _projects_api(factory, user_id: str, role: str = "admin"):
    from fastapi import FastAPI

    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.projects.router import router as projects_router

    app = FastAPI()
    app.include_router(projects_router, prefix="/v1/projects")

    async def _session():
        async with factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": user_id, "role": role, "permissions": []}
    return app


async def test_the_settings_preview_lists_rows_and_removes_only_the_confirmed_ones(boot_factory) -> None:
    import httpx

    async with boot_factory() as s:
        owner_id = await _owner(s)
        real = await _project(s, owner_id, "Warehouse Extension Leipzig")
        for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
            s.add(DailyDiary(project_id=real, diary_date=day, metadata_={"seed": True}))
        s.add(DailyDiary(project_id=real, diary_date="2026-09-04", metadata_={}))
        await s.commit()

    url = "/v1/projects/demo-data/leftovers/"
    editor = _projects_api(boot_factory, str(owner_id), role="editor")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=editor), base_url="http://test") as client:
        assert (await client.get(url)).status_code == 403
        assert (await client.post(url + "remove/", json={"ids": []})).status_code == 403

    app = _projects_api(boot_factory, str(owner_id))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        preview = await client.get(url)
        assert preview.status_code == 200, preview.text
        rows = [r for r in preview.json()["rows"] if r["table"] == DailyDiary.__tablename__]
        assert len(rows) == 3
        assert {r["project_name"] for r in rows} == {"Warehouse Extension Leipzig"}
        assert all(r["module"] == "daily_diary" and r["title"] for r in rows)
        assert await _rows(boot_factory, DailyDiary, real) == 4, "the preview removed something"

        # The person confirms two of the three; the third was not in what they saw.
        confirmed = [r["id"] for r in rows[:2]]
        done = await client.post(url + "remove/", json={"ids": confirmed})
        assert done.status_code == 200, done.text
        assert done.json()["total"] == 2
    assert await _rows(boot_factory, DailyDiary, real) == 2
    assert await _present(boot_factory, DailyDiary, [uuid.UUID(rows[2]["id"])]) == 1
