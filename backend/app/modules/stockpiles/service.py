# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile business logic.

The computer suggests, a person confirms: a survey yields volume, tonnes and a
variance against the book; a variance can become an adjustment proposal, and
only confirming that proposal (``survey.confirm``) writes a movement to the
site inventory and moves the book stock. A booked survey is locked.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.stockpiles import calc
from app.modules.stockpiles.models import Stockpile, StockpileAdjustment, StockpileSurvey
from app.modules.stockpiles.repository import StockpileRepository
from app.modules.stockpiles.schemas import (
    AdjustmentConfirm,
    AdjustmentOut,
    Finding,
    StockpileCreate,
    StockpileDetail,
    StockpileOut,
    StockpileSummary,
    StockpileUpdate,
    SurveyCreate,
    SurveyOut,
    SurveyUpdate,
)
from app.modules.stockpiles.validators import STOCKPILE_RULE_SET
from app.modules.surfaces_volumes.service import VolumesService, tin_of

logger = logging.getLogger(__name__)

UNIT = "t"


def _err(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _bad(detail: str) -> HTTPException:
    return _err(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _q(value: float | Decimal | None, places: str) -> Decimal | None:
    return None if value is None else calc.dec(value).quantize(Decimal(places), ROUND_HALF_UP)


def _next_code(codes: list[str]) -> str:
    top = 0
    for c in codes:
        tail = c[3:] if c.startswith("SP-") else ""
        if tail.isdigit():
            top = max(top, int(tail))
    return f"SP-{top + 1:03d}"


class StockpileService:
    """Stateless operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StockpileRepository(session)
        self.volumes = VolumesService(session)

    async def _audit(self, action: str, entity_type: str, entity_id: uuid.UUID, user_id: str, details: dict) -> None:
        try:
            from app.core.audit import audit_log  # noqa: PLC0415

            uid = _uuid(user_id)
            await audit_log(
                self.session,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                user_id=str(uid) if uid else None,
                details=details,
            )
        except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
            logger.exception("stockpiles: audit entry for %s failed", entity_id)

    # ── Surfaces from a point file ─────────────────────────────────────────

    async def _surface_from_text(
        self, project_id: uuid.UUID, text: str, filename: str, name: str, user_id: str
    ) -> uuid.UUID:
        from app.modules.surfaces_volumes.schemas import SurfaceFromPoints  # noqa: PLC0415
        from app.modules.survey_core.schemas import ImportRequest  # noqa: PLC0415
        from app.modules.survey_core.service import SurveyService  # noqa: PLC0415

        imported = await SurveyService(self.session).import_points(
            project_id,
            ImportRequest(
                text=text, filename=filename, column_preset="PNEZD", default_kind="topo", name=name[:255] or filename
            ),
            user_id,
        )
        surface = await self.volumes.surface_from_points(
            project_id, SurfaceFromPoints(name=name[:255] or filename, point_set_ids=[imported.point_set.id]), user_id
        )
        return surface.id

    async def _own_surface(self, project_id: uuid.UUID, surface_id: uuid.UUID):
        surface = await self.volumes.get_surface(surface_id)
        if surface.project_id != project_id:
            raise _err(status.HTTP_404_NOT_FOUND, "Surface not found")
        return surface

    # ── Findings and output ────────────────────────────────────────────────

    async def findings(self, s: StockpileSurvey, p: Stockpile, locale: str = "en") -> list[Finding]:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        report = await validation_engine.validate(
            data={
                "survey": {
                    "code": p.code,
                    "density_source": s.density_source,
                    "variance_pct": _f(s.variance_pct),
                    "tolerance_pct": _f(p.variance_tolerance_pct),
                }
            },
            rule_sets=[STOCKPILE_RULE_SET],
            target_type="stockpile_survey",
            target_id=str(s.id),
            project_id=str(s.project_id),
            metadata={"locale": locale},
        )
        return [
            Finding(
                rule_id=r.rule_id,
                severity=str(getattr(r.severity, "value", r.severity)),
                message=r.message,
                suggestion=r.suggestion,
                element_ref=r.element_ref,
            )
            for r in report.results
            if not r.passed
        ]

    async def _survey_out(
        self, s: StockpileSurvey, p: Stockpile, adj: StockpileAdjustment | None, locale: str
    ) -> SurveyOut:
        return SurveyOut(
            id=s.id,
            stockpile_id=s.stockpile_id,
            surveyed_on=s.surveyed_on,
            source_kind=s.source_kind,
            pile_surface_id=s.pile_surface_id,
            pile_name=s.pile_name,
            volume_m3=float(s.volume_m3),
            cell_size_m=_f(s.cell_size_m),
            coverage_pct=_f(s.coverage_pct),
            crs_epsg=s.crs_epsg,
            density_t_m3=float(s.density_t_m3),
            density_source=s.density_source,
            tonnes=float(s.tonnes),
            book_tonnes=_f(s.book_tonnes),
            variance_t=_f(s.variance_t),
            variance_pct=_f(s.variance_pct),
            status=s.status,
            note=s.note,
            findings=await self.findings(s, p, locale),
            adjustment=AdjustmentOut.model_validate(adj) if adj is not None else None,
            created_at=s.created_at,
        )

    def _out(self, p: Stockpile, surveys: list[SurveyOut]) -> dict[str, Any]:
        return {
            "id": p.id,
            "project_id": p.project_id,
            "code": p.code,
            "name": p.name,
            "material": p.material,
            "location_note": p.location_note,
            "base_surface_id": p.base_surface_id,
            "base_name": p.base_name,
            "site_inventory_item_id": p.site_inventory_item_id,
            "book_tonnes": _f(p.book_tonnes),
            "variance_tolerance_pct": _f(p.variance_tolerance_pct),
            "note": p.note,
            "survey_count": len(surveys),
            "last_survey": surveys[0] if surveys else None,
            "created_at": p.created_at,
        }

    async def _surveys_out(self, p: Stockpile, locale: str) -> list[SurveyOut]:
        rows = await self.repo.surveys_of(p.id)
        adj = await self.repo.adjustments_of([r.id for r in rows])
        return [await self._survey_out(r, p, adj.get(r.id), locale) for r in rows]

    async def list_stockpiles(self, project_id: uuid.UUID, locale: str = "en") -> list[StockpileOut]:
        out = []
        for p in await self.repo.list_stockpiles(project_id):
            out.append(StockpileOut(**self._out(p, await self._surveys_out(p, locale))))
        return out

    async def get_stockpile(self, stockpile_id: uuid.UUID) -> Stockpile:
        p = await self.repo.get_stockpile(stockpile_id)
        if p is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Stockpile not found")
        return p

    async def get_survey(self, survey_id: uuid.UUID) -> StockpileSurvey:
        s = await self.repo.get_survey(survey_id)
        if s is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Survey not found")
        return s

    async def detail(self, p: Stockpile, locale: str = "en") -> StockpileDetail:
        surveys = await self._surveys_out(p, locale)
        return StockpileDetail(**self._out(p, surveys), surveys=surveys)

    # ── Stockpiles ─────────────────────────────────────────────────────────

    async def create_stockpile(self, project_id: uuid.UUID, data: StockpileCreate, user_id: str) -> StockpileDetail:
        base_id = data.base_surface_id
        if base_id is not None and data.base_text.strip():
            raise _bad("Give a base surface or a point file, not both")
        if base_id is None and data.base_text.strip():
            base_id = await self._surface_from_text(
                project_id, data.base_text, data.base_filename, f"{data.name} base", user_id
            )
        base_name = ""
        if base_id is not None:
            base_name = (await self._own_surface(project_id, base_id)).name
        p = Stockpile(
            project_id=project_id,
            code=_next_code(await self.repo.codes(project_id)),
            name=data.name.strip(),
            material=data.material.strip(),
            location_note=data.location_note.strip(),
            base_surface_id=base_id,
            base_name=base_name,
            site_inventory_item_id=data.site_inventory_item_id,
            book_tonnes=_q(data.book_tonnes, "0.001"),
            variance_tolerance_pct=_q(data.variance_tolerance_pct, "0.01"),
            note=data.note,
            created_by=_uuid(user_id),
        )
        await self.repo.add(p)
        await self._audit("create", "stockpile", p.id, user_id, {"code": p.code, "project_id": str(project_id)})
        return await self.detail(p)

    async def update_stockpile(self, p: Stockpile, data: StockpileUpdate, user_id: str) -> StockpileDetail:
        fields = data.model_fields_set
        for key in ("name", "material", "location_note", "note"):
            if key in fields and getattr(data, key) is not None:
                setattr(p, key, getattr(data, key).strip() if key != "note" else data.note)
        if "base_surface_id" in fields:
            p.base_surface_id = data.base_surface_id
            p.base_name = (
                (await self._own_surface(p.project_id, data.base_surface_id)).name if data.base_surface_id else ""
            )
        if "variance_tolerance_pct" in fields:
            p.variance_tolerance_pct = _q(data.variance_tolerance_pct, "0.01")
        if "site_inventory_item_id" in fields:
            p.site_inventory_item_id = data.site_inventory_item_id
        book_changed = "book_tonnes" in fields
        if book_changed:
            p.book_tonnes = _q(data.book_tonnes, "0.001")
        await self.session.flush()
        for s in await self.repo.surveys_of(p.id):
            if s.status == "open" and (book_changed or "base_surface_id" in fields):
                await self._recompute(s, p)
        await self._audit("update", "stockpile", p.id, user_id, {"code": p.code, "fields": sorted(fields)})
        return await self.detail(p)

    async def delete_stockpile(self, p: Stockpile, user_id: str) -> None:
        if any(s.status == "booked" for s in await self.repo.surveys_of(p.id)):
            raise _err(status.HTTP_409_CONFLICT, "A survey of this stockpile is booked in the inventory")
        await self._audit("delete", "stockpile", p.id, user_id, {"code": p.code, "project_id": str(p.project_id)})
        await self.repo.delete(p)

    # ── Surveys ────────────────────────────────────────────────────────────

    async def _measure(self, s: StockpileSurvey, p: Stockpile) -> None:
        """Volume, cell size, coverage and CRS from the pile surface (typed volumes are kept as given)."""
        if s.source_kind != "surface":
            s.cell_size_m = s.coverage_pct = s.crs_epsg = None  # type: ignore[assignment]
            return
        if p.base_surface_id is None:
            raise _bad("The stockpile has no base surface: add one before a surface survey")
        if s.pile_surface_id is None:
            raise _bad("The pile surface of this survey was deleted: choose another")
        if s.pile_surface_id == p.base_surface_id:
            raise _bad("The pile and the base must be two different surfaces")
        base = await self._own_surface(p.project_id, p.base_surface_id)
        pile = await self._own_surface(p.project_id, s.pile_surface_id)
        if base.epsg and pile.epsg and base.epsg != pile.epsg:
            raise _bad(f"The surfaces are in EPSG {base.epsg} and EPSG {pile.epsg}")
        try:
            r = calc.pile_volume(tin_of(pile), tin_of(base), _f(s.cell_size_m))
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        s.pile_name = pile.name
        s.volume_m3 = _q(r.cut, "0.001")  # type: ignore[assignment]
        s.cell_size_m = _q(r.cell_size, "0.001") if r.cell_size else None
        s.coverage_pct = _q(r.coverage_pct, "0.01")
        s.crs_epsg = pile.epsg or base.epsg

    def _figures(self, s: StockpileSurvey, p: Stockpile) -> None:
        s.tonnes = calc.tonnes(s.volume_m3, s.density_t_m3)  # type: ignore[assignment]
        s.book_tonnes = p.book_tonnes
        v = calc.variance(s.tonnes, p.book_tonnes)
        s.variance_t = v.delta_t if v else None  # type: ignore[assignment]
        s.variance_pct = v.pct if v else None  # type: ignore[assignment]

    async def _recompute(self, s: StockpileSurvey, p: Stockpile) -> None:
        await self._measure(s, p)
        self._figures(s, p)
        await self.session.flush()

    async def add_survey(self, p: Stockpile, data: SurveyCreate, user_id: str, locale: str = "en") -> SurveyOut:
        on = data.surveyed_on or datetime.now(UTC).date()
        pile_id = data.pile_surface_id
        if pile_id is None and data.pile_text.strip():
            pile_id = await self._surface_from_text(
                p.project_id, data.pile_text, data.pile_filename, f"{p.name} {on.isoformat()}", user_id
            )
        s = StockpileSurvey(
            project_id=p.project_id,
            stockpile_id=p.id,
            surveyed_on=on,
            source_kind="surface" if pile_id is not None else "typed",
            pile_surface_id=pile_id,
            volume_m3=_q(data.volume_m3, "0.001") or Decimal(0),
            cell_size_m=_q(data.cell_size_m, "0.001"),
            density_t_m3=_q(data.density_t_m3, "0.0001"),
            density_source=data.density_source,
            note=data.note,
            created_by=_uuid(user_id),
        )
        await self._measure(s, p)
        self._figures(s, p)
        await self.repo.add(s)
        await self._audit(
            "create", "stockpile_survey", s.id, user_id, {"code": p.code, "project_id": str(p.project_id)}
        )
        return await self._survey_out(s, p, None, locale)

    @staticmethod
    def _locked(s: StockpileSurvey) -> None:
        if s.status == "booked":
            raise _err(status.HTTP_409_CONFLICT, "This survey is booked in the inventory and cannot change")

    async def update_survey(
        self, s: StockpileSurvey, data: SurveyUpdate, user_id: str, locale: str = "en"
    ) -> SurveyOut:
        self._locked(s)
        p = await self.get_stockpile(s.stockpile_id)
        fields = data.model_fields_set
        if "surveyed_on" in fields and data.surveyed_on is not None:
            s.surveyed_on = data.surveyed_on
        if "pile_surface_id" in fields and data.pile_surface_id is not None:
            s.source_kind, s.pile_surface_id = "surface", data.pile_surface_id
        if "volume_m3" in fields and data.volume_m3 is not None:
            s.source_kind, s.pile_surface_id, s.pile_name = "typed", None, ""
            s.volume_m3 = _q(data.volume_m3, "0.001")  # type: ignore[assignment]
        if "cell_size_m" in fields:
            s.cell_size_m = _q(data.cell_size_m, "0.001")
        if "density_t_m3" in fields and data.density_t_m3 is not None:
            s.density_t_m3 = _q(data.density_t_m3, "0.0001")  # type: ignore[assignment]
        if "density_source" in fields and data.density_source is not None:
            s.density_source = data.density_source
        if "note" in fields and data.note is not None:
            s.note = data.note
        await self._recompute(s, p)
        await self._audit(
            "update", "stockpile_survey", s.id, user_id, {"code": p.code, "project_id": str(s.project_id)}
        )
        adj = (await self.repo.adjustments_of([s.id])).get(s.id)
        if adj is not None and adj.status == "proposed":
            adj.delta_t = s.variance_t or Decimal(0)  # type: ignore[assignment]
            if adj.delta_t == 0:
                adj.status = "cancelled"
            await self.session.flush()
        return await self._survey_out(s, p, adj, locale)

    async def delete_survey(self, s: StockpileSurvey, user_id: str) -> None:
        self._locked(s)
        await self._audit("delete", "stockpile_survey", s.id, user_id, {"project_id": str(s.project_id)})
        await self.repo.delete(s)

    # ── Adjustments ────────────────────────────────────────────────────────

    async def propose_adjustment(self, s: StockpileSurvey, user_id: str, locale: str = "en") -> AdjustmentOut:
        self._locked(s)
        if s.variance_t is None:
            raise _bad("The stockpile has no book stock to compare with: enter it first")
        if s.variance_t == 0:
            raise _bad("The survey matches the book stock: nothing to adjust")
        existing = await self.repo.open_adjustment(s.id)
        if existing is not None:
            existing.delta_t = s.variance_t
            await self.session.flush()
            return AdjustmentOut.model_validate(existing)
        p = await self.get_stockpile(s.stockpile_id)
        adj = StockpileAdjustment(
            project_id=s.project_id,
            stockpile_id=s.stockpile_id,
            survey_id=s.id,
            delta_t=s.variance_t,
            item_id=p.site_inventory_item_id,
            proposed_by=_uuid(user_id),
        )
        await self.repo.add(adj)
        await self._audit("create", "stockpile_adjustment", adj.id, user_id, {"delta_t": str(adj.delta_t)})
        return AdjustmentOut.model_validate(adj)

    async def get_adjustment(self, adjustment_id: uuid.UUID) -> StockpileAdjustment:
        a = await self.repo.get_adjustment(adjustment_id)
        if a is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Adjustment not found")
        return a

    async def _inventory_item(self, p: Stockpile, s: StockpileSurvey, user_id: str):
        """The stock item that carries this pile, created in tonnes with the book stock as opening balance."""
        try:
            from app.modules.site_inventory.schemas import MovementCreate, StockItemCreate  # noqa: PLC0415
            from app.modules.site_inventory.service import SiteInventoryService  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - module absent
            raise _bad("The site inventory module is not installed") from exc
        inv = SiteInventoryService(self.session)
        if p.site_inventory_item_id is not None:
            item = await inv.get_item(p.project_id, p.site_inventory_item_id)
            if item is None:
                raise _bad("The linked inventory item no longer exists: unlink it or choose another")
            return inv, item, MovementCreate
        item = await inv.create_item(
            p.project_id, StockItemCreate(name=f"{p.name} ({p.material})" if p.material else p.name, unit=UNIT)
        )
        if s.book_tonnes and s.book_tonnes > 0:
            await inv.record_movement(
                p.project_id,
                MovementCreate(
                    item_id=item.id,
                    movement_type="INBOUND",
                    quantity=str(s.book_tonnes.quantize(Decimal("0.001"))),
                    note=f"Opening book stock of stockpile {p.code}",
                    metadata={"source": "stockpiles", "stockpile_id": str(p.id), "kind": "opening"},
                ),
                user_id,
            )
        return inv, item, MovementCreate

    async def confirm_adjustment(
        self, a: StockpileAdjustment, data: AdjustmentConfirm, user_id: str, locale: str = "en"
    ) -> SurveyOut:
        if a.status != "proposed":
            raise _err(status.HTTP_409_CONFLICT, f"The adjustment is already {a.status}")
        s = await self.get_survey(a.survey_id)
        p = await self.get_stockpile(a.stockpile_id)
        if s.variance_t is None or s.variance_t == 0:
            raise _bad("The survey no longer differs from the book stock")
        delta = s.variance_t
        inv, item, movement_create = await self._inventory_item(p, s, user_id)
        move = await inv.record_movement(
            p.project_id,
            movement_create(
                item_id=item.id,
                movement_type="INBOUND" if delta > 0 else "WASTE",
                quantity=str(abs(delta)),
                note=data.note or f"Stockpile {p.code} survey of {s.surveyed_on.isoformat()}",
                metadata={
                    "source": "stockpiles",
                    "stockpile_id": str(p.id),
                    "survey_id": str(s.id),
                    "delta_t": str(delta),
                    "kind": "adjustment",
                },
            ),
            user_id,
        )
        uid = _uuid(user_id)
        a.delta_t, a.status, a.item_id, a.movement_id = delta, "confirmed", item.id, move.id  # type: ignore[assignment]
        a.confirmed_by, a.confirmed_at = uid, datetime.now(UTC)
        a.confirmed_by_name = await self.repo.user_name(uid)
        a.note = data.note
        s.status = "booked"
        p.site_inventory_item_id = item.id
        p.book_tonnes = s.tonnes  # type: ignore[assignment]
        await self.session.flush()
        await self._audit(
            "approve",
            "stockpile_adjustment",
            a.id,
            user_id,
            {"code": p.code, "delta_t": str(delta), "movement_id": str(move.id), "project_id": str(p.project_id)},
        )
        return await self._survey_out(s, p, a, locale)

    async def cancel_adjustment(self, a: StockpileAdjustment, user_id: str, locale: str = "en") -> SurveyOut:
        if a.status != "proposed":
            raise _err(status.HTTP_409_CONFLICT, f"The adjustment is already {a.status}")
        a.status = "cancelled"
        await self.session.flush()
        await self._audit("update", "stockpile_adjustment", a.id, user_id, {"status": "cancelled"})
        s = await self.get_survey(a.survey_id)
        return await self._survey_out(s, await self.get_stockpile(a.stockpile_id), a, locale)

    # ── Summary and report ─────────────────────────────────────────────────

    async def summary(self, project_id: uuid.UUID) -> StockpileSummary:
        piles = await self.repo.list_stockpiles(project_id)
        latest: dict[uuid.UUID, StockpileSurvey] = {}
        for s in await self.repo.surveys_of_project(project_id):
            latest.setdefault(s.stockpile_id, s)
        surveyed = sum((s.tonnes for s in latest.values()), Decimal(0))
        # Book stock is what the stockpile cards show: the pile's own book, surveyed or not.
        book = sum((p.book_tonnes or Decimal(0) for p in piles), Decimal(0))
        # The variance compares each survey with the book it was measured against.
        book_at_survey = sum((s.book_tonnes or Decimal(0) for s in latest.values()), Decimal(0))
        v = (
            calc.variance(surveyed, book_at_survey)
            if latest and any(s.book_tonnes is not None for s in latest.values())
            else None
        )
        return StockpileSummary(
            stockpiles=len(piles),
            surveyed_tonnes=float(surveyed),
            book_tonnes=float(book),
            variance_pct=_f(v.pct) if v else None,
            surveyed_stockpiles=len(latest),
        )

    async def report_data(self, s: StockpileSurvey, locale: str = "en") -> dict[str, Any]:
        p = await self.get_stockpile(s.stockpile_id)
        adj = (await self.repo.adjustments_of([s.id])).get(s.id)
        survey = await self._survey_out(s, p, adj, locale)
        return {
            "stockpile": {"code": p.code, "name": p.name, "material": p.material, "base_name": p.base_name},
            "survey": survey.model_dump(mode="json"),
        }


__all__ = ["StockpileService"]
