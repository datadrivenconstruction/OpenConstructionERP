# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Telematics service: idempotent ingest, counter restart, silent devices, retention.

PostgreSQL because the day rollup upserts against a unique (machine, day) constraint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.equipment.models import Equipment, EquipmentRental, TelemetryReading, UtilisationDay
from app.modules.equipment.telematics import TelematicsSample
from app.modules.equipment.telematics_service import TelematicsService, _prune_state
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

DAY = date(2026, 10, 5)


def _at(hour: int, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def _s(ref: str, when: datetime, eng: str, idle: str | None = None) -> TelematicsSample:
    return TelematicsSample(
        equipment_ref=ref,
        recorded_at=when,
        engine_hours=Decimal(eng),
        idle_hours=Decimal(idle) if idle is not None else None,
    )


async def _machine(session, *, hired: bool = False, start: str = "2026-10-01") -> tuple[Equipment, uuid.UUID | None]:
    project_id = None
    if hired:
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
                name="Telematics fixture",
                description="",
                currency="EUR",
                status="active",
                owner_id=owner_id,
                metadata_={},
            )
        )
        await session.flush()
    eq = Equipment(code=f"EX-{uuid.uuid4().hex[:6]}", name="Excavator")
    session.add(eq)
    await session.flush()
    if hired:
        session.add(EquipmentRental(equipment_id=eq.id, project_id=project_id, start_date=start, status="active"))
        await session.flush()
    return eq, project_id


async def test_posting_the_same_samples_twice_keeps_one_day(pg_session) -> None:
    eq, _ = await _machine(pg_session)
    svc = TelematicsService(pg_session)
    batch = [_s(eq.code, _at(6), "100"), _s(eq.code, _at(14), "108", "2")]
    await svc.ingest(batch, source="csv")
    await svc.ingest(batch, source="csv")
    days = (
        (await pg_session.execute(select(UtilisationDay).where(UtilisationDay.equipment_id == eq.id))).scalars().all()
    )
    assert len(days) == 1
    assert days[0].worked_hours + days[0].idle_hours == Decimal("8")
    assert days[0].counter_reset is False


async def test_out_of_order_samples_give_the_same_day(pg_session) -> None:
    eq, _ = await _machine(pg_session)
    svc = TelematicsService(pg_session)
    await svc.ingest([_s(eq.code, _at(14), "108"), _s(eq.code, _at(6), "100")], source="csv")
    day = (await pg_session.execute(select(UtilisationDay).where(UtilisationDay.equipment_id == eq.id))).scalar_one()
    assert day.worked_hours + day.idle_hours == Decimal("8")


async def test_a_counter_restart_is_flagged_not_silently_zero(pg_session) -> None:
    eq, _ = await _machine(pg_session)
    svc = TelematicsService(pg_session)
    await svc.ingest([_s(eq.code, _at(22, DAY - timedelta(days=1)), "5000"), _s(eq.code, _at(15), "4")], source="csv")
    day = (
        await pg_session.execute(
            select(UtilisationDay).where(UtilisationDay.equipment_id == eq.id, UtilisationDay.day == DAY)
        )
    ).scalar_one()
    assert day.counter_reset is True
    assert day.worked_hours + day.idle_hours == Decimal("4")
    report = await svc.utilisation(DAY, DAY)
    assert report["machines"][0]["counter_reset_days"] == 1


async def test_an_unknown_machine_is_reported_not_stored(pg_session) -> None:
    svc = TelematicsService(pg_session)
    result = await svc.ingest([_s("NOPE-1", _at(6), "1")], source="csv")
    assert result["accepted"] == 0
    assert result["unmatched"] == ["NOPE-1"]


async def test_a_revoked_device_no_longer_authenticates(pg_session) -> None:
    eq, _ = await _machine(pg_session)
    svc = TelematicsService(pg_session)
    device, token = await svc.create_device(eq.id, "cab unit")
    assert (await svc.authenticate(token)).id == device.id
    await svc.revoke_device(device.id)
    assert await svc.authenticate(token) is None


async def test_a_hired_machine_with_a_quiet_device_is_silent(pg_session) -> None:
    eq, project_id = await _machine(pg_session, hired=True)
    svc = TelematicsService(pg_session)
    device, _ = await svc.create_device(eq.id)
    now = datetime.now(UTC)
    device.last_seen_at = now - timedelta(hours=30)
    await pg_session.flush()
    silent = await svc.silent_devices(now)
    assert [s["equipment_id"] for s in silent] == [eq.id]
    assert silent[0]["project_id"] == project_id
    assert silent[0]["hours_silent"] >= 30

    device.last_seen_at = now - timedelta(hours=2)
    await pg_session.flush()
    assert await svc.silent_devices(now) == []


async def test_a_machine_that_is_not_hired_is_never_silent(pg_session) -> None:
    eq, _ = await _machine(pg_session, hired=False)
    svc = TelematicsService(pg_session)
    device, _ = await svc.create_device(eq.id)
    device.last_seen_at = datetime.now(UTC) - timedelta(days=9)
    await pg_session.flush()
    assert await svc.silent_devices() == []


async def test_the_silent_alert_goes_out_once_a_day(pg_session) -> None:
    eq, _ = await _machine(pg_session, hired=True)
    svc = TelematicsService(pg_session)
    device, _ = await svc.create_device(eq.id)
    device.last_seen_at = datetime.now(UTC) - timedelta(hours=40)
    await pg_session.flush()
    first = await svc.notify_silent_devices()
    second = await svc.notify_silent_devices()
    assert first == {"silent": 1, "notified": 1}
    assert second == {"silent": 1, "notified": 0}


async def test_pruning_drops_old_raw_readings_and_keeps_the_day(pg_session) -> None:
    eq, _ = await _machine(pg_session)
    svc = TelematicsService(pg_session)
    _prune_state[eq.id] = datetime.now(UTC)  # keep the ingest's own prune out of the way
    old_day = (datetime.now(UTC) - timedelta(days=200)).date()
    await svc.ingest([_s(eq.code, _at(6, old_day), "10"), _s(eq.code, _at(14, old_day), "16")], source="csv")
    await svc.ingest([_s(eq.code, datetime.now(UTC) - timedelta(hours=1), "400")], source="csv")
    removed = await svc.prune_raw(90)
    assert removed == 2
    left = (await pg_session.execute(select(func.count()).select_from(TelemetryReading))).scalar_one()
    assert left == 1
    kept = (
        await pg_session.execute(select(func.count()).select_from(UtilisationDay).where(UtilisationDay.day == old_day))
    ).scalar_one()
    assert kept == 1
