# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Geofenced time clock end to end and across modules (PostgreSQL)​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Consent gates capture; an outside clock is stored, flagged and notified, not
refused; a supervisor decides with a reason; a day's shifts build the draft
timesheet whose validation blocks submission until the flag is decided; the
approved timesheet feeds payroll, the CVR labour line and the daily diary
headcount; retention erases positions and keeps the record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.field_time.clock_schemas import (
    ClockConsentIn,
    ClockEventCreate,
    ClockSettingsIn,
    GeofenceCreate,
)
from app.modules.field_time.clock_service import ClockService
from app.modules.field_time.service import FieldTimeService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

LAT, LNG = 52.520008, 13.404954
DAY = date(2026, 10, 12)
T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.modules.projects.models import Project
    from app.modules.resources.models import Resource
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"clk-{uuid.uuid4().hex[:10]}@field.io",
        hashed_password="x",
        full_name="Site Manager",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Clock project", owner_id=owner.id, currency="EUR", fx_rates=[])
    session.add(project)
    worker = Resource(
        id=uuid.uuid4(),
        code=f"W-{uuid.uuid4().hex[:8]}",
        name="Mason",
        resource_type="person",
        default_cost_rate=Decimal("40"),
        currency="EUR",
    )
    session.add(worker)
    await session.flush()
    return project.id, worker.id, owner.id


def _clock(project_id: uuid.UUID, worker: uuid.UUID, kind: str, at: datetime, lat: float = LAT) -> ClockEventCreate:
    return ClockEventCreate(
        project_id=project_id, resource_id=worker, kind=kind, latitude=lat, longitude=LNG, accuracy_m=8, occurred_at=at
    )


async def _ready(session: AsyncSession) -> tuple[ClockService, uuid.UUID, uuid.UUID, uuid.UUID]:
    project_id, worker, owner = await _seed(session)
    svc = ClockService(session)
    await svc.create_geofence(
        GeofenceCreate(
            project_id=project_id,
            name="Main gate",
            shape="circle",
            center_lat=LAT,
            center_lng=LNG,
            radius_m=150,
            default_cost_code="03-CONCRETE",
        ),
        str(owner),
    )
    await svc.set_consent(ClockConsentIn(project_id=project_id, resource_id=worker, granted=True), str(owner))
    return svc, project_id, worker, owner


async def test_consent_is_required_before_any_position_is_stored(session: AsyncSession) -> None:
    project_id, worker, _owner = await _seed(session)
    with pytest.raises(HTTPException) as exc:
        await ClockService(session).record_event(_clock(project_id, worker, "in", T0), None)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "consent_required"


async def test_inside_clock_needs_no_approval_and_pairs(session: AsyncSession) -> None:
    svc, project_id, worker, owner = await _ready(session)
    ev_in = await svc.record_event(_clock(project_id, worker, "in", T0), str(owner))
    assert ev_in.inside and ev_in.approval_status == "not_required"
    with pytest.raises(HTTPException) as exc:
        await svc.record_event(_clock(project_id, worker, "in", T0 + timedelta(minutes=5)), str(owner))
    assert exc.value.detail["code"] == "already_clocked_in"
    ev_out = await svc.record_event(_clock(project_id, worker, "out", T0 + timedelta(hours=8)), str(owner))
    assert ev_out.pair_event_id == ev_in.id


async def test_outside_clock_is_flagged_notified_and_blocks_submit_until_approved(session: AsyncSession) -> None:
    from app.modules.notifications.models import Notification

    svc, project_id, worker, owner = await _ready(session)
    # ~1.1 km north of the gate: outside, stored, flagged, not refused.
    ev_in = await svc.record_event(_clock(project_id, worker, "in", T0, lat=LAT + 0.01), str(owner))
    assert ev_in.inside is False
    assert ev_in.approval_status == "pending"
    assert float(ev_in.distance_m) > 900
    await svc.record_event(_clock(project_id, worker, "out", T0 + timedelta(hours=8)), str(owner))
    notes = (await session.execute(select(Notification).where(Notification.entity_id == str(ev_in.id)))).scalars()
    note = notes.first()
    assert note is not None and note.user_id == owner
    assert note.action_url == f"/projects/{project_id}/field-time?tab=approvals"

    timesheet = await svc.build_timesheet(project_id, DAY, str(owner))
    assert len(timesheet.lines) == 1
    assert timesheet.lines[0].hours == Decimal("8.0000")
    assert timesheet.lines[0].cost_code == "03-CONCRETE"
    ft = FieldTimeService(session)
    with pytest.raises(HTTPException) as exc:
        await ft.submit_timesheet(timesheet.id, str(owner))
    assert exc.value.status_code == 422
    assert any(e["rule_id"] == "field_time.clock_outside_unapproved" for e in exc.value.detail["errors"])

    from pydantic import ValidationError

    from app.modules.field_time.clock_schemas import ClockDecision

    with pytest.raises(ValidationError):
        ClockDecision(reason="")
    decided = await svc.decide(ev_in.id, approve=True, reason="Concrete pour at the batching yard", user_id=str(owner))
    assert decided.approval_status == "approved"
    submitted = await ft.submit_timesheet(timesheet.id, str(owner))
    assert submitted.status == "submitted"


async def test_approved_clock_timesheet_feeds_payroll_cvr_and_diary(session: AsyncSession) -> None:
    from app.modules.cvr.schemas import CvrReportCreate
    from app.modules.cvr.service import CvrService
    from app.modules.daily_diary.clock_headcount import apply_headcount
    from app.modules.daily_diary.models import DailyDiary
    from app.modules.payroll.service import PayrollService

    svc, project_id, worker, owner = await _ready(session)
    diary = DailyDiary(project_id=project_id, diary_date=DAY.isoformat(), labour_count=0, status="open")
    session.add(diary)
    await session.flush()
    await svc.record_event(_clock(project_id, worker, "in", T0), str(owner))
    await svc.record_event(_clock(project_id, worker, "out", T0 + timedelta(hours=8)), str(owner))
    assert await apply_headcount(session, project_id, DAY) == 1
    assert diary.labour_count == 1 and diary.metadata_["clock_headcount"] == 1

    await svc.put_settings(ClockSettingsIn(project_id=project_id, default_break_minutes=30))
    timesheet = await svc.build_timesheet(project_id, DAY, str(owner))
    assert timesheet.lines[0].hours == Decimal("7.5000")
    ft = FieldTimeService(session)
    await ft.submit_timesheet(timesheet.id, str(owner))
    await ft.approve_timesheet(timesheet.id, str(owner))
    with pytest.raises(HTTPException) as exc:
        await svc.build_timesheet(project_id, DAY, str(owner))
    assert exc.value.detail["code"] == "timesheet_locked"

    rows = await PayrollService(session)._collect_field_timesheet_hours(project_id, date_from=DAY, date_to=DAY)
    assert sum(Decimal(str(r.get("hours", 0))) for r in rows) == Decimal("7.5")

    cost = await svc.labour_cost(project_id, DAY, DAY)
    assert cost["labour_cost"] == "300.00" and cost["from_clock_hours"] == "7.50"
    cvr = CvrService(session)
    report = await cvr.create_report(CvrReportCreate(project_id=project_id, period="2026-10", currency="EUR"), None)
    line = await cvr.import_field_labour(report.id)
    again = await cvr.import_field_labour(report.id)
    assert line.id == again.id
    assert line.cost_to_date == Decimal("300.00")


async def test_overlap_and_missing_clock_out_are_reported(session: AsyncSession) -> None:
    svc, project_id, worker, owner = await _ready(session)
    # Recent enough for the on-site status window, old enough to be stale.
    start = datetime.now(UTC).replace(hour=0, minute=30, second=0, microsecond=0) - timedelta(days=1)
    await svc.record_event(_clock(project_id, worker, "in", start), str(owner))
    await svc.record_event(_clock(project_id, worker, "out", start + timedelta(hours=4)), str(owner))
    await svc.record_event(_clock(project_id, worker, "in", start + timedelta(hours=5)), str(owner))
    report = await svc.validate_day(project_id, start.date())
    failed = {r["rule_id"] for r in report["results"] if not r["passed"]}
    assert "field_time.clock_missing_clock_out" in failed
    status = await svc.status(project_id)
    assert status["missing_clock_outs"] == 1


async def test_retention_and_withdrawal_erase_positions_but_keep_the_record(session: AsyncSession) -> None:
    svc, project_id, worker, owner = await _ready(session)
    old = datetime.now(UTC) - timedelta(days=120)
    ev = await svc.record_event(_clock(project_id, worker, "in", old), str(owner))
    assert ev.latitude is None and ev.position_purged_at is not None
    fresh = await svc.record_event(_clock(project_id, worker, "out", datetime.now(UTC)), str(owner))
    assert fresh.latitude is not None
    await svc.set_consent(ClockConsentIn(project_id=project_id, resource_id=worker, granted=False), str(owner))
    await session.refresh(fresh)
    assert fresh.latitude is None and fresh.kind == "out"


async def test_offline_replay_with_the_same_client_op_id_is_one_event(session: AsyncSession) -> None:
    svc, project_id, worker, owner = await _ready(session)
    data = _clock(project_id, worker, "in", T0).model_copy(update={"client_op_id": "op-1"})
    first = await svc.record_event(data, str(owner))
    second = await svc.record_event(data, str(owner))
    assert first.id == second.id


async def test_demo_seed_writes_fences_two_weeks_and_both_flag_outcomes(session: AsyncSession) -> None:
    from app.modules.field_time.clock_seed import seed_field_clock_demo
    from app.modules.field_time.models import FieldClockEvent, FieldSiteGeofence
    from app.modules.resources.models import Resource

    project_id, _worker, _owner = await _seed(session)
    for i in range(3):
        session.add(
            Resource(
                id=uuid.uuid4(),
                code=f"D-{uuid.uuid4().hex[:8]}",
                name=f"Crew member {i}",
                resource_type="person",
                home_project_id=project_id,
                status="active",
                default_cost_rate=Decimal("35"),
                currency="EUR",
            )
        )
    await session.flush()
    totals = await seed_field_clock_demo(session, [project_id], today=date(2026, 10, 26))
    assert totals["projects"] == 1 and totals["clock_timesheets"] == 3
    again = await seed_field_clock_demo(session, [project_id], today=date(2026, 10, 26))
    assert again["projects"] == 0
    fences = (
        (await session.execute(select(FieldSiteGeofence).where(FieldSiteGeofence.project_id == project_id)))
        .scalars()
        .all()
    )
    assert len(fences) == 1
    events = (
        (await session.execute(select(FieldClockEvent).where(FieldClockEvent.project_id == project_id))).scalars().all()
    )
    statuses = [e.approval_status for e in events]
    assert statuses.count("approved") == 1 and statuses.count("pending") == 1
    assert len({e.occurred_at.date() for e in events}) == 10
    assert all(e.pair_event_id for e in events if e.kind == "out")
