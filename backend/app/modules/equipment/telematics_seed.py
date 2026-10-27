# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Telematics demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: four machines on a demo project with two weeks of machine data.

One excavator is past its engine-hour service, one loader idles more than the
threshold, one roller is parked outside the site fence today. Every day is
rolled up and allocated, so the utilisation, hire cost and rules screens open
populated. Idempotent on the machine codes ``TLM-01`` to ``TLM-04``.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment, EquipmentRental, MaintenanceSchedule, TelemetryReading
from app.modules.equipment.telematics_service import TelematicsService

logger = logging.getLogger(__name__)

DEMO_SOURCE = "demo_telematics"

# (code, name, type, cost code, emission class, rate per hour, idle share, fuel l/h, service interval h)
_MACHINES = (
    ("TLM-01", "Crawler excavator 22 t", "excavator", "EARTHWORKS", "eu_stage_v", "68", 0.18, 14.0, 500),
    ("TLM-02", "Wheel loader 15 t", "loader", "EARTHWORKS", "eu_stage_v", "55", 0.45, 11.0, 500),
    ("TLM-03", "Tower crane 8 t", "crane", "STRUCTURE", "electric", "90", 0.25, 0.0, 250),
    ("TLM-04", "Tandem roller 9 t", "compactor", "PAVING", "eu_stage_iv", "38", 0.22, 7.0, 250),
)


def _offset(lat: float, lng: float, north_m: float, east_m: float) -> tuple[float, float]:
    import math

    return lat + north_m / 111_320.0, lng + east_m / (111_320.0 * math.cos(math.radians(lat)))


async def _site_centre(session: AsyncSession, project_id: uuid.UUID) -> tuple[float, float]:
    from app.modules.field_time.models import FieldSiteGeofence

    fence = (
        (
            await session.execute(
                select(FieldSiteGeofence).where(
                    FieldSiteGeofence.project_id == project_id, FieldSiteGeofence.active.is_(True)
                )
            )
        )
        .scalars()
        .first()
    )
    if fence is not None and fence.center_lat is not None and fence.center_lng is not None:
        return float(fence.center_lat), float(fence.center_lng)
    if fence is not None and fence.polygon:
        pts = [(float(p[0]), float(p[1])) for p in fence.polygon]
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    lat, lng = 48.1372, 11.5755
    session.add(
        FieldSiteGeofence(
            project_id=project_id,
            name="Site boundary",
            shape="circle",
            center_lat=Decimal(str(lat)),
            center_lng=Decimal(str(lng)),
            radius_m=Decimal("200"),
            tolerance_m=Decimal("20"),
            metadata_={"source": DEMO_SOURCE},
        )
    )
    await session.flush()
    return lat, lng


async def seed_telematics_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed the telematics fleet on the first of ``project_ids``. The caller commits."""
    counts = {"machines": 0, "readings": 0, "days": 0, "allocated": 0}
    ids = list(project_ids)
    if not ids:
        return counts
    if (await session.execute(select(Equipment.id).where(Equipment.code == "TLM-01"))).first() is not None:
        return counts
    from app.modules.projects.models import Project

    project = await session.get(Project, ids[0])
    if project is None:
        return counts
    lat0, lng0 = await _site_centre(session, project.id)
    rng = random.Random(1514)
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    first_day = (now - timedelta(days=13)).date()
    currency = (project.currency or "EUR")[:3]

    for idx, (code, name, type_code, cost_code, emission, rate, idle_share, fuel_lph, interval) in enumerate(_MACHINES):
        start_hours = Decimal(1200 + 650 * idx)
        eq = Equipment(
            code=code,
            name=name,
            type_code=type_code,
            ownership="rented" if idx % 2 else "owned",
            status="active",
            hour_meter=start_hours,
            currency=currency,
            cost_code=cost_code,
            emission_class=emission,
            metadata_={"source": DEMO_SOURCE},
        )
        session.add(eq)
        await session.flush()
        session.add(
            EquipmentRental(
                equipment_id=eq.id,
                project_id=project.id,
                start_date=first_day.isoformat(),
                internal_rate_per_hour=Decimal(rate),
                internal_rate_per_day=Decimal(rate) * 8,
                currency=currency,
                status="active",
                metadata_={"source": DEMO_SOURCE, "cost_code": cost_code},
            )
        )
        engine = float(start_hours)
        idle = engine * idle_share
        fuel = engine * fuel_lph
        north, east = rng.uniform(-80, 80), rng.uniform(-80, 80)
        for d in range(14):
            day = first_day + timedelta(days=d)
            if day.weekday() == 6:
                continue
            for half in range(0, 21):
                ts = datetime(day.year, day.month, day.day, 6, 30, tzinfo=UTC) + timedelta(minutes=30 * half)
                if ts > now:
                    break
                running = rng.random() < 0.85
                if running:
                    step = 0.5
                    engine += step
                    idle += step * idle_share * rng.uniform(0.8, 1.2)
                    fuel += step * fuel_lph * rng.uniform(0.85, 1.1)
                if code == "TLM-04" and d == 13:
                    north, east = 650.0, 120.0  # parked on the road outside the fence today
                lat, lng = _offset(lat0, lng0, north + rng.uniform(-5, 5), east + rng.uniform(-5, 5))
                session.add(
                    TelemetryReading(
                        equipment_id=eq.id,
                        recorded_at=ts,
                        hour_meter=Decimal(str(round(engine, 2))),
                        idle_hours=Decimal(str(round(idle, 2))),
                        fuel_used_l=Decimal(str(round(fuel, 1))) if fuel_lph else None,
                        fuel_level=Decimal(str(rng.randint(35, 90))),
                        lat=lat,
                        lng=lng,
                        engine_status="running" if running else "off",
                        source="aemp",
                        raw_payload={},
                    )
                )
                counts["readings"] += 1
                eq.last_telemetry_at = ts
                eq.location_lat, eq.location_lng = lat, lng
        eq.hour_meter = Decimal(str(round(engine, 2)))
        # TLM-01 crossed its service 30 engine hours ago; the others are inside their interval.
        due = Decimal(str(round(engine - 30, 0))) if code == "TLM-01" else Decimal(str(round(engine + interval / 3, 0)))
        session.add(
            MaintenanceSchedule(
                equipment_id=eq.id,
                trigger_type="hours",
                trigger_threshold=Decimal(interval),
                description=f"{interval} h service",
                last_completed_meter=due - interval,
                next_due_meter=due,
                active=True,
            )
        )
        counts["machines"] += 1
    await session.flush()

    service = TelematicsService(session)
    machines = (await session.execute(select(Equipment).where(Equipment.code.like("TLM-%")))).scalars().all()
    for eq in machines:
        for d in range(14):
            if await service.rollup_day(eq.id, first_day + timedelta(days=d)) is not None:
                counts["days"] += 1
    result = await service.allocate(first_day, now.date() - timedelta(days=1), project.id)
    counts["allocated"] = int(result["allocated_days"])
    return counts
