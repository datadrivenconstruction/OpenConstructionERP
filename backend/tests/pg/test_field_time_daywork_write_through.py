# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Approving a daywork timesheet must post the hours, whatever daywork does.

Approving a field timesheet mirrors each daywork line onto a daywork sheet in
Variations. That mirror is documented as best-effort - "the hours actuals must
post even if the daywork write-through hiccups" - and two things made that
promise false on PostgreSQL, the only database the platform supports:

* ``next_sheet_number`` numbered a new sheet ``COUNT(*) + 1``. A count is only a
  free number while the existing numbers run 1..n with no gaps, and the demo
  estate numbers its sheets across all projects at once, so a project holding
  DW-0008 and DW-0031 had a count of 2 and was handed DW-0003, then DW-0008.
  The unique constraint rejected it.
* ``except Exception`` around the write-through does not undo a failed
  statement. PostgreSQL marks the whole transaction aborted, so the very next
  statement - the update that posts the approval - died with
  ``PendingRollbackError``. The approval was lost, not merely the daywork sheet.

Both are asserted here rather than in the module's own unit tests because
neither is visible on SQLite or in memory: they need a real transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.field_time.schemas import FieldTimesheetCreate, FieldTimesheetLineCreate
from app.modules.field_time.service import FieldTimeService
from app.modules.projects.models import Project
from app.modules.resources.models import Resource
from app.modules.users.models import User
from app.modules.variations.models import DayworkSheet, VariationOrder
from app.modules.variations.repository import DayworkSheetRepository

pytestmark = pytest.mark.asyncio


async def _fixture(session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Return ``(project_id, resource_id, variation_id)`` ready to book against."""
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{uuid.uuid4().hex[:8]}@example.test",
            hashed_password="x",
            full_name="Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()

    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name="Daywork fixture",
            description="",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()

    resource_id = uuid.uuid4()
    session.add(
        Resource(
            id=resource_id,
            code=f"DW-{uuid.uuid4().hex[:6]}",
            name="Worker",
            resource_type="person",
            home_project_id=project_id,
            default_cost_rate=Decimal("40"),
            currency="EUR",
            status="active",
            metadata_={},
        )
    )
    variation_id = uuid.uuid4()
    session.add(
        VariationOrder(
            id=variation_id,
            project_id=project_id,
            code="VO-001",
            title="Instructed extra works",
            currency="EUR",
            status="issued",
            metadata_={},
        )
    )
    await session.flush()
    return project_id, resource_id, variation_id


def _sheet(project_id: uuid.UUID, number: str) -> DayworkSheet:
    return DayworkSheet(
        id=uuid.uuid4(),
        project_id=project_id,
        sheet_number=number,
        work_date=str(date(2026, 1, 5)),
        description="Pre-existing sheet",
        currency="EUR",
        status="signed",
    )


async def _approve_a_daywork_timesheet(session, project_id, resource_id, variation_id) -> str:
    """Book, submit and approve one daywork timesheet. Returns its final status."""
    service = FieldTimeService(session)
    timesheet = await service.create_timesheet(
        FieldTimesheetCreate(
            project_id=project_id,
            date=datetime.now(UTC).date(),
            lines=[
                FieldTimesheetLineCreate(
                    resource_id=resource_id,
                    hours=Decimal("6"),
                    cost_code="01.10.010",
                    is_daywork=True,
                    variation_id=variation_id,
                ),
            ],
        ),
        str(uuid.uuid4()),
    )
    await service.submit_timesheet(timesheet.id, str(uuid.uuid4()))
    approved = await service.approve_timesheet(timesheet.id, str(uuid.uuid4()))
    return approved.status


async def test_a_gappy_sheet_number_sequence_still_yields_a_free_number(pg_session) -> None:
    """The next number must clear what is taken, not count what is there."""
    project_id, _resource_id, _variation_id = await _fixture(pg_session)
    for number in ("DW-0008", "DW-0031"):
        pg_session.add(_sheet(project_id, number))
    await pg_session.flush()

    minted = await DayworkSheetRepository(pg_session).next_sheet_number(project_id)
    assert minted == "DW-0032", f"minted {minted}, which collides with an existing sheet"


async def test_approval_posts_hours_when_the_project_already_has_daywork_sheets(pg_session) -> None:
    """The end-to-end path the demo estate walks into: sheets already numbered."""
    project_id, resource_id, variation_id = await _fixture(pg_session)
    for number in ("DW-0008", "DW-0031"):
        pg_session.add(_sheet(project_id, number))
    await pg_session.flush()

    status = await _approve_a_daywork_timesheet(pg_session, project_id, resource_id, variation_id)
    assert status == "approved", f"the timesheet ended as {status!r}, so the hours never posted"

    total = (
        await pg_session.execute(
            select(func.count()).select_from(DayworkSheet).where(DayworkSheet.project_id == project_id)
        )
    ).scalar_one()
    assert total == 3, f"expected the mirrored sheet alongside the two existing ones, found {total}"


async def test_a_database_failure_inside_the_write_through_does_not_lose_the_approval(
    pg_session,
    monkeypatch,
) -> None:
    """Pin the savepoint, not merely the ``except``.

    The injected failure has to be a real database error: a plain ``raise`` is
    caught by the ``except`` either way and would pass with or without the
    savepoint, proving nothing. This one aborts the transaction, which is what
    used to take the approval down with it.
    """
    from app.modules.variations.service import VariationsService

    project_id, resource_id, variation_id = await _fixture(pg_session)
    pg_session.add(_sheet(project_id, "DW-0001"))
    await pg_session.flush()

    async def _collide(self, data, user_id=None):  # noqa: ANN001, ANN202 - test double
        self.session.add(_sheet(data.project_id, "DW-0001"))
        await self.session.flush()

    monkeypatch.setattr(VariationsService, "create_daywork_sheet", _collide)

    status = await _approve_a_daywork_timesheet(pg_session, project_id, resource_id, variation_id)
    assert status == "approved", f"the timesheet ended as {status!r}: a failed daywork write took the approval with it"
