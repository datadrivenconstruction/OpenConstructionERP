# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""A day recorded with no signal reaches the office once, however often it is sent.

A foreman in a basement or a lift shaft has no data. The device keeps the day in
a local queue and replays it when there is signal, and that replay is
at-least-once by construction: a reconnect can fire twice, and a request whose
response was lost on the way back looks exactly like one that never arrived. So
every delivery of the same day has to land on the same timesheet.

What is asserted here is the part that arithmetic cannot check:

* a replayed create returns the original timesheet and writes no second row;
* a replayed update converges, because each op carries the entry's whole state
  rather than a diff;
* a withdrawal that overtakes its own creation still wins - the day the foreman
  deleted must not come back when the create behind it finally arrives;
* a withdrawal is refused once the day has been sent on for approval;
* an entry key that belongs to another project, or that the field diary already
  spent, is refused rather than followed to whatever row it happens to resolve.

That last one is the one with money behind it. Approving a timesheet posts
labour actuals and takes the ``(project, day, worker)`` claim in the cost model,
the claim is released by reversing the timesheet, and nothing in the database
ties the claim to the timesheet row. Deleting an approved timesheet would
therefore leave a claim that nothing can ever release: neither a corrected sheet
nor the phone could ever cost that day again. The refusal is the guard, so it is
asserted against a real approval with a real claim standing behind it.

PostgreSQL, not SQLite: the idempotency promise leans on a unique constraint to
settle two drains racing on one key, and a constraint that is never exercised
against a real transaction is a comment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.costmodel.models import LabourWorkerDay
from app.modules.costmodel.service import LabourActualsService
from app.modules.field_diary.models import FieldSyncLedger
from app.modules.field_time.models import FieldTimesheet
from app.modules.field_time.schemas import (
    OUTCOME_CREATED,
    OUTCOME_REPLAYED,
    OUTCOME_UPDATED,
    OUTCOME_WITHDRAWN,
    FieldTimesheetLineCreate,
    OfflineEntrySubmission,
    OfflineEntryWithdraw,
)
from app.modules.field_time.service import FieldTimeService
from app.modules.projects.models import Project
from app.modules.resources.models import Resource
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

WORK_DAY = date(2026, 6, 11)


@pytest.fixture(autouse=True)
def _no_detached_labour_subscribers():
    """Keep the cost model's detached labour handlers out of this lane.

    Approving a timesheet publishes its labour actuals with
    ``publish_detached``, which schedules the subscriber as a task on the same
    event loop rather than awaiting it. The task therefore runs somewhere in a
    later test, opens a session from ``async_session_factory`` - a factory this
    lane never binds to the embedded cluster - and takes an unrelated test down
    with it. The conftest documents the same trap for the budget-line handlers.

    The subscribers are not what is under test here: this file asserts what the
    offline path writes, and the one place a real claim is needed it is posted
    directly against the test session. They are put back afterwards.
    """
    from app.core.events import event_bus
    from app.modules.costmodel.service import _on_labour_logged, _on_labour_reversed

    detached = [
        ("fieldreports.labour.logged", _on_labour_logged),
        ("fieldreports.labour.reversed", _on_labour_reversed),
    ]
    removed = [(name, fn) for name, fn in detached if fn in event_bus._handlers.get(name, [])]
    for name, fn in removed:
        event_bus.unsubscribe(name, fn)
    try:
        yield
    finally:
        for name, fn in removed:
            event_bus.subscribe(name, fn)


async def _fixture(session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Return ``(project_id, resource_id, user_id)`` ready to book against."""
    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            email=f"{uuid.uuid4().hex[:8]}@example.test",
            hashed_password="x",
            full_name="Foreman",
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
            name="Offline fixture",
            description="",
            currency="EUR",
            status="active",
            owner_id=user_id,
            metadata_={},
        )
    )
    await session.flush()

    resource_id = uuid.uuid4()
    session.add(
        Resource(
            id=resource_id,
            code=f"OF-{uuid.uuid4().hex[:6]}",
            name="Marta Nowak",
            resource_type="person",
            home_project_id=project_id,
            default_cost_rate=Decimal("40"),
            currency="EUR",
            status="active",
            metadata_={},
        )
    )
    await session.flush()
    return project_id, resource_id, user_id


def _entry(
    project_id: uuid.UUID,
    resource_id: uuid.UUID,
    entry_key: str,
    *,
    hours: str = "8",
    note: str | None = None,
    submit: bool = False,
) -> OfflineEntrySubmission:
    """One day's full state, as the device would send it."""
    return OfflineEntrySubmission(
        entry_key=entry_key,
        project_id=project_id,
        date=WORK_DAY,
        note=note,
        lines=[
            FieldTimesheetLineCreate(
                resource_id=resource_id,
                hours=Decimal(hours),
                cost_code="01.100",
            )
        ],
        captured_at=datetime(2026, 6, 11, 17, 30, tzinfo=UTC),
        device="site-phone-3",
        submit=submit,
    )


async def _count_timesheets(session, project_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(FieldTimesheet).where(FieldTimesheet.project_id == project_id)
            )
        ).scalar_one()
    )


async def test_a_replayed_create_returns_the_first_timesheet(pg_session) -> None:
    """The same day sent three times is one timesheet, not three."""
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)
    key = str(uuid.uuid4())

    first = await service.record_offline_entry(_entry(project_id, resource_id, key), str(user_id))
    second = await service.record_offline_entry(_entry(project_id, resource_id, key), str(user_id))
    third = await service.record_offline_entry(_entry(project_id, resource_id, key), str(user_id))

    assert first.outcome == OUTCOME_CREATED
    assert second.outcome == OUTCOME_REPLAYED
    assert third.outcome == OUTCOME_REPLAYED
    assert first.timesheet is not None
    assert second.timesheet is not None
    assert third.timesheet is not None
    assert second.timesheet.id == first.timesheet.id
    assert third.timesheet.id == first.timesheet.id
    assert await _count_timesheets(pg_session, project_id) == 1

    # And the hours were not doubled by the redeliveries.
    stored = await service.get_timesheet(first.timesheet.id)
    assert len(stored.lines) == 1
    assert stored.lines[0].hours == Decimal("8")


async def test_a_replayed_update_converges_instead_of_accumulating(pg_session) -> None:
    """A corrected day replaces the draft, and re-sending the correction is a no-op.

    Each op carries the entry's whole state, so applying it twice leaves the same
    content. That is what makes an update safe to replay without a revision
    counter to compare.
    """
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)
    key = str(uuid.uuid4())

    await service.record_offline_entry(_entry(project_id, resource_id, key), str(user_id))
    corrected = _entry(project_id, resource_id, key, hours="6.5", note="Rain stopped work at 15:00")

    updated = await service.record_offline_entry(corrected, str(user_id))
    replayed = await service.record_offline_entry(corrected, str(user_id))

    assert updated.outcome == OUTCOME_UPDATED
    assert replayed.outcome == OUTCOME_REPLAYED
    assert await _count_timesheets(pg_session, project_id) == 1

    assert updated.timesheet is not None
    stored = await service.get_timesheet(updated.timesheet.id)
    assert len(stored.lines) == 1
    assert stored.lines[0].hours == Decimal("6.5")
    assert stored.note == "Rain stopped work at 15:00"


async def test_a_withdrawal_that_overtakes_its_create_still_wins(pg_session) -> None:
    """A day deleted on the device does not come back when the create lands late.

    Two requests in flight can arrive in either order. If an unknown key were
    simply answered "no such entry", the create behind the withdrawal would
    write the day the foreman had already deleted and nobody could tell.
    """
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)
    key = str(uuid.uuid4())

    withdrawn = await service.withdraw_offline_entry(
        OfflineEntryWithdraw(entry_key=key, project_id=project_id),
        str(user_id),
    )
    assert withdrawn.outcome == OUTCOME_WITHDRAWN
    assert withdrawn.timesheet is None

    with pytest.raises(HTTPException) as excinfo:
        await service.record_offline_entry(_entry(project_id, resource_id, key), str(user_id))

    assert excinfo.value.status_code == 409
    assert await _count_timesheets(pg_session, project_id) == 0


async def test_a_withdrawal_is_remembered_and_replaying_it_is_a_no_op(pg_session) -> None:
    """Withdrawing an applied entry removes the draft, and sending it again is fine."""
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)
    key = str(uuid.uuid4())

    await service.record_offline_entry(_entry(project_id, resource_id, key), str(user_id))
    assert await _count_timesheets(pg_session, project_id) == 1

    request = OfflineEntryWithdraw(entry_key=key, project_id=project_id)
    first = await service.withdraw_offline_entry(request, str(user_id))
    second = await service.withdraw_offline_entry(request, str(user_id))

    assert first.outcome == OUTCOME_WITHDRAWN
    assert second.outcome == OUTCOME_WITHDRAWN
    assert await _count_timesheets(pg_session, project_id) == 0

    # One ledger row for the key, and it says withdrawn - so a create arriving
    # afterwards is refused rather than resurrecting the day.
    rows = (
        (await pg_session.execute(select(FieldSyncLedger).where(FieldSyncLedger.client_op_id == key))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].result_id is None


async def test_withdrawing_an_approved_day_cannot_strand_its_worker_day_claim(pg_session) -> None:
    """An approved day is refused, so the claim its approval took stays releasable.

    Approval claims ``(project, day, worker)`` in the cost model and only a
    reversal gives it back. No foreign key ties the claim to the timesheet, so
    deleting the row would leave a claim nothing could ever release and the day
    would be stuck for every source at once. The refusal is what prevents that,
    and it is asserted with a real claim standing behind a real approval.
    """
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)
    key = str(uuid.uuid4())

    outcome = await service.record_offline_entry(
        _entry(project_id, resource_id, key, submit=True),
        str(user_id),
    )
    assert outcome.submitted is True
    assert outcome.timesheet is not None
    timesheet_id = outcome.timesheet.id
    approved = await service.approve_timesheet(timesheet_id, str(user_id))
    assert approved.status == "approved"

    # Post the labour the approval published, so a real claim is held. The
    # subscriber is detached in production; here it is driven directly against
    # this session, which is what the claim has to survive.
    await LabourActualsService(pg_session).apply_labour_event(
        project_id=project_id,
        report_id=str(timesheet_id),
        status_value="approved",
        rows=[
            {
                "worker_type": "labour",
                "hours": 8.0,
                "headcount": 1,
                "resource_id": str(resource_id),
                "cost_rate": "40",
                "currency": "EUR",
            }
        ],
        work_date=str(WORK_DAY),
        source_module="field_time",
    )
    claims = (
        (
            await pg_session.execute(
                select(LabourWorkerDay).where(
                    LabourWorkerDay.project_id == project_id,
                    LabourWorkerDay.work_date == str(WORK_DAY),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(claims) == 1
    assert claims[0].source_ref == str(timesheet_id)

    with pytest.raises(HTTPException) as excinfo:
        await service.withdraw_offline_entry(
            OfflineEntryWithdraw(entry_key=key, project_id=project_id),
            str(user_id),
        )
    assert excinfo.value.status_code == 409

    # The timesheet survives, so the reversal that releases the claim is still
    # possible - which is the whole point of refusing.
    survivor = await service.get_timesheet(timesheet_id)
    assert survivor.status == "approved"
    still_claimed = (
        (
            await pg_session.execute(
                select(LabourWorkerDay).where(
                    LabourWorkerDay.project_id == project_id,
                    LabourWorkerDay.source_ref == str(timesheet_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(still_claimed) == 1


async def test_a_correction_arriving_after_approval_is_refused_not_silently_dropped(pg_session) -> None:
    """An edit for a day already approved is a conflict the foreman must be told about.

    Applying it would edit an approved timesheet, which the module forbids
    outright; swallowing it would lose a correction the foreman believes he
    made. A replay of the identical content is not an edit and stays quiet.
    """
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)
    key = str(uuid.uuid4())

    outcome = await service.record_offline_entry(
        _entry(project_id, resource_id, key, submit=True),
        str(user_id),
    )
    assert outcome.timesheet is not None
    await service.approve_timesheet(outcome.timesheet.id, str(user_id))

    # The identical op arriving once more is a redelivery, and says so.
    replayed = await service.record_offline_entry(_entry(project_id, resource_id, key), str(user_id))
    assert replayed.outcome == OUTCOME_REPLAYED
    assert replayed.submitted is True

    with pytest.raises(HTTPException) as excinfo:
        await service.record_offline_entry(
            _entry(project_id, resource_id, key, hours="9"),
            str(user_id),
        )
    assert excinfo.value.status_code == 409
    assert await _count_timesheets(pg_session, project_id) == 1


async def test_an_entry_that_cannot_be_submitted_is_kept_as_a_draft(pg_session) -> None:
    """Validation refusing a submit must not throw away the only record of the shift.

    The hours were recorded where nobody could check them. Rejecting the whole
    op because a line needs a cost code would lose the day; storing the draft and
    reporting it unsubmitted keeps it and puts the fix on a screen where somebody
    can answer it.
    """
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)
    key = str(uuid.uuid4())

    # Storable, but ``line_complete`` blocks a submit until it has a cost code.
    entry = OfflineEntrySubmission(
        entry_key=key,
        project_id=project_id,
        date=WORK_DAY,
        lines=[FieldTimesheetLineCreate(resource_id=resource_id, hours=Decimal("8"), cost_code="")],
        submit=True,
    )
    outcome = await service.record_offline_entry(entry, str(user_id))

    assert outcome.outcome == OUTCOME_CREATED
    assert outcome.submitted is False
    assert outcome.detail is not None
    assert outcome.timesheet is not None
    assert outcome.timesheet.status == "draft"
    # The day survives, which is the whole point.
    assert await _count_timesheets(pg_session, project_id) == 1


async def test_a_line_that_is_neither_labour_nor_plant_is_refused_outright(pg_session) -> None:
    """Some payloads cannot be stored at all, and pretending otherwise helps nobody.

    A line naming neither a worker nor a machine is rejected by a database CHECK
    constraint, so there is no draft to keep it in. The op is refused before
    anything is written and the device has to fix it locally - which is why the
    refusal is a permanent 4xx and not a retry.
    """
    project_id, _resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)

    entry = OfflineEntrySubmission(
        entry_key=str(uuid.uuid4()),
        project_id=project_id,
        date=WORK_DAY,
        lines=[FieldTimesheetLineCreate(hours=Decimal("8"), cost_code="01.100")],
    )
    with pytest.raises(HTTPException) as excinfo:
        await service.record_offline_entry(entry, str(user_id))

    assert 400 <= excinfo.value.status_code < 500
    assert excinfo.value.status_code != 409
    assert await _count_timesheets(pg_session, project_id) == 0


async def test_an_offline_day_carries_its_journey_into_validation(pg_session) -> None:
    """The offline record reaches the rules, and a late sync warns without blocking.

    A fortnight-old day is still a true day. The rule says so to the approver and
    lets the submission through, because refusing it would destroy the hours this
    whole path exists to save.
    """
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)
    key = str(uuid.uuid4())

    entry = _entry(project_id, resource_id, key)
    outcome = await service.record_offline_entry(entry, str(user_id))
    timesheet = outcome.timesheet
    assert timesheet is not None

    from app.modules.field_time import field_time_math as ft

    capture = ft.read_offline_capture(timesheet.metadata_)
    assert capture.recorded is True
    assert capture.entry_key == key
    assert capture.synced_at is not None

    # Backdate the arrival so the delay rule has something to say. This is the
    # phone that was off the network for a month, expressed as data.
    late = dict(timesheet.metadata_)
    late[ft.OFFLINE_METADATA_KEY] = {
        **late[ft.OFFLINE_METADATA_KEY],
        "synced_at": (datetime(2026, 6, 11, tzinfo=UTC) + timedelta(days=40)).isoformat(),
    }
    await service.repo.update_fields(timesheet.id, metadata_=late)
    await pg_session.refresh(timesheet)

    report = await service.validate_timesheet(timesheet.id)
    flagged = [r for r in report["results"] if r["rule_id"] == "field_time.offline_sync_delay" and not r["passed"]]
    assert len(flagged) == 1
    assert "40" in flagged[0]["message"]

    # A warning, so the day can still be sent on for approval.
    submitted = await service.submit_timesheet(timesheet.id, str(user_id))
    assert submitted.status == "submitted"


async def test_a_key_already_spent_by_another_module_is_refused(pg_session) -> None:
    """A key the diary owns is not silently taken over by a timesheet.

    The sync ledger is shared with the field diary and its uniqueness is on
    ``client_op_id`` alone, so a key already spent there resolves to a row this
    module does not own. Its result id points into another table, which reads
    back as "no timesheet yet", and the naive path would write one and then
    repoint the diary's row at it. The diary's replay guard would be gone, and
    the next redelivery of that diary op - the exact thing the guard exists to
    absorb - would land a second time as duplicate activity and duplicate hours.

    So the refusal is asserted together with the diary's row surviving intact.
    """
    project_id, resource_id, user_id = await _fixture(pg_session)
    service = FieldTimeService(pg_session)

    key = str(uuid.uuid4())
    diary_result = uuid.uuid4()
    pg_session.add(
        FieldSyncLedger(
            client_op_id=key,
            project_id=project_id,
            user_id=user_id,
            op_kind="field.diary.activity",
            result_type="diary_activity",
            result_id=diary_result,
        )
    )
    await pg_session.flush()

    with pytest.raises(HTTPException) as caught:
        await service.record_offline_entry(_entry(project_id, resource_id, key), str(user_id))
    assert caught.value.status_code == 409

    with pytest.raises(HTTPException) as caught_withdraw:
        await service.withdraw_offline_entry(
            OfflineEntryWithdraw(entry_key=key, project_id=project_id),
            str(user_id),
        )
    assert caught_withdraw.value.status_code == 409

    # The diary still owns its key, and no timesheet was written behind it.
    row = (await pg_session.execute(select(FieldSyncLedger).where(FieldSyncLedger.client_op_id == key))).scalar_one()
    assert row.op_kind == "field.diary.activity"
    assert row.result_type == "diary_activity"
    assert row.result_id == diary_result
    assert await _count_timesheets(pg_session, project_id) == 0


async def test_a_key_from_another_project_cannot_reach_this_ones_day(pg_session) -> None:
    """The key selects the row, so the key has to be scoped, not just the payload.

    The endpoint checks that the caller may reach the project named in the
    payload, but it is the entry key that picks the timesheet the op goes on to
    rewrite or delete. Without a check on the row it resolved, a key replayed
    against a different project would edit that project's day.
    """
    project_a, resource_a, user_a = await _fixture(pg_session)
    project_b, _resource_b, user_b = await _fixture(pg_session)
    service = FieldTimeService(pg_session)

    key = str(uuid.uuid4())
    original = await service.record_offline_entry(_entry(project_a, resource_a, key), str(user_a))
    assert original.outcome == OUTCOME_CREATED

    # The same key, sent with someone else's project.
    with pytest.raises(HTTPException) as caught:
        await service.record_offline_entry(
            _entry(project_b, resource_a, key, hours="99"),
            str(user_b),
        )
    assert caught.value.status_code == 404

    with pytest.raises(HTTPException) as caught_withdraw:
        await service.withdraw_offline_entry(
            OfflineEntryWithdraw(entry_key=key, project_id=project_b),
            str(user_b),
        )
    assert caught_withdraw.value.status_code == 404

    # The first project's day is untouched: still there, still eight hours.
    assert original.timesheet is not None
    stored = await service.get_timesheet(original.timesheet.id)
    assert stored.project_id == project_a
    assert len(stored.lines) == 1
    assert stored.lines[0].hours == Decimal("8")
    assert await _count_timesheets(pg_session, project_b) == 0
