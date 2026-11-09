# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ on PostgreSQL: token ingest, country limits, alerts, maturity, strikes, downsampling, seed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.projects.models import Project
from app.modules.site_sensors.models import (
    ConcreteMix,
    FormworkStrip,
    SensorAlert,
    SensorDevice,
    sensor_reading,
    sensor_reading_hourly,
)
from app.modules.site_sensors.schemas import DeviceCreate, StripCreate
from app.modules.site_sensors.seed import seed_site_sensors_demo
from app.modules.site_sensors.service import SiteSensorsService
from app.modules.site_sensors.validators import run_rules
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _project(session, country: str = "DE") -> Project:
    owner = User(id=uuid.uuid4(), email=f"sen-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Sensors", owner_id=owner.id, currency="EUR", country_code=country)
    session.add(project)
    await session.flush()
    return project


async def test_dust_above_the_country_limit_opens_one_alert_until_acknowledged(session) -> None:
    project = await _project(session, "DE")
    service = SiteSensorsService(session)
    device = await service.create_device(DeviceCreate(project_id=project.id, code="PM-1", kind="dust_pm10"))
    token = await service.issue_token(device.id)
    assert (await service.authenticate(token)).id == device.id

    t0 = datetime.now(UTC) - timedelta(hours=2, minutes=30)
    report = await service.ingest(
        device, [(t0, 30.0), (t0 + timedelta(hours=1), 61.0), (t0 + timedelta(hours=2), 72.0)]
    )
    # PM10 is compared as its 24 h rolling mean: 30, 45.5, 54.33.
    assert report == {"accepted": 3, "exceedances": 1, "strips_released": 0}
    [alert] = (await session.execute(select(SensorAlert).where(SensorAlert.device_id == device.id))).scalars().all()
    assert alert.value == pytest.approx(54.33, abs=0.01) and alert.limit_value == 50.0
    assert "39. BImSchV" in alert.limit_source

    failed = [r for r in await run_rules(await service.validation_payload(project.id)) if not r["passed"]]
    assert [r["rule_id"] for r in failed] == ["site_sensors.exceedance_acknowledged"]

    await service.acknowledge(alert.id, project.owner_id, "Water bowser sent")
    failed = [r for r in await run_rules(await service.validation_payload(project.id)) if not r["passed"]]
    assert failed == []


async def test_a_device_limit_wins_and_a_country_without_one_raises_nothing(session) -> None:
    project = await _project(session, "ZZ")
    service = SiteSensorsService(session)
    noise = await service.create_device(DeviceCreate(project_id=project.id, code="NS", kind="noise"))
    water = await service.create_device(
        DeviceCreate(project_id=project.id, code="WL", kind="water_level", limit_value=Decimal("1.5"))
    )
    t = datetime(2026, 10, 20, 9, tzinfo=UTC)
    assert (await service.ingest(noise, [(t, 99.0)]))["exceedances"] == 0
    assert (await service.ingest(water, [(t, 1.8)]))["exceedances"] == 1


async def test_offline_sensor_is_flagged_and_a_new_reading_closes_it(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    device = await service.create_device(
        DeviceCreate(project_id=project.id, code="VB", kind="vibration", offline_after_minutes=30)
    )
    old = datetime.now(UTC) - timedelta(hours=3)
    await service.ingest(device, [(old, 1.0)])
    assert await service.sweep_offline(project.id) == 1
    assert await service.sweep_offline(project.id) == 0
    failed = [r["rule_id"] for r in await run_rules(await service.validation_payload(project.id)) if not r["passed"]]
    assert failed == ["site_sensors.sensor_online"]
    lines = await service.sparklines(project.id)
    assert lines[str(device.id)]["limit"] == 5.0 and len(lines[str(device.id)]["points"]) == 24
    await service.ingest(device, [(datetime.now(UTC), 1.2)])
    assert (await service.repo.open_alert(device.id, "offline")) is None


async def test_maturity_releases_the_strike_and_an_early_strike_is_flagged(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    mix = ConcreteMix(
        project_id=project.id,
        code="C30",
        datum_temp_c=Decimal("-10"),
        curve_a=Decimal("-43.1"),
        curve_b=Decimal("18.4"),
        strip_strength_mpa=Decimal("15"),
    )
    session.add(mix)
    await session.flush()
    cast = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=61)
    activity = uuid.uuid4()
    warm = await service.create_device(
        DeviceCreate(
            project_id=project.id,
            code="CM-W",
            offline_after_minutes=240,
            kind="concrete_maturity",
            mix_id=mix.id,
            cast_at=cast,
            schedule_activity_id=activity,
        )
    )
    cold = await service.create_device(
        DeviceCreate(
            project_id=project.id,
            code="CM-C",
            kind="concrete_maturity",
            mix_id=mix.id,
            cast_at=cast,
            offline_after_minutes=240,
        )
    )
    warm_strip = await service.create_strip(StripCreate(device_id=warm.id, element="Slab warm"))
    cold_strip = await service.create_strip(StripCreate(device_id=cold.id, element="Slab cold"))
    assert warm_strip.schedule_activity_id == activity and warm_strip.target_strength_mpa == Decimal("15")

    hours = range(0, 61)
    await service.ingest(warm, [(cast + timedelta(hours=h), 22.0) for h in hours])
    await service.ingest(cold, [(cast + timedelta(hours=h), 8.0) for h in hours])

    est = await service.maturity(warm.id)
    assert est["maturity_c_h"] == pytest.approx(32 * 60, rel=1e-3)
    assert est["strength_mpa"] > 15 and est["hours_to_target"] == 0
    await session.refresh(warm_strip)
    await session.refresh(cold_strip)
    assert warm_strip.status == "released" and cold_strip.status == "planned"
    reached = (await session.execute(select(SensorAlert).where(SensorAlert.kind == "strength_reached"))).scalars().all()
    assert [a.device_id for a in reached] == [warm.id]

    with pytest.raises(ValueError, match="strike_reason_required"):
        await service.strike(cold_strip.id, cast + timedelta(hours=60))
    await service.strike(cold_strip.id, cast + timedelta(hours=60), "Back-propped, cube 15.6 MPa", project.owner_id)
    await service.strike(warm_strip.id, cast + timedelta(hours=60))
    failed = [r for r in await run_rules(await service.validation_payload(project.id)) if not r["passed"]]
    assert "site_sensors.strike_after_target_strength" not in {r["rule_id"] for r in failed}
    struck = (await session.execute(select(FormworkStrip).where(FormworkStrip.id == cold_strip.id))).scalar_one()
    assert struck.strength_at_strike_mpa < Decimal("15")
    assert struck.strike_reason == "Back-propped, cube 15.6 MPa" and struck.struck_by == project.owner_id
    record = await service.pour_record(cold_strip.id)
    assert record["strike_reason"].startswith("Back-propped") and record["series"]
    ctx = await service.context(project.id)
    assert ctx["unit_system"] == "metric" and ctx["strike_ready"] == []


async def test_downsample_folds_old_raw_rows_into_hours_and_keeps_maturity(session) -> None:
    project = await _project(session)
    service = SiteSensorsService(session)
    mix = ConcreteMix(project_id=project.id, code="M", curve_a=Decimal("-43.1"), curve_b=Decimal("18.4"))
    session.add(mix)
    await session.flush()
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=40)
    device = await service.create_device(
        DeviceCreate(project_id=project.id, code="CM", kind="concrete_maturity", mix_id=mix.id, cast_at=start)
    )
    rows = [(start + timedelta(minutes=15 * i), 20.0) for i in range(4 * 48)]
    await service.ingest(device, rows)
    before = (await service.maturity(device.id))["maturity_c_h"]
    folded = await service.downsample(30)
    assert folded == len(rows)
    raw_left = (
        await session.execute(
            select(func.count()).select_from(sensor_reading).where(sensor_reading.c.device_id == device.id)
        )
    ).scalar_one()
    hourly = (
        await session.execute(
            select(func.count())
            .select_from(sensor_reading_hourly)
            .where(sensor_reading_hourly.c.device_id == device.id)
        )
    ).scalar_one()
    assert raw_left == 0 and hourly == 48
    after = (await service.maturity(device.id))["maturity_c_h"]
    assert after == pytest.approx(before, rel=0.03)


async def test_demo_seed_fills_a_project_idempotently_with_alerts_and_a_strike_ready_pour(session) -> None:
    project = await _project(session, "DE")
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)
    counts = await seed_site_sensors_demo(session, [project.id, project.id], now=now)
    assert counts["devices"] == 10
    assert counts["readings"] <= 2200
    assert await seed_site_sensors_demo(session, [project.id], now=now) == {"devices": 0, "readings": 0, "alerts": 0}

    alerts = (await session.execute(select(SensorAlert).where(SensorAlert.project_id == project.id))).scalars().all()
    exceed = [a for a in alerts if a.kind == "exceedance"]
    assert len(exceed) == 6
    assert [a.status for a in exceed].count("open") == 1
    assert all(a.acknowledged_at is not None for a in exceed if a.status == "acknowledged")
    assert any(a.kind == "offline" and a.status == "open" for a in alerts)
    assert sum(a.kind == "strength_reached" for a in alerts) == 2

    strips = (
        (await session.execute(select(FormworkStrip).where(FormworkStrip.project_id == project.id))).scalars().all()
    )
    assert sorted(s.status for s in strips) == ["planned", "released", "released", "struck"]
    struck = next(s for s in strips if s.status == "struck")
    assert struck.strength_at_strike_mpa >= struck.target_strength_mpa

    rules = await run_rules(await SiteSensorsService(session).validation_payload(project.id))
    failed = {r["rule_id"] for r in rules if not r["passed"]}
    assert failed == {"site_sensors.sensor_online", "site_sensors.exceedance_acknowledged"}
    assert any(r["passed"] for r in rules)


async def test_demo_seed_replaces_the_earlier_small_seed_and_leaves_user_sensors_alone(session) -> None:
    mine = await _project(session, "US")
    await SiteSensorsService(session).create_device(DeviceCreate(project_id=mine.id, code="MY-1", kind="noise"))
    legacy = await _project(session, "US")
    await SiteSensorsService(session).create_device(DeviceCreate(project_id=legacy.id, code="CM-01", kind="noise"))
    counts = await seed_site_sensors_demo(session, [mine.id, legacy.id])
    assert counts["devices"] == 10
    codes = (await session.execute(select(SensorDevice.code).where(SensorDevice.project_id == mine.id))).scalars().all()
    assert list(codes) == ["MY-1"]
    wind = (
        await session.execute(
            select(SensorDevice).where(SensorDevice.project_id == legacy.id, SensorDevice.code == "WX-01")
        )
    ).scalar_one()
    assert wind.unit == "mph"
