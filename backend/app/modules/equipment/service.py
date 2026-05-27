"""‌⁠‍Equipment service — business logic for fleet, maintenance, rentals, and damage.

Key features:
    * record_telemetry — append reading + bump Equipment counters if newer.
    * compute_next_due — pure scheduler helper for hours/km/date triggers.
    * generate_due_work_orders — auto-create WO stubs for schedules near threshold.
    * check_inspection_compliance / is_blocked_from_assignment — assignment gate.
    * assign_to_project — creates a rental; raises if blocked. Emits event.
    * compute_rental_billing — pure rate × period helper (hours preferred over days).
    * depreciation_value_at — linear/straight-line depreciation; extension point.
    * record_damage — DamageReport + auto MaintenanceWorkOrder.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.equipment.models import (
    DamageReport,
    Equipment,
    EquipmentRental,
    EquipmentType,
    FuelLog,
    Inspection,
    MaintenanceSchedule,
    MaintenanceWorkOrder,
    PartsLog,
    TelemetryReading,
)
from app.modules.equipment.repository import (
    DamageReportRepository,
    EquipmentRepository,
    EquipmentTypeRepository,
    FuelLogRepository,
    InspectionRepository,
    MaintenanceScheduleRepository,
    PartsLogRepository,
    RentalRepository,
    TelemetryRepository,
    WorkOrderRepository,
    fleet_utilization_avg,
    utilization_for_equipment,
)
from app.modules.equipment.schemas import (
    DamageReportCreate,
    EquipmentCreate,
    EquipmentDashboardResponse,
    EquipmentRentalCreate,
    EquipmentTypeCreate,
    EquipmentUpdate,
    FleetDashboardResponse,
    FuelLogCreate,
    InspectionCreate,
    MaintenanceScheduleCreate,
    MaintenanceWorkOrderCreate,
    PartsLogCreate,
    TelemetryReadingCreate,
)

logger = logging.getLogger(__name__)


# ── Pure helpers (no I/O) ─────────────────────────────────────────────────


def compute_next_due(
    schedule: MaintenanceSchedule,
    *,
    current_hour_meter: Decimal | None = None,
    current_km: Decimal | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """‌⁠‍Compute the next due trigger for a schedule.

    Returns a dict with `next_due_meter` (Decimal | None) and `next_due_date`
    (str | None). The shape mirrors :class:`MaintenanceSchedule` fields.

    Args:
        schedule: The schedule to project forward.
        current_hour_meter: Reference hour-meter (used for ``trigger_type='hours'``).
        current_km: Reference odometer (used for ``trigger_type='km'``).
        today: ISO date string (used for ``trigger_type='date'``).
    """
    threshold = Decimal(str(schedule.trigger_threshold or 0))

    if schedule.trigger_type == "hours":
        base = schedule.last_completed_meter
        if base is None:
            base = current_hour_meter if current_hour_meter is not None else Decimal("0")
        next_meter = Decimal(str(base)) + threshold
        return {"next_due_meter": next_meter, "next_due_date": None}

    if schedule.trigger_type == "km":
        base = schedule.last_completed_meter
        if base is None:
            base = current_km if current_km is not None else Decimal("0")
        next_meter = Decimal(str(base)) + threshold
        return {"next_due_meter": next_meter, "next_due_date": None}

    if schedule.trigger_type == "date":
        base_str = schedule.last_completed_at or today or date.today().isoformat()
        try:
            base_date = date.fromisoformat(base_str)
        except (ValueError, TypeError):
            base_date = date.today()
        days = int(threshold) if threshold else 0
        next_date = (base_date + timedelta(days=days)).isoformat()
        return {"next_due_meter": None, "next_due_date": next_date}

    return {"next_due_meter": None, "next_due_date": None}


def compute_rental_billing(
    rental: EquipmentRental,
    period_start: str,
    period_end: str,
    hours_logged: Decimal | float | int | None = None,
) -> Decimal:
    """‌⁠‍Compute billing for a rental over a period.

    Hours billing takes precedence if ``hours_logged`` is provided and the
    rental has a non-zero hourly rate; otherwise day billing applies.
    """
    if hours_logged is not None and Decimal(str(rental.internal_rate_per_hour or 0)) > 0:
        return Decimal(str(hours_logged)) * Decimal(str(rental.internal_rate_per_hour))

    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except (ValueError, TypeError):
        return Decimal("0")
    if end < start:
        return Decimal("0")

    days = Decimal((end - start).days + 1)
    return days * Decimal(str(rental.internal_rate_per_day or 0))


def depreciation_value_at(
    equipment: Equipment,
    as_of_date: str | None = None,
    *,
    declining_balance_rate: Decimal | None = None,
) -> Decimal:
    """Compute net book value of an equipment unit on ``as_of_date``.

    Methods supported (controlled by ``equipment.depreciation_method``):

    * ``linear`` / ``straight_line`` (default): NBV decreases linearly from
      ``purchase_value`` to ``residual_value`` across ``useful_life_years``.
    * ``declining_balance``: double-declining-balance by default
      (rate = 2 / useful_life). The rate can be overridden by passing
      ``declining_balance_rate`` (e.g. Decimal("0.15") for 15%/yr). Switches
      to straight-line for the final year so the unit hits ``residual_value``
      exactly at the end of its life — this is the GAAP / IFRS practice for
      DB methods.

    Returns ``Decimal("0")`` if any of ``purchase_value``,
    ``useful_life_years``, ``purchase_date`` is missing — caller should
    treat this as "unknown", not "zero NBV".
    """
    method = (equipment.depreciation_method or "linear").lower()

    purchase_value = equipment.purchase_value
    useful_life = equipment.useful_life_years
    purchase_date_str = equipment.purchase_date
    residual = Decimal(str(equipment.residual_value or 0))

    if purchase_value is None or useful_life is None or not purchase_date_str:
        return Decimal("0")

    try:
        purchased = date.fromisoformat(purchase_date_str)
    except (ValueError, TypeError):
        return Decimal("0")

    today = date.fromisoformat(as_of_date) if as_of_date else date.today()
    if today <= purchased:
        return Decimal(str(purchase_value))

    elapsed_days = (today - purchased).days
    total_days = useful_life * 365
    pv = Decimal(str(purchase_value))

    if elapsed_days >= total_days:
        return residual

    if method in ("linear", "straight_line"):
        depreciable = pv - residual
        per_day = depreciable / Decimal(total_days)
        nbv = pv - (per_day * Decimal(elapsed_days))
        if nbv < residual:
            nbv = residual
        return nbv.quantize(Decimal("0.0001"))

    if method in ("declining_balance", "double_declining"):
        # Double-declining-balance with switch to straight-line in the
        # final 12 months so the unit lands on residual_value.
        rate = declining_balance_rate if declining_balance_rate is not None else Decimal("2") / Decimal(useful_life)
        if rate <= 0 or rate > 1:
            raise ValueError(f"declining_balance_rate must be in (0, 1], got {rate}")
        # Number of full years elapsed plus the day fraction of the
        # in-progress year.
        elapsed_years_int = elapsed_days // 365
        remainder_days = elapsed_days % 365

        nbv = pv
        for _ in range(int(elapsed_years_int)):
            depreciation_this_year = nbv * rate
            new_nbv = nbv - depreciation_this_year
            if new_nbv < residual:
                new_nbv = residual
                break
            nbv = new_nbv

        # Final-year switch: if we're in the last year of life, linearly
        # bridge to ``residual`` over the remaining 365 days.
        if elapsed_years_int >= useful_life - 1:
            remaining_to_residual = nbv - residual
            per_day = remaining_to_residual / Decimal("365")
            nbv = nbv - (per_day * Decimal(remainder_days))
        else:
            # Apply pro-rata of the current year's depreciation.
            year_depreciation = nbv * rate
            per_day = year_depreciation / Decimal("365")
            nbv = nbv - (per_day * Decimal(remainder_days))

        if nbv < residual:
            nbv = residual
        return nbv.quantize(Decimal("0.0001"))

    raise NotImplementedError(
        f"Depreciation method '{method}' not implemented; "
        "supported: linear, straight_line, declining_balance, double_declining"
    )


# ── Service ──────────────────────────────────────────────────────────────


class EquipmentService:
    """Business logic for equipment, maintenance, rentals, inspections, fuel, parts, damage."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.equipment_repo = EquipmentRepository(session)
        self.type_repo = EquipmentTypeRepository(session)
        self.telemetry_repo = TelemetryRepository(session)
        self.schedule_repo = MaintenanceScheduleRepository(session)
        self.workorder_repo = WorkOrderRepository(session)
        self.inspection_repo = InspectionRepository(session)
        self.rental_repo = RentalRepository(session)
        self.fuel_repo = FuelLogRepository(session)
        self.parts_repo = PartsLogRepository(session)
        self.damage_repo = DamageReportRepository(session)

    # ── EquipmentType ────────────────────────────────────────────────────

    async def create_type(self, data: EquipmentTypeCreate) -> EquipmentType:
        existing = await self.type_repo.get_by_code(data.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Equipment type with code '{data.code}' already exists",
            )
        entity = EquipmentType(**data.model_dump())
        return await self.type_repo.create(entity)

    async def list_types(self) -> list[EquipmentType]:
        return await self.type_repo.list_all()

    async def delete_type(self, type_id: uuid.UUID) -> None:
        """Delete an equipment type. Blocks if any Equipment still references it."""
        from sqlalchemy import func as _sa_func
        from sqlalchemy import select as _sa_select

        t = await self.type_repo.get_by_id(type_id)
        if t is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Equipment type not found",
            )
        # Block delete when any Equipment still points at this type's code —
        # otherwise we'd orphan the FK reference (it's a string code, not a
        # DB-level FK).
        ref_count = await self.session.scalar(
            _sa_select(_sa_func.count()).select_from(Equipment).where(Equipment.type_code == t.code)
        )
        if ref_count and ref_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Cannot delete type '{t.code}': {ref_count} equipment unit(s) still reference it"),
            )
        await self.type_repo.delete(type_id)

    # ── Equipment ────────────────────────────────────────────────────────

    async def create_equipment(self, data: EquipmentCreate) -> Equipment:
        existing = await self.equipment_repo.get_by_code(data.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Equipment with code '{data.code}' already exists",
            )
        entity = Equipment(**data.model_dump())
        await self.equipment_repo.create(entity)
        logger.info("Equipment created: %s (%s)", entity.code, entity.name)
        return entity

    async def get_equipment(self, equipment_id: uuid.UUID) -> Equipment:
        equipment = await self.equipment_repo.get_by_id(equipment_id)
        if equipment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Equipment not found",
            )
        return equipment

    async def update_equipment(
        self,
        equipment_id: uuid.UUID,
        data: EquipmentUpdate,
    ) -> Equipment:
        equipment = await self.get_equipment(equipment_id)
        fields = data.model_dump(exclude_unset=True)
        if not fields:
            return equipment
        await self.equipment_repo.update_fields(equipment_id, **fields)
        await self.session.refresh(equipment)
        return equipment

    async def delete_equipment(self, equipment_id: uuid.UUID) -> None:
        await self.get_equipment(equipment_id)
        await self.equipment_repo.delete(equipment_id)

    # ── Telemetry ────────────────────────────────────────────────────────

    async def record_telemetry(
        self,
        equipment_id: uuid.UUID,
        data: TelemetryReadingCreate,
    ) -> TelemetryReading:
        """Append telemetry reading, bump Equipment counters, fire WO triggers.

        Three side effects when the reading is newer than the last known:
            1. Equipment.hour_meter / odometer_km / lat,lng updated.
            2. ``equipment.telemetry.recorded`` event emitted.
            3. If the new hour-meter or odometer crosses any active maintenance
               schedule's ``next_due_meter`` threshold (within the standard
               50-hour lookahead), a maintenance work order is auto-created
               via :meth:`generate_due_work_orders` — so the operator
               recording field hours never has to chase the maintenance team.
        """
        equipment = await self.get_equipment(equipment_id)

        reading = TelemetryReading(
            equipment_id=equipment_id,
            recorded_at=data.recorded_at,
            fuel_level=data.fuel_level,
            hour_meter=data.hour_meter,
            odometer_km=data.odometer_km,
            lat=data.lat,
            lng=data.lng,
            engine_status=data.engine_status,
            raw_payload=data.raw_payload,
        )
        await self.telemetry_repo.create(reading)

        # Only update Equipment state if this reading is strictly newer than
        # the last known telemetry timestamp.
        last_at = equipment.last_telemetry_at
        is_newer = last_at is None or _ensure_aware(data.recorded_at) > _ensure_aware(last_at)
        if is_newer:
            update_fields: dict[str, Any] = {"last_telemetry_at": data.recorded_at}
            if data.hour_meter is not None:
                update_fields["hour_meter"] = data.hour_meter
            if data.odometer_km is not None:
                update_fields["odometer_km"] = data.odometer_km
            if data.lat is not None:
                update_fields["location_lat"] = data.lat
            if data.lng is not None:
                update_fields["location_lng"] = data.lng
            await self.equipment_repo.update_fields(equipment_id, **update_fields)

            event_bus.publish_detached(
                "equipment.telemetry.recorded",
                {
                    "equipment_id": str(equipment_id),
                    "recorded_at": (
                        data.recorded_at.isoformat()
                        if hasattr(data.recorded_at, "isoformat")
                        else str(data.recorded_at)
                    ),
                    "hour_meter": (str(data.hour_meter) if data.hour_meter is not None else None),
                    "odometer_km": (str(data.odometer_km) if data.odometer_km is not None else None),
                    "engine_status": data.engine_status,
                },
                source_module="equipment",
            )

            # Auto-fire maintenance WO if the new meter crosses a threshold.
            # This is the safety net that PRD §5 "PPM 50 hours ahead" relies
            # on: an operator updating hours via telematics should not have
            # to also remember to ask the maintenance team to schedule.
            try:
                await self.generate_due_work_orders(
                    equipment_id=equipment_id,
                    lookahead_hours=50.0,
                )
            except Exception:
                logger.debug(
                    "telemetry post-trigger WO generation failed for %s",
                    equipment_id,
                    exc_info=True,
                )

        return reading

    async def get_latest_telemetry(self, equipment_id: uuid.UUID) -> TelemetryReading | None:
        return await self.telemetry_repo.latest_telemetry(equipment_id)

    async def list_telemetry(
        self,
        equipment_id: uuid.UUID,
        *,
        since: Any | None = None,
        limit: int = 500,
    ) -> list[TelemetryReading]:
        return await self.telemetry_repo.list_since(equipment_id, since=since, limit=limit)

    # ── Maintenance ──────────────────────────────────────────────────────

    async def create_schedule(
        self,
        data: MaintenanceScheduleCreate,
    ) -> MaintenanceSchedule:
        await self.get_equipment(data.equipment_id)  # validates existence
        entity = MaintenanceSchedule(**data.model_dump())
        # If next_due not given, auto-compute
        if entity.next_due_date is None and entity.next_due_meter is None:
            equipment = await self.equipment_repo.get_by_id(data.equipment_id)
            computed = compute_next_due(
                entity,
                current_hour_meter=equipment.hour_meter if equipment else Decimal("0"),
                current_km=equipment.odometer_km if equipment else Decimal("0"),
                today=date.today().isoformat(),
            )
            entity.next_due_date = computed["next_due_date"]
            entity.next_due_meter = computed["next_due_meter"]
        return await self.schedule_repo.create(entity)

    async def generate_due_work_orders(
        self,
        equipment_id: uuid.UUID | None = None,
        lookahead_hours: float = 50.0,
    ) -> list[MaintenanceWorkOrder]:
        """Generate WO stubs for schedules within ``lookahead_hours`` of due.

        For 'hours' / 'km' triggers, compares against Equipment.hour_meter /
        Equipment.odometer_km. For 'date' triggers, compares against today.
        """
        active_schedules = await self.schedule_repo.list_active()
        created: list[MaintenanceWorkOrder] = []
        today = date.today()
        today_iso = today.isoformat()

        for schedule in active_schedules:
            if equipment_id is not None and schedule.equipment_id != equipment_id:
                continue

            equipment = await self.equipment_repo.get_by_id(schedule.equipment_id)
            if equipment is None:
                continue

            due_now = False
            scheduled_for = today_iso

            if schedule.trigger_type == "hours" and schedule.next_due_meter is not None:
                remaining = Decimal(str(schedule.next_due_meter)) - Decimal(str(equipment.hour_meter or 0))
                if remaining <= Decimal(str(lookahead_hours)):
                    due_now = True
            elif schedule.trigger_type == "km" and schedule.next_due_meter is not None:
                remaining = Decimal(str(schedule.next_due_meter)) - Decimal(str(equipment.odometer_km or 0))
                # Use the same lookahead magnitude for km (treat 50 hours ≈ 50 km).
                if remaining <= Decimal(str(lookahead_hours)):
                    due_now = True
            elif schedule.trigger_type == "date" and schedule.next_due_date is not None:
                try:
                    due_date = date.fromisoformat(schedule.next_due_date)
                except (ValueError, TypeError):
                    continue
                # Treat lookahead_hours/24 days as the date lookahead window.
                lookahead_days = max(1, int(lookahead_hours / 24))
                if (due_date - today).days <= lookahead_days:
                    due_now = True
                    scheduled_for = schedule.next_due_date

            if not due_now:
                continue

            # Don't duplicate if there's already an open WO for this schedule.
            existing_q = await self.workorder_repo.list_(
                equipment_id=schedule.equipment_id,
                status="scheduled",
            )
            already_open = any(wo.schedule_id == schedule.id for wo in existing_q[0])
            if already_open:
                continue

            wo = MaintenanceWorkOrder(
                equipment_id=schedule.equipment_id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for,
                status="scheduled",
                work_summary=schedule.description or "",
            )
            await self.workorder_repo.create(wo)
            created.append(wo)

            event_bus.publish_detached(
                "equipment.maintenance_due",
                {
                    "equipment_id": str(schedule.equipment_id),
                    "schedule_id": str(schedule.id),
                    "work_order_id": str(wo.id),
                    "trigger_type": schedule.trigger_type,
                    "scheduled_for": scheduled_for,
                },
                source_module="equipment",
            )

        return created

    async def create_work_order(
        self,
        data: MaintenanceWorkOrderCreate,
    ) -> MaintenanceWorkOrder:
        await self.get_equipment(data.equipment_id)
        entity = MaintenanceWorkOrder(**data.model_dump())
        return await self.workorder_repo.create(entity)

    async def complete_work_order(
        self,
        work_order_id: uuid.UUID,
        completed_at: str | None = None,
    ) -> MaintenanceWorkOrder:
        wo = await self.workorder_repo.get_by_id(work_order_id)
        if wo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work order not found",
            )
        # Guard the state transition. Re-completing an already-completed WO
        # would roll the parent schedule forward a second time (corrupting
        # last_completed_meter / next_due_meter), and "completing" a
        # cancelled WO would silently resurrect it. Only scheduled /
        # in_progress orders may transition to completed.
        if wo.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Work order is already completed",
            )
        if wo.status not in ("scheduled", "in_progress"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot complete a work order in '{wo.status}' state",
            )
        completed_iso = completed_at or date.today().isoformat()
        await self.workorder_repo.update_fields(
            work_order_id,
            status="completed",
            completed_at=completed_iso,
        )

        # Roll forward the parent schedule, if any.
        if wo.schedule_id is not None:
            schedule = await self.schedule_repo.get_by_id(wo.schedule_id)
            equipment = await self.equipment_repo.get_by_id(wo.equipment_id)
            if schedule is not None and equipment is not None:
                schedule.last_completed_at = completed_iso
                if schedule.trigger_type == "hours":
                    schedule.last_completed_meter = equipment.hour_meter
                elif schedule.trigger_type == "km":
                    schedule.last_completed_meter = equipment.odometer_km
                computed = compute_next_due(
                    schedule,
                    current_hour_meter=equipment.hour_meter,
                    current_km=equipment.odometer_km,
                    today=completed_iso,
                )
                await self.schedule_repo.update_fields(
                    schedule.id,
                    last_completed_at=schedule.last_completed_at,
                    last_completed_meter=schedule.last_completed_meter,
                    next_due_meter=computed["next_due_meter"],
                    next_due_date=computed["next_due_date"],
                )

        await self.session.refresh(wo)
        return wo

    # ── Inspections ──────────────────────────────────────────────────────

    async def create_inspection(self, data: InspectionCreate) -> Inspection:
        await self.get_equipment(data.equipment_id)
        entity = Inspection(**data.model_dump())
        return await self.inspection_repo.create(entity)

    async def check_inspection_compliance(
        self,
        equipment_id: uuid.UUID,
        today: str | None = None,
    ) -> dict[str, bool]:
        """Return ``{inspection_type: is_expired}`` for the equipment unit.

        ``is_expired`` is True if the most recent inspection of that type has
        ``valid_until < today``.
        """
        today_iso = today or date.today().isoformat()
        all_insp = await self.inspection_repo.list_for_equipment(equipment_id)

        # Group by inspection_type → pick the latest valid_until.
        latest: dict[str, Inspection] = {}
        for insp in all_insp:
            cur = latest.get(insp.inspection_type)
            if cur is None or insp.valid_until > cur.valid_until:
                latest[insp.inspection_type] = insp

        return {t: insp.valid_until < today_iso for t, insp in latest.items()}

    async def expiring_inspections(self, days: int = 30) -> list[Inspection]:
        today = date.today().isoformat()
        return await self.inspection_repo.expiring_within(today, days)

    # ── Assignment gate ──────────────────────────────────────────────────

    async def is_blocked_from_assignment(
        self,
        equipment_id: uuid.UUID,
        today: str | None = None,
    ) -> bool:
        """True if equipment cannot accept new assignment.

        Blocked when:
            * status != 'active', OR
            * any required inspection type currently expired.
        """
        equipment = await self.equipment_repo.get_by_id(equipment_id)
        if equipment is None:
            return True
        if equipment.status != "active":
            return True

        compliance = await self.check_inspection_compliance(equipment_id, today=today)
        # If any inspection type exists and is expired → blocked.
        return any(compliance.values())

    async def assign_to_project(
        self,
        equipment_id: uuid.UUID,
        project_id: uuid.UUID,
        start_date: str,
        daily_rate: Decimal,
        hourly_rate: Decimal,
        *,
        end_date: str | None = None,
        currency: str = "",
    ) -> EquipmentRental:
        """Create a rental linking equipment to a project.

        Raises ``ValueError`` if the unit is blocked. Emits
        ``equipment.assigned`` on success.
        """
        if await self.is_blocked_from_assignment(equipment_id):
            raise ValueError(
                f"Equipment {equipment_id} is blocked from assignment (status != active or inspection expired)"
            )

        # A rental whose end precedes its start has a negative billing
        # window: compute_rental_billing silently returns 0 and the unit
        # never registers as utilized. Reject it at the boundary instead
        # of persisting a corrupt record.
        if end_date is not None and end_date < start_date:
            raise ValueError(f"Rental end_date {end_date} is before start_date {start_date}")

        rental = EquipmentRental(
            equipment_id=equipment_id,
            project_id=project_id,
            start_date=start_date,
            end_date=end_date,
            internal_rate_per_day=Decimal(str(daily_rate)),
            internal_rate_per_hour=Decimal(str(hourly_rate)),
            currency=currency,
            status="active",
        )
        await self.rental_repo.create(rental)

        event_bus.publish_detached(
            "equipment.assigned",
            {
                "equipment_id": str(equipment_id),
                "project_id": str(project_id),
                "rental_id": str(rental.id),
                "start_date": start_date,
                "internal_rate_per_day": str(daily_rate),
                "internal_rate_per_hour": str(hourly_rate),
            },
            source_module="equipment",
        )
        return rental

    async def create_rental(self, data: EquipmentRentalCreate) -> EquipmentRental:
        return await self.assign_to_project(
            equipment_id=data.equipment_id,
            project_id=data.project_id,
            start_date=data.start_date,
            daily_rate=data.internal_rate_per_day,
            hourly_rate=data.internal_rate_per_hour,
            end_date=data.end_date,
            currency=data.currency,
        )

    async def return_rental(
        self,
        rental_id: uuid.UUID,
        end_date: str | None = None,
    ) -> EquipmentRental:
        rental = await self.rental_repo.get_by_id(rental_id)
        if rental is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rental not found",
            )
        # Returning an already-returned rental would overwrite its real
        # end_date (and therefore its billing window) with today's date.
        if rental.status == "returned":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Rental has already been returned",
            )
        end_iso = end_date or date.today().isoformat()
        # The rental cannot end before it started — guard against a caller
        # passing an end_date earlier than start_date, which would make
        # compute_rental_billing silently return 0 for the whole period.
        if rental.start_date and end_iso < rental.start_date:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Return date {end_iso} is before the rental start date {rental.start_date}"),
            )
        await self.rental_repo.update_fields(
            rental_id,
            status="returned",
            end_date=end_iso,
        )
        await self.session.refresh(rental)
        return rental

    # ── Fuel & Parts ─────────────────────────────────────────────────────

    async def _active_rental_project_id(
        self,
        equipment_id: uuid.UUID,
        on_date: str | None = None,
    ) -> uuid.UUID | None:
        """Return the project_id of the rental that is active on ``on_date``,
        or ``None`` when the unit is idle / between rentals.

        A rental is "active on D" when ``start_date <= D`` and either
        ``end_date IS NULL`` or ``end_date >= D``.
        """
        rentals, _ = await self.rental_repo.list_(
            equipment_id=equipment_id,
            status="active",
            limit=10,
        )
        if not rentals:
            return None
        ref = on_date or date.today().isoformat()
        for rental in rentals:
            if rental.start_date and rental.start_date > ref:
                continue
            if rental.end_date and rental.end_date < ref:
                continue
            return rental.project_id
        return rentals[0].project_id

    async def create_fuel_log(self, data: FuelLogCreate) -> FuelLog:
        """Record a fuel fill and emit ``equipment.fuel_logged``.

        Event payload includes the active rental's ``project_id`` (if any) so
        a finance / project-controlling subscriber can credit equipment cost
        to the right project budget line.
        """
        await self.get_equipment(data.equipment_id)
        entity = FuelLog(**data.model_dump())
        entity = await self.fuel_repo.create(entity)

        project_id = await self._active_rental_project_id(
            data.equipment_id,
            on_date=data.logged_at,
        )
        event_bus.publish_detached(
            "equipment.fuel_logged",
            {
                "equipment_id": str(data.equipment_id),
                "fuel_log_id": str(entity.id),
                "logged_at": data.logged_at,
                "fuel_liters": str(data.fuel_liters),
                "cost": str(data.cost),
                "currency": data.currency,
                "project_id": str(project_id) if project_id else None,
                "supplier": data.supplier,
                "fuel_type": data.fuel_type,
            },
            source_module="equipment",
        )
        return entity

    async def create_parts_log(self, data: PartsLogCreate) -> PartsLog:
        """Record a part consumption and emit ``equipment.parts_logged``.

        Same project-resolution pattern as fuel: events that carry an active
        ``project_id`` let finance roll the cost into the right project.
        """
        await self.get_equipment(data.equipment_id)
        entity = PartsLog(**data.model_dump())
        entity = await self.parts_repo.create(entity)

        ref = data.logged_at or date.today().isoformat()
        project_id = await self._active_rental_project_id(
            data.equipment_id,
            on_date=ref,
        )
        line_total = (Decimal(str(data.quantity or 0)) * Decimal(str(data.unit_cost or 0))).quantize(Decimal("0.0001"))
        event_bus.publish_detached(
            "equipment.parts_logged",
            {
                "equipment_id": str(data.equipment_id),
                "parts_log_id": str(entity.id),
                "logged_at": ref,
                "part_number": data.part_number,
                "quantity": str(data.quantity),
                "unit_cost": str(data.unit_cost),
                "line_total": str(line_total),
                "currency": data.currency,
                "project_id": str(project_id) if project_id else None,
                "work_order_id": str(data.work_order_id) if data.work_order_id else None,
            },
            source_module="equipment",
        )
        return entity

    # ── Damage ───────────────────────────────────────────────────────────

    async def record_damage(self, data: DamageReportCreate) -> DamageReport:
        """Create a DamageReport and auto-create a maintenance work order."""
        await self.get_equipment(data.equipment_id)

        damage = DamageReport(
            equipment_id=data.equipment_id,
            reported_at=data.reported_at,
            reported_by=data.reported_by,
            severity=data.severity,
            description=data.description,
            photos=list(data.photos),
            repair_cost_estimate=data.repair_cost_estimate,
            currency=data.currency,
            status="reported",
        )
        await self.damage_repo.create(damage)

        # Auto WO
        wo = MaintenanceWorkOrder(
            equipment_id=data.equipment_id,
            scheduled_for=data.reported_at,
            status="scheduled",
            work_summary=f"[Damage / {data.severity}] {data.description[:400]}",
            cost=data.repair_cost_estimate or Decimal("0"),
            currency=data.currency,
            metadata_={"damage_report_id": str(damage.id), "severity": data.severity},
        )
        await self.workorder_repo.create(wo)

        # Capture PKs BEFORE update_fields() — its trailing expire_all()
        # detaches every attribute on ``damage`` and ``wo``. ``wo`` is never
        # refreshed afterwards, so a later ``wo.id`` access would trigger an
        # illegal *synchronous* lazy-load on the async session and 500 the
        # request. IDs are stable post-flush, so snapshot them here.
        damage_id = damage.id
        work_order_id = wo.id

        # Link back damage → WO
        await self.damage_repo.update_fields(damage_id, work_order_id=work_order_id)
        await self.session.refresh(damage)

        event_bus.publish_detached(
            "equipment.damage_reported",
            {
                "equipment_id": str(data.equipment_id),
                "damage_report_id": str(damage_id),
                "work_order_id": str(work_order_id),
                "severity": data.severity,
                "reported_by": data.reported_by,
            },
            source_module="equipment",
        )
        return damage

    # ── Dashboards ───────────────────────────────────────────────────────

    async def equipment_dashboard(
        self,
        equipment_id: uuid.UUID,
    ) -> EquipmentDashboardResponse:
        equipment = await self.get_equipment(equipment_id)
        today = date.today()
        month_start = today.replace(day=1).isoformat()
        today_iso = today.isoformat()

        fuel_cost_mtd = await self.fuel_repo.cost_in_range(month_start, today_iso, equipment_id=equipment_id)
        open_wo = await self.workorder_repo.count_open_for_equipment(equipment_id)
        expiring = await self.inspection_repo.expiring_within(today_iso, 30)
        expiring_for_unit = sum(1 for i in expiring if i.equipment_id == equipment_id)
        blocked = await self.is_blocked_from_assignment(equipment_id, today=today_iso)
        utilization = await utilization_for_equipment(self.session, equipment_id, month_start, today_iso)

        return EquipmentDashboardResponse(
            equipment_id=equipment_id,
            code=equipment.code,
            name=equipment.name,
            status=equipment.status,
            utilization_pct=utilization,
            fuel_cost_mtd=fuel_cost_mtd,
            open_work_orders=open_wo,
            expiring_inspections=expiring_for_unit,
            blocked=blocked,
            last_telemetry_at=equipment.last_telemetry_at,
        )

    async def fleet_dashboard(self) -> FleetDashboardResponse:
        rows, total = await self.equipment_repo.list_(limit=10_000)

        counts_by_status: dict[str, int] = {}
        counts_by_type: dict[str, int] = {}
        for e in rows:
            counts_by_status[e.status] = counts_by_status.get(e.status, 0) + 1
            counts_by_type[e.type_code] = counts_by_type.get(e.type_code, 0) + 1

        today = date.today()
        month_start = today.replace(day=1).isoformat()
        today_iso = today.isoformat()

        fuel_cost_mtd = await self.fuel_repo.cost_in_range(month_start, today_iso)

        # Single aggregate query instead of one per equipment unit.
        open_wo_total = await self.workorder_repo.count_open_fleet()

        expiring = await self.inspection_repo.expiring_within(today_iso, 30)
        blocked_units = len(await self.equipment_repo.list_blocked(today_iso))
        active_rentals = await self.rental_repo.count_active()

        # Fleet utilization: mean across the units this month. Computed with
        # a single rentals query and averaged over the units actually
        # loaded (not the unbounded total count, which would understate
        # utilization when the unit list is paginated).
        util_avg = await fleet_utilization_avg(
            self.session,
            [e.id for e in rows],
            month_start,
            today_iso,
        )

        return FleetDashboardResponse(
            total_units=total,
            counts_by_status=counts_by_status,
            counts_by_type=counts_by_type,
            utilization_pct=util_avg,
            fuel_cost_mtd=fuel_cost_mtd,
            open_work_orders=open_wo_total,
            expiring_inspections=len(expiring),
            blocked_units=blocked_units,
            active_rentals=active_rentals,
        )


# ── Helpers ──────────────────────────────────────────────────────────────


def _ensure_aware(dt: datetime) -> datetime:
    """Normalise to a tz-aware datetime in UTC for comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
