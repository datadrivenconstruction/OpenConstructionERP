# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: two weeks of readings, alerts and formwork strikes on a site.
The module looks lived in for two weeks on every showcase project: three
concrete pours (one struck, one past its strike strength, one approaching),
noise, dust, vibration, wind and water-level sensors on the boundary, a few
limit breaches with acknowledged alerts and one still open, and one vibration
sensor that has gone silent. A custom sensor the site defined itself (dewatering
pump flow in m3/h, with an upper and a lower limit) carries a few readings typed
in from the flow meter, with notes. Limits come from the project's country through the
service; wind and water-level limits are set on the device. Readings go through
the service, so the alerts, the released strikes and the notifications are the
real ones. Fixed random seed per project, readings capped at about two thousand
per project, idempotent on the device code ``WX-01`` per project.
"""

from __future__ import annotations

import math
import random
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_sensors.analysis import rolling_mean
from app.modules.site_sensors.maturity import nurse_saul, strength_from_maturity
from app.modules.site_sensors.models import (
    ConcreteMix,
    FormworkStrip,
    SensorAlert,
    SensorDevice,
    sensor_reading,
    sensor_reading_hourly,
)
from app.modules.site_sensors.schemas import CalibrationPointIn, DeviceCreate, ReadingIn, StripCreate
from app.modules.site_sensors.service import ROLLING_MEAN_HOURS, SiteSensorsService

#: Projects seeded per call; the demo shows a handful, not every imported pack.
_MAX_PROJECTS = 6
#: Marker of the current seed. Projects that only hold the earlier, smaller seed are replaced.
_MARKER = "WX-01"
_LEGACY_CODES = ("CM-01", "CM-02", "CM-03", "NS-01", "PM-01")
_DAYS = 14
# Calibrated on the demo mix: 15 MPa at about 1 400 degC-h, 25 MPa at about 5 000 degC-h.
_MIX = {"code": "C30/37-CEM II", "name": "C30/37 slab mix", "curve_a": "-43.1", "curve_b": "18.4", "strip": "15"}
_DATUM_C = 0.0
_IMPERIAL = {"US"}
_M_TO_FT = 3.28084
_MS_TO_MPH = 2.23694
#: Used where the country data holds no figure for the kind.
_FALLBACK_LIMIT = {"noise": "70", "dust_pm10": "50", "vibration": "5"}
_WIND_LIMIT_MS = 15.0
_WATER_LIMIT_M = 1.8
#: Why the wind and water limits sit on the device: no country figure, the site sets them.
_LIMIT_NOTES = {
    "weather": "Crane manufacturer's in-service wind limit",
    "water_level": "Dewatering design: excavation sump alarm level",
}
#: The custom sensor: code, name, unit, lower and upper limit, where the limits come from.
_CUSTOM = (
    "FL-01",
    "Dewatering pump flow, sump P1",
    "m3/h",
    Decimal("18"),
    Decimal("60"),
    "Dewatering design: minimum to hold the drawdown, maximum of the discharge consent",
)
#: Hand readings from the flow meter: (hours ago, share of the band, note).
_CUSTOM_MANUAL = (
    (52.5, 0.55, "Read off the flow meter at the morning check"),
    (28.5, 0.62, "After the second pump was started"),
    (4.5, 0.48, "Meter checked by the dewatering subcontractor"),
)


@dataclass(frozen=True)
class Spike:
    """A limit breach: ``days_ago`` at ``hour`` UTC, ``peak`` times the limit, lasting ``hours``."""

    days_ago: int
    hour: int
    peak: float
    hours: int
    note: str | None  # None leaves the alert open


@dataclass(frozen=True)
class Pour:
    code: str
    name: str
    pour_ref: str
    cast_hours_ago: int
    mean_c: float
    swing_c: float
    #: (element, target MPa, hours after reaching it that the strike was done, None = not struck, "ahead" = planned)
    strips: tuple[tuple[str, str, int | None], ...]


_POURS = (
    Pour(
        "CM-01",
        "Wall W2 core",
        "Wall W2, level 02",
        13 * 24,
        16.0,
        3.0,
        (("Wall W2 side forms", "15", 20), ("Wall W2 props", "25", None)),
    ),
    Pour("CM-02", "Slab L03 core", "Slab L03 pour 2", 5 * 24, 19.0, 3.0, (("Slab L03 pour 2 soffit", "15", None),)),
    Pour("CM-03", "Slab L04 core", "Slab L04 pour 1", 46, 13.0, 3.5, (("Slab L04 pour 1 soffit", "15", None),)),
)

#: (code, name, kind, step hours, spikes). The only open breach is the latest one on NS-01.
_ENV = (
    (
        "NS-01",
        "Noise, north fence",
        "noise",
        1,
        (
            Spike(8, 10, 1.12, 2, "Saw cutting moved behind the acoustic screen, foreman briefed."),
            Spike(1, 10, 1.09, 1, None),
        ),
    ),
    (
        "PM-01",
        "Dust PM10, north fence",
        "dust_pm10",
        1,
        (Spike(4, 6, 2.4, 20, "Water bowser on the haul road, dust screen repaired."),),
    ),
    (
        "VB-01",
        "Vibration, party wall",
        "vibration",
        2,
        (Spike(10, 11, 1.18, 2, "Vibro piling stopped, switched to pressed piles."),),
    ),
    ("VB-02", "Vibration, east boundary", "vibration", 2, ()),
    (
        "WX-01",
        "Wind, crane tower",
        "weather",
        1,
        (Spike(6, 15, 1.08, 2, "Crane stood down until the gusts passed."),),
    ),
    (
        "WL-01",
        "Water level, excavation sump",
        "water_level",
        3,
        (Spike(2, 3, 1.15, 6, "Second pump started, level back under the limit."),),
    ),
)
#: This sensor stopped reporting this many hours ago.
_SILENT = {"VB-02": 9}


def _clamp(v: float, hi: float) -> float:
    return min(v, hi)


def env_series(
    kind: str,
    now: datetime,
    step_h: int,
    lim_by_hour: dict[int, float],
    spikes: Iterable[Spike],
    rng: random.Random,
    stop_hours_ago: int = 0,
) -> list[tuple[datetime, float]]:
    """Readings of one boundary sensor over ``_DAYS`` days on a grid ending at ``now``.

    Values are fractions of the limit in force at that hour, with a working-day
    cycle, quieter weekends and a few spikes. Pure: same inputs, same rows.
    """
    spikes = list(spikes)
    rows: list[tuple[datetime, float]] = []
    t = now - timedelta(days=_DAYS)
    end = now - timedelta(hours=stop_hours_ago)
    while t <= end:
        lim = lim_by_hour[t.hour]
        working = 7 <= t.hour < 19 and t.weekday() < 5
        half = 7 <= t.hour < 15 and t.weekday() == 5
        wave = math.sin((t.hour - 6) / 12 * math.pi) if 6 <= t.hour <= 18 else 0.0
        if kind == "noise":
            v = lim * ((0.78 + 0.08 * wave) if working else (0.66 if half else 0.5)) + rng.uniform(-0.05, 0.05) * lim
            v = _clamp(v, lim * 0.93)
        elif kind == "dust_pm10":
            v = lim * ((0.40 + 0.12 * wave + rng.uniform(0, 0.2)) if working else 0.18 + rng.uniform(0, 0.05))
            v = _clamp(v, lim * 0.9)
        elif kind == "vibration":
            quiet = lim * (0.02 + rng.uniform(0, 0.01))
            v = lim * rng.uniform(0.05, 0.2) if working else quiet
            if working and rng.random() < 0.05:
                v = lim * rng.uniform(0.3, 0.5)
            v = _clamp(v, lim * 0.6)
        elif kind == "weather":
            ms = 4.0 + 2.5 * math.sin((t.hour - 9) / 24 * 2 * math.pi) + rng.uniform(-1.2, 1.8)
            v = _clamp(max(ms, 0.3) * lim / _WIND_LIMIT_MS, lim * 0.8)
        else:  # water_level: a sump that fills and is pumped down
            v = lim * (0.3 + 0.25 * ((t.hour // step_h) % 4) / 3 + rng.uniform(-0.02, 0.02))
        rows.append((t, v))
        t += timedelta(hours=step_h)
    by_t = dict(rows)
    for sp in spikes:
        start = (now - timedelta(days=sp.days_ago)).replace(hour=sp.hour, minute=0, second=0, microsecond=0)
        for j in range(max(sp.hours, step_h)):
            tt = start + timedelta(hours=j)
            if tt in by_t:
                by_t[tt] = lim_by_hour[tt.hour] * sp.peak * (1 - 0.04 * j)
    return [(t, round(by_t[t], 2)) for t, _ in rows]


def pour_series(pour: Pour, now: datetime, rng: random.Random) -> list[tuple[datetime, float]]:
    """Hourly core temperature of a pour: the heat of hydration on day one, then the daily swing."""
    cast_at = now - timedelta(hours=pour.cast_hours_ago)
    rows = []
    t = cast_at
    while t <= now:
        h = (t - cast_at).total_seconds() / 3600
        hydration = 6.0 * math.exp(-((h - 18) ** 2) / 200)
        rows.append(
            (
                t,
                round(
                    pour.mean_c + hydration + pour.swing_c * math.sin(h / 24 * 2 * math.pi) + rng.uniform(-0.3, 0.3), 2
                ),
            )
        )
        t += timedelta(hours=1)
    return rows


def reached_at(rows: list[tuple[datetime, float]], target_mpa: float) -> datetime | None:
    """First reading at which the demo mix curve gives ``target_mpa``."""
    for t, m in nurse_saul(rows, _DATUM_C):
        if strength_from_maturity(m, float(_MIX["curve_a"]), float(_MIX["curve_b"])) >= target_mpa:
            return t
    return None


async def _activities(session: AsyncSession, project_id: uuid.UUID, n: int) -> list[uuid.UUID]:
    try:
        from app.modules.schedule.models import Activity, Schedule

        rows = (
            await session.execute(
                select(Activity.id)
                .join(Schedule, Activity.schedule_id == Schedule.id)
                .where(Schedule.project_id == project_id)
                .order_by(Activity.id)
                .limit(n)
            )
        ).all()
        return [r[0] for r in rows]
    except Exception:
        return []


async def _purge_legacy(session: AsyncSession, project_id: uuid.UUID) -> None:
    ids = list((await session.execute(select(SensorDevice.id).where(SensorDevice.project_id == project_id))).scalars())
    if ids:
        for table in (sensor_reading, sensor_reading_hourly):
            await session.execute(delete(table).where(table.c.device_id.in_(ids)))
    await session.execute(delete(SensorAlert).where(SensorAlert.project_id == project_id))
    await session.execute(delete(FormworkStrip).where(FormworkStrip.project_id == project_id))
    await session.execute(delete(SensorDevice).where(SensorDevice.project_id == project_id))
    await session.execute(
        delete(ConcreteMix).where(ConcreteMix.project_id == project_id, ConcreteMix.code == _MIX["code"])
    )
    await session.flush()


async def _settle(alert: SensorAlert, service: SiteSensorsService, user: uuid.UUID, note: str, after_h: float) -> None:
    await service.acknowledge(alert.id, user, note)
    alert.acknowledged_at = alert.raised_at + timedelta(hours=after_h)


async def _seed_pours(
    session: AsyncSession,
    service: SiteSensorsService,
    project_id: uuid.UUID,
    user: uuid.UUID,
    now: datetime,
    rng: random.Random,
    counts: dict[str, int],
) -> None:
    mix = ConcreteMix(
        project_id=project_id,
        code=_MIX["code"],
        name=_MIX["name"],
        datum_temp_c=Decimal(str(int(_DATUM_C))),
        curve_a=Decimal(_MIX["curve_a"]),
        curve_b=Decimal(_MIX["curve_b"]),
        strip_strength_mpa=Decimal(_MIX["strip"]),
        notes="Curve from the mix calibration cubes at 1, 3, 7 and 28 days.",
    )
    session.add(mix)
    await session.flush()
    # Lab cubes cured at 20 degC: index = 20 degC x age, strengths around the curve.
    await service.set_calibration(
        mix.id,
        [
            CalibrationPointIn(maturity_index=480, strength_mpa=Decimal("6.4"), age_hours=24, note="1 day cube"),
            CalibrationPointIn(maturity_index=960, strength_mpa=Decimal("11.5"), age_hours=48, note="2 day cube"),
            CalibrationPointIn(maturity_index=1440, strength_mpa=Decimal("15.2"), age_hours=72, note="3 day cube"),
            CalibrationPointIn(maturity_index=3360, strength_mpa=Decimal("21.6"), age_hours=168, note="7 day cube"),
            CalibrationPointIn(maturity_index=13440, strength_mpa=Decimal("32.9"), age_hours=672, note="28 day cube"),
        ],
    )
    activities = await _activities(session, project_id, len(_POURS))
    for i, pour in enumerate(_POURS):
        cast_at = now - timedelta(hours=pour.cast_hours_ago)
        activity_id = activities[i % len(activities)] if activities else None
        device = await service.create_device(
            DeviceCreate(
                project_id=project_id,
                code=pour.code,
                name=pour.name,
                kind="concrete_maturity",
                mix_id=mix.id,
                pour_ref=pour.pour_ref,
                cast_at=cast_at,
                schedule_activity_id=activity_id,
                offline_after_minutes=180,
            )
        )
        strips = []
        for element, target, _ in pour.strips:
            planned = cast_at + timedelta(hours=72 if target == "15" else 7 * 24)
            strips.append(
                await service.create_strip(
                    StripCreate(
                        device_id=device.id,
                        element=element,
                        target_strength_mpa=Decimal(target),
                        planned_at=planned,
                        schedule_activity_id=activity_id,
                    )
                )
            )
        rows = pour_series(pour, now, rng)
        await service.ingest(device, rows)
        counts["devices"] += 1
        counts["readings"] += len(rows)
        for strip, (_, target, struck_after) in zip(strips, pour.strips, strict=True):
            at = reached_at(rows, float(target))
            if at is None or strip.status != "released":
                continue
            strip.released_at = at
            if struck_after is not None:
                await service.strike(strip.id, at + timedelta(hours=struck_after))
        alert = await service.repo.any_alert(device.id, "strength_reached")
        at15 = reached_at(rows, 15.0)
        if alert is not None and at15 is not None:
            alert.raised_at = at15
            if pour.code == "CM-01":
                await _settle(alert, service, user, "Side forms struck; props stay until 25 MPa.", 3.0)
    await session.flush()


async def _seed_environment(
    session: AsyncSession,
    service: SiteSensorsService,
    project_id: uuid.UUID,
    country: str,
    user: uuid.UUID,
    now: datetime,
    rng: random.Random,
    counts: dict[str, int],
) -> None:
    imperial = country in _IMPERIAL
    for code, name, kind, step_h, spikes in _ENV:
        factor = 1.0
        limit_value: Decimal | None = None
        unit = ""
        if kind == "weather":
            factor = _MS_TO_MPH if imperial else 1.0
            unit = "mph" if imperial else "m/s"
            limit_value = Decimal(str(round(_WIND_LIMIT_MS * factor, 1)))
        elif kind == "water_level":
            factor = _M_TO_FT if imperial else 1.0
            unit = "ft" if imperial else "m"
            limit_value = Decimal(str(round(_WATER_LIMIT_M * factor, 2)))
        device = await service.create_device(
            DeviceCreate(
                project_id=project_id,
                code=code,
                name=name,
                kind=kind,
                unit=unit,
                limit_value=limit_value,
                limit_note=_LIMIT_NOTES.get(kind, ""),
                offline_after_minutes=120 if step_h < 3 else 240,
            )
        )
        if limit_value is None and (await service.limit_of(device, now))[0] is None:
            device.limit_value = Decimal(_FALLBACK_LIMIT[kind])
            await session.flush()
        lim_by_hour = {}
        for h in range(24):
            lim, _ = await service.limit_of(device, now.replace(hour=h, minute=0))
            lim_by_hour[h] = float(lim or 0.0)
        rows = env_series(kind, now, step_h, lim_by_hour, spikes, rng, _SILENT.get(code, 0))
        # One chunk per breach so an acknowledged alert is closed before the next episode raises its own.
        window = ROLLING_MEAN_HOURS.get(kind)
        cut = 0
        for sp in spikes:
            start = (now - timedelta(days=sp.days_ago)).replace(hour=sp.hour, minute=0, second=0, microsecond=0)
            end_idx = max(
                (
                    i
                    for i, (t, v) in enumerate(rows)
                    if start <= t < start + timedelta(hours=2 * window if window else max(sp.hours, step_h))
                    and (rolling_mean(rows, t, window) if window else v) > lim_by_hour[t.hour]
                ),
                default=None,
            )
            if end_idx is None:
                continue
            chunk = rows[cut : end_idx + 1]
            if chunk:
                await service.ingest(device, chunk)
            cut = end_idx + 1
            if sp.note is not None:
                alert = await service.repo.open_alert(device.id, "exceedance")
                if alert is not None:
                    await _settle(alert, service, user, sp.note, 1.5 + rng.uniform(0, 3))
        rest = rows[cut:]
        if rest:
            await service.ingest(device, rest)
        counts["devices"] += 1
        counts["readings"] += len(rows)
        if code in _SILENT:
            await service.sweep_offline(project_id, now)
            offline = await service.repo.open_alert(device.id, "offline")
            if offline is not None and device.last_seen_at is not None:
                offline.raised_at = device.last_seen_at + timedelta(minutes=device.offline_after_minutes)


async def _seed_custom(
    service: SiteSensorsService,
    project_id: uuid.UUID,
    user: uuid.UUID,
    now: datetime,
    rng: random.Random,
    counts: dict[str, int],
) -> None:
    """A sensor the site defined itself: pump flow logged every 6 hours, plus readings typed in by hand."""
    code, name, unit, lower, upper, note = _CUSTOM
    device = await service.create_device(
        DeviceCreate(
            project_id=project_id,
            code=code,
            name=name,
            kind="custom",
            unit=unit,
            limit_value=upper,
            lower_limit=lower,
            limit_note=note,
            offline_after_minutes=360,
        )
    )
    lo, hi = float(lower), float(upper)
    rows = []
    t = now - timedelta(days=_DAYS)
    while t <= now:
        share = 0.45 + 0.15 * math.sin(t.hour / 24 * 2 * math.pi) + rng.uniform(-0.05, 0.05)
        rows.append((t, round(lo + (hi - lo) * share, 1)))
        t += timedelta(hours=6)
    await service.ingest(device, rows)
    manual = [
        ReadingIn(recorded_at=now - timedelta(hours=h), value=round(lo + (hi - lo) * share, 1), note=text)
        for h, share, text in _CUSTOM_MANUAL
    ]
    await service.add_user_readings(device, manual, "manual", user)
    counts["devices"] += 1
    counts["readings"] += len(rows) + len(manual)


async def seed_site_sensors_demo(
    session: AsyncSession, project_ids: Iterable[uuid.UUID], *, now: datetime | None = None
) -> dict[str, int]:
    """Seed each of the first ``_MAX_PROJECTS`` projects. The caller commits."""
    from app.modules.projects.models import Project

    counts = {"devices": 0, "readings": 0, "alerts": 0}
    now = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    service = SiteSensorsService(session)
    seen: set[uuid.UUID] = set()
    for project_id in list(project_ids)[:_MAX_PROJECTS]:
        if project_id in seen:
            continue
        seen.add(project_id)
        project = await session.get(Project, project_id)
        if project is None:
            continue
        codes = set(
            (await session.execute(select(SensorDevice.code).where(SensorDevice.project_id == project_id))).scalars()
        )
        if _MARKER in codes:
            if _CUSTOM[0] not in codes:
                # Seeded before custom sensors existed: add only the custom one.
                rng = random.Random(f"site-sensors-custom:{project_id}")
                user = project.owner_id or uuid.uuid5(uuid.NAMESPACE_URL, f"site-sensors:{project_id}")
                await _seed_custom(service, project_id, user, now, rng, counts)
            continue
        if codes & set(_LEGACY_CODES):
            await _purge_legacy(session, project_id)
        elif codes:
            continue  # the project holds sensors somebody added; leave it alone
        rng = random.Random(f"site-sensors:{project_id}")
        user = project.owner_id or uuid.uuid5(uuid.NAMESPACE_URL, f"site-sensors:{project_id}")
        before = counts["alerts"]
        await _seed_pours(session, service, project_id, user, now, rng, counts)
        await _seed_environment(
            session, service, project_id, (project.country_code or "").upper(), user, now, rng, counts
        )
        await _seed_custom(service, project_id, user, now, rng, counts)
        counts["alerts"] = before + len(await service.repo.alerts(project_id))
    return counts
