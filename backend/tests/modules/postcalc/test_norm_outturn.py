# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a production norm predicted, against what the job actually cost.

Issue #457 asks for one number an estimator cannot get today: for a given
production norm, what did the estimates built from it allow, and what did the
work booked against those estimates really consume. Half of it shipped. The
write side records which norm a position was priced from; nothing read it back,
so the comparison the issue exists for stayed impossible.

The test that matters here is the end-to-end one, and it is worth saying why the
obvious test is not it. Asserting that a position carries a norm id passes the
moment the column exists and says nothing about whether anybody can answer the
question. That assertion would have been green for the whole time the feature
was unusable, which is exactly how this was missed once already. So the contract
asserted below is the answer, not the plumbing: build a real norm, price two
bill positions from it, book hours and progress against both, and ask what the
norm predicted versus what it cost.

Two positions rather than one, deliberately. A norm is reused across a bill -
that is the point of a norm - so a rollup that silently reported only the first
position it found, or averaged two factors instead of dividing summed hours by
summed earned hours, would pass a one-position test and be wrong on every real
job.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assemblies.schemas import ApplyToBOQRequest
from app.modules.assemblies.service import AssemblyService
from app.modules.boq.models import BOQ, Position
from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
from app.modules.labor_rates.models import LaborRateTemplate, OnCostComponent
from app.modules.norm_expansion.models import ProductionNorm
from app.modules.norm_expansion.service import build_assembly_from_norm
from app.modules.postcalc.model import (
    STATUS_NO_ACTUALS,
    STATUS_NO_PROGRESS,
    STATUS_UNDER_PRODUCTIVE,
)
from app.modules.postcalc.service import PostCalcService
from app.modules.progress.models import ProgressEntry
from tests._pg import transactional_session

D = Decimal


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # FKs off for the same reason the position-actuals suite turns them off: a
    # timesheet line points at a resources row this test has no interest in
    # creating, and the reference is not what is under test.
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


async def seed_norm(session: AsyncSession, *, labour_hours: str = "0.45") -> ProductionNorm:
    """A plastering norm at ``labour_hours`` per m2, with no materials.

    No materials on purpose: the material half needs a cost catalogue to match
    against and it is not what this test is asking about. Labour hours are, and
    they are the half a productivity norm is judged on.
    """
    norm = ProductionNorm(
        work_key=f"plastering_internal_{uuid.uuid4().hex[:8]}",
        name="Internal plastering",
        unit="m2",
        category="finishing",
        labor_hours_per_unit=D(labour_hours),
        machine_hours_per_unit=D("0"),
        is_active=True,
    )
    session.add(norm)
    await session.flush()
    return norm


async def seed_labour_template(session: AsyncSession) -> LaborRateTemplate:
    """A template building up to 36.00/h all-in (30 base plus 20 percent)."""
    template = LaborRateTemplate(name="Plasterer", base_wage=D("30"), currency="EUR")
    template.components.append(
        OnCostComponent(label="Statutory charges", kind="percentage", value=D("20"), sort_order=0)
    )
    session.add(template)
    await session.flush()
    return template


async def seed_bill(session: AsyncSession, project_id: uuid.UUID) -> BOQ:
    boq = BOQ(project_id=project_id, name="Bill of quantities", description="")
    session.add(boq)
    await session.flush()
    return boq


async def book_hours(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    reference: str,
    position_id: uuid.UUID,
    hours: str,
    status: str = "approved",
) -> FieldTimesheet:
    sheet = FieldTimesheet(
        project_id=project_id,
        reference=reference,
        date=date(2026, 9, 1),
        status=status,
        reverses_id=None,
    )
    session.add(sheet)
    await session.flush()
    session.add(
        FieldTimesheetLine(
            timesheet_id=sheet.id,
            resource_id=uuid.uuid4(),
            hours=D(hours),
            cost_code="LAB-01",
            boq_position_id=position_id,
        )
    )
    await session.flush()
    return sheet


async def report_progress(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    position_id: uuid.UUID,
    percent: str,
) -> None:
    session.add(
        ProgressEntry(
            project_id=project_id,
            boq_position_id=position_id,
            percent_complete=percent,
            period_label="2026-09",
        )
    )
    await session.flush()


async def price_two_positions_from(
    session: AsyncSession,
    norm: ProductionNorm,
    boq: BOQ,
    *,
    project_id: uuid.UUID,
    quantities: tuple[float, float] = (100.0, 50.0),
) -> tuple[Position, Position]:
    """Build an assembly from the norm and apply it to the bill twice.

    The ordinals are passed explicitly. Left empty, apply-to-boq derives one
    from the assembly code, so applying the same assembly to the same bill a
    second time collides on it and 409s - which is a real edge of that endpoint
    and not what this test is about.
    """
    template = await seed_labour_template(session)
    assembly = await build_assembly_from_norm(
        session,
        norm.id,
        labor_rate_template_id=template.id,
        project_id=project_id,
        currency="EUR",
        apply_waste=False,
    )
    service = AssemblyService(session)
    first = await service.apply_to_boq(
        assembly.id, ApplyToBOQRequest(boq_id=boq.id, quantity=quantities[0], ordinal="1.1")
    )
    second = await service.apply_to_boq(
        assembly.id, ApplyToBOQRequest(boq_id=boq.id, quantity=quantities[1], ordinal="1.2")
    )
    return first, second


class TestTheComparisonIsAnswerableEndToEnd:
    """The contract the issue is actually about."""

    async def test_a_norm_reports_what_it_predicted_and_what_it_cost(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        norm = await seed_norm(session, labour_hours="0.45")
        boq = await seed_bill(session, project_id)
        first, second = await price_two_positions_from(session, norm, boq, project_id=project_id)

        # Half of each item is in place: 50 m2 and 25 m2, 75 m2 installed.
        await report_progress(session, project_id, position_id=first.id, percent="50")
        await report_progress(session, project_id, position_id=second.id, percent="50")
        # The norm allowed 0.45 h/m2, so 75 m2 in place earned 33.75 hours. The
        # crew booked 40, which is over the allowance and must read as such.
        await book_hours(session, project_id, reference="FT-0001", position_id=first.id, hours="27")
        await book_hours(session, project_id, reference="FT-0002", position_id=second.id, hours="13")

        report = await PostCalcService(session).norm_outturn(project_id)

        rows = {row.work_key: row for row in report.norms}
        assert norm.work_key in rows, "the norm the bill was priced from is not in the report"
        row = rows[norm.work_key]

        # Both positions rolled up, not just the first one found.
        assert row.positions == 2
        assert row.bill_quantity == D("150.0000")

        # The predicted side, read from the norm row that is still there.
        assert row.norm_row_present is True
        assert row.norm_labour_hours_per_unit == D("0.450000")
        assert row.norm_labour_hours == D("67.50")

        # The outturn side.
        assert row.installed_quantity == D("75.0000")
        assert row.actual_labour_hours == D("40.00")

        # Summed numerator over summed denominator, never an average of two
        # factors: 40 booked against 33.75 earned is 1.1852.
        assert row.norm_earned_hours == D("33.75")
        assert row.norm_productivity_factor == D("1.1852")
        assert row.status == STATUS_UNDER_PRODUCTIVE

    async def test_the_bill_baseline_and_the_norm_baseline_are_reported_apart(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        """Two different questions that a single "estimated" number would blur.

        What the bill says is fixed at the moment it was priced and is what the
        client was offered. What the norm says is read live from a row anybody
        can edit. They agree here, and the point of the assertion is that both
        are reported so they can be seen to disagree when they do.
        """
        norm = await seed_norm(session, labour_hours="0.45")
        boq = await seed_bill(session, project_id)
        await price_two_positions_from(session, norm, boq, project_id=project_id)

        report = await PostCalcService(session).norm_outturn(project_id)
        (row,) = [r for r in report.norms if r.work_key == norm.work_key]

        assert row.bill_labour_hours == D("67.50")
        assert row.norm_labour_hours == D("67.50")

        # Editing the norm moves the norm baseline and must not move the bill.
        norm.labor_hours_per_unit = D("0.60")
        await session.flush()

        report = await PostCalcService(session).norm_outturn(project_id)
        (row,) = [r for r in report.norms if r.work_key == norm.work_key]
        assert row.bill_labour_hours == D("67.50"), "the offered estimate changed under an edit to the library"
        assert row.norm_labour_hours == D("90.00")

    async def test_a_norm_whose_row_is_gone_still_reports_its_bill_and_its_outturn(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        """Provenance is copied, not resolved, so deleting the norm cannot erase it.

        This is the whole reason the identity was copied onto the position
        instead of being resolved through the assembly at read time. A report
        that dropped the row would say the work was never estimated.
        """
        norm = await seed_norm(session, labour_hours="0.45")
        work_key = norm.work_key
        boq = await seed_bill(session, project_id)
        first, _second = await price_two_positions_from(session, norm, boq, project_id=project_id)
        await report_progress(session, project_id, position_id=first.id, percent="50")
        await book_hours(session, project_id, reference="FT-0001", position_id=first.id, hours="27")

        await session.delete(norm)
        await session.flush()

        report = await PostCalcService(session).norm_outturn(project_id)
        (row,) = [r for r in report.norms if r.work_key == work_key]

        assert row.norm_row_present is False
        assert row.norm_labour_hours is None
        assert row.norm_productivity_factor is None
        # The bill said what it said, and the crew booked what it booked.
        assert row.bill_labour_hours == D("67.50")
        assert row.actual_labour_hours == D("27.00")


class TestWhatItSaysWhenItCannotAnswer:
    """A norm with nothing recorded against it gets a status, never a zero."""

    async def test_no_actuals_at_all_is_said_rather_than_reported_as_nothing_spent(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        norm = await seed_norm(session)
        boq = await seed_bill(session, project_id)
        await price_two_positions_from(session, norm, boq, project_id=project_id)

        report = await PostCalcService(session).norm_outturn(project_id)
        (row,) = [r for r in report.norms if r.work_key == norm.work_key]

        assert row.status == STATUS_NO_ACTUALS
        assert row.norm_productivity_factor is None
        assert row.productivity_factor is None

    async def test_hours_booked_against_nothing_installed_is_not_a_productivity_result(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        norm = await seed_norm(session)
        boq = await seed_bill(session, project_id)
        first, _second = await price_two_positions_from(session, norm, boq, project_id=project_id)
        await book_hours(session, project_id, reference="FT-0001", position_id=first.id, hours="27")

        report = await PostCalcService(session).norm_outturn(project_id)
        (row,) = [r for r in report.norms if r.work_key == norm.work_key]

        assert row.status == STATUS_NO_PROGRESS
        assert row.actual_labour_hours == D("27.00")
        assert row.norm_productivity_factor is None


class TestThePositionsNobodyPricedFromANorm:
    """Most of a real bill is typed by hand and carries no norm at all."""

    async def test_a_hand_typed_position_is_counted_not_invented_into_a_norm(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        norm = await seed_norm(session)
        boq = await seed_bill(session, project_id)
        await price_two_positions_from(session, norm, boq, project_id=project_id)
        session.add(
            Position(
                boq_id=boq.id,
                ordinal="9.1",
                description="Site hoarding, typed by hand",
                unit="m",
                quantity="40",
                unit_rate="25.00",
                total="1000.00",
            )
        )
        await session.flush()

        report = await PostCalcService(session).norm_outturn(project_id)

        assert report.positions_without_norm == 1
        assert all(r.work_key != "" for r in report.norms)
        assert len(report.norms) == 1


class TestTheProvenanceSurvivesTheShapeItWasWrittenIn:
    """Rows priced before the column existed carry the identity in metadata."""

    async def test_a_position_carrying_only_the_metadata_still_reaches_the_report(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        """The read side has to coalesce, or the feature starts empty.

        The write side landed before the column did, so every bill priced from a
        norm between those two moments has ``metadata["norm_id"]`` set and a
        NULL column. Reading the column alone would report those jobs as never
        having been estimated from a norm, which is the state the issue is
        complaining about, restated.
        """
        norm = await seed_norm(session)
        boq = await seed_bill(session, project_id)
        session.add(
            Position(
                boq_id=boq.id,
                ordinal="1.1",
                description="Internal plastering, priced before the column existed",
                unit="m2",
                quantity="100",
                unit_rate="16.20",
                total="1620.00",
                source="assembly",
                metadata_={
                    "assembly_id": str(uuid.uuid4()),
                    "norm_id": str(norm.id),
                    "work_key": norm.work_key,
                    "resources": [
                        {"type": "labor", "unit": "h", "quantity": "0.45", "unit_rate": "36.00"},
                    ],
                },
            )
        )
        await session.flush()

        report = await PostCalcService(session).norm_outturn(project_id)
        (row,) = [r for r in report.norms if r.work_key == norm.work_key]

        assert row.positions == 1
        assert row.bill_labour_hours == D("45.00")


class TestScope:
    """The limits, asserted rather than only written down."""

    async def test_another_project_bill_priced_from_the_same_norm_stays_out(
        self, session: AsyncSession, project_id: uuid.UUID
    ) -> None:
        """Money is per project and so is the currency it is reported in."""
        norm = await seed_norm(session)
        boq = await seed_bill(session, project_id)
        await price_two_positions_from(session, norm, boq, project_id=project_id)

        other_project = uuid.uuid4()
        other_boq = await seed_bill(session, other_project)
        await price_two_positions_from(session, norm, other_boq, project_id=other_project)

        report = await PostCalcService(session).norm_outturn(project_id)
        (row,) = [r for r in report.norms if r.work_key == norm.work_key]

        assert row.positions == 2, "another project's bill was rolled into this project's norm"
        assert row.bill_quantity == D("150.0000")


@pytest.mark.parametrize("percent", ["0", "100"])
async def test_progress_of_zero_and_of_one_hundred_are_both_real_readings(
    session: AsyncSession, project_id: uuid.UUID, percent: str
) -> None:
    """A reported zero is a reading; an unreported position is not.

    Both go through the same guard, so the parametrisation is the control: at
    100 percent the factor exists, at 0 percent it must not, and neither may
    raise.
    """
    norm = await seed_norm(session, labour_hours="0.45")
    boq = await seed_bill(session, project_id)
    first, _second = await price_two_positions_from(session, norm, boq, project_id=project_id)
    await report_progress(session, project_id, position_id=first.id, percent=percent)
    await book_hours(session, project_id, reference="FT-0001", position_id=first.id, hours="27")

    report = await PostCalcService(session).norm_outturn(project_id)
    (row,) = [r for r in report.norms if r.work_key == norm.work_key]

    if percent == "0":
        assert row.norm_productivity_factor is None
    else:
        assert row.norm_productivity_factor is not None
