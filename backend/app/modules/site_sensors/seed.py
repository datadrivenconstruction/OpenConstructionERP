# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: a slab pour with three maturity sensors, noise and dust on the fence.

The core sensor of the pour reaches the strike strength and releases its
formwork strike; the two edge sensors run colder and have not. The noise
sensor carries one unacknowledged exceedance. Readings go through the service,
so the alerts, the released strike and the notifications are the real ones.
Idempotent on the device code ``CM-01`` per project.
"""

from __future__ import annotations

import math
import random
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_sensors.models import ConcreteMix, SensorDevice
from app.modules.site_sensors.schemas import DeviceCreate, StripCreate
from app.modules.site_sensors.service import SiteSensorsService

# Calibrated on the demo mix: 15 MPa at about 1 400 degC-h, 25 MPa at about 5 000 degC-h.
_MIX = {"code": "C30/37-CEM II", "name": "C30/37 slab mix", "curve_a": "-43.1", "curve_b": "18.4", "strip": "15"}
# (code, name, mean temperature, swing)
_POUR = (
    ("CM-01", "Slab L03 core", 21.0, 3.0),
    ("CM-02", "Slab L03 north edge", 8.0, 3.0),
    ("CM-03", "Slab L03 east edge", 7.0, 3.5),
)


async def _first_activity(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID | None:
    try:
        from app.modules.schedule.models import Activity, Schedule

        row = (
            await session.execute(
                select(Activity.id)
                .join(Schedule, Activity.schedule_id == Schedule.id)
                .where(Schedule.project_id == project_id)
                .limit(1)
            )
        ).first()
        return row[0] if row else None
    except Exception:
        return None


async def seed_site_sensors_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seed the pour and the environment sensors on the first of ``project_ids``. The caller commits."""
    counts = {"devices": 0, "readings": 0, "alerts": 0}
    ids = list(project_ids)
    if not ids:
        return counts
    project_id = ids[0]
    exists = await session.execute(
        select(SensorDevice.id).where(SensorDevice.project_id == project_id, SensorDevice.code == "CM-01")
    )
    if exists.first() is not None:
        return counts
    service = SiteSensorsService(session)
    rng = random.Random(1074)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    cast_at = now - timedelta(hours=62)
    mix = ConcreteMix(
        project_id=project_id,
        code=_MIX["code"],
        name=_MIX["name"],
        datum_temp_c=Decimal("-10"),
        curve_a=Decimal(_MIX["curve_a"]),
        curve_b=Decimal(_MIX["curve_b"]),
        strip_strength_mpa=Decimal(_MIX["strip"]),
        notes="Curve from the mix calibration cubes at 1, 3, 7 and 28 days.",
    )
    session.add(mix)
    await session.flush()
    activity_id = await _first_activity(session, project_id)

    for code, name, mean, swing in _POUR:
        device = await service.create_device(
            DeviceCreate(
                project_id=project_id,
                code=code,
                name=name,
                kind="concrete_maturity",
                mix_id=mix.id,
                pour_ref="Slab L03 pour 2",
                cast_at=cast_at,
                schedule_activity_id=activity_id,
                offline_after_minutes=120,
            )
        )
        await service.create_strip(StripCreate(device_id=device.id, element=f"Slab L03 pour 2 ({name})"))
        rows = []
        t = cast_at
        while t <= now:
            hours = (t - cast_at).total_seconds() / 3600
            hydration = 6.0 * math.exp(-((hours - 18) ** 2) / 200)  # heat of hydration on the first day
            rows.append((t, mean + hydration + swing * math.sin(hours / 24 * 2 * math.pi) + rng.uniform(-0.3, 0.3)))
            t += timedelta(minutes=30)
        await service.ingest(device, rows)
        counts["devices"] += 1
        counts["readings"] += len(rows)

    for code, name, kind, base, spread in (
        ("NS-01", "Noise, north fence", "noise", 62.0, 4.0),
        ("PM-01", "Dust PM10, north fence", "dust_pm10", 22.0, 8.0),
    ):
        device = await service.create_device(
            DeviceCreate(project_id=project_id, code=code, name=name, kind=kind, offline_after_minutes=120)
        )
        limit, _ = await service.limit_of(device, now)
        if limit is None:
            device.limit_value = Decimal("70" if kind == "noise" else "50")
            limit = float(device.limit_value)
        rows = []
        t = now - timedelta(days=3)
        while t <= now:
            v = base + rng.uniform(-spread, spread) if 6 <= t.hour < 19 else base - 15 + rng.uniform(0, 3)
            rows.append((t, round(min(v, limit - 1), 1)))
            t += timedelta(hours=1)
        if kind == "noise":
            peak_at = (now - timedelta(days=1)).replace(hour=10, minute=0)
            rows = [(t, v) for t, v in rows if t != peak_at] + [(peak_at, round(limit + 6.5, 1))]
        await service.ingest(device, rows)
        counts["devices"] += 1
        counts["readings"] += len(rows)

    counts["alerts"] = len(await service.repo.alerts(project_id))
    return counts
