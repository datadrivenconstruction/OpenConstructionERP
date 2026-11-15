# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plant cost board: gathers the facts per machine and hands them to ``cost_board``."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.cost_board import (
    DEFAULT_DAY_HOURS,
    DEFAULT_MIN_UTILISATION_PCT,
    MachineFacts,
    build_row,
)
from app.modules.equipment.models import (
    Equipment,
    FuelLog,
    MaintenanceWorkOrder,
    PartsLog,
    UtilisationDay,
)
from app.modules.equipment.repository import tenant_options

_ZERO = Decimal("0")


def _day(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _same(entry_currency: str, machine_currency: str) -> bool:
    return not entry_currency or not machine_currency or entry_currency == machine_currency


def _in_window(column: Any, date_from: date, date_to: date) -> tuple[Any, Any]:
    # ISO strings sort like dates; the exclusive upper bound keeps a timestamp on date_to.
    return column >= date_from.isoformat(), column < (date_to + timedelta(days=1)).isoformat()


class CostBoardService:
    """Per-machine owning vs operating cost against used hours."""

    def __init__(self, session: AsyncSession, tenant_id: str | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def _run(self, stmt: Any) -> Any:
        """Execute ``stmt`` confined to the caller's tenant (system callers pass none)."""
        if self.tenant_id is not None and isinstance(stmt, Select):
            stmt = stmt.options(*tenant_options(self.tenant_id))
        return await self.session.execute(stmt)

    async def _get(self, model: Any, row_id: uuid.UUID) -> Any:
        if self.tenant_id is None:
            return await self.session.get(model, row_id)
        return (await self._run(select(model).where(model.id == row_id))).scalar_one_or_none()

    async def board(
        self,
        date_from: date,
        date_to: date,
        day_hours: Decimal = DEFAULT_DAY_HOURS,
        min_utilisation_pct: Decimal = DEFAULT_MIN_UTILISATION_PCT,
    ) -> dict[str, Any]:
        eqs = list((await self._run(select(Equipment).where(Equipment.status != "decommissioned"))).scalars().all())
        days_by_eq: dict[Any, list[UtilisationDay]] = defaultdict(list)
        stmt = select(UtilisationDay).where(and_(UtilisationDay.day >= date_from, UtilisationDay.day <= date_to))
        for d in (await self._run(stmt)).scalars():
            days_by_eq[d.equipment_id].append(d)
        fuel_by_eq: dict[Any, list[FuelLog]] = defaultdict(list)
        for fl in (
            await self._run(select(FuelLog).where(*_in_window(FuelLog.logged_at, date_from, date_to)))
        ).scalars():
            if (when := _day(fl.logged_at)) and date_from <= when <= date_to:
                fuel_by_eq[fl.equipment_id].append(fl)
        wo_by_eq: dict[Any, list[MaintenanceWorkOrder]] = defaultdict(list)
        for wo in (
            await self._run(
                select(MaintenanceWorkOrder).where(
                    MaintenanceWorkOrder.status == "completed",
                    *_in_window(MaintenanceWorkOrder.completed_at, date_from, date_to),
                )
            )
        ).scalars():
            if (when := _day(wo.completed_at)) and date_from <= when <= date_to:
                wo_by_eq[wo.equipment_id].append(wo)
        parts_by_eq: dict[Any, list[PartsLog]] = defaultdict(list)
        # Parts tied to a work order are already inside that order's cost.
        for p in (
            await self._run(
                select(PartsLog).where(
                    PartsLog.work_order_id.is_(None), *_in_window(PartsLog.logged_at, date_from, date_to)
                )
            )
        ).scalars():
            if (when := _day(p.logged_at)) and date_from <= when <= date_to:
                parts_by_eq[p.equipment_id].append(p)

        rows: list[dict[str, Any]] = []
        for eq in eqs:
            mismatch = False
            fuel = maint = hire = worked = idle = _ZERO
            billed_days = 0
            for d in days_by_eq.get(eq.id, []):
                worked += d.worked_hours
                idle += d.idle_hours
                if d.hire_cost is not None and d.hire_cost > 0:
                    if _same(d.currency, eq.currency):
                        hire += d.hire_cost
                        billed_days += 1
                    else:
                        mismatch = True
            for fl in fuel_by_eq.get(eq.id, []):
                if _same(fl.currency, eq.currency):
                    fuel += fl.cost
                else:
                    mismatch = True
            for wo in wo_by_eq.get(eq.id, []):
                if _same(wo.currency, eq.currency):
                    maint += wo.cost
                else:
                    mismatch = True
            for p in parts_by_eq.get(eq.id, []):
                if _same(p.currency, eq.currency):
                    maint += p.quantity * p.unit_cost
                else:
                    mismatch = True
            facts = MachineFacts(
                equipment_id=str(eq.id),
                code=eq.code,
                name=eq.name,
                ownership=eq.ownership,
                currency=eq.currency,
                purchase_date=_day(eq.purchase_date),
                purchase_value=eq.purchase_value,
                residual_value=eq.residual_value,
                useful_life_years=eq.useful_life_years,
                holding_cost_per_month=eq.holding_cost_per_month,
                market_hire_rate_per_day=eq.market_hire_rate_per_day,
                telemetry_days=len(days_by_eq.get(eq.id, [])),
                worked_hours=worked,
                idle_hours=idle,
                billed_days=billed_days,
                hire_cost=hire,
                fuel_cost=fuel,
                maintenance_cost=maint,
                currency_mismatch=mismatch,
            )
            rows.append(build_row(facts, date_from, date_to, day_hours, min_utilisation_pct))
        rows.sort(key=lambda r: str(r["code"]))
        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "day_hours": str(day_hours),
            "min_utilisation_pct": str(min_utilisation_pct),
            "machines": rows,
            "totals_by_currency": _totals(rows),
        }


def _totals(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, Decimal]] = {}
    for r in rows:
        t = out.setdefault(
            str(r["currency"]),
            {"owning_cost": _ZERO, "operating_cost": _ZERO, "total_cost": _ZERO, "hire_cost": _ZERO},
        )
        for k in t:
            t[k] += Decimal(str(r[k]))
    return {cur: {k: str(v) for k, v in t.items()} for cur, t in out.items()}
