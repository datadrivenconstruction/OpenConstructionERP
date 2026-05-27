"""‌⁠‍Equipment data access layer."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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


class _BaseRepository:
    """‌⁠‍Common CRUD primitives."""

    model: type
    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> Any:
        return await self.session.get(self.model, entity_id)

    async def create(self, entity: Any) -> Any:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update_fields(self, entity_id: uuid.UUID, **fields: Any) -> None:
        stmt = update(self.model).where(self.model.id == entity_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, entity_id: uuid.UUID) -> None:
        entity = await self.get_by_id(entity_id)
        if entity is not None:
            await self.session.delete(entity)
            await self.session.flush()


class EquipmentTypeRepository(_BaseRepository):
    """‌⁠‍Data access for EquipmentType."""

    model = EquipmentType

    async def list_all(self) -> list[EquipmentType]:
        result = await self.session.execute(select(EquipmentType).order_by(EquipmentType.code))
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> EquipmentType | None:
        result = await self.session.execute(select(EquipmentType).where(EquipmentType.code == code))
        return result.scalar_one_or_none()


class EquipmentRepository(_BaseRepository):
    """Data access for Equipment."""

    model = Equipment

    async def get_by_code(self, code: str) -> Equipment | None:
        result = await self.session.execute(select(Equipment).where(Equipment.code == code))
        return result.scalar_one_or_none()

    async def list_(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        type_code: str | None = None,
        ownership: str | None = None,
    ) -> tuple[list[Equipment], int]:
        base = select(Equipment)
        if status is not None:
            base = base.where(Equipment.status == status)
        if type_code is not None:
            base = base.where(Equipment.type_code == type_code)
        if ownership is not None:
            base = base.where(Equipment.ownership == ownership)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Equipment.code).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_by_status(self, status: str) -> list[Equipment]:
        result = await self.session.execute(
            select(Equipment).where(Equipment.status == status).order_by(Equipment.code)
        )
        return list(result.scalars().all())

    async def list_blocked(self, today: str) -> list[Equipment]:
        """List units blocked from assignment: non-active OR with expired inspection."""
        # Sub-query: equipment with at least one expired inspection.
        expired_inspections = select(Inspection.equipment_id).where(Inspection.valid_until < today).distinct()
        stmt = select(Equipment).where((Equipment.status != "active") | (Equipment.id.in_(expired_inspections)))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class TelemetryRepository(_BaseRepository):
    """Data access for TelemetryReading."""

    model = TelemetryReading

    async def latest_telemetry(self, equipment_id: uuid.UUID) -> TelemetryReading | None:
        stmt = (
            select(TelemetryReading)
            .where(TelemetryReading.equipment_id == equipment_id)
            .order_by(desc(TelemetryReading.recorded_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_since(
        self,
        equipment_id: uuid.UUID,
        since: Any | None = None,
        limit: int = 500,
    ) -> list[TelemetryReading]:
        stmt = select(TelemetryReading).where(TelemetryReading.equipment_id == equipment_id)
        if since is not None:
            stmt = stmt.where(TelemetryReading.recorded_at >= since)
        stmt = stmt.order_by(desc(TelemetryReading.recorded_at)).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class MaintenanceScheduleRepository(_BaseRepository):
    """Data access for MaintenanceSchedule."""

    model = MaintenanceSchedule

    async def list_for_equipment(self, equipment_id: uuid.UUID) -> list[MaintenanceSchedule]:
        result = await self.session.execute(
            select(MaintenanceSchedule).where(MaintenanceSchedule.equipment_id == equipment_id)
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[MaintenanceSchedule]:
        result = await self.session.execute(select(MaintenanceSchedule).where(MaintenanceSchedule.active.is_(True)))
        return list(result.scalars().all())


class WorkOrderRepository(_BaseRepository):
    """Data access for MaintenanceWorkOrder."""

    model = MaintenanceWorkOrder

    async def list_(
        self,
        *,
        equipment_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[MaintenanceWorkOrder], int]:
        base = select(MaintenanceWorkOrder)
        if equipment_id is not None:
            base = base.where(MaintenanceWorkOrder.equipment_id == equipment_id)
        if status is not None:
            base = base.where(MaintenanceWorkOrder.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(desc(MaintenanceWorkOrder.created_at)).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_open_for_equipment(self, equipment_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(MaintenanceWorkOrder)
            .where(
                MaintenanceWorkOrder.equipment_id == equipment_id,
                MaintenanceWorkOrder.status.in_(("scheduled", "in_progress")),
            )
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_open_fleet(self) -> int:
        """Total open (scheduled / in_progress) work orders across the fleet.

        Single aggregate query — replaces a per-equipment N+1 loop in the
        fleet dashboard.
        """
        stmt = (
            select(func.count())
            .select_from(MaintenanceWorkOrder)
            .where(MaintenanceWorkOrder.status.in_(("scheduled", "in_progress")))
        )
        return (await self.session.execute(stmt)).scalar_one()


class InspectionRepository(_BaseRepository):
    """Data access for Inspection."""

    model = Inspection

    async def list_for_equipment(self, equipment_id: uuid.UUID) -> list[Inspection]:
        result = await self.session.execute(select(Inspection).where(Inspection.equipment_id == equipment_id))
        return list(result.scalars().all())

    async def expiring_within(self, today: str, days: int) -> list[Inspection]:
        """Inspections expiring within `days` days of `today` (inclusive)."""
        from datetime import date, timedelta

        try:
            today_d = date.fromisoformat(today)
        except (ValueError, TypeError):
            return []
        cutoff = (today_d + timedelta(days=days)).isoformat()

        stmt = (
            select(Inspection)
            .where(Inspection.valid_until >= today)
            .where(Inspection.valid_until <= cutoff)
            .order_by(Inspection.valid_until)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def expired_for_equipment(self, equipment_id: uuid.UUID, today: str) -> list[Inspection]:
        stmt = select(Inspection).where(Inspection.equipment_id == equipment_id).where(Inspection.valid_until < today)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RentalRepository(_BaseRepository):
    """Data access for EquipmentRental."""

    model = EquipmentRental

    async def list_(
        self,
        *,
        equipment_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[EquipmentRental], int]:
        base = select(EquipmentRental)
        if equipment_id is not None:
            base = base.where(EquipmentRental.equipment_id == equipment_id)
        if project_id is not None:
            base = base.where(EquipmentRental.project_id == project_id)
        if status is not None:
            base = base.where(EquipmentRental.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(desc(EquipmentRental.start_date)).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_active(self) -> int:
        stmt = select(func.count()).select_from(EquipmentRental).where(EquipmentRental.status == "active")
        return (await self.session.execute(stmt)).scalar_one()


class FuelLogRepository(_BaseRepository):
    """Data access for FuelLog."""

    model = FuelLog

    async def list_for_equipment(
        self,
        equipment_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[FuelLog], int]:
        base = select(FuelLog).where(FuelLog.equipment_id == equipment_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(desc(FuelLog.logged_at)).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def fuel_consumption(
        self,
        equipment_id: uuid.UUID,
        period_start: str,
        period_end: str,
    ) -> dict[str, Decimal]:
        """Return {liters, cost} for fuel logs in the period."""
        stmt = (
            select(FuelLog)
            .where(FuelLog.equipment_id == equipment_id)
            .where(FuelLog.logged_at >= period_start)
            .where(FuelLog.logged_at <= period_end)
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        total_l = sum((r.fuel_liters or Decimal("0") for r in rows), Decimal("0"))
        total_cost = sum((r.cost or Decimal("0") for r in rows), Decimal("0"))
        return {"liters": total_l, "cost": total_cost}

    async def cost_in_range(
        self,
        period_start: str,
        period_end: str,
        equipment_id: uuid.UUID | None = None,
    ) -> Decimal:
        stmt = (
            select(func.coalesce(func.sum(FuelLog.cost), 0))
            .where(FuelLog.logged_at >= period_start)
            .where(FuelLog.logged_at <= period_end)
        )
        if equipment_id is not None:
            stmt = stmt.where(FuelLog.equipment_id == equipment_id)
        raw = (await self.session.execute(stmt)).scalar_one()
        return Decimal(str(raw or "0"))


class PartsLogRepository(_BaseRepository):
    """Data access for PartsLog."""

    model = PartsLog

    async def list_for_equipment(
        self,
        equipment_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PartsLog], int]:
        base = select(PartsLog).where(PartsLog.equipment_id == equipment_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(desc(PartsLog.created_at)).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class DamageReportRepository(_BaseRepository):
    """Data access for DamageReport."""

    model = DamageReport

    async def list_(
        self,
        *,
        equipment_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DamageReport], int]:
        base = select(DamageReport)
        if equipment_id is not None:
            base = base.where(DamageReport.equipment_id == equipment_id)
        if status is not None:
            base = base.where(DamageReport.status == status)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(desc(DamageReport.reported_at)).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


# ── Utilization helper (pure data → ratio) ─────────────────────────────────


async def utilization_for_equipment(
    session: AsyncSession,
    equipment_id: uuid.UUID,
    period_start: str,
    period_end: str,
) -> float:
    """Compute rough utilization % as days-rented / days-in-period.

    Counts days where an EquipmentRental was active overlapping the window.
    Falls back to 0.0 on bad inputs.
    """
    from datetime import date

    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except (ValueError, TypeError):
        return 0.0
    total_days = max(1, (end - start).days + 1)

    result = await session.execute(select(EquipmentRental).where(EquipmentRental.equipment_id == equipment_id))
    rentals = list(result.scalars().all())

    busy_days = _busy_days_in_window(rentals, start, end)
    return round(min(100.0, 100.0 * busy_days / total_days), 2)


def _busy_days_in_window(rentals: list[Any], start: Any, end: Any) -> int:
    """Distinct days within [start, end] covered by any of ``rentals``.

    Overlapping rentals are merged so a day rented by two concurrent
    rentals is not double-counted (which previously let utilization
    exceed 100% before the min() clamp masked it).
    """
    from datetime import date, timedelta

    intervals: list[tuple[Any, Any]] = []
    for r in rentals:
        try:
            r_start = date.fromisoformat(r.start_date)
        except (ValueError, TypeError):
            continue
        try:
            r_end = date.fromisoformat(r.end_date) if r.end_date else end
        except (ValueError, TypeError):
            r_end = end
        clip_start = max(r_start, start)
        clip_end = min(r_end, end)
        if clip_end >= clip_start:
            intervals.append((clip_start, clip_end))

    if not intervals:
        return 0

    intervals.sort()
    busy_days = 0
    cur_start, cur_end = intervals[0]
    for nxt_start, nxt_end in intervals[1:]:
        if nxt_start <= cur_end + timedelta(days=1):
            cur_end = max(cur_end, nxt_end)
        else:
            busy_days += (cur_end - cur_start).days + 1
            cur_start, cur_end = nxt_start, nxt_end
    busy_days += (cur_end - cur_start).days + 1
    return busy_days


async def fleet_utilization_avg(
    session: AsyncSession,
    equipment_ids: list[uuid.UUID],
    period_start: str,
    period_end: str,
) -> float:
    """Mean utilization across ``equipment_ids`` over the window.

    Loads every rental for the requested units in a single query (instead
    of one query per unit) and computes per-unit overlap in Python. The
    denominator is the number of units actually averaged, so the result is
    consistent even when the caller worked from a paginated unit list.
    """
    from datetime import date

    if not equipment_ids:
        return 0.0
    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except (ValueError, TypeError):
        return 0.0
    total_days = max(1, (end - start).days + 1)

    result = await session.execute(select(EquipmentRental).where(EquipmentRental.equipment_id.in_(equipment_ids)))
    rentals = list(result.scalars().all())

    by_equipment: dict[uuid.UUID, list[Any]] = {}
    for r in rentals:
        by_equipment.setdefault(r.equipment_id, []).append(r)

    util_sum = 0.0
    for eid in equipment_ids:
        busy = _busy_days_in_window(by_equipment.get(eid, []), start, end)
        util_sum += min(100.0, 100.0 * busy / total_days)
    return round(util_sum / len(equipment_ids), 2)
