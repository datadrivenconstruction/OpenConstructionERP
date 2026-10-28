# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Hours booked on site, read back against the bill position that predicted them.

The money side of this report was already here. This is the other half an
estimator asks for: an estimate written from productivity norms predicts labour
hours per unit, and until the hours the crew booked can be read against the same
position the norm library cannot learn anything from the job it was used on.

Three things are worth testing and only one of them is the happy path.

A corrected day must be worth nothing. Correcting an approved timesheet does not
edit it: the original flips to ``reversed`` and a mirror sheet is written whose
hours are still POSITIVE, because in that module the sign lives on the sheet.
The obvious filter, ``status == 'approved'``, therefore drops the original and
counts the mirror at face value, reporting the cancelled hours once, in full, in
the wrong direction. Nothing but a test with a real reversed pair in it catches
that.

The per-unit figure must refuse where it has no denominator. Hours over the
BILLED quantity flatter every unfinished item and flatter an untouched one most
of all, which is the same failure as a zero risk dispersion. The control here
is the assertion that the rate is NOT the number the billed denominator would
have produced.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.costmodel.position_actuals import build_position_actuals, hours_by_position
from app.modules.field_time import field_time_math as ft
from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
from app.modules.progress.models import ProgressEntry
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


async def seed_position(session: AsyncSession, project_id: uuid.UUID) -> Position:
    """A 120 m3 concrete item, so a rate has a quantity to divide by."""
    boq = BOQ(project_id=project_id, name="Bill of quantities", description="")
    session.add(boq)
    await session.flush()
    position = Position(
        boq_id=boq.id,
        ordinal="1.1",
        description="Reinforced concrete, C30/37",
        unit="m3",
        quantity="120",
        unit_rate="180.00",
        total="21600.00",
    )
    session.add(position)
    await session.flush()
    return position


async def seed_timesheet(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    reference: str,
    status: str,
    lines: list[dict[str, object]],
    reverses_id: uuid.UUID | None = None,
) -> FieldTimesheet:
    sheet = FieldTimesheet(
        project_id=project_id,
        reference=reference,
        date=date(2026, 9, 1),
        status=status,
        reverses_id=reverses_id,
    )
    session.add(sheet)
    await session.flush()
    for spec in lines:
        session.add(FieldTimesheetLine(timesheet_id=sheet.id, **spec))
    await session.flush()
    return sheet


def labour(position_id: uuid.UUID | None, hours: str) -> dict[str, object]:
    return {
        "resource_id": uuid.uuid4(),
        "hours": Decimal(hours),
        "cost_code": "LAB-01",
        "boq_position_id": position_id,
    }


def plant(position_id: uuid.UUID | None, hours: str) -> dict[str, object]:
    return {
        "equipment_id": uuid.uuid4(),
        "hours": Decimal(hours),
        "cost_code": "PLT-01",
        "boq_position_id": position_id,
    }


async def report_hours(session: AsyncSession, project_id: uuid.UUID) -> Decimal:
    report = await build_position_actuals(session, project_id)
    (row,) = report.rows
    return row.labour_hours


class TestOnlyHoursSomebodyApprovedCount:
    """Hours nobody has approved are a proposal, not an actual."""

    async def test_approved_hours_reach_the_position(self, session: AsyncSession, project_id: uuid.UUID) -> None:
        position = await seed_position(session, project_id)
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status="approved",
            lines=[labour(position.id, "12"), labour(position.id, "9")],
        )
        assert await report_hours(session, project_id) == Decimal("21.00")

    @pytest.mark.parametrize("status", ["draft", "submitted"])
    async def test_unapproved_hours_do_not(self, session: AsyncSession, project_id: uuid.UUID, status: str) -> None:
        position = await seed_position(session, project_id)
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status=status,
            lines=[labour(position.id, "12")],
        )
        assert await report_hours(session, project_id) == Decimal("0.00")

    async def test_hours_attributed_to_nothing_stay_out_of_every_position(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        # A day that covered six items names none of them, and that has to
        # remain possible: the column exists so somebody CAN attribute a line,
        # not so every line must be attributed to something.
        position = await seed_position(session, project_id)
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status="approved",
            lines=[labour(position.id, "12"), labour(None, "8")],
        )
        assert await report_hours(session, project_id) == Decimal("12.00")


class TestACorrectedDayIsWorthNothing:
    """The reversal trap, which the obvious filter gets exactly backwards."""

    async def test_a_reversed_pair_nets_to_zero(self, session: AsyncSession, project_id: uuid.UUID) -> None:
        position = await seed_position(session, project_id)
        original = await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status="approved",
            lines=[labour(position.id, "12")],
        )
        # What reverse_timesheet writes: the original flips to reversed and the
        # mirror carries the SAME positive hours with reverses_id set.
        original.status = "reversed"
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0002",
            status="approved",
            lines=[labour(position.id, "12")],
            reverses_id=original.id,
        )
        await session.flush()

        assert await report_hours(session, project_id) == Decimal("0.00")

    async def test_a_reversal_does_not_leave_its_mirror_standing(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        # The failing half of the pair above, asserted on its own so a
        # regression says which side broke. Filtering on status alone would
        # report 12 here: the original is gone and the mirror is approved.
        position = await seed_position(session, project_id)
        original = await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status="reversed",
            lines=[labour(position.id, "12")],
        )
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0002",
            status="approved",
            lines=[labour(position.id, "12")],
            reverses_id=original.id,
        )
        booked = await hours_by_position(session, project_id, [position.id])
        assert booked == {}

    async def test_a_day_that_was_never_corrected_still_counts(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        # The control for the rule above: excluding reversals must not be
        # excluding ordinary approved sheets by accident.
        position = await seed_position(session, project_id)
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status="approved",
            lines=[labour(position.id, "7.5")],
        )
        assert await report_hours(session, project_id) == Decimal("7.50")

    def test_the_reversal_mirror_carries_the_position(self) -> None:
        """A credit attributed nowhere cannot cancel a debit attributed somewhere.

        This module drops both halves, so netting here survives a mirror that
        forgot the position. ``ft.net_hours`` does not: it sums signed
        contributions, and a reversal with no position leaves the original
        hours standing against it for ever.
        """
        position_id = str(uuid.uuid4())
        (mirrored,) = ft.reverse_lines(
            [
                {
                    "resource_id": str(uuid.uuid4()),
                    "hours": Decimal("12"),
                    "cost_code": "LAB-01",
                    "wbs": None,
                    "boq_position_id": position_id,
                    "is_daywork": False,
                    "variation_id": None,
                    "note": "",
                }
            ]
        )
        assert mirrored["boq_position_id"] == position_id


class TestLabourAndPlantAnswerDifferentQuestions:
    """Only one of the two compares with a productivity norm."""

    async def test_plant_hours_are_not_labour_hours(self, session: AsyncSession, project_id: uuid.UUID) -> None:
        position = await seed_position(session, project_id)
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status="approved",
            lines=[labour(position.id, "12"), plant(position.id, "5")],
        )
        report = await build_position_actuals(session, project_id)
        (row,) = report.rows
        assert row.labour_hours == Decimal("12.00")
        assert row.plant_hours == Decimal("5.00")
        assert report.totals["labour_hours"] == Decimal("12.00")
        assert report.totals["plant_hours"] == Decimal("5.00")


class TestTheRateRefusesWhereThereIsNoDenominator:
    """A rate with no denominator is not a rate, and a blank says so."""

    async def test_hours_with_no_progress_report_no_rate(self, session: AsyncSession, project_id: uuid.UUID) -> None:
        position = await seed_position(session, project_id)
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status="approved",
            lines=[labour(position.id, "21")],
        )
        report = await build_position_actuals(session, project_id)
        (row,) = report.rows
        assert row.labour_hours == Decimal("21.00")
        assert row.labour_hours_per_installed_unit is None

    async def test_the_denominator_is_what_is_installed_not_what_was_billed(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        position = await seed_position(session, project_id)
        session.add(
            ProgressEntry(
                project_id=project_id,
                boq_position_id=position.id,
                percent_complete="50",
                period_label="2026-09",
            )
        )
        await seed_timesheet(
            session,
            project_id,
            reference="FT-0001",
            status="approved",
            lines=[labour(position.id, "21")],
        )
        report = await build_position_actuals(session, project_id)
        (row,) = report.rows
        # 21 hours over the 60 m3 actually in place.
        assert row.labour_hours_per_installed_unit == Decimal("0.3500")
        # The control, and the whole reason the property is named for its
        # denominator: over the billed 120 m3 the same crew would post 0.175
        # and read as twice as productive as it is.
        assert row.labour_hours_per_installed_unit != Decimal("0.1750")
