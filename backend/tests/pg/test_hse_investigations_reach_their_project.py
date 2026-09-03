# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""An HSE investigation is only real if its project can reach it.

The seeder minted a fresh ``uuid4()`` for every investigation's ``incident_ref``
and so wrote ten rows that belong to no incident anywhere. Nothing about the
table could show it: the rows are present, well formed and non-null, and a count
over them reads exactly like a populated register. What decides is the join -
``InvestigationRepository.list_for_project`` resolves scope through
``oe_safety_incident``, so an id matching no incident is scoped to no project.
Incidents are the module's default tab, which is why the module read as empty on
arrival while six other tabs were full.

Every assertion below therefore goes through the repository's own project-scoped
read. A test that counted rows would have passed on the broken seeder.

The second failure is the guard. The seeder's own rule was that any populated
HSE Advanced table makes the whole seed a no-op, so on the databases that carry
the bug - the ones already seeded - a corrected block would never run. A
table-wide guard on the investigations table itself would fail the same way,
satisfied for good by the ten unreachable rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.hse_advanced.models import HSEIncidentInvestigation, ToolboxTopic
from app.modules.hse_advanced.repository import InvestigationRepository
from app.modules.hse_advanced.seed import seed_hse_advanced_demo
from app.modules.projects.models import Project
from app.modules.safety.models import SafetyIncident
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _make_project(session, name: str, *, incidents: int) -> uuid.UUID:
    """A project carrying ``incidents`` safety incidents, as the demo estate does.

    The demo projects hold between one and four each (the hand-written demos one
    or two, the generated ones four), so those are the shapes worth fixturing.
    """
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.replace(' ', '-').lower()}@example.test",
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
            description="HSE investigation fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()
    for index in range(incidents):
        session.add(
            SafetyIncident(
                project_id=project_id,
                incident_number=f"INC-{index + 1:03d}",
                title=f"{name} incident {index + 1}",
                incident_date="2026-05-04",
                location="Level 2, east core",
                incident_type="near_miss",
                severity="moderate",
                description="Material fell from the leading edge; no one was struck.",
                corrective_actions=[],
                status="closed",
                metadata_={},
            )
        )
    await session.flush()
    return project_id


def _block_the_bulk_seed(session) -> None:
    """Put the seeder in the state every already-seeded database is in.

    One row in any HSE Advanced sentinel table turns the bulk seed into a no-op.
    Used where the test is about the investigations and not about the other nine
    thousand rows, so it also keeps the run short.
    """
    session.add(
        ToolboxTopic(
            code="TBX-EXISTING",
            title="Existing library entry",
            content="Already on the shelf before this seed ran.",
            category="general",
            language="en",
            duration_minutes=10,
            version="1.0",
            is_active=True,
        )
    )


async def _reachable(session, project_id: uuid.UUID) -> list[HSEIncidentInvestigation]:
    """The investigations the project's own screen would list."""
    rows, _total = await InvestigationRepository(session).list_for_project(project_id)
    return rows


async def _own_incident_ids(session, project_id: uuid.UUID) -> set[str]:
    rows = (
        (await session.execute(select(SafetyIncident.id).where(SafetyIncident.project_id == project_id)))
        .scalars()
        .all()
    )
    return {str(r) for r in rows}


async def test_every_project_with_an_incident_can_reach_an_investigation(pg_session) -> None:
    """Coverage and reachability in one read, per project.

    The seeded investigations must come back from the project-scoped query, and
    each one must name an incident that project actually owns.
    """
    many = await _make_project(pg_session, "HSE many", incidents=4)
    few = await _make_project(pg_session, "HSE few", incidents=1)
    _block_the_bulk_seed(pg_session)

    await seed_hse_advanced_demo(pg_session, [many, few])
    await pg_session.flush()

    for project_id, label in ((many, "four incidents"), (few, "one incident")):
        rows = await _reachable(pg_session, project_id)
        assert rows, f"project with {label} has no investigation on its own tab"
        owned = await _own_incident_ids(pg_session, project_id)
        assert {str(r.incident_ref) for r in rows} <= owned, f"investigation points outside the project ({label})"


async def test_a_project_with_no_incidents_gets_no_investigation(pg_session) -> None:
    """Nothing to investigate must stay nothing, not a row pointing nowhere."""
    quiet = await _make_project(pg_session, "HSE quiet", incidents=0)
    _block_the_bulk_seed(pg_session)

    await seed_hse_advanced_demo(pg_session, [quiet])
    await pg_session.flush()

    assert await _reachable(pg_session, quiet) == []


async def test_investigations_land_on_an_already_seeded_database(pg_session) -> None:
    """The assertion the whole-module guard cannot pass.

    Every install that already ran this seeder has eight populated tables, so a
    corrected investigations block sitting behind the module-wide sentinel would
    never execute on any of them.
    """
    project_id = await _make_project(pg_session, "HSE already seeded", incidents=3)
    _block_the_bulk_seed(pg_session)

    counts = await seed_hse_advanced_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts.get("skipped") == 1, "the bulk seed was expected to short-circuit here"
    assert counts.get("investigations", 0) > 0, "the investigations block was skipped with the bulk tables"
    assert await _reachable(pg_session, project_id), "no investigation is reachable from the project"


async def test_unreachable_rows_do_not_satisfy_the_guard(pg_session) -> None:
    """Ten orphans in the table are exactly what the shipped databases hold.

    A guard asking "does this table have rows" is satisfied by them for good,
    and every project stays empty behind a check that reads as passing.
    """
    project_id = await _make_project(pg_session, "HSE orphans", incidents=2)
    for _ in range(10):
        pg_session.add(
            HSEIncidentInvestigation(
                incident_ref=uuid.uuid4(),
                started_at=datetime.now(UTC),
                method="5_whys",
                findings="Belongs to no incident.",
                recommendations="",
                status="in_progress",
            )
        )
    _block_the_bulk_seed(pg_session)
    await pg_session.flush()

    await seed_hse_advanced_demo(pg_session, [project_id])
    await pg_session.flush()

    assert await _reachable(pg_session, project_id), "a table-wide guard was satisfied by the orphan rows"


async def test_a_second_run_does_not_double_the_investigations(pg_session) -> None:
    project_id = await _make_project(pg_session, "HSE twice", incidents=4)
    _block_the_bulk_seed(pg_session)

    await seed_hse_advanced_demo(pg_session, [project_id])
    await pg_session.flush()
    first = [str(r.id) for r in await _reachable(pg_session, project_id)]

    await seed_hse_advanced_demo(pg_session, [project_id])
    await pg_session.flush()

    assert sorted(str(r.id) for r in await _reachable(pg_session, project_id)) == sorted(first)


async def test_a_project_seeded_later_is_not_locked_out(pg_session) -> None:
    """The guard is per project, so a project added afterwards still gets covered."""
    early = await _make_project(pg_session, "HSE early", incidents=2)
    _block_the_bulk_seed(pg_session)
    await seed_hse_advanced_demo(pg_session, [early])
    await pg_session.flush()
    before = len(await _reachable(pg_session, early))

    late = await _make_project(pg_session, "HSE late", incidents=3)
    await seed_hse_advanced_demo(pg_session, [early, late])
    await pg_session.flush()

    assert len(await _reachable(pg_session, early)) == before, "the already-covered project was seeded again"
    assert await _reachable(pg_session, late), "the later project was skipped"


async def test_the_full_seed_on_an_empty_database_also_reaches_the_project(pg_session) -> None:
    """The fresh-install path, with every other block running as well."""
    project_id = await _make_project(pg_session, "HSE fresh", incidents=2)

    counts = await seed_hse_advanced_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts.get("investigations", 0) > 0
    assert counts.get("jsas", 0) > 0, "the bulk seed did not run on an empty database"
    assert await _reachable(pg_session, project_id)
