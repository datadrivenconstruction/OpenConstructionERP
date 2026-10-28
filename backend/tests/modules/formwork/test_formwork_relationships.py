# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The declared loading strategy on every formwork relationship.

Per ``.claude/rules/backend-modules.md`` a green test lane is NOT evidence that
a loading strategy is right - a lane that never walks the relationship passes
whatever the strategy is. These tests walk each one deliberately:

* ``FormworkAssignment.schedule_lines`` is ``selectin``, so it must be
  populated on an instance the session just loaded, with no further SQL.
* ``FormworkScheduleLine.assignment`` and ``FormworkAssignment.system`` are
  ``raise_on_sql``, so touching them on an instance loaded alone must raise
  with the relationship named, and must NOT raise when the parent was already
  brought in eagerly. That difference is the whole reason the policy says
  ``raise_on_sql`` rather than ``raise``.
* ``cascade="all, delete-orphan"`` on ``schedule_lines`` still deletes the
  children even though the collection is walked through a strategy that
  refuses ad-hoc SQL.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import selectinload


@pytest_asyncio.fixture(scope="module")
async def tables():
    """Create the schema once for this module.

    ``Base.metadata`` only knows the models that have been imported, so the
    three modules these tests touch are imported before ``create_all`` rather
    than relying on whatever an earlier suite happened to pull in.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    import app.modules.formwork.models  # noqa: F401 - registers the tables
    import app.modules.projects.models  # noqa: F401 - FK target
    import app.modules.users.models  # noqa: F401 - project owner
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return True


@pytest_asyncio.fixture
async def seeded(tables):
    """One system, one assignment and two pour lines.

    The assignment's ``project_id`` points at a real project row (the column is
    FK-constrained) and the project needs an owner, so both are created through
    the ORM here rather than the API - this file is about the mapping, not the
    HTTP layer.
    """
    from app.database import async_session_factory
    from app.modules.formwork.models import (
        FormworkAssignment,
        FormworkScheduleLine,
        FormworkSystem,
    )
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async with async_session_factory() as session:
        tag = uuid.uuid4().hex[:8]
        owner = User(
            email=f"formwork-rel-{tag}@test.io",
            hashed_password="not-a-real-hash",
            full_name=f"Formwork Relations {tag}",
            role="admin",
        )
        session.add(owner)
        await session.flush()

        project = Project(
            name=f"Formwork relationships {tag}",
            owner_id=owner.id,
        )
        session.add(project)
        await session.flush()

        system = FormworkSystem(
            name=f"Relationship system {uuid.uuid4().hex[:6]}",
            system_type="wall",
            material="steel",
            reuses_max=100,
            unit_rate=Decimal("65.00"),
            erect_strike_rate=Decimal("16.00"),
            strip_time_days=1,
            currency="EUR",
        )
        session.add(system)
        await session.flush()

        assignment = FormworkAssignment(
            project_id=project.id,
            formwork_system_id=system.id,
            area_m2=Decimal("400.00"),
            reuse_count=2,
            waste_pct=Decimal("5.00"),
            computed_unit_cost=Decimal("50.13"),
            material_unit_cost=Decimal("34.13"),
            labour_unit_cost=Decimal("16.00"),
            computed_total=Decimal("20052.00"),
        )
        session.add(assignment)
        await session.flush()

        for pour_no in (1, 2):
            session.add(
                FormworkScheduleLine(
                    project_id=project.id,
                    assignment_id=assignment.id,
                    pour_no=pour_no,
                    level_label=f"L{pour_no:02d}",
                    area_m2=Decimal("200.00"),
                ),
            )
        await session.commit()
        return {
            "project_id": project.id,
            "system_id": system.id,
            "assignment_id": assignment.id,
        }


async def test_schedule_lines_are_loaded_eagerly(seeded):
    """The pour cycle is the point of the parent, so it arrives with it."""
    from app.database import async_session_factory
    from app.modules.formwork.models import FormworkAssignment

    async with async_session_factory() as session:
        assignment = await session.get(FormworkAssignment, seeded["assignment_id"])
        assert assignment is not None
        # No eager option was requested here - selectin on the model is what
        # makes this read work at all.
        assert len(assignment.schedule_lines) == 2
        assert [line.pour_no for line in assignment.schedule_lines] == [1, 2]


async def test_the_system_back_reference_refuses_lazy_sql(seeded):
    """``assignment.system`` on a bare get must raise, not quietly query."""
    from app.database import async_session_factory
    from app.modules.formwork.models import FormworkAssignment

    async with async_session_factory() as session:
        assignment = await session.get(FormworkAssignment, seeded["assignment_id"])
        assert assignment is not None
        with pytest.raises(InvalidRequestError) as excinfo:
            _ = assignment.system
        # The error names the relationship, at the point of touch.
        assert "system" in str(excinfo.value)


async def test_the_system_reads_freely_when_it_was_loaded_eagerly(seeded):
    """``raise_on_sql`` allows the free read - that is why it is not ``raise``.

    A strategy that also refused this would break every correct call site,
    which is exactly the trade-off the loading policy documents.
    """
    from app.database import async_session_factory
    from app.modules.formwork.models import FormworkAssignment

    async with async_session_factory() as session:
        stmt = (
            select(FormworkAssignment)
            .where(FormworkAssignment.id == seeded["assignment_id"])
            .options(selectinload(FormworkAssignment.system))
        )
        assignment = (await session.execute(stmt)).scalars().one()
        assert assignment.system is not None
        assert assignment.system.unit_rate == Decimal("65.00")


async def test_the_pour_line_parent_back_reference_refuses_lazy_sql(seeded):
    """Walking up from a line loaded on its own must raise."""
    from app.database import async_session_factory
    from app.modules.formwork.models import FormworkScheduleLine

    async with async_session_factory() as session:
        stmt = select(FormworkScheduleLine).where(
            FormworkScheduleLine.assignment_id == seeded["assignment_id"],
        )
        line = (await session.execute(stmt)).scalars().first()
        assert line is not None
        with pytest.raises(InvalidRequestError) as excinfo:
            _ = line.assignment
        assert "assignment" in str(excinfo.value)


async def test_the_pour_line_parent_reads_freely_from_the_loaded_collection(seeded):
    """Coming down through ``schedule_lines`` leaves the parent in memory."""
    from app.database import async_session_factory
    from app.modules.formwork.models import FormworkAssignment

    async with async_session_factory() as session:
        assignment = await session.get(FormworkAssignment, seeded["assignment_id"])
        assert assignment is not None
        line = assignment.schedule_lines[0]
        # The parent is already the identity-mapped object; no SQL is needed.
        assert line.assignment is assignment


async def test_the_catalogue_assignments_collection_refuses_lazy_sql(seeded):
    """One catalogue row can back every assignment on every project."""
    from app.database import async_session_factory
    from app.modules.formwork.models import FormworkSystem

    async with async_session_factory() as session:
        system = await session.get(FormworkSystem, seeded["system_id"])
        assert system is not None
        with pytest.raises(InvalidRequestError) as excinfo:
            _ = list(system.assignments)
        assert "assignments" in str(excinfo.value)


async def test_deleting_an_assignment_still_cascades_to_its_pour_lines(seeded):
    """``raise_on_sql`` on the child side does not break delete-orphan."""
    from sqlalchemy import func

    from app.database import async_session_factory
    from app.modules.formwork.models import FormworkAssignment, FormworkScheduleLine

    async with async_session_factory() as session:
        assignment = await session.get(FormworkAssignment, seeded["assignment_id"])
        assert assignment is not None
        await session.delete(assignment)
        await session.commit()

    async with async_session_factory() as session:
        remaining = await session.execute(
            select(func.count(FormworkScheduleLine.id)).where(
                FormworkScheduleLine.assignment_id == seeded["assignment_id"],
            ),
        )
        assert remaining.scalar_one() == 0
