"""Payroll export period against the database: build, lock, blocked edit, export, cost posting."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payroll.period_service import PayrollPeriodService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

MON = date(2026, 10, 5)
TUE = date(2026, 10, 6)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _seed(session: AsyncSession, *, overtime_approved: bool = True) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
    from app.modules.projects.models import Project
    from app.modules.resources.models import Resource
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"pp-{uuid.uuid4().hex[:10]}@payroll.io",
        hashed_password="x",
        full_name="Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Period", owner_id=owner.id, currency="EUR", fx_rates=[], country_code="DE")
    session.add(project)
    await session.flush()
    worker = Resource(
        id=uuid.uuid4(),
        code=f"PP-{uuid.uuid4().hex[:6]}",
        name="Mason",
        resource_type="person",
        home_project_id=project.id,
        default_cost_rate=Decimal("20"),
        currency="EUR",
        status="active",
        metadata_={"personnel_number": "1001"},
    )
    sub = Resource(
        id=uuid.uuid4(),
        code=f"PS-{uuid.uuid4().hex[:6]}",
        name="Sub crew",
        resource_type="person",
        home_project_id=project.id,
        default_cost_rate=Decimal("30"),
        currency="EUR",
        status="active",
        metadata_={},
    )
    session.add_all([worker, sub])
    await session.flush()
    sheet_ids = []
    for day, lines in (
        (MON, [(worker.id, "10", None, None, None), (sub.id, "8", None, None, "subcontractor")]),
        (TUE, [(worker.id, "8", datetime(2026, 10, 6, 21, tzinfo=UTC), datetime(2026, 10, 7, 5, tzinfo=UTC), None)]),
    ):
        ts = FieldTimesheet(
            project_id=project.id,
            reference=f"FT-{uuid.uuid4().hex[:6]}",
            date=day,
            status="approved",
            metadata_={"overtime_approved": overtime_approved},
        )
        session.add(ts)
        await session.flush()
        sheet_ids.append(ts.id)
        for rid, hours, start, end, kind in lines:
            session.add(
                FieldTimesheetLine(
                    timesheet_id=ts.id,
                    resource_id=rid,
                    hours=Decimal(hours),
                    cost_code="KG330",
                    started_at=start,
                    ended_at=end,
                    employer_kind=kind,
                )
            )
    await session.flush()
    return project.id, worker.id, sheet_ids[0]


async def test_period_lines_exclude_subcontractors_and_split_pay_types(session: AsyncSession) -> None:
    project_id, _worker, _ = await _seed(session)
    period = await PayrollPeriodService(session).create(project_id, period_start=MON, period_end=TUE)
    lines = await PayrollPeriodService(session).lines(period.id)
    assert {ln.employee_name for ln in lines} == {"Mason"}
    by_type = {}
    for ln in lines:
        by_type[ln.pay_type] = by_type.get(ln.pay_type, Decimal("0")) + ln.hours
    assert by_type == {"regular": Decimal("16"), "overtime": Decimal("2"), "night_premium": Decimal("8")}
    assert period.rule_profile == "de_brtv_bau"
    # 16 x 20 + 2 x 20 x 1.25 + 8 x 20 x 0.20
    assert period.total_gross == Decimal("402.00")
    assert period.total_burden == Decimal("152.76")


async def test_export_needs_lock_and_lock_blocks_timesheet_edits(session: AsyncSession) -> None:
    from app.modules.field_time.schemas import ReverseTimesheetRequest
    from app.modules.field_time.service import FieldTimeService

    project_id, _worker, sheet_id = await _seed(session)
    svc = PayrollPeriodService(session)
    period = await svc.create(project_id, period_start=MON, period_end=TUE)
    with pytest.raises(HTTPException) as early:
        await svc.export(period.id, "csv")
    assert early.value.status_code == 409

    await svc.lock(period.id)
    with pytest.raises(HTTPException) as blocked:
        await FieldTimeService(session).reverse_timesheet(sheet_id, ReverseTimesheetRequest(note="late fix"), None)
    assert blocked.value.status_code == 409

    content, _media, name = await svc.export(period.id, "lodas", consultant_number="1234567", client_number="12345")
    assert name.endswith("_lodas.txt")
    assert b"1;01/10/2026;1001;100;1;16,00;KG330;" in content
    assert period.status == "exported"

    with pytest.raises(HTTPException):
        await svc.reopen(period.id, "  ")
    await svc.reopen(period.id, "Correct a cost code")
    assert period.status == "open"
    actions = [e.action for e in await svc.events(period.id)]
    assert actions[-1] == "reopened"


async def test_unapproved_overtime_blocks_the_export(session: AsyncSession) -> None:
    project_id, _worker, _ = await _seed(session, overtime_approved=False)
    svc = PayrollPeriodService(session)
    period = await svc.create(project_id, period_start=MON, period_end=TUE)
    await svc.lock(period.id)
    with pytest.raises(HTTPException) as exc:
        await svc.export(period.id, "json")
    assert exc.value.status_code == 409
    assert any("overtime" in m for m in exc.value.detail["findings"])


async def test_post_costs_puts_gross_plus_burden_on_the_labour_actuals(session: AsyncSession) -> None:
    from app.modules.costmodel.models import BudgetLine

    project_id, _worker, _ = await _seed(session)
    svc = PayrollPeriodService(session)
    period = await svc.create(project_id, period_start=MON, period_end=TUE)
    with pytest.raises(HTTPException):
        await svc.post_costs(period.id)
    await svc.lock(period.id)
    await svc.post_costs(period.id)
    await svc.post_costs(period.id)  # idempotent
    rows = await session.execute(
        select(BudgetLine.actual_amount).where(BudgetLine.project_id == project_id, BudgetLine.category == "labor")
    )
    assert sum((Decimal(str(v or "0")) for v in rows.scalars().all()), Decimal("0")) == Decimal("554.76")


async def test_demo_period_is_locked_exported_and_records_a_blocked_edit(session: AsyncSession) -> None:
    from app.modules.payroll.period_demo import seed_payroll_period_demo

    project_id, _worker, _ = await _seed(session)
    counts = await seed_payroll_period_demo(session, [project_id], today=date(2026, 10, 27))
    assert counts["periods"] == 1
    assert counts["blocked_edits"] == 1
    svc = PayrollPeriodService(session)
    period = (await svc.list_for_project(project_id))[0][0]
    assert period.status == "exported"
    assert period.posted_ref
    types = {ln.pay_type for ln in await svc.lines(period.id)}
    assert {"regular", "overtime", "night_premium"} <= types
    assert [e.action for e in await svc.events(period.id)][-1] == "edit_blocked"
    again = await seed_payroll_period_demo(session, [project_id], today=date(2026, 10, 27))
    assert again["periods"] == 0
