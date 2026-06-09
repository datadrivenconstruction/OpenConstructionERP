"""Formwork business logic.

Centralises the reuse-aware unit-cost math so callers (router, future
import wizard, future BOQ-rollup webhook) all share one source of truth.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.formwork.models import (
    FormworkAssignment,
    FormworkScheduleLine,
    FormworkSystem,
)
from app.modules.formwork.repository import (
    FormworkAssignmentRepository,
    FormworkScheduleLineRepository,
    FormworkSystemRepository,
)
from app.modules.formwork.schemas import (
    FormworkAssignmentCreate,
    FormworkAssignmentUpdate,
    FormworkScheduleLineCreate,
    FormworkScheduleLineUpdate,
    FormworkSystemCreate,
    FormworkSystemUpdate,
    default_seed_systems,
)

_TWO_DP = Decimal("0.01")


class ReuseCountExceedsMaxError(ValueError):
    """Raised when an assignment's ``reuse_count`` exceeds the system cap.

    A formwork system carries a manufacturer reuse limit (``reuses_max``).
    Pricing an assignment with more reuses than the panels physically
    survive would understate the unit cost, so the service rejects it
    instead of silently producing a too-cheap figure.
    """

    def __init__(self, reuse_count: int, reuses_max: int) -> None:
        self.reuse_count = reuse_count
        self.reuses_max = reuses_max
        super().__init__(
            f"reuse_count {reuse_count} exceeds the system reuses_max {reuses_max}",
        )


def _q(v: Decimal) -> Decimal:
    """Round to 2 dp using banker-safe ROUND_HALF_UP (matches contracts)."""
    return Decimal(v).quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def compute_cost(
    *,
    unit_rate: Decimal,
    area_m2: Decimal,
    waste_pct: Decimal,
    reuse_count: int,
) -> tuple[Decimal, Decimal]:
    """Return ``(computed_unit_cost, computed_total)`` for an assignment.

    Formula (per ROADMAP task #112 spec):

        unit_cost = unit_rate * (1 + waste_pct/100) / reuse_count
        total     = area_m2  * unit_cost

    Both figures are persisted and shown to the user, so ``total`` is
    derived from the **rounded** ``unit_cost`` (not the raw quotient).
    Otherwise ``area_m2 * computed_unit_cost`` recomputed client-side
    would not match the stored ``computed_total`` whenever the quotient
    carried fractional cents (e.g. unit_rate 65.00, waste 5%, reuse 2 =>
    34.125, where area 100 gave 3412.50 stored vs 3413.00 displayed).

    ``reuse_count`` is guaranteed >= 1 by the schema; we still defend
    against 0 here in case the service is called from a future import
    path that bypasses Pydantic.
    """
    reuses = max(int(reuse_count), 1)
    waste_factor = Decimal("1") + (Decimal(waste_pct) / Decimal("100"))
    unit_cost = _q((Decimal(unit_rate) * waste_factor) / Decimal(reuses))
    total = _q(Decimal(area_m2) * unit_cost)
    return unit_cost, total


class FormworkService:
    """Thin orchestration layer over the three repositories."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.system_repo = FormworkSystemRepository(session)
        self.assignment_repo = FormworkAssignmentRepository(session)
        self.schedule_repo = FormworkScheduleLineRepository(session)

    # ── Systems ────────────────────────────────────────────────────────

    async def create_system(self, data: FormworkSystemCreate) -> FormworkSystem:
        obj = FormworkSystem(**data.model_dump())
        return await self.system_repo.create(obj)

    async def update_system(
        self,
        system_id: uuid.UUID,
        data: FormworkSystemUpdate,
    ) -> FormworkSystem | None:
        fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if fields:
            await self.system_repo.update_fields(system_id, **fields)
        return await self.system_repo.get_by_id(system_id)

    async def seed_defaults(
        self,
        *,
        tenant_id: uuid.UUID | None,
    ) -> dict[str, int]:
        """Idempotently insert the starter formwork catalogue."""
        already = await self.system_repo.list_names_for_tenant(tenant_id)
        inserted = 0
        skipped = 0
        for row in default_seed_systems():
            if row["name"] in already:
                skipped += 1
                continue
            obj = FormworkSystem(tenant_id=tenant_id, **row)
            self.session.add(obj)
            inserted += 1
        await self.session.flush()
        total = len(already) + inserted
        return {"inserted": inserted, "skipped": skipped, "total_after": total}

    # ── Assignments ────────────────────────────────────────────────────

    async def create_assignment(
        self,
        data: FormworkAssignmentCreate,
    ) -> FormworkAssignment:
        system = await self.system_repo.get_by_id(data.formwork_system_id)
        if system is None:
            raise LookupError("formwork_system_not_found")
        if data.reuse_count > system.reuses_max:
            raise ReuseCountExceedsMaxError(data.reuse_count, system.reuses_max)
        unit_cost, total = compute_cost(
            unit_rate=system.unit_rate,
            area_m2=data.area_m2,
            waste_pct=data.waste_pct,
            reuse_count=data.reuse_count,
        )
        obj = FormworkAssignment(
            project_id=data.project_id,
            boq_position_id=data.boq_position_id,
            formwork_system_id=data.formwork_system_id,
            area_m2=data.area_m2,
            reuse_count=data.reuse_count,
            waste_pct=data.waste_pct,
            computed_unit_cost=unit_cost,
            computed_total=total,
            notes=data.notes,
            tenant_id=data.tenant_id,
        )
        return await self.assignment_repo.create(obj)

    async def update_assignment(
        self,
        assignment_id: uuid.UUID,
        data: FormworkAssignmentUpdate,
    ) -> FormworkAssignment | None:
        obj = await self.assignment_repo.get_by_id(assignment_id)
        if obj is None:
            return None
        fields: dict[str, Any] = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        # Apply patches in-memory so we can recompute against the merged state.
        for k, v in fields.items():
            setattr(obj, k, v)
        # Recompute cost - resolve the (possibly swapped) system.
        system = await self.system_repo.get_by_id(obj.formwork_system_id)
        if system is None:
            raise LookupError("formwork_system_not_found")
        if obj.reuse_count > system.reuses_max:
            raise ReuseCountExceedsMaxError(obj.reuse_count, system.reuses_max)
        unit_cost, total = compute_cost(
            unit_rate=system.unit_rate,
            area_m2=obj.area_m2,
            waste_pct=obj.waste_pct,
            reuse_count=obj.reuse_count,
        )
        obj.computed_unit_cost = unit_cost
        obj.computed_total = total
        await self.session.flush()
        return obj

    # ── Schedule lines ─────────────────────────────────────────────────

    async def add_schedule_line(
        self,
        assignment: FormworkAssignment,
        data: FormworkScheduleLineCreate,
    ) -> FormworkScheduleLine:
        obj = FormworkScheduleLine(
            project_id=assignment.project_id,
            assignment_id=assignment.id,
            pour_no=data.pour_no,
            pour_date=data.pour_date,
            level_label=data.level_label,
            area_m2=data.area_m2,
            notes=data.notes,
        )
        return await self.schedule_repo.create(obj)

    async def update_schedule_line(
        self,
        line_id: uuid.UUID,
        data: FormworkScheduleLineUpdate,
    ) -> FormworkScheduleLine | None:
        """Patch a pour-cycle line in place.

        Only the fields the caller actually sent are touched, so the
        nullable ``pour_date`` / ``notes`` can be explicitly cleared by
        sending them as ``null`` while an omitted field is left untouched.
        ``project_id`` and ``assignment_id`` are never reparented.
        """
        obj = await self.schedule_repo.get_by_id(line_id)
        if obj is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        await self.session.flush()
        return obj
