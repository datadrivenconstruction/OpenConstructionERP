# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Manual bar bending schedule: entries, totals, validation and CSV."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rebar_schedule.bbs import BbsError, compute_row, render_csv, totals_by_diameter
from app.modules.rebar_schedule.bbs_validators import DEFAULT_LAP_MULTIPLE, DEFAULT_TOLERANCE_PCT, RULE_SET
from app.modules.rebar_schedule.models import BarBendingEntry
from app.modules.rebar_schedule.schemas import BbsEntryCreate, BbsEntryUpdate

_DIMS = ("dim_a", "dim_b", "dim_c", "dim_d", "dim_e")


class BarBendingService:
    """Bar marks of a project's bar bending schedule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def entries(self, project_id: uuid.UUID) -> list[BarBendingEntry]:
        stmt = (
            select(BarBendingEntry)
            .where(BarBendingEntry.project_id == project_id)
            .order_by(BarBendingEntry.member, BarBendingEntry.bar_mark)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def entry(self, entry_id: uuid.UUID) -> BarBendingEntry:
        row = await self.session.get(BarBendingEntry, entry_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bar mark not found")
        return row

    @staticmethod
    def _compute(row: BarBendingEntry) -> None:
        try:
            values = compute_row(
                standard=row.shape_standard,
                code=row.shape_code,
                diameter_mm=row.diameter_mm,
                dims={d[-1].upper(): getattr(row, d) for d in _DIMS},
                members_count=row.members_count,
                bars_per_member=row.bars_per_member,
            )
        except BbsError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        for key, value in values.items():
            setattr(row, key, value)

    async def _flush(self, row: BarBendingEntry) -> None:
        # A savepoint, so a duplicate bar mark leaves the caller's transaction usable.
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="This bar mark already exists for the member") from exc

    async def create(self, data: BbsEntryCreate, actor: str | None) -> BarBendingEntry:
        """Add a bar mark; cut length and weight are computed from its shape code."""
        row = BarBendingEntry(**data.model_dump(), created_by=actor)
        self._compute(row)
        await self._flush(row)
        return row

    async def update(self, row: BarBendingEntry, data: BbsEntryUpdate) -> BarBendingEntry:
        """Edit a bar mark and recompute it."""
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is None and key not in (*_DIMS, "steel_grade", "lap_length_mm", "boq_position_id", "notes"):
                continue
            setattr(row, key, value)
        self._compute(row)
        await self._flush(row)
        return row

    async def delete(self, row: BarBendingEntry) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def schedule(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Bar marks with totals per diameter and the total weight."""
        rows = await self.entries(project_id)
        totals = totals_by_diameter(rows)
        return {
            "items": rows,
            "totals_by_diameter": totals,
            "total_weight_kg": sum((t["weight_kg"] for t in totals), Decimal("0")),
        }

    async def csv(self, project_id: uuid.UUID) -> str:
        return render_csv(await self.entries(project_id))

    async def validate(
        self,
        project_id: uuid.UUID,
        *,
        lap_multiple: Decimal = DEFAULT_LAP_MULTIPLE,
        tolerance_pct: Decimal = DEFAULT_TOLERANCE_PCT,
    ) -> dict[str, Any]:
        """Run the ``bar_bending_schedule`` rule set; failed results only."""
        from app.core.validation.engine import validation_engine  # noqa: PLC0415
        from app.modules.boq.models import Position  # noqa: PLC0415

        rows = await self.entries(project_id)
        pids = {r.boq_position_id for r in rows if r.boq_position_id}
        positions: dict[str, dict[str, Any]] = {}
        if pids:
            found = (await self.session.execute(select(Position).where(Position.id.in_(pids)))).scalars().all()
            positions = {str(p.id): {"ordinal": p.ordinal, "unit": p.unit, "quantity": p.quantity} for p in found}
        data = {
            "rows": [
                {
                    "id": str(r.id),
                    "member": r.member,
                    "bar_mark": r.bar_mark,
                    "diameter_mm": r.diameter_mm,
                    "lap_length_mm": r.lap_length_mm,
                    "unit_weight_kg_m": r.unit_weight_kg_m,
                    "weight_kg": r.weight_kg,
                    "boq_position_id": str(r.boq_position_id) if r.boq_position_id else None,
                }
                for r in rows
            ],
            "positions": positions,
            "lap_multiple": lap_multiple,
            "tolerance_pct": tolerance_pct,
        }
        report = await validation_engine.validate(
            data=data,
            rule_sets=[RULE_SET],
            target_type="bar_bending_schedule",
            target_id=str(project_id),
            project_id=str(project_id),
        )
        failed = [r for r in report.results if not r.passed]
        return {
            "status": "errors" if report.errors else "warnings" if report.warnings else "passed",
            "checked": len(report.results),
            "results": [
                {
                    "rule_id": r.rule_id,
                    "severity": str(r.severity),
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details,
                }
                for r in failed
            ],
        }
