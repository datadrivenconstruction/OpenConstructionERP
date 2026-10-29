# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Telematics service​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: device tokens, ingest, utilisation, hire allocation, geofence, CO2.

Ingest goes through :meth:`EquipmentService.record_telemetry`, so a reading
that crosses an hour-based maintenance schedule still opens its work order.
Each touched day is rolled up into one ``oe_equipment_utilisation_day`` row,
which is what the utilisation view, the allocation and the rules read: the raw
readings are never scanned for a dashboard.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.site_monitoring import fuel_co2_kg_per_l
from app.modules.equipment.models import (
    Equipment,
    EquipmentRental,
    MaintenanceSchedule,
    TelematicsDevice,
    TelemetryReading,
    UtilisationDay,
)
from app.modules.equipment.schemas import TelemetryReadingCreate
from app.modules.equipment.telematics import TelematicsSample, daily_utilisation

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "oet_"
#: Idle share of engine hours above which a machine is flagged (rule and dashboard default).
DEFAULT_IDLE_THRESHOLD = Decimal("0.35")
_ZERO = Decimal("0")

EVENT_INGESTED = "equipment.telematics.ingested"
EVENT_GEOFENCE_EXIT = "equipment.geofence.exited"
EVENT_HIRE_ALLOCATED = "equipment.hire.allocated"


def hash_token(token: str) -> str:
    """SHA-256 hex of a device token (what is stored and looked up)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso_day(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _rental_covers(rental: EquipmentRental, day: date) -> bool:
    start = _iso_day(rental.start_date)
    end = _iso_day(rental.end_date)
    if start is None or day < start:
        return False
    return end is None or day <= end


class TelematicsService:
    """Telematics ingest and the views built on its daily rollup."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Devices ─────────────────────────────────────────────────────────

    async def create_device(self, equipment_id: uuid.UUID, label: str = "") -> tuple[TelematicsDevice, str]:
        """Register a device and return it with its plaintext token (shown once)."""
        if await self.session.get(Equipment, equipment_id) is None:
            raise LookupError("equipment_not_found")
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        device = TelematicsDevice(
            equipment_id=equipment_id,
            label=label,
            token_hash=hash_token(token),
            token_prefix=token[:10],
        )
        self.session.add(device)
        await self.session.flush()
        return device, token

    async def list_devices(
        self, equipment_id: uuid.UUID | None = None, offset: int = 0, limit: int = 50
    ) -> tuple[list[TelematicsDevice], int]:
        base = select(TelematicsDevice)
        if equipment_id is not None:
            base = base.where(TelematicsDevice.equipment_id == equipment_id)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        page = base.order_by(TelematicsDevice.created_at, TelematicsDevice.id).offset(offset).limit(limit)
        return list((await self.session.execute(page)).scalars()), total

    async def revoke_device(self, device_id: uuid.UUID) -> None:
        device = await self.session.get(TelematicsDevice, device_id)
        if device is None:
            raise LookupError("device_not_found")
        device.active = False
        await self.session.flush()

    async def authenticate(self, token: str | None) -> TelematicsDevice | None:
        """The active device holding ``token``, or None."""
        if not token or not token.startswith(TOKEN_PREFIX):
            return None
        row = (
            await self.session.execute(select(TelematicsDevice).where(TelematicsDevice.token_hash == hash_token(token)))
        ).scalar_one_or_none()
        return row if row is not None and row.active else None

    # ── Ingest ──────────────────────────────────────────────────────────

    async def _resolve(self, refs: set[str]) -> dict[str, Equipment]:
        if not refs:
            return {}
        rows = (
            await self.session.execute(
                select(Equipment).where(or_(Equipment.code.in_(refs), Equipment.serial.in_(refs)))
            )
        ).scalars()
        out: dict[str, Equipment] = {}
        for eq in rows:
            out[eq.code] = eq
            if eq.serial:
                out.setdefault(eq.serial, eq)
        return out

    async def ingest(
        self,
        samples: list[TelematicsSample],
        *,
        source: str,
        equipment_id: uuid.UUID | None = None,
        device: TelematicsDevice | None = None,
    ) -> dict[str, Any]:
        """Store samples, roll up the days they touch and report what matched.

        Args:
            samples: Parsed samples.
            source: ``rest`` / ``aemp`` / ``csv`` / ``manual``.
            equipment_id: When set, every sample belongs to this machine (device ingest).
            device: The authenticated device, stamped ``last_seen_at``.
        """
        from app.modules.equipment.service import EquipmentService

        eq_service = EquipmentService(self.session)
        by_ref = (
            {}
            if equipment_id
            else await self._resolve({s.equipment_ref for s in samples} | {s.serial for s in samples if s.serial})
        )
        touched: set[tuple[uuid.UUID, date]] = set()
        unmatched: list[str] = []
        accepted = 0
        for s in sorted(samples, key=lambda x: _aware(x.recorded_at)):
            target = equipment_id
            if target is None:
                eq = by_ref.get(s.equipment_ref) or (by_ref.get(s.serial) if s.serial else None)
                if eq is None:
                    if s.equipment_ref not in unmatched:
                        unmatched.append(s.equipment_ref)
                    continue
                target = eq.id
            await eq_service.record_telemetry(
                target,
                TelemetryReadingCreate(
                    recorded_at=_aware(s.recorded_at),
                    fuel_level=s.fuel_level_pct,
                    hour_meter=s.engine_hours,
                    odometer_km=s.odometer_km,
                    lat=s.lat,
                    lng=s.lng,
                    engine_status=s.engine_status,
                    idle_hours=s.idle_hours,
                    fuel_used_l=s.fuel_used_l,
                    fault_codes=s.fault_codes,
                    source=source,
                ),
            )
            accepted += 1
            touched.add((target, _aware(s.recorded_at).astimezone(UTC).date()))
        for eq_id, day in sorted(touched):
            await self.rollup_day(eq_id, day)
        if device is not None:
            device.last_seen_at = datetime.now(UTC)
        await self.session.flush()
        if accepted:
            event_bus.publish_detached(
                EVENT_INGESTED,
                {"source": source, "accepted": accepted, "days": len(touched)},
                source_module="equipment",
            )
        return {"accepted": accepted, "unmatched": unmatched, "days_rolled_up": len(touched)}

    # ── Daily rollup ────────────────────────────────────────────────────

    async def _rental_for(self, equipment_id: uuid.UUID, day: date) -> EquipmentRental | None:
        rows = (
            await self.session.execute(
                select(EquipmentRental).where(
                    EquipmentRental.equipment_id == equipment_id,
                    EquipmentRental.status.in_(("active", "returned")),
                )
            )
        ).scalars()
        cover = [r for r in rows if _rental_covers(r, day)]
        return max(cover, key=lambda r: r.start_date) if cover else None

    async def _fences(self, project_id: uuid.UUID) -> list[Any]:
        from app.modules.field_time.geofence_math import FenceSpec
        from app.modules.field_time.models import FieldSiteGeofence

        rows = (
            await self.session.execute(
                select(FieldSiteGeofence).where(
                    FieldSiteGeofence.project_id == project_id, FieldSiteGeofence.active.is_(True)
                )
            )
        ).scalars()
        specs = []
        for f in rows:
            specs.append(
                FenceSpec(
                    fence_id=str(f.id),
                    name=f.name,
                    shape=f.shape,
                    center_lat=float(f.center_lat) if f.center_lat is not None else None,
                    center_lng=float(f.center_lng) if f.center_lng is not None else None,
                    radius_m=float(f.radius_m) if f.radius_m is not None else None,
                    polygon=tuple((float(p[0]), float(p[1])) for p in (f.polygon or [])),
                    tolerance_m=float(f.tolerance_m or 0),
                )
            )
        return specs

    async def outside_by_m(self, project_id: uuid.UUID, lat: float | None, lng: float | None) -> Decimal | None:
        """Metres outside the project's fences (0 inside), None without a fence or a position."""
        from app.modules.field_time.geofence_math import evaluate_fences

        if lat is None or lng is None:
            return None
        hit = evaluate_fences(lat, lng, await self._fences(project_id))
        if hit is None:
            return None
        return Decimal("0") if hit.inside else Decimal(str(hit.distance_m))

    async def rollup_day(self, equipment_id: uuid.UUID, day: date) -> UtilisationDay | None:
        """Recompute one machine-day. An allocated day keeps its posted cost and is left alone."""
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        readings = (
            (
                await self.session.execute(
                    select(TelemetryReading)
                    .where(
                        TelemetryReading.equipment_id == equipment_id,
                        TelemetryReading.recorded_at >= start - timedelta(days=3),
                        TelemetryReading.recorded_at < start + timedelta(days=1),
                    )
                    .order_by(TelemetryReading.recorded_at)
                )
            )
            .scalars()
            .all()
        )
        rows = [
            {
                "recorded_at": _aware(r.recorded_at),
                "engine_hours": r.hour_meter,
                "idle_hours": r.idle_hours,
                "fuel_used_l": r.fuel_used_l,
            }
            for r in readings
        ]
        use = daily_utilisation(rows, day)
        if use is None:
            return None
        row = (
            await self.session.execute(
                select(UtilisationDay).where(UtilisationDay.equipment_id == equipment_id, UtilisationDay.day == day)
            )
        ).scalar_one_or_none()
        if row is not None and row.allocated_at is not None:
            return row
        if row is None:
            row = UtilisationDay(equipment_id=equipment_id, day=day)
            self.session.add(row)
        rental = await self._rental_for(equipment_id, day)
        row.project_id = rental.project_id if rental else None
        row.worked_hours = use.worked_hours
        row.idle_hours = use.idle_hours
        row.off_hours = use.off_hours
        row.fuel_l = use.fuel_l
        row.co2_kg = (
            (use.fuel_l * fuel_co2_kg_per_l("diesel")).quantize(Decimal("0.01")) if use.fuel_l is not None else None
        )
        row.engine_hours_end = use.engine_hours_end
        located = [r for r in readings if r.lat is not None and r.lng is not None and _aware(r.recorded_at) >= start]
        previous = row.outside_geofence_m
        row.outside_geofence_m = None
        if rental is not None and located:
            row.outside_geofence_m = await self.outside_by_m(rental.project_id, located[-1].lat, located[-1].lng)
        await self.session.flush()
        if row.outside_geofence_m and row.outside_geofence_m > 0 and not previous:
            event_bus.publish_detached(
                EVENT_GEOFENCE_EXIT,
                {
                    "equipment_id": str(equipment_id),
                    "project_id": str(row.project_id),
                    "day": day.isoformat(),
                    "outside_m": str(row.outside_geofence_m),
                },
                source_module="equipment",
            )
            await self._notify_owner(row.project_id, equipment_id, row.outside_geofence_m)
        return row

    async def _notify_owner(self, project_id: uuid.UUID | None, equipment_id: uuid.UUID, outside_m: Decimal) -> None:
        if project_id is None:
            return
        try:
            from app.modules.notifications.service import NotificationService
            from app.modules.projects.models import Project

            project = await self.session.get(Project, project_id)
            if project is None or project.owner_id is None:
                return
            eq = await self.session.get(Equipment, equipment_id)
            await NotificationService(self.session).create(
                user_id=project.owner_id,
                notification_type="warning",
                title_key="notifications.equipment_geofence_exit_title",
                body_key="notifications.equipment_geofence_exit_body",
                body_context={"equipment": eq.code if eq else "", "distance_m": str(outside_m)},
                entity_type="equipment",
                entity_id=str(equipment_id),
                action_url="/equipment",
            )
        except Exception:
            logger.debug("geofence notification skipped", exc_info=True)

    # ── Utilisation ─────────────────────────────────────────────────────

    async def _days(
        self, date_from: date, date_to: date, project_id: uuid.UUID | None, equipment_id: uuid.UUID | None = None
    ) -> list[UtilisationDay]:
        stmt = select(UtilisationDay).where(and_(UtilisationDay.day >= date_from, UtilisationDay.day <= date_to))
        if project_id is not None:
            stmt = stmt.where(UtilisationDay.project_id == project_id)
        if equipment_id is not None:
            stmt = stmt.where(UtilisationDay.equipment_id == equipment_id)
        return list((await self.session.execute(stmt.order_by(UtilisationDay.day))).scalars())

    async def utilisation(self, date_from: date, date_to: date, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Worked, idle and off hours per machine and in total over a window."""
        days = await self._days(date_from, date_to, project_id)
        machines: dict[uuid.UUID, dict[str, Any]] = {}
        for d in days:
            m = machines.setdefault(
                d.equipment_id,
                {
                    "equipment_id": str(d.equipment_id),
                    "worked_hours": _ZERO,
                    "idle_hours": _ZERO,
                    "off_hours": _ZERO,
                    "fuel_l": _ZERO,
                    "co2_kg": _ZERO,
                    "hire_cost": _ZERO,
                    "days": 0,
                    "project_ids": set(),
                    "currencies": set(),
                },
            )
            m["worked_hours"] += d.worked_hours
            m["idle_hours"] += d.idle_hours
            m["off_hours"] += d.off_hours
            m["fuel_l"] += d.fuel_l or _ZERO
            m["co2_kg"] += d.co2_kg or _ZERO
            m["hire_cost"] += d.hire_cost or _ZERO
            m["days"] += 1
            if d.hire_cost and d.currency:
                m["currencies"].add(d.currency)
            if d.project_id:
                m["project_ids"].add(str(d.project_id))
        eqs = {}
        if machines:
            eqs = {
                e.id: e
                for e in (await self.session.execute(select(Equipment).where(Equipment.id.in_(machines)))).scalars()
            }
        rows = []
        totals = dict.fromkeys(("worked_hours", "idle_hours", "off_hours", "fuel_l", "co2_kg", "hire_cost"), _ZERO)
        all_currencies: set[str] = set()
        for eq_id, m in machines.items():
            # One currency names the hire cost; mixed currencies leave it blank rather than add them up silently.
            currencies = m.pop("currencies")
            all_currencies |= currencies
            m["currency"] = next(iter(currencies)) if len(currencies) == 1 else ""
            eq = eqs.get(eq_id)
            engine = m["worked_hours"] + m["idle_hours"]
            m["code"] = eq.code if eq else ""
            m["name"] = eq.name if eq else ""
            m["project_ids"] = sorted(m["project_ids"])
            m["utilisation_pct"] = _pct(m["worked_hours"], engine + m["off_hours"])
            m["idle_pct"] = _pct(m["idle_hours"], engine)
            for k in totals:
                totals[k] += m[k]
            rows.append({k: (str(v) if isinstance(v, Decimal) else v) for k, v in m.items()})
        engine_total = totals["worked_hours"] + totals["idle_hours"]
        summary = {k: str(v) for k, v in totals.items()}
        summary["utilisation_pct"] = _pct(totals["worked_hours"], engine_total + totals["off_hours"])
        summary["idle_pct"] = _pct(totals["idle_hours"], engine_total)
        summary["machines"] = len(rows)
        summary["currency"] = next(iter(all_currencies)) if len(all_currencies) == 1 else ""
        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "machines": sorted(rows, key=lambda r: r["code"]),
            "totals": summary,
        }

    # ── Hire allocation ─────────────────────────────────────────────────

    async def allocate(self, date_from: date, date_to: date, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Book each unallocated machine-day to its project and cost code.

        The charge is engine hours at the rental's hourly rate, or the day rate
        when the rental has no hourly rate. It is posted once per machine-day to
        the project's equipment budget line (idempotent on ``telematics_day``),
        and the rental is switched to telematics billing so its return does not
        bill the same days again.
        """
        from app.modules.equipment.service import EquipmentActualsService

        actuals = EquipmentActualsService(self.session)
        days = [d for d in await self._days(date_from, date_to, project_id) if d.allocated_at is None]
        posted = 0
        amount_total = _ZERO
        skipped_no_project = 0
        for d in days:
            rental = await self._rental_for(d.equipment_id, d.day)
            if rental is None:
                skipped_no_project += 1
                continue
            eq = await self.session.get(Equipment, d.equipment_id)
            engine = d.worked_hours + d.idle_hours
            rate_h = Decimal(str(rental.internal_rate_per_hour or 0))
            rate_d = Decimal(str(rental.internal_rate_per_day or 0))
            amount = (engine * rate_h) if rate_h > 0 else rate_d
            amount = amount.quantize(Decimal("0.01"))
            md = dict(rental.metadata_ or {})
            cost_code = (eq.cost_code if eq else "") or str(md.get("cost_code") or "")
            d.project_id = rental.project_id
            d.cost_code = cost_code
            d.hire_cost = amount
            d.currency = rental.currency or (eq.currency if eq else "")
            d.allocated_at = datetime.now(UTC)
            if md.get("billing_mode") != "telematics":
                md["billing_mode"] = "telematics"
                rental.metadata_ = md
            if amount > 0:
                await actuals.post_actual_to_budget_line(
                    project_id=rental.project_id,
                    cost_category="equipment:telematics",
                    amount_native=amount,
                    currency=d.currency,
                    source_kind="telematics_day",
                    source_ref=f"{d.equipment_id}:{d.day.isoformat()}",
                    logged_at=d.day.isoformat(),
                )
                amount_total += amount
            posted += 1
        await self.session.flush()
        if posted:
            event_bus.publish_detached(
                EVENT_HIRE_ALLOCATED,
                {
                    "project_id": str(project_id) if project_id else None,
                    "days": posted,
                    "amount": str(amount_total),
                },
                source_module="equipment",
            )
        return {"allocated_days": posted, "amount": str(amount_total), "skipped_no_project": skipped_no_project}

    # ── Geofence and rules ──────────────────────────────────────────────

    async def _on_site_project(self, eq: Equipment, fences_by_project: dict[uuid.UUID, list[Any]]) -> uuid.UUID | None:
        from app.modules.field_time.geofence_math import evaluate_fences

        if eq.location_lat is None or eq.location_lng is None:
            return None
        for pid, specs in fences_by_project.items():
            hit = evaluate_fences(eq.location_lat, eq.location_lng, specs)
            if hit is not None and hit.inside:
                return pid
        return None

    async def validation_payload(
        self, project_id: uuid.UUID | None = None, idle_threshold: Decimal = DEFAULT_IDLE_THRESHOLD
    ) -> dict[str, Any]:
        """Facts the equipment telematics rules read, one row per machine in scope."""
        from app.modules.field_time.models import FieldSiteGeofence

        today = datetime.now(UTC).date()
        fence_pids = set(
            (
                await self.session.execute(
                    select(FieldSiteGeofence.project_id).where(FieldSiteGeofence.active.is_(True)).distinct()
                )
            ).scalars()
        )
        if project_id is not None:
            fence_pids &= {project_id}
        fences = {pid: await self._fences(pid) for pid in fence_pids}
        rentals = [
            r
            for r in (
                await self.session.execute(select(EquipmentRental).where(EquipmentRental.status == "active"))
            ).scalars()
            if _rental_covers(r, today)
        ]
        allocated = {r.equipment_id: r.project_id for r in rentals}
        equipment = list(
            (await self.session.execute(select(Equipment).where(Equipment.status != "disposed"))).scalars()
        )
        schedules = list(
            (
                await self.session.execute(select(MaintenanceSchedule).where(MaintenanceSchedule.active.is_(True)))
            ).scalars()
        )
        week = await self._days(today - timedelta(days=7), today, None)
        machines = []
        for eq in equipment:
            on_site = await self._on_site_project(eq, fences)
            alloc = allocated.get(eq.id)
            if project_id is not None and project_id not in {on_site, alloc}:
                continue
            overdue = []
            for s in schedules:
                if s.equipment_id != eq.id:
                    continue
                if s.trigger_type == "hours" and s.next_due_meter is not None and eq.hour_meter >= s.next_due_meter:
                    overdue.append({"schedule_id": str(s.id), "due": str(s.next_due_meter), "now": str(eq.hour_meter)})
                elif s.trigger_type == "date" and (due := _iso_day(s.next_due_date)) is not None and due < today:
                    overdue.append({"schedule_id": str(s.id), "due": due.isoformat(), "now": today.isoformat()})
            outside = None
            if alloc is not None and alloc in fences:
                outside = await self.outside_by_m(alloc, eq.location_lat, eq.location_lng)
            mine = [d for d in week if d.equipment_id == eq.id]
            engine = sum((d.worked_hours + d.idle_hours for d in mine), _ZERO)
            idle = sum((d.idle_hours for d in mine), _ZERO)
            machines.append(
                {
                    "equipment_id": str(eq.id),
                    "code": eq.code,
                    "on_site_project_id": str(on_site) if on_site else None,
                    "allocated_project_id": str(alloc) if alloc else None,
                    "maintenance_overdue": overdue,
                    "outside_geofence_m": str(outside) if outside is not None else None,
                    "engine_hours_7d": str(engine),
                    "idle_ratio_7d": str((idle / engine).quantize(Decimal("0.001"))) if engine > 0 else None,
                }
            )
        return {"today": today.isoformat(), "idle_threshold": str(idle_threshold), "machines": machines}


def _pct(part: Decimal, whole: Decimal) -> str:
    if whole <= 0:
        return "0.0"
    return str((part / whole * 100).quantize(Decimal("0.1")))
