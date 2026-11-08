# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Daily diary entries and weather from site sensors.

A limit exceedance and a formwork strike each become a draft entry in the
day's diary (``metadata.draft`` until the site manager confirms it), and the
alert is linked back to the diary. Weather sensors give the day's min and max,
stored as a weather record with ``source="sensor"`` and in the diary's
weather summary under ``sensor``. A closed diary is never touched.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.daily_diary.models import DailyDiary, DiaryEntry, WeatherRecord

logger = logging.getLogger(__name__)

SOURCE = "site_sensors"
WEATHER_KINDS = ("weather",)


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _day(value: object) -> date:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            pass
    return datetime.now(UTC).date()


async def open_diary(session: AsyncSession, project_id: uuid.UUID, day: date) -> DailyDiary | None:
    """The day's diary, created when missing. None when the day is already closed."""
    stmt = select(DailyDiary).where(DailyDiary.project_id == project_id, DailyDiary.diary_date == day.isoformat())
    diary = (await session.execute(stmt)).scalars().first()
    if diary is None:
        diary = DailyDiary(project_id=project_id, diary_date=day.isoformat(), status="open", weather_summary={})
        session.add(diary)
        await session.flush()
    return diary if diary.status == "open" else None


async def _existing(session: AsyncSession, ref: uuid.UUID, kind: str) -> DiaryEntry | None:
    stmt = select(DiaryEntry).where(DiaryEntry.source_module == SOURCE, DiaryEntry.source_ref == ref)
    for entry in (await session.execute(stmt)).scalars():
        if (entry.metadata_ or {}).get("kind") == kind:
            return entry
    return None


async def record_exceedance(session: AsyncSession, data: dict[str, Any]) -> DiaryEntry | None:
    """Draft entry for one exceedance episode; links the alert to the diary."""
    from app.modules.site_sensors.models import SensorAlert, SensorDevice

    alert_id, project_id = _uuid(data.get("alert_id")), _uuid(data.get("project_id"))
    if alert_id is None or project_id is None:
        return None
    alert = await session.get(SensorAlert, alert_id)
    if alert is None or alert.project_id != project_id:
        return None
    found = await _existing(session, alert_id, "exceedance")
    if found is not None:
        return found
    diary = await open_diary(session, project_id, alert.raised_at.date())
    if diary is None:
        return None
    device = await session.get(SensorDevice, alert.device_id)
    code = device.code if device else ""
    unit = device.unit if device else ""
    params = {"device": code, "value": f"{alert.value:g}", "limit": f"{alert.limit_value:g}", "unit": unit}
    entry = DiaryEntry(
        diary_id=diary.id,
        entry_type="event",
        entry_time=alert.raised_at,
        title=f"Sensor {code}: {params['value']} {unit} above limit {params['limit']} {unit}"[:500],
        description=alert.limit_source or None,
        source_module=SOURCE,
        source_ref=alert_id,
        metadata_={"kind": "exceedance", "draft": True, "title_key": "dailyDiary.sensor_exceedance", "params": params},
    )
    session.add(entry)
    alert.diary_id = diary.id
    await session.flush()
    await apply_sensor_weather(session, diary)
    return entry


async def record_strike(session: AsyncSession, data: dict[str, Any]) -> DiaryEntry | None:
    """Draft completion entry for a formwork strike."""
    strip_id, project_id = _uuid(data.get("strip_id")), _uuid(data.get("project_id"))
    if strip_id is None or project_id is None:
        return None
    from app.modules.site_sensors.models import FormworkStrip

    strip = await session.get(FormworkStrip, strip_id)
    if strip is None or strip.project_id != project_id:
        return None
    found = await _existing(session, strip_id, "strike")
    if found is not None:
        return found
    when = strip.struck_at or datetime.now(UTC)
    diary = await open_diary(session, project_id, when.date())
    if diary is None:
        return None
    strength = data.get("strength_mpa")
    params = {
        "element": strip.element,
        "strength": f"{strength:g}" if isinstance(strength, int | float) else "",
        "target": f"{float(strip.target_strength_mpa):g}",
    }
    entry = DiaryEntry(
        diary_id=diary.id,
        entry_type="completion",
        entry_time=when,
        title=f"Formwork struck: {params['element']} at {params['strength']} MPa (target {params['target']})"[:500],
        source_module=SOURCE,
        source_ref=strip_id,
        metadata_={"kind": "strike", "draft": True, "title_key": "dailyDiary.sensor_strike", "params": params},
    )
    session.add(entry)
    await session.flush()
    await apply_sensor_weather(session, diary)
    return entry


async def sensor_day_range(session: AsyncSession, project_id: uuid.UUID, day: date) -> dict[str, Any] | None:
    """Min and max over the day for the project's weather sensors, raw and hourly rows together."""
    from app.modules.site_sensors.models import SensorDevice, sensor_reading, sensor_reading_hourly

    devices = list(
        (
            await session.execute(
                select(SensorDevice).where(SensorDevice.project_id == project_id, SensorDevice.kind.in_(WEATHER_KINDS))
            )
        ).scalars()
    )
    if not devices:
        return None
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    ids = [d.id for d in devices]
    raw = (
        await session.execute(
            select(func.min(sensor_reading.c.value), func.max(sensor_reading.c.value)).where(
                sensor_reading.c.device_id.in_(ids),
                sensor_reading.c.recorded_at >= start,
                sensor_reading.c.recorded_at < end,
            )
        )
    ).one()
    hourly = (
        await session.execute(
            select(func.min(sensor_reading_hourly.c.v_min), func.max(sensor_reading_hourly.c.v_max)).where(
                sensor_reading_hourly.c.device_id.in_(ids),
                sensor_reading_hourly.c.hour >= start,
                sensor_reading_hourly.c.hour < end,
            )
        )
    ).one()
    lows = [v for v in (raw[0], hourly[0]) if v is not None]
    highs = [v for v in (raw[1], hourly[1]) if v is not None]
    if not lows:
        return None
    return {
        "min": round(min(lows), 2),
        "max": round(max(highs), 2),
        "unit": devices[0].unit,
        "devices": sorted(d.code for d in devices),
    }


async def apply_sensor_weather(session: AsyncSession, diary: DailyDiary) -> dict[str, Any] | None:
    """Write the day's sensor range into the diary weather. Returns the range, or None."""
    day = _day(diary.diary_date)
    rng = await sensor_day_range(session, diary.project_id, day)
    if rng is None or diary.status != "open":
        return rng
    summary = dict(diary.weather_summary or {})
    summary["sensor"] = {**rng, "source": "sensor"}
    diary.weather_summary = summary
    start = datetime.combine(day, time(12), tzinfo=UTC)
    stmt = select(WeatherRecord).where(
        WeatherRecord.project_id == diary.project_id,
        WeatherRecord.source == "sensor",
        WeatherRecord.captured_at == start,
    )
    rec = (await session.execute(stmt)).scalars().first()
    if rec is None:
        rec = WeatherRecord(project_id=diary.project_id, captured_at=start, source="sensor")
        session.add(rec)
    # Site weather stations report wind speed; m/s is converted for the diary column.
    if rng["unit"] == "m/s":
        rec.wind_speed_kmh = round(rng["max"] * 3.6, 2)
    rec.metadata_ = {"day_min": rng["min"], "day_max": rng["max"], "unit": rng["unit"], "devices": rng["devices"]}
    await session.flush()
    return rng
