# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Equipment service - business logic for fleet, maintenance, rentals, and damage.

Key features:
    * record_telemetry - append reading + bump Equipment counters if newer.
    * compute_next_due - pure scheduler helper for hours/km/date triggers.
    * generate_due_work_orders - auto-create WO stubs for schedules near threshold.
    * check_inspection_compliance / is_blocked_from_assignment - assignment gate.
    * assign_to_project - creates a rental; raises if blocked. Emits event.
    * compute_rental_billing - pure rate × period helper (hours preferred over days).
    * depreciation_value_at - linear/straight-line depreciation; extension point.
    * record_damage - DamageReport + auto MaintenanceWorkOrder.
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
    EquipmentCostSummaryResponse,
    EquipmentCreate,
    EquipmentDashboardResponse,
    EquipmentRentalCreate,
    EquipmentTypeCreate,
    EquipmentUpdate,
    FailureForecastResponse,
    FleetDashboardResponse,
    FleetMaintenanceBundleResponse,
    FleetOptimizationResponse,
    FleetUnderutilizedResponse,
    FuelLogCreate,
    HealthAnalyticsResponse,
    HealthAnomalyResponse,
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
    """Compute the next due trigger for a schedule.

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


def _non_negative(value: Decimal | float | int | str | None) -> Decimal:
    """Coerce a value to Decimal and never let it go below zero.

    Rental billing must never produce a credit from a bad input, so a negative
    logged-hours value or a negative rate (both only reachable through corrupt
    data) is floored at zero rather than silently reversing the charge.
    """
    try:
        result = Decimal(str(value if value is not None else 0))
    except (ArithmeticError, ValueError, TypeError):
        return Decimal("0")
    return result if result > 0 else Decimal("0")


def compute_rental_billing(
    rental: EquipmentRental,
    period_start: str,
    period_end: str,
    hours_logged: Decimal | float | int | None = None,
) -> Decimal:
    """Compute billing for a rental over a period.

    Hours billing takes precedence if ``hours_logged`` is provided and the
    rental has a non-zero hourly rate; otherwise day billing applies. Dates are
    ISO 8601 (YYYY-MM-DD), unambiguous in every country, and the currency is
    whatever the rental rate is stored in. Negative hours or rates from corrupt
    data are floored at zero so billing is never a credit.
    """
    rate_per_hour = _non_negative(rental.internal_rate_per_hour)
    if hours_logged is not None and rate_per_hour > 0:
        return _non_negative(hours_logged) * rate_per_hour

    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except (ValueError, TypeError):
        return Decimal("0")
    if end < start:
        return Decimal("0")

    days = Decimal((end - start).days + 1)
    return days * _non_negative(rental.internal_rate_per_day)


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
      exactly at the end of its life - this is the GAAP / IFRS practice for
      DB methods.

    Returns ``Decimal("0")`` if any of ``purchase_value``,
    ``useful_life_years``, ``purchase_date`` is missing - caller should
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
        # Block delete when any Equipment still points at this type's code -
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
               via :meth:`generate_due_work_orders` - so the operator
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

        # Reload the reading's columns within the async greenlet so the
        # router's model_validate() serialises its stored row, including any
        # value the trigger handling above wrote.
        await self.session.refresh(reading)
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
        # The rental cannot end before it started - guard against a caller
        # passing an end_date earlier than start_date, which would make
        # compute_rental_billing silently return 0 for the whole period.
        if rental.start_date and end_iso < rental.start_date:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Return date {end_iso} is before the rental start date {rental.start_date}"),
            )

        # ── Gap C: compute rental billing and post it to the cost spine ──────
        # Snapshot every attribute we need BEFORE update_fields() expires the
        # ORM row (reading rental.* afterwards would re-issue a sync SELECT and
        # raise MissingGreenlet on the async session).
        project_id = rental.project_id
        start_date = rental.start_date
        rate_per_day = rental.internal_rate_per_day
        rate_per_hour = rental.internal_rate_per_hour
        currency = rental.currency
        # Hours-based billing is opt-in: a rental gains an hourly charge only
        # when actual hours are recorded against it (metadata.hours_logged). No
        # hours -> day-rate billing over the [start, end] window.
        md = rental.metadata_ if isinstance(rental.metadata_, dict) else {}
        hours_logged = md.get("hours_logged")

        billing_amount = compute_rental_billing(rental, start_date, end_iso, hours_logged)
        billing_type = "hourly" if (hours_logged is not None and Decimal(str(rate_per_hour or 0)) > 0) else "daily"
        calculated_at = datetime.now(UTC).isoformat()

        await self.rental_repo.update_fields(
            rental_id,
            status="returned",
            end_date=end_iso,
            billing_calculated_at=calculated_at,
        )
        await self.session.refresh(rental)

        # Emit the rollup trigger only when there is a non-zero charge to post.
        # The subscriber is idempotent on ``rental:{rental_id}`` anyway, but
        # skipping a zero charge avoids creating an empty equipment budget line.
        if billing_amount > 0:
            event_bus.publish_detached(
                "equipment.rental_returned",
                {
                    "rental_id": str(rental_id),
                    "project_id": str(project_id) if project_id else None,
                    "equipment_id": str(rental.equipment_id),
                    "start_date": start_date,
                    "end_date": end_iso,
                    "internal_rate_per_day": str(rate_per_day or 0),
                    "internal_rate_per_hour": str(rate_per_hour or 0),
                    "billing_amount": str(billing_amount),
                    "billing_type": billing_type,
                    "currency": currency,
                },
                source_module="equipment",
            )
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
        return None

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

        # Capture both PKs here: they are stable once the create above has
        # flushed, and the cross-links below need them as plain values.
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

    async def equipment_cost_summary(
        self,
        equipment_id: uuid.UUID,
        project_id: uuid.UUID | None = None,
    ) -> EquipmentCostSummaryResponse:
        """Aggregate all cost buckets for one machine, optionally per project."""
        await self.get_equipment(equipment_id)

        # Rental cost: sum of (days * daily_rate)
        rentals, _ = await self.rental_repo.list_(equipment_id=equipment_id, limit=10_000)
        rental_cost = Decimal("0")
        rental_days = 0
        for r in rentals:
            if project_id and r.project_id != project_id:
                continue
            start = date.fromisoformat(r.start_date) if r.start_date else date.today()
            end = date.fromisoformat(r.end_date) if r.end_date else date.today()
            d = max((end - start).days, 0)
            rental_days += d
            rate = r.internal_rate_per_day or Decimal("0")
            rental_cost += rate * d

        # Fuel cost (FuelLog has no project_id, so project filter is skipped)
        fuel_logs, _ = await self.fuel_repo.list_for_equipment(equipment_id, limit=10_000)
        fuel_cost = Decimal("0")
        fuel_litres = Decimal("0")
        for f in fuel_logs:
            fuel_cost += f.cost or Decimal("0")
            fuel_litres += f.fuel_liters or Decimal("0")

        # Maintenance work order costs (WO has a single `cost` field)
        work_orders, _ = await self.workorder_repo.list_(equipment_id=equipment_id, limit=10_000)
        maintenance_cost = Decimal("0")
        wo_count = len(work_orders)
        for wo in work_orders:
            maintenance_cost += wo.cost or Decimal("0")

        # Parts cost from PartsLog (quantity * unit_cost)
        parts_list, _ = await self.parts_repo.list_for_equipment(equipment_id, limit=10_000)
        parts_cost = Decimal("0")
        for p in parts_list:
            parts_cost += (p.quantity or Decimal("1")) * (p.unit_cost or Decimal("0"))

        total = rental_cost + fuel_cost + maintenance_cost + parts_cost

        # Plant hours from field_time (if available)
        plant_hours = Decimal("0")
        try:
            from sqlalchemy import func as sa_func
            from sqlalchemy import select as sa_select

            from app.modules.field_time.models import FieldTimesheetLine

            q = sa_select(sa_func.coalesce(sa_func.sum(FieldTimesheetLine.hours), 0)).where(
                FieldTimesheetLine.equipment_id == equipment_id,
            )
            if project_id:
                q = q.where(FieldTimesheetLine.project_id == project_id)
            result = await self.session.execute(q)
            plant_hours = Decimal(str(result.scalar_one()))
        except Exception:
            pass

        cost_per_hour = (total / plant_hours).quantize(Decimal("0.01")) if plant_hours > 0 else None

        return EquipmentCostSummaryResponse(
            equipment_id=equipment_id,
            project_id=project_id,
            rental_cost=rental_cost,
            rental_days=rental_days,
            fuel_cost=fuel_cost,
            fuel_litres=fuel_litres,
            maintenance_cost=maintenance_cost,
            maintenance_orders=wo_count,
            parts_cost=parts_cost,
            total_cost=total,
            plant_hours=plant_hours,
            cost_per_hour=cost_per_hour,
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

    # ── Predictive maintenance / fleet analytics ─────────────────────────

    async def health_analytics(
        self,
        equipment_id: uuid.UUID,
    ) -> HealthAnalyticsResponse:
        """Predictive health assessment for one unit (validates existence)."""
        from app.modules.equipment.predictive_service import EquipmentPredictiveService

        await self.get_equipment(equipment_id)
        predictive = EquipmentPredictiveService(self.session)
        assessment = await predictive.analyze_equipment_health(equipment_id)
        return HealthAnalyticsResponse(
            equipment_id=equipment_id,
            health_score=assessment.health_score,
            band=assessment.band,
            anomaly_detected=assessment.anomaly_detected,
            maintenance_trend=assessment.maintenance_trend,
            reasons=assessment.reasons,
            anomalies=[
                HealthAnomalyResponse(
                    recorded_at=a.recorded_at,
                    metric=a.metric,
                    value=a.value,
                    z_score=a.z_score,
                    reason=a.reason,
                )
                for a in assessment.anomalies
            ],
            sample_count=assessment.sample_count,
        )

    async def failure_forecast(
        self,
        equipment_id: uuid.UUID,
    ) -> FailureForecastResponse:
        """Predicted next-service date + confidence for one unit."""
        from app.modules.equipment.predictive_service import EquipmentPredictiveService

        await self.get_equipment(equipment_id)
        predictive = EquipmentPredictiveService(self.session)
        forecast = await predictive.forecast_maintenance_need(equipment_id)
        return FailureForecastResponse(
            equipment_id=equipment_id,
            predicted_failure_date=forecast.predicted_failure_date,
            failure_confidence=forecast.failure_confidence,
            days_to_failure=forecast.days_to_failure,
            basis=forecast.basis,
            daily_usage=forecast.daily_usage,
        )

    async def fleet_optimization(
        self,
        *,
        target_utilization_pct: float = 70.0,
        window_days: int = 30,
    ) -> FleetOptimizationResponse:
        """Fleet-wide optimisation recommendations."""
        from app.modules.equipment.predictive_service import EquipmentPredictiveService

        predictive = EquipmentPredictiveService(self.session)
        data = await predictive.fleet_optimization_recommendations(
            target_utilization_pct=target_utilization_pct,
            window_days=window_days,
        )
        return FleetOptimizationResponse(
            total_units=int(data.get("total_units", 0)),  # type: ignore[arg-type]
            target_utilization_pct=float(data.get("target_utilization_pct", target_utilization_pct)),  # type: ignore[arg-type]
            window_days=int(data.get("window_days", window_days)),  # type: ignore[arg-type]
            underutilized_count=int(data.get("underutilized_count", 0)),  # type: ignore[arg-type]
            estimated_monthly_savings=str(data.get("estimated_monthly_savings", "0")),
            underutilized=[
                FleetUnderutilizedResponse(**u)  # type: ignore[arg-type]
                for u in data.get("underutilized", [])  # type: ignore[union-attr]
            ],
            maintenance_bundles=[
                FleetMaintenanceBundleResponse(**b)  # type: ignore[arg-type]
                for b in data.get("maintenance_bundles", [])  # type: ignore[union-attr]
            ],
        )


# ── Helpers ──────────────────────────────────────────────────────────────


def _ensure_aware(dt: datetime) -> datetime:
    """Normalise to a tz-aware datetime in UTC for comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ── Equipment actuals (fuel / parts / rental / work-order -> budget) ────────────


# Marker used to find/track the single auto-maintained equipment budget line per
# project, and to record which (source_kind, source_ref) pairs have already been
# folded into ``actual_amount`` so a re-fired event never double-counts.
_EQUIPMENT_LINE_MARKER = "equipment_actuals_auto"

# Cost categories a posting can carry. Equipment costs always land on the single
# project-level ``category="equipment"`` budget line (the cost_category argument
# is recorded in the posting trail for audit, not used to fan out rows).
_EQUIPMENT_BUDGET_CATEGORY = "equipment"


def _to_decimal_nonneg(value: object) -> Decimal:
    """Coerce ``value`` to a finite, non-negative Decimal (else 0).

    Used for cost inputs (fuel/parts/rental amounts) that must never poison the
    rollup with a NaN/negative. Mirrors the labour-actuals ``_to_decimal``
    guard so the two cost sinks share identical numeric hygiene.
    """
    if value is None:
        return Decimal("0")
    try:
        d = Decimal(str(value))
    except (ValueError, ArithmeticError, TypeError):
        return Decimal("0")
    return d if d.is_finite() and d >= 0 else Decimal("0")


class EquipmentActualsService:
    """Roll equipment costs (fuel, parts, rental billing, work orders) into budget.

    Owns the Gap C shared cost-spine interface for equipment. For each posting it
    converts the native cost to the project base currency via the shared
    :func:`_amount_in_base` FX helper and idempotently accumulates the total onto
    a single auto-maintained ``category="equipment"`` budget line per project.

    The line is found / created idempotently per project (tagged via
    ``metadata.kind == _EQUIPMENT_LINE_MARKER``), and each posting is applied at
    most once: the ``"{source_kind}:{source_ref}"`` key is recorded in
    ``metadata.applied_events`` so a re-fired event is a no-op.

    FX is never blended: a cost's own currency is converted to the project base
    via the project ``fx_rates`` using :func:`_amount_in_base`. A missing rate
    keeps the value in its own units (never zeroed) so a forgotten rate surfaces
    as a visibly-wrong total rather than silently dropping money.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Imported lazily-by-reference here (top of module would create an import
        # cycle: costmodel.service -> ... is unrelated, but keeping the import
        # local mirrors the labour subscriber and avoids importing costmodel at
        # equipment module-load time).
        from app.modules.costmodel.repository import BudgetLineRepository

        self.budget_repo = BudgetLineRepository(session)

    async def _compute_fx_context(self, project_id: uuid.UUID) -> tuple[str, dict[str, str]]:
        """Resolve the project's ``(base_currency, fx_rates)`` for conversion."""
        return await self.budget_repo._project_fx_context(project_id)

    async def _amount_in_base(
        self,
        amount_native: Decimal,
        currency: str,
        project_id: uuid.UUID,
    ) -> Decimal:
        """Convert a native cost amount into the project base currency.

        Thin wrapper over the shared :func:`_amount_in_base` helper so every
        equipment posting shares one set of FX semantics with the rest of the
        cost domain (BOQ, budget, labour).
        """
        from app.modules.costmodel.repository import _amount_in_base

        base, fx = await self._compute_fx_context(project_id)
        return _amount_in_base(str(amount_native), (currency or "").strip().upper(), base, fx)

    async def _get_or_create_equipment_line(self, project_id: uuid.UUID):
        """Find (or create) the single auto-maintained equipment budget line."""
        from app.modules.costmodel.models import BudgetLine

        lines, _ = await self.budget_repo.list_for_project(
            project_id,
            category=_EQUIPMENT_BUDGET_CATEGORY,
            limit=1000,
        )
        for line in lines:
            md = line.metadata_ if isinstance(line.metadata_, dict) else {}
            if md.get("kind") == _EQUIPMENT_LINE_MARKER:
                return line

        # New auto-line. Inherit the project base currency (empty string when
        # the project has none - the dashboard renders a currency-less number
        # rather than mislabelling, see CostModelService._get_project_currency).
        from app.modules.costmodel.service import CostModelService

        currency = await CostModelService(self.session)._get_project_currency(project_id)
        line = BudgetLine(
            project_id=project_id,
            category=_EQUIPMENT_BUDGET_CATEGORY,
            description="Equipment cost (auto)",
            planned_amount="0",
            committed_amount="0",
            actual_amount="0",
            forecast_amount="0",
            currency=currency,
            metadata_={"kind": _EQUIPMENT_LINE_MARKER, "applied_events": []},
        )
        return await self.budget_repo.create(line)

    async def post_actual_to_budget_line(
        self,
        project_id: uuid.UUID,
        cost_category: str,
        amount_native: Decimal,
        currency: str,
        source_kind: str,
        source_ref: str,
        logged_at: str | None = None,
    ) -> Decimal:
        """Idempotently post an equipment cost onto the equipment budget line.

        Gap C shared cost-spine interface for equipment. Converts ``amount_native``
        (in ``currency``) to the project base via ``fx_rates`` and accumulates it
        onto the single ``category="equipment"`` budget line's ``actual_amount``.

        Idempotency: the ``"{source_kind}:{source_ref}"`` key is recorded in
        ``metadata.applied_events``; re-posting the same source returns 0 and
        leaves the actual unchanged. ``cost_category`` and ``logged_at`` are
        recorded in the posting trail for audit only.

        Args:
            project_id: Owning project.
            cost_category: Fine-grained source category recorded for audit
                (``equipment:rental`` / ``equipment:fuel`` / ``equipment:parts``
                / ``equipment:work_order``). The budget line itself is always
                ``category="equipment"``.
            amount_native: Cost amount in ``currency`` (native units).
            currency: ISO currency of ``amount_native``.
            source_kind: Posting source family (``fuel_log`` / ``parts_log`` /
                ``rental`` / ``work_order``).
            source_ref: Stable unique reference within the source family
                (typically the source row's UUID as a string).
            logged_at: Optional ISO timestamp recorded in the posting trail.

        Returns:
            The Decimal amount applied in base currency (``Decimal("0")`` when the
            posting was skipped: a zero/negative cost, or an already-applied
            (source_kind, source_ref)).
        """
        native = _to_decimal_nonneg(amount_native)
        if native <= 0:
            return Decimal("0")

        amount = await self._amount_in_base(native, currency, project_id)
        amount = _to_decimal_nonneg(amount)
        if amount <= 0:
            return Decimal("0")
        amount = amount.quantize(Decimal("0.01"))

        line = await self._get_or_create_equipment_line(project_id)

        # Snapshot every attribute we need BEFORE the update, so the idempotency
        # check below tests the event list as it was read instead of reloading
        # it (MissingGreenlet on the async session).
        line_id = line.id
        md = dict(line.metadata_) if isinstance(line.metadata_, dict) else {}
        applied = md.get("applied_events")
        if not isinstance(applied, list):
            applied = []
        event_key = f"{source_kind}:{source_ref}"
        if event_key in applied:
            return Decimal("0")  # already counted

        prior = _to_decimal_nonneg(line.actual_amount)
        new_actual = (prior + amount).quantize(Decimal("0.01"))
        applied = [*applied, event_key]
        md["applied_events"] = applied
        if md.get("kind") is None:
            md["kind"] = _EQUIPMENT_LINE_MARKER

        # Keep an append-only posting trail for audit (mirrors the spine).
        postings = md.get("postings")
        if not isinstance(postings, list):
            postings = []
        postings = [
            *postings,
            {
                "source_kind": source_kind,
                "source_ref": source_ref,
                "cost_category": cost_category,
                "amount": str(amount),
                "currency": (currency or "").strip().upper(),
                "logged_at": logged_at,
                "posted_at": datetime.now(UTC).isoformat(),
            },
        ]
        md["postings"] = postings

        await self.budget_repo.update_fields(
            line_id,
            actual_amount=str(new_actual),
            metadata_=md,
        )
        logger.info(
            "Equipment actuals: project=%s kind=%s ref=%s +%s -> %s",
            project_id,
            source_kind,
            source_ref,
            amount,
            new_actual,
        )
        return amount


# ── Detached event subscribers (Gap C) ─────────────────────────────────────────


def _coerce_project_id(raw: object) -> uuid.UUID | None:
    """Parse a project_id from an event payload, or None when absent/invalid."""
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


async def _post_equipment_cost(
    *,
    project_id: uuid.UUID,
    cost_category: str,
    amount_native: Decimal,
    currency: str,
    source_kind: str,
    source_ref: str,
    logged_at: str | None,
    log_label: str,
) -> None:
    """Open a fresh session and fold one equipment cost into budget actuals.

    The publisher is still inside its own request transaction, so this opens an
    independent session (mirroring the labour subscriber). Errors are swallowed
    and logged so a cost-rollup failure never breaks the fuel/parts/rental
    submission that triggered it.
    """
    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            service = EquipmentActualsService(session)
            await service.post_actual_to_budget_line(
                project_id=project_id,
                cost_category=cost_category,
                amount_native=amount_native,
                currency=currency,
                source_kind=source_kind,
                source_ref=source_ref,
                logged_at=logged_at,
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Equipment actuals rollup failed for %s - source submission unaffected",
            log_label,
        )


async def _on_fuel_logged(event: object) -> None:
    """Detached subscriber: roll a fuel cost into the equipment budget line."""
    data = getattr(event, "data", None) or {}
    project_id = _coerce_project_id(data.get("project_id"))
    fuel_log_id = str(data.get("fuel_log_id") or "")
    if project_id is None or not fuel_log_id:
        return
    amount = _to_decimal_nonneg(data.get("cost"))
    if amount <= 0:
        return
    await _post_equipment_cost(
        project_id=project_id,
        cost_category="equipment:fuel",
        amount_native=amount,
        currency=str(data.get("currency") or ""),
        source_kind="fuel_log",
        source_ref=fuel_log_id,
        logged_at=str(data.get("logged_at")) if data.get("logged_at") else None,
        log_label=f"fuel_log={fuel_log_id}",
    )


async def _on_parts_logged(event: object) -> None:
    """Detached subscriber: roll a parts cost into the equipment budget line.

    Prefers the publisher-computed ``line_total`` (quantity x unit_cost); falls
    back to multiplying ``quantity`` by ``unit_cost`` if it is absent.
    """
    data = getattr(event, "data", None) or {}
    project_id = _coerce_project_id(data.get("project_id"))
    parts_log_id = str(data.get("parts_log_id") or "")
    if project_id is None or not parts_log_id:
        return

    line_total_raw = data.get("line_total")
    if line_total_raw is not None:
        amount = _to_decimal_nonneg(line_total_raw)
    else:
        amount = _to_decimal_nonneg(data.get("quantity")) * _to_decimal_nonneg(data.get("unit_cost"))
    if amount <= 0:
        return

    await _post_equipment_cost(
        project_id=project_id,
        cost_category="equipment:parts",
        amount_native=amount,
        currency=str(data.get("currency") or ""),
        source_kind="parts_log",
        source_ref=parts_log_id,
        logged_at=str(data.get("logged_at")) if data.get("logged_at") else None,
        log_label=f"parts_log={parts_log_id}",
    )


async def _on_rental_returned(event: object) -> None:
    """Detached subscriber: roll the rental billing into the equipment budget line.

    The router computes the billing amount on return and emits it in the event
    payload; this subscriber posts it (idempotent on ``rental:{rental_id}``).
    """
    data = getattr(event, "data", None) or {}
    project_id = _coerce_project_id(data.get("project_id"))
    rental_id = str(data.get("rental_id") or "")
    if project_id is None or not rental_id:
        return
    amount = _to_decimal_nonneg(data.get("billing_amount"))
    if amount <= 0:
        return
    await _post_equipment_cost(
        project_id=project_id,
        cost_category="equipment:rental",
        amount_native=amount,
        currency=str(data.get("currency") or ""),
        source_kind="rental",
        source_ref=rental_id,
        logged_at=str(data.get("end_date")) if data.get("end_date") else None,
        log_label=f"rental={rental_id}",
    )


# Register the Gap C subscribers at import time. The module loader imports
# ``equipment`` (its ``on_startup`` calls ``register_equipment_subscribers``,
# which imports this module), so binding here keeps the wiring inside an allowed
# file. Guard against double-registration on repeated imports (test reload, etc.).
for _evt_name, _handler in (
    ("equipment.fuel_logged", _on_fuel_logged),
    ("equipment.parts_logged", _on_parts_logged),
    ("equipment.rental_returned", _on_rental_returned),
):
    if _handler not in event_bus._handlers.get(_evt_name, []):
        event_bus.subscribe(_evt_name, _handler)
