# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors on PostgreSQL: custom sensors, readings typed in or imported, their audit trail, limit overrides."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.projects.models import Project
from app.modules.site_sensors.models import SensorAlert, sensor_reading
from app.modules.site_sensors.schemas import DeviceCreate, DeviceUpdate, MixCreate, MixUpdate, ReadingIn
from app.modules.site_sensors.seed import seed_site_sensors_demo
from app.modules.site_sensors.service import SiteSensorsService
from app.modules.site_sensors.validators import run_rules
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 2, 8, tzinfo=UTC)


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _user(session, name: str = "Site engineer") -> User:
    user = User(id=uuid.uuid4(), email=f"sm-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name=name)
    session.add(user)
    await session.flush()
    return user


async def _project(session, country: str = "DE") -> Project:
    owner = await _user(session, "Owner")
    project = Project(id=uuid.uuid4(), name="Sensors", owner_id=owner.id, currency="EUR", country_code=country)
    session.add(project)
    await session.flush()
    return project


async def _pump(service: SiteSensorsService, project: Project):
    return await service.create_device(
        DeviceCreate(
            project_id=project.id,
            code="FL-1",
            name="Pump flow",
            kind="custom",
            unit="m3/h",
            limit_value=Decimal("60"),
            lower_limit=Decimal("18"),
            limit_note="Dewatering design D-104",
        )
    )


async def test_custom_sensor_alerts_above_the_upper_and_below_the_lower_limit(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    pump = await _pump(service, project)
    assert (await service.ingest(pump, [(T0, 40.0)]))["exceedances"] == 0
    assert (await service.ingest(pump, [(T0 + timedelta(hours=1), 64.0)]))["exceedances"] == 1
    [alert] = (await session.execute(select(SensorAlert).where(SensorAlert.device_id == pump.id))).scalars().all()
    assert alert.limit_value == 60.0 and alert.limit_source == "Dewatering design D-104"
    await service.acknowledge(alert.id, project.owner_id, "Valve throttled")
    assert (await service.ingest(pump, [(T0 + timedelta(hours=2), 12.0)]))["exceedances"] == 1
    low = await service.repo.open_alert(pump.id, "exceedance")
    assert low is not None and low.value == 12.0 and low.limit_value == 18.0


async def test_record_only_custom_sensor_raises_nothing_and_passes_the_rules(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    load = await service.create_device(
        DeviceCreate(project_id=project.id, code="LC-1", kind="custom", unit="kN", record_only=True)
    )
    assert (await service.ingest(load, [(T0, 9999.0)]))["exceedances"] == 0
    rules = await run_rules(await service.validation_payload(project.id))
    assert not [r for r in rules if not r["passed"] and r["rule_id"] != "site_sensors.sensor_online"]


async def test_custom_rolling_window_compares_the_mean(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    dev = await service.create_device(
        DeviceCreate(
            project_id=project.id,
            code="RH-1",
            kind="custom",
            unit="%RH",
            limit_value=Decimal("80"),
            rolling_mean_hours=3,
        )
    )
    report = await service.ingest(dev, [(T0, 70.0), (T0 + timedelta(hours=1), 85.0)])
    # Means 70 and 77.5, both under 80, although the second reading is above it.
    assert report["exceedances"] == 0


async def test_manual_readings_keep_source_author_note_and_skip_taken_times(session) -> None:
    project = await _project(session)
    engineer = await _user(session, "Site engineer")
    service = SiteSensorsService(session)
    pump = await _pump(service, project)
    await service.ingest(pump, [(T0, 40.0)])
    report = await service.add_user_readings(
        pump,
        [
            ReadingIn(recorded_at=T0, value=41.0, note="clash"),
            ReadingIn(recorded_at=T0 + timedelta(minutes=30), value=42.5, note="Meter read at the check"),
        ],
        "manual",
        engineer.id,
    )
    assert report["accepted"] == 1 and report["skipped"] == 1
    raw = (await service.readings(pump.id, None, None))["raw"]
    assert [(r["v"], r["source"]) for r in raw] == [(40.0, "device"), (42.5, "manual")]
    assert raw[1]["entered_by"] == str(engineer.id) and raw[1]["entered_by_name"] == "Site engineer"
    assert raw[1]["note"] == "Meter read at the check"
    imported = await service.add_user_readings(
        pump, [ReadingIn(recorded_at=T0 + timedelta(hours=1), value=70.0)], "import", engineer.id
    )
    assert imported["exceedances"] == 1


async def test_only_the_author_or_a_manager_edits_and_every_change_is_audited(session) -> None:
    project = await _project(session)
    author = await _user(session, "Author")
    other = await _user(session, "Other")
    service = SiteSensorsService(session)
    pump = await _pump(service, project)
    t = T0 + timedelta(minutes=30)
    await service.ingest(pump, [(T0, 40.0)])
    await service.add_user_readings(pump, [ReadingIn(recorded_at=t, value=30.0)], "manual", author.id)

    with pytest.raises(PermissionError):
        await service.edit_reading(pump, t, 31.0, "", other.id)
    with pytest.raises(ValueError, match="device_reading_not_editable"):
        await service.edit_reading(pump, T0, 1.0, "", author.id, is_manager=True)
    out = await service.edit_reading(pump, t, 65.0, "Typo, meter showed 65", author.id)
    assert out["exceedances"] == 1
    await service.delete_reading(pump, t, other.id, is_manager=True)

    left = (await session.execute(select(func.count()).select_from(sensor_reading))).scalar_one()
    assert left >= 1
    audit = await service.reading_audit(pump.id)
    assert [a["action"] for a in audit] == ["delete", "update", "create"]
    assert audit[1]["value_before"] == 30.0 and audit[1]["value_after"] == 65.0
    assert audit[0]["user_name"] == "Other" and audit[0]["value_before"] == 65.0


async def test_downsample_keeps_hand_entered_readings_raw(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    pump = await _pump(service, project)
    old = datetime.now(UTC) - timedelta(days=60)
    await service.ingest(pump, [(old, 40.0)])
    await service.add_user_readings(
        pump, [ReadingIn(recorded_at=old + timedelta(minutes=30), value=41.0)], "manual", project.owner_id
    )
    assert await service.downsample(30) == 1
    raw = (await service.readings(pump.id, None, None))["raw"]
    assert [r["source"] for r in raw] == ["manual"]


async def test_an_override_of_the_country_limit_shows_the_country_figure_and_needs_a_reason(session) -> None:
    project = await _project(session, "DE")
    service = SiteSensorsService(session)
    dust = await service.create_device(
        DeviceCreate(project_id=project.id, code="PM-1", kind="dust_pm10", limit_value=Decimal("40"))
    )
    shown = await service.describe_limit(dust)
    assert shown["effective_limit"] == 40.0 and shown["country_limit"] == 50.0
    rules = {r["rule_id"]: r for r in await run_rules(await service.validation_payload(project.id))}
    assert rules["site_sensors.limit_override_explained"]["passed"] is False
    await service.update_device(dust.id, DeviceUpdate(limit_note="Stricter limit in the planning consent"))
    rules = {r["rule_id"]: r for r in await run_rules(await service.validation_payload(project.id))}
    assert rules["site_sensors.limit_override_explained"]["passed"] is True
    with pytest.raises(ValueError, match="lower_limit_not_below_upper"):
        await service.update_device(dust.id, DeviceUpdate(lower_limit=Decimal("45")))


async def test_a_mix_takes_its_own_datum_temperature(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    mix = await service.create_mix(
        MixCreate(project_id=project.id, code="M1", curve_a=Decimal("-40"), curve_b=Decimal("18"))
    )
    updated = await service.update_mix(mix.id, MixUpdate(datum_temp_c=Decimal("-10")))
    assert updated.datum_temp_c == Decimal("-10")


async def test_demo_seed_shows_a_custom_sensor_with_hand_readings(session) -> None:
    project = await _project(session, "DE")
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)
    await seed_site_sensors_demo(session, [project.id], now=now)
    service = SiteSensorsService(session)
    [pump] = await service.repo.devices(project.id, "custom")
    assert pump.unit == "m3/h" and pump.lower_limit is not None and pump.limit_note
    raw = (await service.readings(pump.id, None, None))["raw"]
    manual = [r for r in raw if r["source"] == "manual"]
    assert len(manual) == 3 and all(r["note"] for r in manual)
