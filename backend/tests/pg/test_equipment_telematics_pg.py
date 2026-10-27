# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Telematics​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ on PostgreSQL: device ingest, AEMP import, daily rollup, hire allocation, rules.

A machine-day is allocated once: its hire cost lands on the project's
equipment budget line, a second allocation adds nothing, and returning the
rental afterwards does not bill the same days again.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.costmodel.models import BudgetLine
from app.modules.equipment.models import (
    Equipment,
    EquipmentRental,
    MaintenanceSchedule,
    TelemetryReading,
    UtilisationDay,
)
from app.modules.equipment.service import EquipmentService
from app.modules.equipment.telematics import TelematicsSample, parse_aemp
from app.modules.equipment.telematics_service import TelematicsService
from app.modules.equipment.validators import run_rules
from app.modules.field_time.models import FieldSiteGeofence
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

LAT, LNG = 48.1372, 11.5755
DAY = date(2026, 10, 20)


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _site(session, *, rate_hour: str = "50", fence: bool = True) -> tuple[Project, Equipment, EquipmentRental]:
    owner = User(id=uuid.uuid4(), email=f"tlm-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Telematics", owner_id=owner.id, currency="EUR", country_code="DE")
    session.add(project)
    await session.flush()
    if fence:
        session.add(
            FieldSiteGeofence(
                project_id=project.id,
                name="Site",
                shape="circle",
                center_lat=Decimal(str(LAT)),
                center_lng=Decimal(str(LNG)),
                radius_m=Decimal("200"),
                tolerance_m=Decimal("10"),
            )
        )
    eq = Equipment(
        code=f"T-{uuid.uuid4().hex[:6]}", name="Excavator", type_code="excavator", currency="EUR", cost_code="EARTH"
    )
    session.add(eq)
    await session.flush()
    rental = EquipmentRental(
        equipment_id=eq.id,
        project_id=project.id,
        start_date=(DAY - timedelta(days=5)).isoformat(),
        internal_rate_per_hour=Decimal(rate_hour),
        internal_rate_per_day=Decimal("400"),
        currency="EUR",
        status="active",
    )
    session.add(rental)
    await session.flush()
    return project, eq, rental


def _sample(h: int, engine: str, idle: str, fuel: str, *, day: date = DAY, lat: float = LAT) -> TelematicsSample:
    return TelematicsSample(
        equipment_ref="",
        recorded_at=datetime(day.year, day.month, day.day, h, tzinfo=UTC),
        engine_hours=Decimal(engine),
        idle_hours=Decimal(idle),
        fuel_used_l=Decimal(fuel),
        lat=lat,
        lng=LNG,
    )


async def test_device_token_ingest_rolls_up_the_day(session) -> None:
    _, eq, _ = await _site(session)
    service = TelematicsService(session)
    device, token = await service.create_device(eq.id, "cab unit")
    assert token.startswith("oet_") and device.token_hash != token
    assert (await service.authenticate(token)).id == device.id
    assert await service.authenticate("oet_wrong") is None

    samples = [
        _sample(17, "100", "10", "1000", day=DAY - timedelta(days=1)),
        _sample(8, "101", "10.5", "1012"),
        _sample(16, "108", "12", "1096"),
    ]
    result = await service.ingest(samples, source="rest", equipment_id=eq.id, device=device)
    assert result["accepted"] == 3
    row = (
        await session.execute(
            select(UtilisationDay).where(UtilisationDay.equipment_id == eq.id, UtilisationDay.day == DAY)
        )
    ).scalar_one()
    assert row.worked_hours == Decimal("6") and row.idle_hours == Decimal("2") and row.off_hours == Decimal("16")
    assert row.fuel_l == Decimal("96")
    assert row.co2_kg == Decimal("257.28")
    assert row.outside_geofence_m == Decimal("0")
    assert device.last_seen_at is not None
    await session.refresh(eq)
    assert eq.hour_meter == Decimal("108")


async def test_aemp_import_matches_by_code_and_serial_and_reports_unknowns(session) -> None:
    _, eq, _ = await _site(session)
    eq.serial = f"SN-{uuid.uuid4().hex[:6]}"
    await session.flush()
    xml = f"""<Fleet xmlns="http://standards.iso.org/iso/15143/-3" version="2">
      <Equipment><EquipmentHeader><SerialNumber>{eq.serial}</SerialNumber></EquipmentHeader>
        <CumulativeOperatingHours datetime="2026-10-20T10:00:00Z"><Hour>55</Hour></CumulativeOperatingHours>
        <CumulativeIdleHours datetime="2026-10-20T10:00:00Z"><Hour>5</Hour></CumulativeIdleHours></Equipment>
      <Equipment><EquipmentHeader><EquipmentID>NOT-OURS</EquipmentID></EquipmentHeader>
        <CumulativeOperatingHours datetime="2026-10-20T10:00:00Z"><Hour>1</Hour></CumulativeOperatingHours></Equipment>
    </Fleet>""".encode()
    result = await TelematicsService(session).ingest(parse_aemp(xml), source="aemp")
    assert result["accepted"] == 1
    assert result["unmatched"] == ["NOT-OURS"]
    reading = (
        await session.execute(select(TelemetryReading).where(TelemetryReading.equipment_id == eq.id))
    ).scalar_one()
    assert reading.source == "aemp" and reading.idle_hours == Decimal("5")


async def test_allocation_posts_once_and_the_rental_return_does_not_bill_again(session) -> None:
    project, eq, rental = await _site(session, rate_hour="50")
    service = TelematicsService(session)
    await service.ingest(
        [_sample(17, "100", "10", "0", day=DAY - timedelta(days=1)), _sample(16, "108", "12", "0")],
        source="csv",
        equipment_id=eq.id,
    )
    first = await service.allocate(DAY, DAY, project.id)
    assert first == {"allocated_days": 1, "amount": "400.00", "skipped_no_project": 0}
    line = (
        await session.execute(
            select(BudgetLine).where(BudgetLine.project_id == project.id, BudgetLine.category == "equipment")
        )
    ).scalar_one()
    assert Decimal(str(line.actual_amount)) == Decimal("400.00")
    day_row = (
        await session.execute(
            select(UtilisationDay).where(UtilisationDay.equipment_id == eq.id, UtilisationDay.day == DAY)
        )
    ).scalar_one()
    assert day_row.cost_code == "EARTH" and day_row.hire_cost == Decimal("400.00")

    again = await service.allocate(DAY, DAY, project.id)
    assert again["allocated_days"] == 0
    await session.refresh(line)
    assert Decimal(str(line.actual_amount)) == Decimal("400.00")

    await session.refresh(rental)
    assert rental.metadata_["billing_mode"] == "telematics"
    returned = await EquipmentService(session).return_rental(rental.id)
    assert returned.status == "returned"
    await session.refresh(line)
    assert Decimal(str(line.actual_amount)) == Decimal("400.00")


async def test_rules_see_outside_fence_overdue_and_unallocated_machines(session) -> None:
    project, eq, rental = await _site(session)
    eq.hour_meter = Decimal("520")
    eq.location_lat, eq.location_lng = LAT + 0.01, LNG  # about 1.1 km north
    session.add(
        MaintenanceSchedule(
            equipment_id=eq.id,
            trigger_type="hours",
            trigger_threshold=Decimal("500"),
            next_due_meter=Decimal("500"),
            active=True,
        )
    )
    loose = Equipment(
        code=f"L-{uuid.uuid4().hex[:6]}", name="Loose roller", type_code="compactor", location_lat=LAT, location_lng=LNG
    )
    session.add(loose)
    rental.start_date = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    await session.flush()

    payload = await TelematicsService(session).validation_payload(project.id)
    results = await run_rules(payload)
    failed = {(r["rule_id"], r["element_ref"]) for r in results if not r["passed"]}
    assert ("equipment_telematics.maintenance_overdue", str(eq.id)) in failed
    assert ("equipment_telematics.inside_geofence", str(eq.id)) in failed
    assert ("equipment_telematics.on_site_allocated", str(loose.id)) in failed


async def test_utilisation_totals_over_a_window(session) -> None:
    project, eq, _ = await _site(session)
    service = TelematicsService(session)
    await service.ingest(
        [_sample(17, "100", "10", "0", day=DAY - timedelta(days=1)), _sample(16, "110", "14", "0")],
        source="csv",
        equipment_id=eq.id,
    )
    report = await service.utilisation(DAY, DAY, project.id)
    [m] = report["machines"]
    assert m["worked_hours"] == "6.0000" or Decimal(m["worked_hours"]) == Decimal("6")
    assert Decimal(m["idle_hours"]) == Decimal("4")
    assert report["totals"]["idle_pct"] == "40.0"


async def test_demo_seed_gives_four_machines_one_overdue_and_allocated_days(session) -> None:
    from app.modules.equipment.telematics_seed import seed_telematics_demo

    project, _, _ = await _site(session)
    counts = await seed_telematics_demo(session, [project.id])
    assert counts["machines"] == 4 and counts["readings"] > 800 and counts["allocated"] > 30
    assert (await seed_telematics_demo(session, [project.id]))["machines"] == 0
    payload = await TelematicsService(session).validation_payload(project.id)
    results = await run_rules(payload)
    overdue = [r for r in results if r["rule_id"] == "equipment_telematics.maintenance_overdue" and not r["passed"]]
    assert [r["details"]["equipment"] for r in overdue] == ["TLM-01"]
    idle = [
        r["details"]["equipment"]
        for r in results
        if r["rule_id"] == "equipment_telematics.idle_threshold" and not r["passed"]
    ]
    assert idle == ["TLM-02"]
