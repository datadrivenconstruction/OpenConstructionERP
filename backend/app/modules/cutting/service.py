# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cutting optimisation business logic.

Jobs and their cut lists, the optimiser run, validation, and the three bridges
to other modules:

* sources: bending schedules (rebar_schedule), linear takeoff measurements,
  BOQ lines split into pieces of a known size, CSV / XLSX cut lists;
* site inventory: offcuts on hand become free stock, and a plan's reusable
  offcuts go back in (with the reused ones consumed);
* proposal / apply: the measured waste factor and stock quantity are proposed
  to the linked BOQ line and requisition item and written only on confirmation.
"""

from __future__ import annotations

import io
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.validation.engine import validation_engine
from app.modules.cutting import events as cutting_events
from app.modules.cutting.models import CuttingJob, CuttingPiece, CuttingPlan, CuttingStock
from app.modules.cutting.planning import PlanFigures, confidence, plan_job
from app.modules.cutting.repository import CuttingRepository
from app.modules.cutting.schemas import (
    ApplyLineResult,
    ApplyResponse,
    BoqImportRequest,
    InventoryOffcut,
    JobCreate,
    JobUpdate,
    LineProposal,
    PieceIn,
    PlanProposal,
    RebarImportRequest,
    ReturnOffcutsResponse,
    StockIn,
    TakeoffImportRequest,
)
from app.modules.cutting.validators import RULE_SET

logger = logging.getLogger(__name__)

_Q4 = Decimal("0.0001")
_MM = Decimal("0.1")
_STEEL_KG_PER_M_PER_MM2 = Decimal("0.0061654")  # pi / 4 * 7850 kg/m3, per mm2 of bar diameter squared
_MAX_HISTORY = 20
_OFFCUT_META = "cutting_offcut"

#: Length units a quantity or a measurement may be kept in, as millimetres per unit.
LENGTH_UNITS: dict[str, Decimal] = {
    "mm": Decimal("1"),
    "cm": Decimal("10"),
    "m": Decimal("1000"),
    "lm": Decimal("1000"),
    "m1": Decimal("1000"),
    "rm": Decimal("1000"),
    "lfm": Decimal("1000"),
    "km": Decimal("1000000"),
    "in": Decimal("25.4"),
    "ft": Decimal("304.8"),
    "lf": Decimal("304.8"),
    "yd": Decimal("914.4"),
}
#: Area units, as square metres per unit.
AREA_UNITS: dict[str, Decimal] = {
    "m2": Decimal("1"),
    "m²": Decimal("1"),
    "sqm": Decimal("1"),
    "ft2": Decimal("0.09290304"),
    "sf": Decimal("0.09290304"),
    "sqft": Decimal("0.09290304"),
}
COUNT_UNITS = frozenset({"pcs", "pc", "nr", "no", "ea", "each", "st", "stk", "stck", "pce", "u", "un", "unit", "шт"})
MASS_UNITS: dict[str, Decimal] = {
    "kg": Decimal("1"),
    "t": Decimal("1000"),
    "to": Decimal("1000"),
    "tonne": Decimal("1000"),
}


def _unit_key(unit: str | None) -> str:
    return (unit or "").strip().lower().rstrip(".").replace(" ", "")


def _dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or isinstance(value, bool):
        return default
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return default
    return number if number.is_finite() else default


def _mm(value: Decimal) -> Decimal:
    return value.quantize(_MM, rounding=ROUND_HALF_UP)


class CuttingService:
    """Orchestration over cutting jobs, plans and the bridges to other modules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CuttingRepository(session)

    # ── Jobs ──────────────────────────────────────────────────────────────

    async def get_job(self, job_id: uuid.UUID) -> CuttingJob:
        """Load a job or raise 404."""
        job = await self.repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cutting job not found")
        return job

    async def get_plan(self, plan_id: uuid.UUID) -> CuttingPlan:
        """Load a plan or raise 404."""
        plan = await self.repo.get_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cutting plan not found")
        return plan

    async def list_jobs(
        self, project_id: uuid.UUID, *, kind: str | None = None, offset: int = 0, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int]:
        """Job rows with their latest plan figures."""
        jobs, total = await self.repo.list_jobs(project_id, kind=kind, offset=offset, limit=limit)
        latest = await self.repo.latest_plans([j.id for j in jobs])
        rows = []
        for job in jobs:
            plan = latest.get(job.id)
            rows.append(
                {
                    "id": job.id,
                    "project_id": job.project_id,
                    "name": job.name,
                    "kind": job.kind,
                    "material": job.material,
                    "status": job.status,
                    "source_type": job.source_type,
                    "piece_count": sum(p.quantity for p in job.pieces),
                    "stock_count": len(job.stocks),
                    "latest_plan_id": plan.id if plan else None,
                    "latest_yield_pct": plan.yield_pct if plan else None,
                    "latest_waste_pct": plan.waste_pct if plan else None,
                    "latest_cost": plan.cost if plan else None,
                    "updated_at": job.updated_at,
                }
            )
        return rows, total

    async def create_job(self, data: JobCreate, *, user_id: str | None) -> CuttingJob:
        """Create a job with its optional pieces and stock."""
        payload = data.model_dump(exclude={"pieces", "stocks"})
        job = CuttingJob(**payload, created_by=user_id, source_type="manual")
        job.pieces = [self._piece(p, i) for i, p in enumerate(data.pieces)]
        job.stocks = [self._stock(s, i) for i, s in enumerate(data.stocks)]
        self.session.add(job)
        await self.session.flush()
        return await self.reload(job.id)

    async def update_job(self, job: CuttingJob, data: JobUpdate) -> CuttingJob:
        """Patch a job; NOT NULL columns are never nulled."""
        nullable = {"unit_mass_kg", "boq_position_id", "procurement_req_item_id", "notes"}
        for name, value in data.model_dump(exclude_unset=True).items():
            if value is None and name not in nullable:
                continue
            setattr(job, name, value)
        job.status = "draft"
        await self.session.flush()
        return await self.reload(job.id)

    async def delete_job(self, job: CuttingJob) -> None:
        """Delete a job with its pieces, stock and plans."""
        await self.session.delete(job)
        await self.session.flush()

    async def replace_pieces(self, job: CuttingJob, pieces: list[PieceIn]) -> CuttingJob:
        """Replace the job's cut list."""
        self._require_widths(job.kind, pieces=pieces)
        job.pieces = [self._piece(p, i) for i, p in enumerate(pieces)]
        job.status = "draft"
        await self.session.flush()
        return await self.reload(job.id)

    async def replace_stocks(self, job: CuttingJob, stocks: list[StockIn]) -> CuttingJob:
        """Replace the job's stock on offer."""
        self._require_widths(job.kind, stocks=stocks)
        job.stocks = [self._stock(s, i) for i, s in enumerate(stocks)]
        job.status = "draft"
        await self.session.flush()
        return await self.reload(job.id)

    async def reload(self, job_id: uuid.UUID) -> CuttingJob:
        """Re-read a job after a write so its collections reflect the database."""
        self.session.expire_all()
        return await self.get_job(job_id)

    @staticmethod
    def _piece(p: PieceIn, order: int) -> CuttingPiece:
        return CuttingPiece(**p.model_dump(), sort_order=order)

    @staticmethod
    def _stock(s: StockIn, order: int) -> CuttingStock:
        return CuttingStock(**s.model_dump(), sort_order=order)

    @staticmethod
    def _require_widths(kind: str, *, pieces: Sequence[Any] = (), stocks: Sequence[Any] = ()) -> None:
        if kind == "sheet" and (any(p.width_mm is None for p in pieces) or any(s.width_mm is None for s in stocks)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Sheet jobs need width_mm on every piece and stock entry",
            )

    # ── Validation and optimisation ───────────────────────────────────────

    async def validate(self, job: CuttingJob, plan: Any | None = None, *, locale: str | None = None) -> dict[str, Any]:
        """Run the ``cutting`` rule set over a job and, when given, a plan."""
        report = await validation_engine.validate(
            {"job": job, "plan": plan},
            rule_sets=[RULE_SET],
            target_type="cutting_job",
            target_id=str(job.id),
            project_id=str(job.project_id),
            metadata={"locale": locale} if locale else {},
        )
        return {
            "status": report.status.value,
            "score": report.score,
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "infos": len(report.infos),
            "results": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": str(r.severity),
                    "category": str(r.category),
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details,
                    "suggestion": r.suggestion,
                }
                for r in report.results
            ],
        }

    async def optimise(self, job: CuttingJob, *, user_id: str | None, locale: str | None = None) -> CuttingPlan:
        """Run the optimiser, validate the result and store it as a new plan.

        Raises:
            HTTPException 422: the job has no pieces or no stock.
        """
        if not job.pieces or not job.stocks:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Add at least one piece and one stock entry before optimising",
            )
        self._require_widths(job.kind, pieces=job.pieces, stocks=job.stocks)
        figures = plan_job(job)
        report = await self.validate(job, figures, locale=locale)
        plan = CuttingPlan(
            job_id=job.id,
            project_id=job.project_id,
            kind=figures.kind,
            algorithm=figures.algorithm,
            stock_count=figures.stock_count,
            pieces_placed=figures.pieces_placed,
            pieces_unplaced=figures.pieces_unplaced,
            stock_total=figures.stock_total,
            pieces_total=figures.pieces_total,
            offcut_total=figures.offcut_total,
            scrap_total=figures.scrap_total,
            yield_pct=figures.yield_pct,
            waste_pct=figures.waste_pct,
            cost=figures.cost,
            currency=job.currency,
            exact=figures.exact,
            proven_optimal=figures.proven_optimal,
            elapsed_ms=figures.elapsed_ms,
            layout=figures.layout,
            stock_usage=figures.stock_usage,
            offcuts=figures.offcuts,
            unplaced=figures.unplaced,
            validation=report,
            settings={**figures.settings, "waste_factor": str(figures.waste_factor)},
            created_by=user_id,
        )
        self.session.add(plan)
        job.status = "optimised"
        await self.session.flush()
        event_bus.publish_detached(
            cutting_events.PLAN_CREATED,
            data={
                "project_id": str(job.project_id),
                "job_id": str(job.id),
                "plan_id": str(plan.id),
                "yield_pct": str(plan.yield_pct),
                "waste_pct": str(plan.waste_pct),
                "user_id": user_id,
            },
            source_module="cutting",
        )
        return plan

    # ── Sources ───────────────────────────────────────────────────────────

    async def import_rebar(self, job: CuttingJob, req: RebarImportRequest) -> tuple[int, int, list[str]]:
        """Bars of one diameter from a stored bending schedule become the cut list."""
        from app.modules.rebar_schedule.models import RebarScheduleImport, RebarShape

        record = await self.session.get(RebarScheduleImport, req.import_id)
        if record is None or record.project_id != job.project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rebar schedule import not found")
        shapes = (
            (
                await self.session.execute(
                    select(RebarShape)
                    .where(RebarShape.import_id == req.import_id, RebarShape.diameter_mm == req.diameter_mm)
                    .order_by(RebarShape.line_no)
                )
            )
            .scalars()
            .all()
        )
        merged: dict[tuple[str, Decimal], int] = {}
        skipped = 0
        for shape in shapes:
            if shape.mesh_type or not shape.length_mm or not shape.quantity or shape.length_mm <= 0:
                skipped += 1
                continue
            ref = (shape.position or f"L{shape.line_no}").strip()[:48]
            key = (ref, _mm(Decimal(shape.length_mm)))
            merged[key] = merged.get(key, 0) + int(shape.quantity)
        pieces = self._unique_pieces(
            [(ref, length, qty, f"{record.filename}") for (ref, length), qty in merged.items()],
            source_prefix=f"rebar:{req.import_id}",
        )
        await self._apply_import(
            job, pieces, replace=req.replace, source_type="rebar_schedule", source_ref=str(req.import_id)
        )
        if not job.material:
            job.material = f"Ø{req.diameter_mm.normalize()}"
        if job.unit_mass_kg is None:
            job.unit_mass_kg = (_STEEL_KG_PER_M_PER_MM2 * req.diameter_mm * req.diameter_mm).quantize(_Q4)
        await self.session.flush()
        return len(pieces), skipped, []

    async def import_takeoff(self, job: CuttingJob, req: TakeoffImportRequest) -> tuple[int, int, list[str]]:
        """Linear takeoff measurements of the project become the cut list (one piece per measurement)."""
        from app.modules.takeoff.models import TakeoffMeasurement

        stmt = select(TakeoffMeasurement).where(
            TakeoffMeasurement.project_id == job.project_id,
            TakeoffMeasurement.type.in_(("distance", "polyline", "line")),
        )
        if req.group_name:
            stmt = stmt.where(TakeoffMeasurement.group_name == req.group_name)
        if req.document_id:
            stmt = stmt.where(TakeoffMeasurement.document_id == req.document_id)
        rows = (await self.session.execute(stmt.order_by(TakeoffMeasurement.created_at))).scalars().all()
        raw: list[tuple[str, Decimal, int, str]] = []
        skipped = 0
        messages: list[str] = []
        for n, row in enumerate(rows, start=1):
            factor = LENGTH_UNITS.get(_unit_key(row.measurement_unit))
            value = _dec(row.measurement_value)
            if row.is_deduction or factor is None or value <= 0:
                skipped += 1
                continue
            qty = int(row.count_value) if row.count_value and row.count_value > 0 else 1
            ref = (row.annotation or f"{row.group_name}-{n}").strip()[:48]
            raw.append((ref, _mm(value * factor), qty, row.group_name or ""))
        pieces = self._unique_pieces(raw, source_prefix="takeoff")
        await self._apply_import(
            job, pieces, replace=req.replace, source_type="takeoff", source_ref=req.group_name or req.document_id
        )
        if skipped:
            messages.append(f"skipped:{skipped}")
        return len(pieces), skipped, messages

    async def import_boq(self, job: CuttingJob, req: BoqImportRequest) -> tuple[int, int, list[str]]:
        """A BOQ line's quantity split into pieces of the given size; links the job to the line."""
        position, _boq = await self._position_in_project(req.position_id, job.project_id)
        qty = _dec(position.quantity)
        unit = _unit_key(position.unit)
        pieces: list[PieceIn] = []
        ref = (position.ordinal or "POS")[:48]
        label = (position.description or "")[:255]
        source = f"boq:{position.id}"
        if job.kind == "sheet":
            if req.piece_width_mm is None:
                raise HTTPException(status_code=422, detail="A sheet job needs piece_width_mm")
            if unit in AREA_UNITS:
                area_mm2 = qty * AREA_UNITS[unit] * Decimal("1000000")
                count = int((area_mm2 / (req.piece_length_mm * req.piece_width_mm)).to_integral_value(ROUND_CEILING))
            elif unit in COUNT_UNITS:
                count = int(qty.to_integral_value(ROUND_CEILING))
            else:
                raise HTTPException(status_code=422, detail=f"BOQ unit '{position.unit}' cannot be split into sheets")
            if count > 0:
                pieces.append(
                    PieceIn(
                        ref=ref,
                        label=label,
                        length_mm=req.piece_length_mm,
                        width_mm=req.piece_width_mm,
                        quantity=min(count, 100000),
                        source_ref=source,
                    )
                )
        else:
            if unit in LENGTH_UNITS:
                total_mm = qty * LENGTH_UNITS[unit]
                full = int((total_mm / req.piece_length_mm).to_integral_value(ROUND_FLOOR))
                rest = _mm(total_mm - full * req.piece_length_mm)
                if full > 0:
                    pieces.append(
                        PieceIn(
                            ref=ref,
                            label=label,
                            length_mm=req.piece_length_mm,
                            quantity=min(full, 100000),
                            source_ref=source,
                        )
                    )
                if rest >= Decimal("1"):
                    pieces.append(
                        PieceIn(ref=f"{ref}-R"[:64], label=label, length_mm=rest, quantity=1, source_ref=source)
                    )
            elif unit in COUNT_UNITS:
                count = int(qty.to_integral_value(ROUND_CEILING))
                if count > 0:
                    pieces.append(
                        PieceIn(
                            ref=ref,
                            label=label,
                            length_mm=req.piece_length_mm,
                            quantity=min(count, 100000),
                            source_ref=source,
                        )
                    )
            else:
                raise HTTPException(status_code=422, detail=f"BOQ unit '{position.unit}' cannot be split into lengths")
        await self._apply_import(job, pieces, replace=req.replace, source_type="boq", source_ref=str(position.id))
        job.boq_position_id = position.id
        await self.session.flush()
        return len(pieces), 0, []

    async def import_file(self, job: CuttingJob, content: bytes, filename: str) -> tuple[int, int, list[str]]:
        """A CSV or XLSX cut list (columns: ref, length, width, quantity, label, rotatable) becomes the cut list."""
        rows, skipped = parse_cut_list(content, filename, sheet=job.kind == "sheet")
        if not rows:
            raise HTTPException(status_code=422, detail="No cut list rows found in the file")
        pieces = self._unique_pieces(
            [(r["ref"], r["length_mm"], r["quantity"], r["label"]) for r in rows],
            source_prefix=f"file:{filename[:100]}",
            widths=[r.get("width_mm") for r in rows],
            rotatable=[r.get("rotatable", True) for r in rows],
        )
        await self._apply_import(job, pieces, replace=True, source_type="import", source_ref=filename[:255])
        return len(pieces), skipped, []

    @staticmethod
    def _unique_pieces(
        raw: list[tuple[str, Decimal, int, str]],
        *,
        source_prefix: str,
        widths: list[Decimal | None] | None = None,
        rotatable: list[bool] | None = None,
    ) -> list[PieceIn]:
        seen: dict[str, int] = {}
        out: list[PieceIn] = []
        for i, (ref, length, qty, label) in enumerate(raw):
            base = ref or f"P{i + 1}"
            n = seen.get(base, 0)
            seen[base] = n + 1
            unique = base if n == 0 else f"{base}.{n + 1}"
            out.append(
                PieceIn(
                    ref=unique[:64],
                    label=(label or "")[:255],
                    length_mm=length,
                    width_mm=widths[i] if widths else None,
                    quantity=max(1, min(int(qty), 100000)),
                    rotatable=rotatable[i] if rotatable else True,
                    source_ref=source_prefix[:255],
                )
            )
        return out

    async def _apply_import(
        self, job: CuttingJob, pieces: list[PieceIn], *, replace: bool, source_type: str, source_ref: str | None
    ) -> None:
        existing = [] if replace else [PieceIn.model_validate(p, from_attributes=True) for p in job.pieces]
        taken = {p.ref for p in existing}
        merged = list(existing)
        for piece in pieces:
            ref = piece.ref
            n = 1
            while ref in taken:
                n += 1
                ref = f"{piece.ref}.{n}"[:64]
            taken.add(ref)
            merged.append(piece.model_copy(update={"ref": ref}))
        if job.kind == "sheet" and any(p.width_mm is None for p in merged):
            raise HTTPException(status_code=422, detail="Sheet jobs need a width on every imported piece")
        job.pieces = [self._piece(p, i) for i, p in enumerate(merged)]
        job.source_type = source_type
        job.source_ref = (source_ref or "")[:255] or None
        job.status = "draft"
        await self.session.flush()

    async def _position_in_project(self, position_id: uuid.UUID, project_id: uuid.UUID) -> tuple[Any, Any]:
        from app.modules.boq.models import BOQ, Position

        position = await self.session.get(Position, position_id)
        boq = await self.session.get(BOQ, position.boq_id) if position is not None else None
        if position is None or boq is None or boq.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ position not found in this project")
        return position, boq

    # ── Site inventory ────────────────────────────────────────────────────

    async def inventory_offcuts(
        self, project_id: uuid.UUID, *, kind: str, material: str | None
    ) -> list[InventoryOffcut]:
        """Offcuts on hand in site inventory that a job of this kind and material can reuse."""
        from app.modules.site_inventory.service import SiteInventoryService

        inv = SiteInventoryService(self.session)
        items = await inv.list_items(project_id)
        on_hand = {row["item_id"]: _dec(row["on_hand"]) for row in (await inv.stock_on_hand(project_id))["rows"]}
        wanted = (material or "").strip().lower()
        out: list[InventoryOffcut] = []
        for item in items:
            meta = (item.metadata_ or {}).get(_OFFCUT_META)
            if not isinstance(meta, dict) or meta.get("kind") != kind or not item.is_active:
                continue
            if wanted and str(meta.get("material") or "").strip().lower() != wanted:
                continue
            count = int(on_hand.get(str(item.id), Decimal("0")).to_integral_value(ROUND_FLOOR))
            length = _dec(meta.get("length_mm"))
            if count <= 0 or length <= 0:
                continue
            width = _dec(meta.get("width_mm")) if meta.get("width_mm") else None
            out.append(
                InventoryOffcut(
                    inventory_item_id=item.id,
                    name=item.name,
                    material=str(meta.get("material") or ""),
                    kind=kind,
                    length_mm=length,
                    width_mm=width,
                    on_hand=count,
                )
            )
        out.sort(key=lambda o: (-o.length_mm, str(o.inventory_item_id)))
        return out

    async def add_inventory_stock(self, job: CuttingJob, item_ids: list[uuid.UUID]) -> CuttingJob:
        """Add inventory offcuts to the job's stock as free entries limited to what is on hand."""
        offcuts = {
            o.inventory_item_id: o for o in await self.inventory_offcuts(job.project_id, kind=job.kind, material=None)
        }
        current = [StockIn.model_validate(s, from_attributes=True) for s in job.stocks]
        known = {s.inventory_item_id for s in current if s.inventory_item_id}
        taken = {s.ref for s in current}
        for item_id in item_ids:
            offcut = offcuts.get(item_id)
            if offcut is None:
                raise HTTPException(status_code=404, detail="Inventory offcut not found or not on hand")
            if item_id in known:
                continue
            ref = f"INV-{len(taken) + 1}"
            while ref in taken:
                ref = f"{ref}x"
            taken.add(ref)
            current.append(
                StockIn(
                    ref=ref,
                    label=offcut.name[:255],
                    length_mm=offcut.length_mm,
                    width_mm=offcut.width_mm,
                    unit_cost=Decimal("0"),
                    available=offcut.on_hand,
                    is_offcut=True,
                    inventory_item_id=item_id,
                )
            )
        return await self.replace_stocks(job, current)

    async def return_offcuts(
        self, job: CuttingJob, plan: CuttingPlan, *, location_id: uuid.UUID | None, user_id: str | None
    ) -> ReturnOffcutsResponse:
        """Book the plan against site inventory once: reused offcuts consumed, new offcuts received.

        Raises:
            HTTPException 409: the plan was already booked.
        """
        from app.modules.site_inventory.schemas import MovementCreate, StockItemCreate
        from app.modules.site_inventory.service import SiteInventoryService

        if plan.inventory_synced_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Offcuts of this plan were already booked")
        inv = SiteInventoryService(self.session)
        note = f"Cutting plan {plan.id} ({job.name})"[:2000]
        consumed = 0
        for usage in plan.stock_usage or []:
            item_id = usage.get("inventory_item_id")
            if not usage.get("is_offcut") or not item_id:
                continue
            await inv.record_movement(
                job.project_id,
                MovementCreate(
                    item_id=uuid.UUID(item_id),
                    movement_type="CONSUMPTION",
                    quantity=str(usage["count"]),
                    location_id=location_id,
                    boq_position_id=job.boq_position_id,
                    note=note,
                    metadata={"cutting_plan_id": str(plan.id)},
                ),
                user_id,
            )
            consumed += int(usage["count"])
        existing = {}
        for item in await inv.list_items(job.project_id):
            meta = (item.metadata_ or {}).get(_OFFCUT_META)
            if isinstance(meta, dict):
                existing[self._offcut_key(meta)] = item
        returned = 0
        item_ids: list[uuid.UUID] = []
        for offcut in plan.offcuts or []:
            meta = {
                "material": job.material,
                "kind": job.kind,
                "length_mm": str(offcut["length_mm"]),
                "width_mm": str(offcut["width_mm"]) if offcut.get("width_mm") else None,
            }
            item = existing.get(self._offcut_key(meta))
            if item is None:
                size = meta["length_mm"] if not meta["width_mm"] else f"{meta['length_mm']} x {meta['width_mm']}"
                item = await inv.create_item(
                    job.project_id,
                    StockItemCreate(
                        name=f"{job.material or job.name} {size} mm"[:255],
                        unit="pcs",
                        default_location_id=location_id,
                        currency=job.currency,
                        metadata={_OFFCUT_META: meta},
                    ),
                )
                existing[self._offcut_key(meta)] = item
            await inv.record_movement(
                job.project_id,
                MovementCreate(
                    item_id=item.id,
                    movement_type="INBOUND",
                    quantity=str(offcut["quantity"]),
                    location_id=location_id,
                    note=note,
                    metadata={"cutting_plan_id": str(plan.id)},
                ),
                user_id,
            )
            returned += int(offcut["quantity"])
            item_ids.append(item.id)
        plan.inventory_synced_at = datetime.now(UTC)
        await self.session.flush()
        event_bus.publish_detached(
            cutting_events.OFFCUTS_RETURNED,
            data={
                "project_id": str(job.project_id),
                "job_id": str(job.id),
                "plan_id": str(plan.id),
                "returned": returned,
                "consumed": consumed,
                "user_id": user_id,
            },
            source_module="cutting",
        )
        return ReturnOffcutsResponse(plan_id=plan.id, returned=returned, consumed=consumed, item_ids=item_ids)

    @staticmethod
    def _offcut_key(meta: dict[str, Any]) -> tuple[str, str, str, str]:
        width = meta.get("width_mm")
        return (
            str(meta.get("material") or "").strip().lower(),
            str(meta.get("kind") or ""),
            str(_dec(meta.get("length_mm")).normalize()),
            str(_dec(width).normalize()) if width else "",
        )

    # ── Proposal and apply ────────────────────────────────────────────────

    def _purchased(self, plan: CuttingPlan) -> tuple[int, Decimal]:
        """Purchased (non-inventory) stock: piece count and total in m or m2."""
        count = 0
        total = Decimal("0")
        for usage in plan.stock_usage or []:
            if usage.get("is_offcut"):
                continue
            n = int(usage["count"])
            count += n
            if plan.kind == "sheet":
                total += _dec(usage["length_mm"]) * _dec(usage.get("width_mm")) * n / Decimal("1000000")
            else:
                total += _dec(usage["length_mm"]) * n / Decimal("1000")
        return count, total.quantize(_Q4)

    def _quantity_for(
        self, job: CuttingJob, plan: CuttingPlan, unit: str | None, *, purchase: bool
    ) -> tuple[Decimal | None, str]:
        """The plan's quantity in a target line's unit: (quantity or None, basis or refusal reason)."""
        key = _unit_key(unit)
        purchased_count, purchased_total = self._purchased(plan)
        consumed = _dec(plan.pieces_total) + _dec(plan.scrap_total)
        base = purchased_total if purchase else consumed
        if key in COUNT_UNITS:
            return Decimal(purchased_count), "stock_count"
        if plan.kind == "linear" and key in LENGTH_UNITS:
            return (base * Decimal("1000") / LENGTH_UNITS[key]).quantize(_Q4), "length"
        if plan.kind == "sheet" and key in AREA_UNITS:
            return (base / AREA_UNITS[key]).quantize(_Q4), "area"
        if key in MASS_UNITS:
            if job.unit_mass_kg is None:
                return None, "unit_mass_missing"
            return (base * _dec(job.unit_mass_kg) / MASS_UNITS[key]).quantize(_Q4), "mass"
        return None, "unit_not_convertible"

    async def proposal(self, job: CuttingJob, plan: CuttingPlan) -> PlanProposal:
        """What applying the plan would write to the linked lines; nothing is written."""
        figures = PlanFigures(
            kind=plan.kind,
            algorithm=plan.algorithm,
            pieces_unplaced=plan.pieces_unplaced,
            pieces_total=_dec(plan.pieces_total),
            scrap_total=_dec(plan.scrap_total),
            yield_pct=_dec(plan.yield_pct),
            proven_optimal=plan.proven_optimal,
        )
        lines: list[LineProposal] = []
        if job.boq_position_id:
            lines.append(await self._boq_line(job, plan))
        if job.procurement_req_item_id:
            line = await self._req_line(job, plan)
            if line is not None:
                lines.append(line)
        return PlanProposal(
            plan_id=plan.id,
            waste_factor=figures.waste_factor,
            waste_pct=plan.waste_pct,
            yield_pct=plan.yield_pct,
            confidence=confidence(figures, _dec(job.yield_threshold_pct)),
            lines=lines,
        )

    async def _boq_line(self, job: CuttingJob, plan: CuttingPlan) -> LineProposal:
        from app.modules.boq.models import BOQ, Position

        position = await self.session.get(Position, job.boq_position_id)
        boq = await self.session.get(BOQ, position.boq_id) if position is not None else None
        if position is None or boq is None or boq.project_id != job.project_id:
            return LineProposal(
                target="boq_position",
                target_id=job.boq_position_id,
                label="",
                unit="",
                current_quantity=Decimal("0"),
                proposed_quantity=Decimal("0"),
                basis="",
                appliable=False,
                reason="not_found",
            )
        qty, basis = self._quantity_for(job, plan, position.unit, purchase=False)
        reason = None if qty is not None else basis
        if qty is not None and boq.is_locked:
            reason = "boq_locked"
        if qty is not None and plan.pieces_unplaced:
            reason = "pieces_unplaced"
        return LineProposal(
            target="boq_position",
            target_id=position.id,
            label=f"{position.ordinal} {position.description or ''}".strip()[:300],
            unit=position.unit or "",
            current_quantity=_dec(position.quantity),
            proposed_quantity=qty if qty is not None else Decimal("0"),
            basis=basis if qty is not None else "",
            appliable=reason is None,
            reason=reason,
        )

    async def _req_line(self, job: CuttingJob, plan: CuttingPlan) -> LineProposal | None:
        from app.modules.procurement.models import MaterialRequisition, MaterialRequisitionItem

        item = await self.session.get(MaterialRequisitionItem, job.procurement_req_item_id)
        req = await self.session.get(MaterialRequisition, item.requisition_id) if item is not None else None
        if item is None or req is None or req.project_id != job.project_id:
            return LineProposal(
                target="requisition_item",
                target_id=job.procurement_req_item_id,
                label="",
                unit="",
                current_quantity=Decimal("0"),
                proposed_quantity=Decimal("0"),
                basis="",
                appliable=False,
                reason="not_found",
            )
        qty, basis = self._quantity_for(job, plan, item.unit, purchase=True)
        reason = None if qty is not None else basis
        if qty is not None and req.status != "draft":
            reason = "requisition_not_draft"
        if qty is not None and plan.pieces_unplaced:
            reason = "pieces_unplaced"
        return LineProposal(
            target="requisition_item",
            target_id=item.id,
            label=f"{req.req_number or ''} {item.description}".strip()[:300],
            unit=item.unit or "",
            current_quantity=_dec(item.quantity_requested),
            proposed_quantity=qty if qty is not None else Decimal("0"),
            basis=basis if qty is not None else "",
            appliable=reason is None,
            reason=reason,
        )

    async def apply(
        self, job: CuttingJob, plan: CuttingPlan, *, apply_boq: bool, apply_procurement: bool, user_id: str | None
    ) -> ApplyResponse:
        """Write the confirmed proposal. Every figure is recomputed here, not taken from the client."""
        from app.modules.boq.models import Position
        from app.modules.boq.repository import PositionRepository
        from app.modules.boq.service import _compute_total, _quantize_money_str
        from app.modules.procurement.models import MaterialRequisitionItem

        proposal = await self.proposal(job, plan)
        now = datetime.now(UTC)
        results: list[ApplyLineResult] = []
        for line in proposal.lines:
            wanted = apply_boq if line.target == "boq_position" else apply_procurement
            if not wanted:
                continue
            if not line.appliable:
                results.append(
                    ApplyLineResult(target=line.target, target_id=line.target_id, applied=False, reason=line.reason)
                )
                continue
            provenance = {
                "plan_id": str(plan.id),
                "job_id": str(job.id),
                "waste_factor": str(proposal.waste_factor),
                "waste_pct": str(plan.waste_pct),
                "yield_pct": str(plan.yield_pct),
                "confidence": proposal.confidence,
                "basis": line.basis,
                "old_quantity": str(line.current_quantity),
                "new_quantity": str(line.proposed_quantity),
                "applied_at": now.isoformat(),
                "applied_by": user_id,
            }
            if line.target == "boq_position":
                position = await self.session.get(Position, line.target_id)
                assert position is not None  # the proposal just read it
                new_qty = _quantize_money_str(line.proposed_quantity)
                meta = dict(position.metadata_ or {})
                history = list(meta.get("cutting_update_history") or [])
                history.append(provenance)
                meta["cutting_update"] = provenance
                meta["cutting_update_history"] = history[-_MAX_HISTORY:]
                await PositionRepository(self.session).update_fields(
                    position.id,
                    quantity=new_qty,
                    total=_compute_total(new_qty, position.unit_rate),
                    metadata_=meta,
                    version=Position.version + 1,
                )
            else:
                item = await self.session.get(MaterialRequisitionItem, line.target_id)
                assert item is not None  # the proposal just read it
                item.quantity_requested = str(line.proposed_quantity)
                if item.unit_cost:
                    item.extended_cost = (Decimal(item.unit_cost) * line.proposed_quantity).quantize(_Q4)
            results.append(
                ApplyLineResult(
                    target=line.target,
                    target_id=line.target_id,
                    applied=True,
                    old_quantity=line.current_quantity,
                    new_quantity=line.proposed_quantity,
                )
            )
        if any(r.applied for r in results):
            plan.applied_at = now
            job.status = "applied"
        await self.session.flush()
        if any(r.applied for r in results):
            event_bus.publish_detached(
                cutting_events.PLAN_APPLIED,
                data={
                    "project_id": str(job.project_id),
                    "job_id": str(job.id),
                    "plan_id": str(plan.id),
                    "targets": [str(r.target_id) for r in results if r.applied],
                    "user_id": user_id,
                },
                source_module="cutting",
            )
        return ApplyResponse(plan_id=plan.id, results=results)


# ── Cut-list file parsing ─────────────────────────────────────────────────

_HEADER_ROLES: dict[str, tuple[str, ...]] = {
    "ref": ("ref", "mark", "pos", "position", "id", "code", "item"),
    "length": ("length", "length mm", "l", "len", "cut length", "length (mm)"),
    "width": ("width", "width mm", "w", "breadth", "height", "width (mm)"),
    "quantity": ("quantity", "qty", "count", "pcs", "n", "number", "amount"),
    "label": ("label", "description", "name", "text"),
    "rotatable": ("rotatable", "rotate", "rotation"),
    "grain": ("grain", "grain locked", "grain direction"),
}
_TRUE = frozenset({"1", "yes", "y", "true", "x", "ja", "да", "oui", "si", "sí", "evet"})
_MAX_ROWS = 5000


def parse_cut_list(content: bytes, filename: str, *, sheet: bool) -> tuple[list[dict[str, Any]], int]:
    """Rows of a CSV or XLSX cut list, through the shared tabular reader.

    The first row whose cells name a length column is the header. Lengths are
    millimetres. Returns (rows, skipped row count).
    """
    from app.core.upload_guards import reject_if_xlsx_bomb
    from app.modules.costs.pricelists.containers import Member
    from app.modules.costs.pricelists.tabular import iter_tables, normalise_header

    reject_if_xlsx_bomb(content)
    name = filename if filename.lower().endswith((".csv", ".txt", ".xlsx")) else f"{filename}.csv"
    member = Member(name=name, size=len(content), opener=lambda: io.BytesIO(content))
    out: list[dict[str, Any]] = []
    skipped = 0
    aliases = {role: {normalise_header(a) for a in names} for role, names in _HEADER_ROLES.items()}
    for _title, rows in iter_tables(member):
        index: dict[str, int] | None = None
        for row in rows:
            cells = [("" if c is None else str(c)).strip() for c in row]
            if index is None:
                found = {}
                for i, cell in enumerate(cells):
                    norm = normalise_header(cell)
                    for role, names in aliases.items():
                        if norm in names and role not in found:
                            found[role] = i
                if "length" in found:
                    index = found
                continue
            if not any(cells):
                continue

            def cell(role: str, cells: list[str] = cells, index: dict[str, int] = index) -> str:
                i = index.get(role)
                return cells[i] if i is not None and i < len(cells) else ""

            length = _dec(cell("length").replace(",", "."))
            width = _dec(cell("width").replace(",", ".")) if "width" in index else None
            qty_raw = _dec(cell("quantity").replace(",", "."), Decimal("1")) if "quantity" in index else Decimal("1")
            if length <= 0 or qty_raw <= 0 or (sheet and (width is None or width <= 0)):
                skipped += 1
                continue
            rotatable = True
            if "rotatable" in index:
                rotatable = cell("rotatable").lower() in _TRUE
            elif "grain" in index:
                rotatable = cell("grain").lower() not in _TRUE
            out.append(
                {
                    "ref": cell("ref")[:48] or f"P{len(out) + 1}",
                    "label": cell("label")[:255],
                    "length_mm": _mm(length),
                    "width_mm": _mm(width) if sheet and width else None,
                    "quantity": int(qty_raw.to_integral_value(ROUND_CEILING)),
                    "rotatable": rotatable,
                }
            )
            if len(out) >= _MAX_ROWS:
                return out, skipped
        if out:
            break
    return out, skipped


__all__ = ["COUNT_UNITS", "LENGTH_UNITS", "CuttingService", "parse_cut_list"]
