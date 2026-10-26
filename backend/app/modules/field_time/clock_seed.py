# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Demo data for the geofenced time clock​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

For up to three demo projects that have a crew: one site geofence (two
circles and one polygon across the estate) around the project's map anchor,
clock settings, recorded consent for the crew, and two weeks of clock-ins and
clock-outs at positions inside the fence. One clock outside the fence was
approved by a supervisor with a reason; the latest one outside is still
pending. The last three clock days are built into draft timesheets, so the
validation panel shows the pending clock blocking submission.

Drafts only: the approved demo timesheets come from the field time seed, and
a second approved set from the clock would book the same hours twice.
Idempotent per project: a project that already has a geofence is skipped.
"""

from __future__ import annotations

import logging
import math
import random
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.field_time import geofence_math as gm
from app.modules.field_time.models import (
    FieldClockConsent,
    FieldClockEvent,
    FieldClockSettings,
    FieldSiteGeofence,
)

logger = logging.getLogger(__name__)

DEMO_SOURCE = "field_clock_demo_seed"
_MAX_PROJECTS = 3
_MAX_WORKERS = 4
_DAYS = 10
# Used only when a demo project has no map anchor yet.
_FALLBACK_SITES = ((52.5163, 13.3777), (48.1374, 11.5755), (53.5511, 9.9937))


def _working_days(count: int, ending: date) -> list[date]:
    days: list[date] = []
    cursor = ending
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def _offset(lat: float, lng: float, north_m: float, east_m: float) -> tuple[float, float]:
    dlat = north_m / 111_195.0
    dlng = east_m / (111_195.0 * max(0.1, math.cos(math.radians(lat))))
    return round(lat + dlat, 7), round(lng + dlng, 7)


async def _anchor(session: AsyncSession, project_id: uuid.UUID, ordinal: int) -> tuple[float, float]:
    try:
        from app.modules.geo_hub.models import GeoAnchor

        row = (
            await session.execute(select(GeoAnchor.lat, GeoAnchor.lon).where(GeoAnchor.project_id == project_id))
        ).first()
        if row is not None and row[0] is not None and row[1] is not None:
            return float(row[0]), float(row[1])
    except Exception:
        logger.debug("Geo anchor lookup unavailable for project=%s", project_id)
    return _FALLBACK_SITES[ordinal % len(_FALLBACK_SITES)]


async def _cost_code(session: AsyncSession, project_id: uuid.UUID) -> str:
    try:
        from app.modules.field_time.seed import _project_cost_codes

        codes = await _project_cost_codes(session, project_id)
        if codes:
            return str(codes[0])
    except Exception:
        logger.debug("Cost code lookup unavailable for project=%s", project_id)
    return ""


async def _seed_project(
    session: AsyncSession, project_id: uuid.UUID, owner_id: uuid.UUID, ordinal: int, today: date
) -> dict[str, int]:
    from app.modules.field_time.clock_service import ClockService
    from app.modules.field_time.seed import _project_workers

    workers = [w for w, _name in await _project_workers(session, project_id)][:_MAX_WORKERS]
    if len(workers) < 2:
        return {}
    rng = random.Random(f"field-clock:{project_id}")
    lat, lng = await _anchor(session, project_id, ordinal)
    if ordinal == 1:
        corners = ((-120, -160), (-120, 170), (140, 170), (140, -160))
        fence = FieldSiteGeofence(
            project_id=project_id,
            name="Site boundary",
            shape=gm.SHAPE_POLYGON,
            polygon=[list(_offset(lat, lng, n, e)) for n, e in corners],
            tolerance_m=Decimal("15"),
        )
    else:
        fence = FieldSiteGeofence(
            project_id=project_id,
            name="Main gate" if ordinal == 0 else "Site compound",
            shape=gm.SHAPE_CIRCLE,
            center_lat=Decimal(str(lat)),
            center_lng=Decimal(str(lng)),
            radius_m=Decimal("180" if ordinal == 0 else "220"),
            tolerance_m=Decimal("20"),
        )
    fence.supervisor_user_ids = [str(owner_id)]
    fence.default_cost_code = await _cost_code(session, project_id)
    fence.created_by = owner_id
    fence.metadata_ = {"source": DEMO_SOURCE}
    session.add(fence)
    session.add(FieldClockSettings(project_id=project_id, enabled=True, retention_days=90, default_break_minutes=30))
    granted_at = datetime.combine(today - timedelta(days=30), time(7, 0), tzinfo=UTC)
    for worker in workers:
        session.add(
            FieldClockConsent(
                project_id=project_id,
                resource_id=worker,
                granted=True,
                granted_at=granted_at,
                text_version="1",
                recorded_by=owner_id,
            )
        )
    await session.flush()

    days = _working_days(_DAYS, today - timedelta(days=1))
    approved_day, pending_day = days[3], days[-1]
    events = 0
    for day in days:
        for index, worker in enumerate(workers):
            start = datetime.combine(day, time(6, 30), tzinfo=UTC) + timedelta(minutes=rng.randint(0, 40))
            end = datetime.combine(day, time(15, 0), tzinfo=UTC) + timedelta(minutes=rng.randint(0, 75))
            for kind, at in (("in", start), ("out", end)):
                outside = index == 0 and kind == "in" and day in (approved_day, pending_day)
                north, east = (650.0, 420.0) if outside else (rng.uniform(-60, 60), rng.uniform(-60, 60))
                p_lat, p_lng = _offset(lat, lng, north, east)
                hit = gm.evaluate_fence(p_lat, p_lng, _spec(fence))
                status = gm.approval_for(hit)
                ev = FieldClockEvent(
                    project_id=project_id,
                    resource_id=worker,
                    kind=kind,
                    occurred_at=at,
                    latitude=Decimal(str(p_lat)),
                    longitude=Decimal(str(p_lng)),
                    accuracy_m=Decimal(str(round(rng.uniform(4, 18), 1))),
                    geofence_id=fence.id,
                    inside=hit.inside,
                    distance_m=Decimal(str(hit.distance_m)),
                    approval_status=status,
                    recorded_by=owner_id,
                    client_op_id=f"demo-{project_id.hex[:8]}-{day.isoformat()}-{index}-{kind}",
                )
                if status == gm.APPROVAL_PENDING and day == approved_day:
                    ev.approval_status = gm.APPROVAL_APPROVED
                    ev.approval_reason = "Collected rebar from the supplier's yard on the way to site"
                    ev.approved_by = owner_id
                    ev.approved_at = at + timedelta(hours=3)
                session.add(ev)
                events += 1
    await session.flush()
    # Pair clock-outs with their clock-ins, as the live capture path does.
    rows = (
        (
            await session.execute(
                select(FieldClockEvent)
                .where(FieldClockEvent.project_id == project_id)
                .order_by(FieldClockEvent.resource_id, FieldClockEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )
    last_in: dict[uuid.UUID, FieldClockEvent] = {}
    for ev in rows:
        if ev.kind == "in":
            last_in[ev.resource_id] = ev
        elif ev.resource_id in last_in:
            ev.pair_event_id = last_in.pop(ev.resource_id).id
    await session.flush()

    service = ClockService(session)
    built = 0
    for day in days[-3:]:
        await service.build_timesheet(project_id, day, str(owner_id))
        built += 1
    return {"projects": 1, "geofences": 1, "clock_events": events, "clock_timesheets": built}


def _spec(fence: FieldSiteGeofence) -> gm.FenceSpec:
    from app.modules.field_time.clock_service import fence_spec

    return fence_spec(fence)


async def seed_field_clock_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
    *,
    today: date | None = None,
) -> dict[str, int]:
    """Seed geofences and two weeks of clock events into up to three demo projects.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Candidate demo projects, in priority order.
        today: Reference date (defaults to the current UTC date).

    Returns:
        Insert counts across every project seeded.
    """
    totals = {"projects": 0, "geofences": 0, "clock_events": 0, "clock_timesheets": 0}
    ids = list(project_ids)
    if not ids:
        return totals
    from app.modules.projects.models import Project

    owners = dict((await session.execute(select(Project.id, Project.owner_id).where(Project.id.in_(ids)))).all())
    fenced = set(
        (await session.execute(select(FieldSiteGeofence.project_id).where(FieldSiteGeofence.project_id.in_(ids))))
        .scalars()
        .all()
    )
    today = today or datetime.now(UTC).date()
    seeded = len(fenced)
    for project_id in ids:
        if seeded >= _MAX_PROJECTS:
            break
        if project_id in fenced or owners.get(project_id) is None:
            continue
        try:
            async with session.begin_nested():
                counts = await _seed_project(session, project_id, owners[project_id], seeded, today)
        except Exception:
            logger.warning("Field clock demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        if not counts:
            continue
        seeded += 1
        for key, value in counts.items():
            totals[key] += value
    return totals
