# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Field-time timesheet lifecycle + payroll integration (CI-only, PostgreSQL).

Exercises the full ``draft -> submitted -> approved`` lifecycle, the validation
gate (a 24 h over-booking blocks submission), reversal netting, approved-sheet
immutability, and the payroll hand-off (an approved timesheet becomes the
authoritative source of field labour hours). Runs against a transaction-isolated
PostgreSQL session - the only dialect the app runs on - rolled back on teardown,
so it is CI-only (the local Python 3.11 runner cannot import ``app.database``).

The pure engine is covered separately and DB-free in
``tests/unit/test_field_time_math.py``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.field_time.schemas import (
    FieldTimesheetCreate,
    FieldTimesheetLineCreate,
    FieldTimesheetUpdate,
    ReverseTimesheetRequest,
)
from app.modules.field_time.service import FieldTimeService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

_WORK_DATE = date(2026, 7, 3)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _seed_project(session: AsyncSession, *, currency: str = "EUR") -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"ft-{uuid.uuid4().hex[:10]}@field.io",
        hashed_password="x",
        full_name="Field Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()

    project = Project(
        id=uuid.uuid4(),
        name="Field time project",
        owner_id=owner.id,
        currency=currency,
        fx_rates=[],
    )
    session.add(project)
    await session.flush()
    return project.id


async def _seed_resource(
    session: AsyncSession,
    *,
    rate: str = "50",
    currency: str = "EUR",
) -> uuid.UUID:
    from app.modules.resources.models import Resource

    resource = Resource(
        id=uuid.uuid4(),
        code=f"R-{uuid.uuid4().hex[:8]}",
        name="Carpenter",
        resource_type="person",
        default_cost_rate=Decimal(rate),
        currency=currency,
    )
    session.add(resource)
    await session.flush()
    return resource.id


def _create_payload(
    project_id: uuid.UUID,
    resource_id: uuid.UUID,
    *,
    hours: str = "8",
    cost_code: str = "01.10",
) -> FieldTimesheetCreate:
    return FieldTimesheetCreate(
        project_id=project_id,
        date=_WORK_DATE,
        lines=[
            FieldTimesheetLineCreate(resource_id=resource_id, hours=Decimal(hours), cost_code=cost_code),
        ],
    )


async def test_full_lifecycle_draft_submit_approve(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    resource_id = await _seed_resource(session)
    service = FieldTimeService(session)
    actor = str(uuid.uuid4())

    timesheet = await service.create_timesheet(_create_payload(project_id, resource_id), actor)
    assert timesheet.status == "draft"
    assert timesheet.reference.startswith("FT-")
    assert len(timesheet.lines) == 1

    submitted = await service.submit_timesheet(timesheet.id, actor)
    assert submitted.status == "submitted"
    assert submitted.submitted_by is not None

    approved = await service.approve_timesheet(timesheet.id, actor)
    assert approved.status == "approved"
    assert approved.approved_by is not None


async def test_submit_blocked_when_worker_exceeds_24h(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    resource_id = await _seed_resource(session)
    service = FieldTimeService(session)

    timesheet = await service.create_timesheet(
        _create_payload(project_id, resource_id, hours="25"),
        None,
    )
    with pytest.raises(HTTPException) as exc:
        await service.submit_timesheet(timesheet.id, None)
    assert exc.value.status_code == 422
    # Still a draft - a blocked submit must not advance the status.
    reloaded = await service.get_timesheet(timesheet.id)
    assert reloaded.status == "draft"


async def test_line_must_be_labour_xor_plant(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    service = FieldTimeService(session)

    # Neither a resource nor equipment -> 422 at create time.
    bad = FieldTimesheetCreate(
        project_id=project_id,
        date=_WORK_DATE,
        lines=[FieldTimesheetLineCreate(hours=Decimal("8"), cost_code="01.10")],
    )
    with pytest.raises(HTTPException) as exc:
        await service.create_timesheet(bad, None)
    assert exc.value.status_code == 422


async def test_reverse_approved_timesheet_flips_original_and_nets(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    resource_id = await _seed_resource(session)
    service = FieldTimeService(session)

    timesheet = await service.create_timesheet(_create_payload(project_id, resource_id), None)
    await service.submit_timesheet(timesheet.id, None)
    await service.approve_timesheet(timesheet.id, None)

    reversal = await service.reverse_timesheet(timesheet.id, ReverseTimesheetRequest(note="typo"), None)
    assert reversal.reverses_id == timesheet.id
    assert reversal.status == "approved"
    assert len(reversal.lines) == 1

    original = await service.get_timesheet(timesheet.id)
    assert original.status == "reversed"


async def test_approved_timesheet_is_immutable(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    resource_id = await _seed_resource(session)
    service = FieldTimeService(session)

    timesheet = await service.create_timesheet(_create_payload(project_id, resource_id), None)
    await service.submit_timesheet(timesheet.id, None)
    await service.approve_timesheet(timesheet.id, None)

    with pytest.raises(HTTPException) as exc:
        await service.update_timesheet(timesheet.id, FieldTimesheetUpdate(note="late edit"))
    assert exc.value.status_code == 400


async def test_payroll_uses_approved_timesheet_hours(session: AsyncSession) -> None:
    from app.modules.payroll.service import PayrollService

    project_id = await _seed_project(session)
    resource_id = await _seed_resource(session, rate="50", currency="EUR")
    service = FieldTimeService(session)

    timesheet = await service.create_timesheet(
        _create_payload(project_id, resource_id, hours="8"),
        None,
    )
    await service.submit_timesheet(timesheet.id, None)

    payroll = PayrollService(session)
    # Before approval the draft/submitted hours are NOT authoritative.
    cost_before, hours_before, _base = await payroll.labour_cost(project_id)
    assert hours_before == Decimal("0.00")

    await service.approve_timesheet(timesheet.id, None)
    cost_after, hours_after, base = await payroll.labour_cost(project_id)
    assert hours_after == Decimal("8.00")
    assert cost_after == Decimal("400.00")  # 8 h x 50
    assert base == "EUR"


async def test_payroll_nets_a_reversed_timesheet_to_zero(session: AsyncSession) -> None:
    from app.modules.payroll.service import PayrollService

    project_id = await _seed_project(session)
    resource_id = await _seed_resource(session)
    service = FieldTimeService(session)

    timesheet = await service.create_timesheet(_create_payload(project_id, resource_id), None)
    await service.submit_timesheet(timesheet.id, None)
    await service.approve_timesheet(timesheet.id, None)
    await service.reverse_timesheet(timesheet.id, ReverseTimesheetRequest(), None)

    payroll = PayrollService(session)
    _cost, hours, _base = await payroll.labour_cost(project_id)
    # Original flips to 'reversed' (excluded) and the reversal carries
    # reverses_id (excluded), so the net authoritative labour is zero.
    assert hours == Decimal("0.00")


async def test_a_line_can_name_the_bill_position_the_hours_went_on(session: AsyncSession) -> None:
    """Issue #454. Hours are worth comparing only against what predicted them.

    A cost code is free text on the project chart and a WBS path is a tree
    address. Neither resolves to a position id, so before this the recorded
    hours could be grouped by cost code and never set beside the estimate line
    they belong to.
    """
    project_id = await _seed_project(session)
    resource_id = await _seed_resource(session)
    position_id = uuid.uuid4()
    service = FieldTimeService(session)

    timesheet = await service.create_timesheet(
        FieldTimesheetCreate(
            project_id=project_id,
            date=_WORK_DATE,
            lines=[
                FieldTimesheetLineCreate(
                    resource_id=resource_id,
                    hours=Decimal("8"),
                    cost_code="01.10",
                    boq_position_id=position_id,
                ),
                # Unattributed on purpose: a day that covered several items
                # names none of them, and that has to stay possible.
                FieldTimesheetLineCreate(resource_id=resource_id, hours=Decimal("2"), cost_code="01.20"),
            ],
        ),
        str(uuid.uuid4()),
    )

    attributed, unattributed = sorted(timesheet.lines, key=lambda ln: ln.cost_code)
    assert attributed.boq_position_id == position_id
    assert unattributed.boq_position_id is None


async def test_a_reversal_carries_the_position_it_is_cancelling(session: AsyncSession) -> None:
    """A credit attributed nowhere cannot cancel a debit attributed somewhere.

    Consumers net a corrected day either by dropping both sheets or by summing
    signed contributions. The second one needs the position on both halves.
    """
    project_id = await _seed_project(session)
    resource_id = await _seed_resource(session)
    position_id = uuid.uuid4()
    service = FieldTimeService(session)
    actor = str(uuid.uuid4())

    timesheet = await service.create_timesheet(
        FieldTimesheetCreate(
            project_id=project_id,
            date=_WORK_DATE,
            lines=[
                FieldTimesheetLineCreate(
                    resource_id=resource_id,
                    hours=Decimal("8"),
                    cost_code="01.10",
                    boq_position_id=position_id,
                )
            ],
        ),
        actor,
    )
    await service.submit_timesheet(timesheet.id, actor)
    await service.approve_timesheet(timesheet.id, actor)

    reversal = await service.reverse_timesheet(timesheet.id, ReverseTimesheetRequest(note="wrong item"), actor)

    (mirrored,) = reversal.lines
    assert mirrored.boq_position_id == position_id
