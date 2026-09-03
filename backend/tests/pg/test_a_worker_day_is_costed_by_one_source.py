# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""One shift, two honest records, one entry on the budget.

A foreman punches the crew in and out on a phone; the diary publishes those
hours to the cost model when the entry is approved. Somebody in the office fills
in the desktop timesheet for the same site and the same day; that publishes too.
Both records are true. Together they used to make the project look like it had
paid twice for one shift, and no screen said which day it was.

The cost model's only guard was ``(report_id, status)``. That stops a message
being delivered twice and cannot see this at all: the diary entry and the
timesheet have different ids by construction. The claim asserted here is the
coarser one a person can actually check - project, day, worker.

These are PostgreSQL tests because the guard leans on a unique constraint to
settle the race between two sources arriving at once, and a constraint that is
never exercised against a real transaction is a comment.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.costmodel.models import BudgetLine, LabourWorkerDay
from app.modules.costmodel.service import _LABOUR_LINE_MARKER, LabourActualsService
from app.modules.field_time.schemas import FieldTimesheetCreate, FieldTimesheetLineCreate
from app.modules.field_time.service import FieldTimeService
from app.modules.projects.models import Project
from app.modules.resources.models import Resource
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

WORK_DAY = "2026-06-04"


async def _fixture(session, *, rate: str = "40") -> tuple[uuid.UUID, uuid.UUID]:
    """Return ``(project_id, resource_id)`` with a costable hourly rate."""
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
            name="Worker-day fixture",
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
            code=f"WD-{uuid.uuid4().hex[:6]}",
            name="Marta Nowak",
            resource_type="person",
            home_project_id=project_id,
            default_cost_rate=Decimal(rate),
            currency="EUR",
            status="active",
            metadata_={},
        )
    )
    await session.flush()
    return project_id, resource_id


def _row(resource_id: uuid.UUID, hours: float = 8.0) -> dict:
    return {
        "worker_type": "labour",
        "hours": hours,
        "headcount": 1,
        "resource_id": str(resource_id),
        "cost_rate": "40",
        "currency": "EUR",
    }


async def _actual(session, project_id: uuid.UUID) -> Decimal:
    """The auto-maintained labour line's posted actual, or zero."""
    result = await session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))
    for line in result.scalars().all():
        md = line.metadata_ if isinstance(line.metadata_, dict) else {}
        if md.get("kind") == _LABOUR_LINE_MARKER:
            return Decimal(str(line.actual_amount or "0"))
    return Decimal("0")


async def test_the_second_source_does_not_cost_the_day_again(pg_session) -> None:
    """The phone books the day; the office timesheet finds it already booked."""
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)

    from_phone = await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-entry-1",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )
    assert from_phone == Decimal("320")

    from_office = await service.apply_labour_event(
        project_id=project_id,
        report_id="timesheet-1",
        status_value="approved",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert from_office == Decimal("0"), "the same worker-day reached the budget twice"
    assert await _actual(pg_session, project_id) == Decimal("320")


async def test_the_claim_names_the_source_that_took_it(pg_session) -> None:
    """An approver asking why a day was skipped has to be able to find out."""
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-entry-1",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )

    claim = (
        await pg_session.execute(select(LabourWorkerDay).where(LabourWorkerDay.project_id == project_id))
    ).scalar_one()
    assert claim.work_date == WORK_DAY
    assert claim.resource_id == str(resource_id)
    assert claim.source_module == "field_diary"
    assert claim.source_ref == "diary-entry-1"
    assert claim.hours == Decimal("8")


async def test_a_different_day_for_the_same_worker_still_costs(pg_session) -> None:
    """The claim is per day. Tuesday must not block Wednesday."""
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-1",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )
    second = await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-2",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date="2026-06-05",
        source_module="field_diary",
    )
    assert second == Decimal("320")
    assert await _actual(pg_session, project_id) == Decimal("640")


async def test_a_second_worker_on_a_claimed_day_still_costs(pg_session) -> None:
    """The claim is per worker. Marta's day must not block Piotr's."""
    project_id, marta = await _fixture(pg_session)
    piotr = uuid.uuid4()
    pg_session.add(
        Resource(
            id=piotr,
            code=f"WD-{uuid.uuid4().hex[:6]}",
            name="Piotr Kowal",
            resource_type="person",
            home_project_id=project_id,
            default_cost_rate=Decimal("40"),
            currency="EUR",
            status="active",
            metadata_={},
        )
    )
    await pg_session.flush()

    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-1",
        status_value="submitted",
        rows=[_row(marta)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )
    # The office sheet holds both of them. Marta is already costed, Piotr is not.
    mixed = await service.apply_labour_event(
        project_id=project_id,
        report_id="timesheet-1",
        status_value="approved",
        rows=[_row(marta), _row(piotr)],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert mixed == Decimal("320"), "the partly-claimed sheet costed all of itself or none"
    assert await _actual(pg_session, project_id) == Decimal("640")


async def test_hours_with_no_worker_are_costed_rather_than_dropped(pg_session) -> None:
    """A typed name has no id, so there is nothing to prove a duplicate with.

    Refusing those hours to avoid a duplicate nobody can demonstrate would lose
    real work. They are costed and left for a human to reconcile, which is the
    case the field roster picker exists to make rare.
    """
    project_id, _resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    nameless = {"worker_type": "labour", "hours": 8.0, "cost_rate": "40", "currency": "EUR"}

    first = await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-1",
        status_value="submitted",
        rows=[nameless],
        work_date=WORK_DAY,
        source_module="field_diary",
    )
    second = await service.apply_labour_event(
        project_id=project_id,
        report_id="timesheet-1",
        status_value="approved",
        rows=[nameless],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert first == Decimal("320")
    assert second == Decimal("320")
    claims = (
        await pg_session.execute(select(func.count(LabourWorkerDay.id)).where(LabourWorkerDay.project_id == project_id))
    ).scalar_one()
    assert claims == 0, "a row with no worker claimed a day it cannot identify"


async def test_an_event_with_no_date_behaves_exactly_as_before(pg_session) -> None:
    """An older publisher that sends no work date is not silently changed.

    Without a date there is no claim to take, and inventing one would be a
    guess. The guard stands down and the event is costed the way it was before
    this table existed.
    """
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    first = await service.apply_labour_event(
        project_id=project_id,
        report_id="legacy-1",
        status_value="submitted",
        rows=[_row(resource_id)],
    )
    second = await service.apply_labour_event(
        project_id=project_id,
        report_id="legacy-2",
        status_value="submitted",
        rows=[_row(resource_id)],
    )
    assert first == Decimal("320")
    assert second == Decimal("320")


async def test_a_redelivered_event_is_still_counted_once(pg_session) -> None:
    """The replay guard has to keep working now that a claim sits beside it."""
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    kwargs = {
        "project_id": project_id,
        "report_id": "diary-1",
        "status_value": "submitted",
        "rows": [_row(resource_id)],
        "work_date": WORK_DAY,
        "source_module": "field_diary",
    }
    assert await service.apply_labour_event(**kwargs) == Decimal("320")
    assert await service.apply_labour_event(**kwargs) == Decimal("0")
    assert await _actual(pg_session, project_id) == Decimal("320")


async def test_approving_a_timesheet_sends_its_labour_hours_to_cost(pg_session) -> None:
    """Approval used to move no money at all, while saying that it did.

    ``field_time.timesheet_approved`` carries a rollup and has no subscriber, so
    the desktop timesheet's hours reached nothing. They now go down the same
    pipe the diary uses, per worker, because an aggregate cannot tell the cost
    model whose day it is.
    """
    from app.core.events import event_bus
    from app.modules.costmodel.service import _on_labour_logged

    project_id, resource_id = await _fixture(pg_session)

    captured: list[dict] = []

    async def _capture(event: object) -> None:
        captured.append(dict(getattr(event, "data", None) or {}))

    # The real consumer opens a session of its own against a database this lane
    # does not bind, so it stands aside while the publish is what is asserted.
    event_bus.unsubscribe("fieldreports.labour.logged", _on_labour_logged)
    event_bus.subscribe("fieldreports.labour.logged", _capture)
    try:
        service = FieldTimeService(pg_session)
        timesheet = await service.create_timesheet(
            FieldTimesheetCreate(
                project_id=project_id,
                date=date(2026, 6, 4),
                lines=[
                    FieldTimesheetLineCreate(
                        resource_id=resource_id,
                        hours=Decimal("8"),
                        cost_code="01.10.010",
                    ),
                ],
            ),
            str(uuid.uuid4()),
        )
        await service.submit_timesheet(timesheet.id, str(uuid.uuid4()))
        await service.approve_timesheet(timesheet.id, str(uuid.uuid4()))
    finally:
        event_bus.unsubscribe("fieldreports.labour.logged", _capture)
        event_bus.subscribe("fieldreports.labour.logged", _on_labour_logged)

    assert captured, "approving a timesheet published nothing to the cost model"
    payload = captured[-1]
    assert payload["report_date"] == WORK_DAY
    assert payload["status"] == "approved"
    assert payload["source_module"] == "field_time"
    rows = payload["rows"]
    assert len(rows) == 1
    assert rows[0]["resource_id"] == str(resource_id)
    assert rows[0]["hours"] == 8.0


async def test_a_timesheet_of_plant_only_publishes_no_labour(pg_session) -> None:
    """Machine hours are not labour and do not belong on the labour line.

    Publishing them here would put plant on a budget line named for people and
    then claim a worker-day for a machine, blocking the person who ran it.
    """
    from app.core.events import event_bus
    from app.modules.costmodel.service import _on_labour_logged
    from app.modules.equipment.models import Equipment

    project_id, _resource_id = await _fixture(pg_session)
    equipment_id = uuid.uuid4()
    pg_session.add(
        Equipment(
            id=equipment_id,
            code=f"EQ-{uuid.uuid4().hex[:6]}",
            name="Excavator",
            status="available",
            metadata_={},
        )
    )
    await pg_session.flush()

    captured: list[dict] = []

    async def _capture(event: object) -> None:
        captured.append(dict(getattr(event, "data", None) or {}))

    event_bus.unsubscribe("fieldreports.labour.logged", _on_labour_logged)
    event_bus.subscribe("fieldreports.labour.logged", _capture)
    try:
        service = FieldTimeService(pg_session)
        timesheet = await service.create_timesheet(
            FieldTimesheetCreate(
                project_id=project_id,
                date=date(2026, 6, 4),
                lines=[
                    FieldTimesheetLineCreate(
                        equipment_id=equipment_id,
                        hours=Decimal("6"),
                        cost_code="01.10.010",
                    ),
                ],
            ),
            str(uuid.uuid4()),
        )
        await service.submit_timesheet(timesheet.id, str(uuid.uuid4()))
        await service.approve_timesheet(timesheet.id, str(uuid.uuid4()))
    finally:
        event_bus.unsubscribe("fieldreports.labour.logged", _capture)
        event_bus.subscribe("fieldreports.labour.logged", _on_labour_logged)

    assert captured == [], "plant hours were published as labour"


async def test_a_claim_survives_the_worker_being_deleted(pg_session) -> None:
    """Deleting a leaver must not reopen every day they ever worked.

    The claim holds the worker key as text on purpose. A cascading foreign key
    would take the claim with the person, and the next timesheet touching those
    days would cost them a second time months later.
    """
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-1",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )

    resource = await pg_session.get(Resource, resource_id)
    await pg_session.delete(resource)
    await pg_session.flush()

    surviving = (
        await pg_session.execute(select(func.count(LabourWorkerDay.id)).where(LabourWorkerDay.project_id == project_id))
    ).scalar_one()
    assert surviving == 1

    again = await service.apply_labour_event(
        project_id=project_id,
        report_id="timesheet-1",
        status_value="approved",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert again == Decimal("0")


async def test_the_unique_constraint_is_the_thing_that_settles_a_race(pg_session) -> None:
    """Two claims for one worker-day cannot both exist, whoever writes second."""
    project_id, resource_id = await _fixture(pg_session)
    from sqlalchemy.exc import IntegrityError

    def _claim(ref: str) -> LabourWorkerDay:
        return LabourWorkerDay(
            project_id=project_id,
            work_date=WORK_DAY,
            resource_id=str(resource_id),
            source_module="field_diary",
            source_ref=ref,
            hours=Decimal("8"),
        )

    pg_session.add(_claim("first"))
    await pg_session.flush()

    async def _write_a_second_claim() -> None:
        async with pg_session.begin_nested():
            pg_session.add(_claim("second"))
            await pg_session.flush()

    with pytest.raises(IntegrityError):
        await _write_a_second_claim()


async def test_a_field_report_claims_the_day_like_every_other_source(pg_session) -> None:
    """Three modules publish these hours, and the guard covers all three.

    Field reports were the original publisher and they send a real report date,
    so they take the claim too. That is the point rather than a side effect: a
    site report and a diary entry for the same worker on the same day used to
    cost twice, exactly like the phone and the timesheet did.
    """
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)

    from_report = await service.apply_labour_event(
        project_id=project_id,
        report_id="field-report-1",
        status_value="approved",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="fieldreports",
    )
    assert from_report == Decimal("320")

    from_diary = await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-1",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )
    assert from_diary == Decimal("0"), "a field report and a diary entry costed one day twice"
    assert await _actual(pg_session, project_id) == Decimal("320")

    claim = (
        await pg_session.execute(select(LabourWorkerDay).where(LabourWorkerDay.project_id == project_id))
    ).scalar_one()
    assert claim.source_module == "fieldreports"


async def test_reversing_a_timesheet_takes_the_money_back_and_frees_the_day(pg_session) -> None:
    """A reversal has to undo both halves of what approval did.

    Approval posts money and claims the worker-day. Crediting the money without
    releasing the claim would leave that day held forever: neither the corrected
    sheet nor the phone could ever cost it again, so a reversal would strand the
    day rather than free it.
    """
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="timesheet-1",
        status_value="approved",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert await _actual(pg_session, project_id) == Decimal("320")

    credited = await service.reverse_labour_event(
        project_id=project_id,
        report_id="reversal-1",
        reverses_id="timesheet-1",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert credited == Decimal("320")
    assert await _actual(pg_session, project_id) == Decimal("0.00")

    held = (
        await pg_session.execute(select(func.count(LabourWorkerDay.id)).where(LabourWorkerDay.project_id == project_id))
    ).scalar_one()
    assert held == 0, "the reversal credited the money but left the day claimed"

    # And the day is genuinely available again, to a different source.
    again = await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-1",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )
    assert again == Decimal("320")


async def test_a_reversal_credits_what_was_posted_not_todays_rate(pg_session) -> None:
    """A rate edited between approval and reversal must not leave a residue.

    The amount each event put on the line is recorded beside its replay key, so
    the credit is the debit. Re-deriving it from the current rate would take off
    a different number and leave money on the budget that nothing accounts for.
    """
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="timesheet-1",
        status_value="approved",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    )

    # Somebody puts the worker's rate up before the sheet is reversed.
    dearer = {**_row(resource_id), "cost_rate": "95"}
    credited = await service.reverse_labour_event(
        project_id=project_id,
        report_id="reversal-1",
        reverses_id="timesheet-1",
        rows=[dearer],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert credited == Decimal("320"), "the credit followed the new rate instead of the posting"
    assert await _actual(pg_session, project_id) == Decimal("0.00")


async def test_a_reversal_does_not_give_away_another_sources_day(pg_session) -> None:
    """The phone costed the day; reversing the office sheet must not free it.

    The office sheet was skipped on that worker, so it posted nothing for them.
    Releasing the phone's claim would let the day be costed a second time, and
    crediting for it would take off money the phone correctly posted.
    """
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-1",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )
    # The office sheet finds the day taken and posts nothing.
    assert await service.apply_labour_event(
        project_id=project_id,
        report_id="timesheet-1",
        status_value="approved",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    ) == Decimal("0")

    credited = await service.reverse_labour_event(
        project_id=project_id,
        report_id="reversal-1",
        reverses_id="timesheet-1",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert credited == Decimal("0"), "a reversal credited hours it had never posted"
    assert await _actual(pg_session, project_id) == Decimal("320"), "the phone's money was taken off"

    claim = (
        await pg_session.execute(select(LabourWorkerDay).where(LabourWorkerDay.project_id == project_id))
    ).scalar_one()
    assert claim.source_module == "field_diary", "the reversal gave away another source's claim"


async def test_a_redelivered_reversal_credits_once(pg_session) -> None:
    """The credit is replay-guarded under the reversing document's own id."""
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="timesheet-1",
        status_value="approved",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    kwargs = {
        "project_id": project_id,
        "report_id": "reversal-1",
        "reverses_id": "timesheet-1",
        "rows": [_row(resource_id)],
        "work_date": WORK_DAY,
        "source_module": "field_time",
    }
    assert await service.reverse_labour_event(**kwargs) == Decimal("320")
    assert await service.reverse_labour_event(**kwargs) == Decimal("0")
    assert await _actual(pg_session, project_id) == Decimal("0.00")


async def test_a_reversal_on_a_project_that_never_posted_does_nothing(pg_session) -> None:
    """It must not mint the labour line it is crediting.

    An empty labour line reading zero would appear on a budget that has never
    had a labour cost, and a reader cannot tell an intentional zero from a
    posting that failed.
    """
    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    credited = await service.reverse_labour_event(
        project_id=project_id,
        report_id="reversal-1",
        reverses_id="timesheet-1",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_time",
    )
    assert credited == Decimal("0")
    lines = (await pg_session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))).scalars().all()
    assert lines == [], "a reversal created the budget line it was crediting"


async def test_reversing_a_timesheet_publishes_the_credit(pg_session) -> None:
    """The wiring, not the arithmetic: reversal has to reach the cost model."""
    from app.core.events import event_bus
    from app.modules.costmodel.service import _on_labour_logged, _on_labour_reversed
    from app.modules.field_time.schemas import ReverseTimesheetRequest

    project_id, resource_id = await _fixture(pg_session)

    captured: list[dict] = []

    async def _capture(event: object) -> None:
        captured.append(dict(getattr(event, "data", None) or {}))

    async def _swallow(event: object) -> None:
        return None

    # Both real consumers open sessions of their own against a database this
    # lane does not bind, so they stand aside while the publish is asserted.
    event_bus.unsubscribe("fieldreports.labour.logged", _on_labour_logged)
    event_bus.unsubscribe("fieldreports.labour.reversed", _on_labour_reversed)
    event_bus.subscribe("fieldreports.labour.logged", _swallow)
    event_bus.subscribe("fieldreports.labour.reversed", _capture)
    try:
        service = FieldTimeService(pg_session)
        timesheet = await service.create_timesheet(
            FieldTimesheetCreate(
                project_id=project_id,
                date=date(2026, 6, 4),
                lines=[
                    FieldTimesheetLineCreate(
                        resource_id=resource_id,
                        hours=Decimal("8"),
                        cost_code="01.10.010",
                    ),
                ],
            ),
            str(uuid.uuid4()),
        )
        await service.submit_timesheet(timesheet.id, str(uuid.uuid4()))
        await service.approve_timesheet(timesheet.id, str(uuid.uuid4()))
        reversal = await service.reverse_timesheet(
            timesheet.id,
            ReverseTimesheetRequest(note="wrong day"),
            str(uuid.uuid4()),
        )
    finally:
        event_bus.unsubscribe("fieldreports.labour.logged", _swallow)
        event_bus.unsubscribe("fieldreports.labour.reversed", _capture)
        event_bus.subscribe("fieldreports.labour.logged", _on_labour_logged)
        event_bus.subscribe("fieldreports.labour.reversed", _on_labour_reversed)

    assert captured, "reversing a timesheet published no credit to the cost model"
    payload = captured[-1]
    assert payload["reverses_id"] == str(timesheet.id)
    assert payload["report_id"] == str(reversal.id)
    assert payload["report_date"] == WORK_DAY
    assert payload["source_module"] == "field_time"
    rows = payload["rows"]
    assert len(rows) == 1
    assert rows[0]["resource_id"] == str(resource_id)
    assert rows[0]["hours"] == 8.0, "the credit rows carry a sign the cost calculator would skip"
    # Every timesheet approved before this shipped has no recorded amount to credit,
    # so it takes the fallback and re-derives the money from this rate. A rate that
    # arrives as zero credits nothing and leaves the original defect in place for
    # exactly the backlog the fallback exists to serve.
    assert Decimal(rows[0]["cost_rate"]) == Decimal("40"), (
        "the credit carries no usable rate, so the fallback would refund zero"
    )


async def test_a_timesheet_after_the_phone_still_approves(pg_session) -> None:
    """Skipped hours are a cost decision, never a refusal to approve.

    The manager standing in front of the sheet is not the person who caused the
    overlap and cannot fix it from that screen. Blocking them would strand the
    document; the hours are simply not costed twice.
    """
    from app.core.events import event_bus
    from app.modules.costmodel.service import _on_labour_logged

    project_id, resource_id = await _fixture(pg_session)
    service = LabourActualsService(pg_session)
    await service.apply_labour_event(
        project_id=project_id,
        report_id="diary-1",
        status_value="submitted",
        rows=[_row(resource_id)],
        work_date=WORK_DAY,
        source_module="field_diary",
    )

    async def _swallow(event: object) -> None:
        return None

    event_bus.unsubscribe("fieldreports.labour.logged", _on_labour_logged)
    event_bus.subscribe("fieldreports.labour.logged", _swallow)
    try:
        ft_service = FieldTimeService(pg_session)
        timesheet = await ft_service.create_timesheet(
            FieldTimesheetCreate(
                project_id=project_id,
                date=date(2026, 6, 4),
                lines=[
                    FieldTimesheetLineCreate(
                        resource_id=resource_id,
                        hours=Decimal("8"),
                        cost_code="01.10.010",
                    ),
                ],
            ),
            str(uuid.uuid4()),
        )
        await ft_service.submit_timesheet(timesheet.id, str(uuid.uuid4()))
        approved = await ft_service.approve_timesheet(timesheet.id, str(uuid.uuid4()))
    finally:
        event_bus.unsubscribe("fieldreports.labour.logged", _swallow)
        event_bus.subscribe("fieldreports.labour.logged", _on_labour_logged)

    assert approved.status == "approved"
    assert approved.approved_at is not None
