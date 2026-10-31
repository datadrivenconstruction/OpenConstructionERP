# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book service: entries, check-measurement, positions, running bill."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.measurement_book.models import MeasurementBookEntry
from app.modules.measurement_book.repository import MeasurementBookRepository
from app.modules.measurement_book.schemas import EntryCheck, EntryCreate, EntryUpdate

ZERO = Decimal("0")
HUNDRED = Decimal("100")
QTY = Decimal("0.0001")
MONEY = Decimal("0.01")

#: Default threshold for the check-measure deviation rule, in percent of the measured quantity.
DEFAULT_DEVIATION_PCT = Decimal("5")

_TEXT_FIELDS = {"location", "description", "measured_by"}


def to_dec(value: Any) -> Decimal:
    """Read a BOQ string or a number as Decimal; anything unreadable is zero."""
    try:
        return Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError):
        return ZERO


def compute_quantity(
    *,
    length: Decimal | None,
    breadth: Decimal | None,
    height: Decimal | None,
    number: Decimal | None,
    direct_quantity: Decimal | None,
) -> Decimal:
    """Quantity of one measurement line: the direct quantity, or No x L x B x H.

    A missing dimension counts as 1, so a length-only line gives running metres
    and a count-only line gives numbers. A line with neither is refused.
    """
    if direct_quantity is not None:
        return Decimal(direct_quantity).quantize(QTY)
    dims = [length, breadth, height]
    if all(d is None for d in dims) and number is None:
        raise ValueError("Give at least one dimension, a number, or a direct quantity")
    qty = Decimal(number) if number is not None else Decimal("1")
    for d in dims:
        if d is not None:
            qty *= Decimal(d)
    return qty.quantize(QTY)


def accepted_quantity(entry: Any) -> Decimal:
    """The quantity a checked entry contributes: the checker's figure when given."""
    return entry.check_quantity if entry.check_quantity is not None else entry.quantity


def summarize(positions: list[Any], entries: list[Any]) -> list[dict[str, Any]]:
    """Cumulative measured and checked quantities per position, in bill order."""
    by_pos: dict[uuid.UUID, list[Any]] = {}
    for e in entries:
        by_pos.setdefault(e.boq_position_id, []).append(e)
    out = []
    for p in positions:
        rows = by_pos.get(p.id, [])
        boq_qty = to_dec(p.quantity)
        rate = to_dec(p.unit_rate)
        measured = sum((Decimal(e.quantity) for e in rows), ZERO)
        checked = sum((Decimal(accepted_quantity(e)) for e in rows if e.check_status == "checked"), ZERO)
        pct = (measured / boq_qty * HUNDRED).quantize(MONEY) if boq_qty > 0 else ZERO
        out.append(
            {
                "boq_position_id": p.id,
                "ordinal": p.ordinal or "",
                "description": p.description or "",
                "unit": p.unit or "",
                "boq_quantity": boq_qty,
                "unit_rate": rate,
                "measured_quantity": measured,
                "checked_quantity": checked,
                "entry_count": len(rows),
                "unchecked_count": sum(1 for e in rows if e.check_status != "checked"),
                "percent_measured": pct,
                "value_to_date": (checked * rate).quantize(MONEY),
            }
        )
    return out


class MeasurementBookService:
    """Entries, check-measurement and the running bill of one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MeasurementBookRepository(session)

    async def entry(self, entry_id: uuid.UUID) -> MeasurementBookEntry:
        row = await self.repo.get(entry_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Measurement entry not found")
        return row

    @staticmethod
    def _quantity(row: MeasurementBookEntry) -> None:
        try:
            row.quantity = compute_quantity(
                length=row.length,
                breadth=row.breadth,
                height=row.height,
                number=row.number,
                direct_quantity=row.direct_quantity,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    async def create(self, data: EntryCreate, actor: str | None) -> MeasurementBookEntry:
        """Write one measurement of a position that belongs to the project."""
        if await self.repo.position_project(data.boq_position_id) != data.project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="BOQ position is not in this project")
        row = MeasurementBookEntry(**data.model_dump(exclude_none=True), created_by=actor)
        self._quantity(row)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, row: MeasurementBookEntry, data: EntryUpdate) -> MeasurementBookEntry:
        """Edit an entry that is not checked yet; the quantity is recomputed."""
        if row.check_status == "checked":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="A checked measurement is part of the record; set it back to unchecked first",
            )
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, "" if value is None and key in _TEXT_FIELDS else value)
        self._quantity(row)
        await self.session.flush()
        return row

    async def delete(self, row: MeasurementBookEntry) -> None:
        """Delete an entry that is not checked."""
        if row.check_status == "checked":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="A checked measurement cannot be deleted")
        await self.session.delete(row)
        await self.session.flush()

    async def check(self, row: MeasurementBookEntry, data: EntryCheck, actor: str | None) -> MeasurementBookEntry:
        """Record the check-measurement: checked, disputed, or back to unchecked."""
        row.check_status = data.status
        if data.status == "unchecked":
            row.check_quantity = None
            row.checked_by = None
            row.checked_at = None
        else:
            row.check_quantity = data.check_quantity.quantize(QTY) if data.check_quantity is not None else None
            row.checked_by = data.checked_by or actor
            row.checked_at = datetime.now(UTC)
        await self.session.flush()
        return row

    async def positions(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every measurable position of the project with its cumulative quantities."""
        return summarize(await self.repo.project_positions(project_id), await self.repo.entries(project_id))

    async def running_bill(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Positions with measurements, valued on checked quantities at the BOQ rate."""
        from app.modules.projects.models import Project  # noqa: PLC0415

        project = await self.session.get(Project, project_id)
        lines = [ln for ln in await self.positions(project_id) if ln["entry_count"]]
        unchecked = sum(ln["unchecked_count"] for ln in lines)
        return {
            "project_id": project_id,
            "currency": (getattr(project, "currency", None) or "") if project else "",
            "lines": lines,
            "total_value": sum((ln["value_to_date"] for ln in lines), ZERO),
            "unchecked_count": unchecked,
            "can_certify": unchecked == 0,
        }

    async def post_to_progress(self, project_id: uuid.UUID, period_label: str, actor: str | None) -> dict[str, int]:
        """Record the checked quantity to date as a progress observation per position.

        Refused while any entry is unchecked or disputed: an interim payment is
        certified on checked measurements only. A progress claim then reads these
        observations through its existing populate-from-progress flow.
        """
        from app.modules.progress.schemas import ProgressEntryCreate  # noqa: PLC0415
        from app.modules.progress.service import ProgressService  # noqa: PLC0415

        bill = await self.running_bill(project_id)
        if not bill["can_certify"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"{bill['unchecked_count']} measurement(s) are not checked yet; check them before billing",
            )
        progress = ProgressService(self.session)
        recorded = skipped = 0
        for ln in bill["lines"]:
            if ln["boq_quantity"] <= 0:
                skipped += 1
                continue
            pct = min(HUNDRED, ln["checked_quantity"] / ln["boq_quantity"] * HUNDRED).quantize(Decimal("0.001"))
            await progress.record_entry(
                ProgressEntryCreate(
                    project_id=project_id,
                    boq_position_id=ln["boq_position_id"],
                    period_label=period_label,
                    percent_complete=float(pct),
                    notes=f"Measurement book: {ln['checked_quantity']} {ln['unit']} checked to date",
                    metadata={"source": "measurement_book", "checked_quantity": str(ln["checked_quantity"])},
                ),
                user_id=actor,
            )
            recorded += 1
        return {"recorded": recorded, "skipped": skipped}

    async def validate(
        self, project_id: uuid.UUID, deviation_threshold_pct: Decimal = DEFAULT_DEVIATION_PCT
    ) -> dict[str, Any]:
        """Run the measurement_book rule set; failed results only."""
        from app.core.validation.engine import validation_engine  # noqa: PLC0415
        from app.modules.measurement_book.validators import RULE_SET  # noqa: PLC0415

        data = {
            "positions": await self.positions(project_id),
            "entries": [
                {
                    "id": str(e.id),
                    "boq_position_id": str(e.boq_position_id),
                    "entry_date": e.entry_date.isoformat(),
                    "quantity": e.quantity,
                    "check_status": e.check_status,
                    "check_quantity": e.check_quantity,
                }
                for e in await self.repo.entries(project_id)
            ],
            "deviation_threshold_pct": deviation_threshold_pct,
        }
        report = await validation_engine.validate(
            data=data,
            rule_sets=[RULE_SET],
            target_type="measurement_book",
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
