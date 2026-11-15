# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Fleet tenancy on PostgreSQL: one tenant never sees or changes another tenant's machines.

Both tenants hire a machine to the same project and both use the unit code
``EX-1``. Scoped services (what the HTTP layer builds) must see only their own
unit, rentals, telemetry and cost figures, get a 404 for the other's ids, and
leave the other's rows untouched. System mode (no tenant) still sees both.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.equipment.models import Equipment, EquipmentRental, TelemetryReading
from app.modules.equipment.schemas import EquipmentCreate, TelemetryReadingCreate
from app.modules.equipment.service import EquipmentService
from app.modules.equipment.telematics import TelematicsSample
from app.modules.equipment.telematics_service import TelematicsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

DAY = date(2026, 10, 20)
CODE = "EX-1"


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _fleet(session):
    """Two tenants, one shared project, one unit (same code) and one rental each."""
    owner = User(id=uuid.uuid4(), email=f"ten-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Shared", owner_id=owner.id, currency="EUR", country_code="DE")
    session.add(project)
    await session.flush()
    out = {}
    for tenant in (f"ta-{uuid.uuid4().hex[:6]}", f"tb-{uuid.uuid4().hex[:6]}"):
        unit = await EquipmentService(session, tenant).create_equipment(
            EquipmentCreate(code=CODE, name=f"Excavator {tenant}", type_code="excavator", currency="EUR")
        )
        rental = EquipmentRental(
            equipment_id=unit.id,
            project_id=project.id,
            start_date=(DAY - timedelta(days=5)).isoformat(),
            internal_rate_per_hour=Decimal("50"),
            internal_rate_per_day=Decimal("400"),
            currency="EUR",
            status="active",
        )
        session.add(rental)
        await session.flush()
        await TelematicsService(session).ingest(
            [
                TelematicsSample(
                    equipment_ref="",
                    recorded_at=datetime(DAY.year, DAY.month, DAY.day, h, tzinfo=UTC),
                    engine_hours=Decimal(eng),
                    idle_hours=Decimal("0"),
                    fuel_used_l=Decimal("10"),
                    lat=None,
                    lng=None,
                )
                for h, eng in ((8, "100"), (16, "108"))
            ],
            source="rest",
            equipment_id=unit.id,
        )
        out[tenant] = (unit, rental)
    return project, out


async def test_the_same_unit_code_lives_in_two_tenants_but_not_twice_in_one(session) -> None:
    _, fleet = await _fleet(session)
    (ta, (unit_a, _)), (tb, (unit_b, _)) = fleet.items()
    assert unit_a.code == unit_b.code == CODE and unit_a.id != unit_b.id

    with pytest.raises(HTTPException) as err:
        await EquipmentService(session, ta).create_equipment(EquipmentCreate(code=CODE, name="Dup", type_code="other"))
    assert err.value.status_code == 409

    # The database holds the line too, whatever the service does.
    session.add(Equipment(tenant_id=tb, code=CODE, name="Raw dup", type_code="other"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_scoped_service_sees_only_its_own_units_and_rentals(session) -> None:
    _, fleet = await _fleet(session)
    (ta, (unit_a, rental_a)), (tb, (unit_b, rental_b)) = fleet.items()
    service_a = EquipmentService(session, ta)

    rows, total = await service_a.equipment_repo.list_(limit=100)
    assert {r.id for r in rows} == {unit_a.id} and total == 1
    assert (await service_a.rental_repo.get_by_id(rental_a.id)) is not None
    assert await service_a.rental_repo.get_by_id(rental_b.id) is None
    with pytest.raises(HTTPException) as err:
        await service_a.get_equipment(unit_b.id)
    assert err.value.status_code == 404
    assert (await service_a.fleet_dashboard()).total_units == 1

    system_rows, _ = await EquipmentService(session).equipment_repo.list_(limit=100)
    assert {unit_a.id, unit_b.id} <= {r.id for r in system_rows}


async def test_a_tenant_cannot_change_or_delete_the_other_tenants_unit(session) -> None:
    _, fleet = await _fleet(session)
    (ta, _), (tb, (unit_b, rental_b)) = fleet.items()
    service_a = EquipmentService(session, ta)

    with pytest.raises(HTTPException) as err:
        await service_a.update_rental(rental_b.id, {"status": "returned"})
    assert err.value.status_code == 404
    with pytest.raises(HTTPException):
        await service_a.delete_equipment(unit_b.id)
    before = len(
        (await session.execute(select(TelemetryReading).where(TelemetryReading.equipment_id == unit_b.id))).all()
    )
    before = len(
        (await session.execute(select(TelemetryReading).where(TelemetryReading.equipment_id == unit_b.id))).all()
    )
    with pytest.raises(HTTPException):
        await service_a.record_telemetry(unit_b.id, TelemetryReadingCreate(recorded_at=datetime.now(UTC)))

    await session.refresh(rental_b)
    assert rental_b.status == "active"
    assert (await EquipmentService(session, tb).get_equipment(unit_b.id)).id == unit_b.id
    after = len(
        (await session.execute(select(TelemetryReading).where(TelemetryReading.equipment_id == unit_b.id))).all()
    )
    assert after == before


async def test_telemetry_and_cost_board_never_cross_tenants(session) -> None:
    project, fleet = await _fleet(session)
    (ta, (unit_a, _)), (tb, (unit_b, _)) = fleet.items()
    service_a = EquipmentService(session, ta)
    telematics_a = TelematicsService(session, ta)

    assert await service_a.list_telemetry(unit_b.id) == []
    with pytest.raises(HTTPException) as err:
        await service_a.equipment_cost_summary(unit_b.id)
    assert err.value.status_code == 404
    with pytest.raises(LookupError):
        await telematics_a.create_device(unit_b.id, "intruder")

    board = await telematics_a.utilisation(DAY, DAY)
    assert {m["equipment_id"] for m in board["machines"]} == {str(unit_a.id)}
    board_b = await TelematicsService(session, tb).utilisation(DAY, DAY)
    assert {m["equipment_id"] for m in board_b["machines"]} == {str(unit_b.id)}

    first = await telematics_a.allocate(DAY, DAY, project.id)
    assert first["allocated_days"] == 1  # A's machine-day only; B's stays unbooked
    second = await TelematicsService(session, tb).allocate(DAY, DAY, project.id)
    assert second["allocated_days"] == 1
