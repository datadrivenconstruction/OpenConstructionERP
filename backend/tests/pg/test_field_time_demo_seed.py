# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The Field Time demo seed must fill the register, and fill it only once.

Field Time shipped with no timesheet data anywhere, so the screen rendered
byte-identical on every demo project. The seeder that fixes that has three ways
to be wrong that a green exit code cannot show, so each is pinned here against a
real database:

* it writes rows the application itself would reject (every row goes through
  ``FieldTimeService``, so a validation error surfaces as a raised exception and
  an empty register rather than as bad data);
* it doubles the register on the second boot, because idempotency in this
  codebase is per loop rather than per seeder;
* it produces rows the downstream readers cannot use. Payroll only counts a line
  that is approved, not a reversal, and carries a ``resource_id``; a register
  full of drafts reads as zero there and no error is raised anywhere.

The last one is asserted through the payroll collector itself rather than by
restating its ``WHERE`` clause, so a change to what payroll counts fails here.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.boq.models import BOQ, Position
from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
from app.modules.field_time.seed import seed_field_time_demo
from app.modules.projects.models import Project
from app.modules.resources.models import Resource
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

_CODES = ("01.10.010", "01.20.020", "03.30.030", "05.40.040")


async def _make_project(session, name: str) -> uuid.UUID:
    """Build the minimum a project needs before hours can be booked to it."""
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
            description="Field time seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()

    for index in range(4):
        session.add(
            Resource(
                id=uuid.uuid4(),
                code=f"{name[:4]}-P-{index:03d}",
                name=f"Worker {index}",
                resource_type="person",
                home_project_id=project_id,
                default_cost_rate=Decimal("42.50"),
                currency="EUR",
                status="active",
                metadata_={},
            )
        )

    boq_id = uuid.uuid4()
    session.add(
        BOQ(
            id=boq_id,
            project_id=project_id,
            name="Fixture BOQ",
            description="",
            status="draft",
            metadata_={},
        )
    )
    await session.flush()
    for code in _CODES:
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq_id,
                ordinal=code,
                reference_code=code,
                description=f"Position {code}",
                unit="m2",
                quantity="10",
                unit_rate="100",
                total="1000",
                metadata_={},
            )
        )
    await session.flush()
    return project_id


async def _count(session, project_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(FieldTimesheet).where(FieldTimesheet.project_id == project_id)
        )
    ).scalar_one()


async def _statuses(session, project_id: uuid.UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            select(FieldTimesheet.status, func.count())
            .where(FieldTimesheet.project_id == project_id)
            .group_by(FieldTimesheet.status)
        )
    ).all()
    return {status: int(count) for status, count in rows}


async def test_the_register_is_populated_and_mixed(pg_session) -> None:
    """A seeded project shows weeks of hours across more than one status."""
    project_id = await _make_project(pg_session, "Tower")

    counts = await seed_field_time_demo(pg_session, [project_id])
    await pg_session.flush()

    assert counts["timesheets"] >= 15, f"only {counts['timesheets']} timesheet(s) seeded"
    assert await _count(pg_session, project_id) == counts["timesheets"]

    statuses = await _statuses(pg_session, project_id)
    # A register where everything is approved teaches nothing about the workflow.
    assert set(statuses) >= {"draft", "submitted", "approved"}, f"only saw {sorted(statuses)}"
    assert counts["reversals"] >= 1, "no reversal seeded, so the reversing correction is never shown"
    assert statuses.get("reversed", 0) >= 1, "a reversal was counted but no original flipped to 'reversed'"

    # Every line has to name a worker or a machine, hours and a cost code the
    # estimate actually uses - the same three things the validation rules check.
    lines = (
        (
            await pg_session.execute(
                select(FieldTimesheetLine)
                .join(FieldTimesheet, FieldTimesheetLine.timesheet_id == FieldTimesheet.id)
                .where(FieldTimesheet.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    assert lines, "timesheets were written with no lines"
    for line in lines:
        assert bool(line.resource_id) != bool(line.equipment_id), "line is neither labour nor plant, or is both"
        assert Decimal(str(line.hours)) > 0
        assert line.cost_code in _CODES, f"line coded to {line.cost_code!r}, which is not in the project BOQ"


async def test_a_second_pass_adds_no_timesheets(pg_session) -> None:
    """Running the seed twice must not double the register."""
    project_id = await _make_project(pg_session, "Depot")

    await seed_field_time_demo(pg_session, [project_id])
    await pg_session.flush()
    after_first = await _count(pg_session, project_id)
    assert after_first > 0

    second = await seed_field_time_demo(pg_session, [project_id])
    await pg_session.flush()
    assert second["timesheets"] == 0, f"the second pass wrote {second['timesheets']} timesheet(s) again"
    assert await _count(pg_session, project_id) == after_first


async def test_payroll_reads_real_hours_from_the_seeded_rows(pg_session) -> None:
    """The hours must arrive at the module downstream of them, not just exist.

    Payroll counts a line only when its sheet is approved, is not a reversal and
    the line names a worker. Seeded rows that miss any of those read as zero
    there and nothing raises, so the check runs through payroll's own collector.
    """
    from app.modules.payroll.service import PayrollService

    project_id = await _make_project(pg_session, "Wharf")
    await seed_field_time_demo(pg_session, [project_id])
    await pg_session.flush()

    rows = await PayrollService(pg_session)._collect_field_timesheet_hours(
        project_id,
        date_from=None,
        date_to=None,
    )
    assert rows, "payroll sees no hours at all from the seeded register"
    total = sum(Decimal(str(row["hours"])) for row in rows)
    # A month of a four-person gang is hundreds of hours, not a handful.
    assert total > Decimal("100"), f"payroll totals only {total} hours"
    assert all(row["source"] == "field_timesheet" for row in rows)


async def test_no_two_projects_get_the_same_register(pg_session) -> None:
    """A reader flipping between demo projects must see a different picture each time.

    Six projects, not two. The history length used to be drawn per project from
    a tuple of four, so two projects collided one run in four and this test
    passed most of the time while the defect was live. Six also runs past the
    end of that tuple, which is where a wrap that adds too little would put a
    later project back onto an earlier project's register.
    """
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
    projects = [await _make_project(pg_session, name) for name in names]

    await seed_field_time_demo(pg_session, projects)
    await pg_session.flush()

    def _shape(rows: list[tuple]) -> list[tuple]:
        return sorted((str(day), status) for day, status in rows)

    async def _rows(project_id: uuid.UUID) -> list[tuple]:
        return (
            await pg_session.execute(
                select(FieldTimesheet.date, FieldTimesheet.status).where(FieldTimesheet.project_id == project_id)
            )
        ).all()

    shapes = {name: _shape(await _rows(pid)) for name, pid in zip(names, projects, strict=True)}
    assert all(shapes.values()), f"a project got no register at all: {[n for n, s in shapes.items() if not s]}"

    seen: dict[tuple, str] = {}
    for name, shape in shapes.items():
        key = tuple(shape)
        clash = seen.get(key)
        assert clash is None, (
            f"{name} and {clash} rendered the same register, which is the defect this seed exists to fix"
        )
        seen[key] = name
