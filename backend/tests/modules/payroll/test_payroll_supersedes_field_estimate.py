"""An approved payroll batch and the field logs it was built from count once.

Field labour is costed onto the budget as it is logged, at the resource rate.
A payroll batch is generated from those same field records and, on approval,
posts what the people are paid. Both used to stay on the budget, so every day a
batch covered read as paid twice on the EVM and BI screens. The invariant
asserted here is the money one: the project's labour actual after approval is
the payroll figure for the covered days plus the field estimate for the days
payroll does not cover, never the sum of both for the same day.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine, LabourWorkerDay
from app.modules.costmodel.service import LabourActualsService
from app.modules.payroll.models import PayrollBatch, PayrollEntry
from app.modules.payroll.service import PayrollService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

DAY_1 = "2026-06-01"
DAY_2 = "2026-06-02"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.projects.models import Project
    from app.modules.resources.models import Resource
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"q11-{uuid.uuid4().hex[:10]}@payroll.io",
        hashed_password="x",
        full_name="Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Two budgets", owner_id=owner.id, currency="EUR", fx_rates=[])
    session.add(project)
    await session.flush()
    resource = Resource(
        id=uuid.uuid4(),
        code=f"Q11-{uuid.uuid4().hex[:6]}",
        name="Crew member",
        resource_type="person",
        home_project_id=project.id,
        default_cost_rate=Decimal("40"),
        currency="EUR",
        status="active",
        metadata_={},
    )
    session.add(resource)
    await session.flush()
    return project.id, resource.id


async def _batch(session: AsyncSession, project_id: uuid.UUID, entries: list[tuple[uuid.UUID | None, str, str]]):
    total = sum((Decimal(amount) for _r, _d, amount in entries), Decimal("0"))
    batch = PayrollBatch(
        project_id=project_id,
        period_label="Week 2026-W23",
        period_start=DAY_1,
        period_end=DAY_1,
        status="draft",
        currency="EUR",
        total_hours="8.00",
        total_amount=str(total),
        entry_count=len(entries),
    )
    session.add(batch)
    await session.flush()
    for resource_id, work_date, amount in entries:
        session.add(
            PayrollEntry(
                batch_id=batch.id,
                resource_id=resource_id,
                worker="crew",
                work_date=work_date,
                hours="8.00",
                rate="45.0000",
                amount=amount,
                currency="EUR",
                source="field_timesheet",
            )
        )
    await session.flush()
    return batch


async def _labour_actual(session: AsyncSession, project_id: uuid.UUID) -> Decimal:
    """Every labour actual on the project, across all labour lines."""
    rows = await session.execute(
        select(BudgetLine.actual_amount).where(BudgetLine.project_id == project_id, BudgetLine.category == "labor")
    )
    return sum((Decimal(str(value or "0")) for value in rows.scalars().all()), Decimal("0"))


async def _log(service: LabourActualsService, project_id, report_id, work_date, rows) -> Decimal:
    return await service.apply_labour_event(
        project_id=project_id,
        report_id=report_id,
        status_value="approved",
        rows=rows,
        work_date=work_date,
        source_module="field_time",
    )


async def test_a_covered_day_is_counted_once_at_the_payroll_figure(session: AsyncSession) -> None:
    project_id, resource_id = await _seed(session)
    field = LabourActualsService(session)
    named = [{"resource_id": str(resource_id), "hours": 8}]

    assert await _log(field, project_id, "ts-day1", DAY_1, named) == Decimal("320")
    assert await _log(field, project_id, "ts-day2", DAY_2, named) == Decimal("320")
    assert await _labour_actual(session, project_id) == Decimal("640")

    batch = await _batch(session, project_id, [(resource_id, DAY_1, "360.00")])
    batch_id = batch.id
    await PayrollService(session).finalize_batch(batch_id)
    session.expire_all()

    # Day 1 at payroll (360) plus day 2 still at the field estimate (320).
    # Without the supersede this read 1000: day 1 counted at 320 and 360.
    assert await _labour_actual(session, project_id) == Decimal("680")

    claim = (
        await session.execute(
            select(LabourWorkerDay).where(LabourWorkerDay.project_id == project_id, LabourWorkerDay.work_date == DAY_1)
        )
    ).scalar_one()
    assert claim.source_module == "payroll"
    assert claim.source_ref == str(batch_id)


async def test_a_field_log_after_approval_does_not_cost_the_paid_day_again(session: AsyncSession) -> None:
    project_id, resource_id = await _seed(session)
    batch = await _batch(session, project_id, [(resource_id, DAY_1, "360.00")])
    await PayrollService(session).finalize_batch(batch.id)

    late = await _log(
        LabourActualsService(session), project_id, "late-diary", DAY_1, [{"resource_id": str(resource_id), "hours": 8}]
    )
    session.expire_all()
    assert late == Decimal("0")
    assert await _labour_actual(session, project_id) == Decimal("360")


async def test_reversing_a_superseded_field_log_does_not_refund_payroll_money(session: AsyncSession) -> None:
    project_id, resource_id = await _seed(session)
    field = LabourActualsService(session)
    named = [{"resource_id": str(resource_id), "hours": 8}]
    await _log(field, project_id, "ts-day1", DAY_1, named)

    batch = await _batch(session, project_id, [(resource_id, DAY_1, "360.00")])
    await PayrollService(session).finalize_batch(batch.id)

    refunded = await field.reverse_labour_event(
        project_id=project_id,
        report_id="ts-day1-rev",
        reverses_id="ts-day1",
        rows=named,
        work_date=DAY_1,
        source_module="field_time",
    )
    session.expire_all()
    assert refunded == Decimal("0")
    assert await _labour_actual(session, project_id) == Decimal("360")


async def test_unnamed_headcount_is_superseded_by_date(session: AsyncSession) -> None:
    project_id, _resource_id = await _seed(session)
    field = LabourActualsService(session)
    await _log(field, project_id, "fr-day1", DAY_1, [{"hours": 8, "cost_rate": "30", "currency": "EUR"}])
    assert await _labour_actual(session, project_id) == Decimal("240")

    batch = await _batch(session, project_id, [(None, DAY_1, "250.00")])
    await PayrollService(session).finalize_batch(batch.id)
    session.expire_all()
    assert await _labour_actual(session, project_id) == Decimal("250")


async def test_finalize_twice_supersedes_once(session: AsyncSession) -> None:
    project_id, resource_id = await _seed(session)
    field = LabourActualsService(session)
    await _log(field, project_id, "ts-day1", DAY_1, [{"resource_id": str(resource_id), "hours": 8}])

    batch = await _batch(session, project_id, [(resource_id, DAY_1, "360.00")])
    svc = PayrollService(session)
    await svc.finalize_batch(batch.id)
    await svc.finalize_batch(batch.id)
    again = await field.supersede_with_payroll(
        project_id=project_id,
        batch_id=str(batch.id),
        entries=[{"resource_id": str(resource_id), "work_date": DAY_1, "hours": "8"}],
    )
    session.expire_all()
    assert again == Decimal("0")
    assert await _labour_actual(session, project_id) == Decimal("360")
