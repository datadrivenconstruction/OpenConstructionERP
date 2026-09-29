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

    # The user's diary is untouched.
    async with boot_factory() as s:
        kept = (await s.execute(select(DailyDiary.notes).where(DailyDiary.project_id == real))).scalars().all()
    assert kept == ["Poured the east footing"]

    # The quality plan carries no mark; its content is the seed's, so it goes too.
    assert report.marked["qms_itp_plans"] == 1
    assert await _rows(boot_factory, ITPPlan, real) == 0


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
    assert again.marked == dry.marked, "a person's look-alike was taken for the seed's"

    async with boot_factory() as s:
        done = await clean_leaked_demo_rows(s, apply=True)
        await s.commit()
    assert done.marked == dry.marked

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
