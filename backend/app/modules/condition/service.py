# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Condition assessment service: scales, ratings, maintenance plan.

Ratings are recorded per asset or element (typically during an inspection);
the plan is derived from them as proposals a person approves, priced per year
with inflation from the price index module when a series is named, and its
annual figure can be written into the asset register, where the whole-life
cost calculation of the carbon module already reads ``annual_maintenance_cost``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.condition import planning, scales
from app.modules.condition.models import ConditionAction, ConditionAssessment, ConditionScale
from app.modules.condition.repository import ConditionRepository
from app.modules.condition.schemas import (
    ActionCreate,
    ActionUpdate,
    AssessmentCreate,
    AssessmentUpdate,
    ScaleCreate,
)

logger = logging.getLogger(__name__)

#: Plan horizon when the caller names none (years).
DEFAULT_HORIZON_YEARS = 10


def _custom_to_dict(row: ConditionScale) -> dict[str, Any]:
    return {
        "id": row.id,
        "key": row.key,
        "name": row.name,
        "description": row.description,
        "action_threshold": row.action_threshold,
        "levels": list(row.levels or []),
        "source": scales.SOURCE_CUSTOM,
        "pack_slug": None,
    }


class ConditionService:
    """Stateless service for condition ratings and maintenance planning."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ConditionRepository(session)

    # ── Scales ───────────────────────────────────────────────────────────

    async def list_scales(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Shipped scales, then the active pack's, then the project's own."""
        out = list(scales.builtin_scales())
        taken = {s["key"] for s in out}
        for pack_scale in scales.pack_scales():
            if pack_scale["key"] in taken:
                logger.warning("Pack condition scale %r ignored: the key is a shipped scale", pack_scale["key"])
                continue
            taken.add(pack_scale["key"])
            out.append(pack_scale)
        for row in await self.repo.list_scales(project_id):
            if row.key not in taken:
                out.append(_custom_to_dict(row))
        return out

    async def get_scale(self, project_id: uuid.UUID, key: str) -> dict[str, Any]:
        """One scale by key, from any source (404 when unknown)."""
        for scale in await self.list_scales(project_id):
            if scale["key"] == key:
                return scale
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Condition scale {key!r} not found")

    async def create_scale(self, project_id: uuid.UUID, data: ScaleCreate, user_id: str | None) -> dict[str, Any]:
        """Define a project scale; its key may not shadow a shipped or pack scale."""
        try:
            clean = scales.validate_scale(data.model_dump())
        except scales.ScaleError as exc:
            raise HTTPException(status_code=422, detail={"problems": exc.problems}) from exc
        if any(s["key"] == clean["key"] for s in await self.list_scales(project_id)):
            raise HTTPException(status_code=409, detail=f"A scale with key {clean['key']!r} already exists")
        row = ConditionScale(
            project_id=project_id,
            key=clean["key"],
            name=clean["name"],
            description=clean["description"],
            action_threshold=clean["action_threshold"],
            levels=clean["levels"],
            created_by=user_id,
        )
        self.session.add(row)
        await self.session.flush()
        return _custom_to_dict(row)

    async def delete_scale(self, project_id: uuid.UUID, key: str) -> None:
        """Remove a project scale that no assessment uses."""
        row = await self.repo.get_scale(project_id, key)
        if row is None:
            raise HTTPException(status_code=404, detail="Only a project scale can be deleted")
        if await self.repo.count_assessments_with_scale(project_id, key):
            raise HTTPException(status_code=409, detail="The scale is used by recorded assessments")
        await self.session.delete(row)
        await self.session.flush()

    # ── Assessments ──────────────────────────────────────────────────────

    async def _check_rating(self, project_id: uuid.UUID, scale_key: str, rating: int) -> dict[str, Any]:
        scale = await self.get_scale(project_id, scale_key)
        if planning.scale_level(scale, rating) is None:
            raise HTTPException(
                status_code=422,
                detail=f"Rating {rating} is not a level of scale {scale_key!r} (1..{len(scale['levels'])})",
            )
        return scale

    async def suggest(
        self,
        project_id: uuid.UUID | None,
        scale_key: str,
        *,
        severity: int | None,
        extent_pct: float | None,
        intensity: int | None,
    ) -> tuple[int | None, float, dict[str, Any] | None]:
        """A proposed rating for a defect record on the given scale."""
        if project_id is None:
            scale = next((s for s in scales.builtin_scales() if s["key"] == scale_key), None)
            if scale is None:
                raise HTTPException(status_code=404, detail=f"Condition scale {scale_key!r} not found")
        else:
            scale = await self.get_scale(project_id, scale_key)
        rating, confidence = planning.suggest_rating(
            len(scale["levels"]), severity=severity, extent_pct=extent_pct, intensity=intensity
        )
        return rating, confidence, planning.scale_level(scale, rating) if rating else None

    async def create_assessment(self, data: AssessmentCreate, user_id: str | None) -> ConditionAssessment:
        """Record a rating; the proposal from the defect record is kept beside it."""
        scale = await self._check_rating(data.project_id, data.scale_key, data.rating)
        suggested, confidence = planning.suggest_rating(
            len(scale["levels"]), severity=data.severity, extent_pct=data.extent_pct, intensity=data.intensity
        )
        row = ConditionAssessment(
            **data.model_dump(),
            suggested_rating=suggested,
            suggestion_confidence=confidence if suggested else None,
            assessed_by=user_id,
            photos=[],
            metadata_={},
        )
        if row.assessed_at is None:
            row.assessed_at = datetime.now(UTC).date()
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_assessment(self, assessment_id: uuid.UUID) -> ConditionAssessment:
        row = await self.session.get(ConditionAssessment, assessment_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Assessment not found")
        return row

    async def update_assessment(self, row: ConditionAssessment, data: AssessmentUpdate) -> ConditionAssessment:
        patch = data.model_dump(exclude_unset=True)
        if "rating" in patch and patch["rating"] is not None:
            await self._check_rating(row.project_id, row.scale_key, int(patch["rating"]))
        for key, value in patch.items():
            setattr(row, key, value)
        if {"severity", "extent_pct", "intensity"} & patch.keys():
            scale = await self.get_scale(row.project_id, row.scale_key)
            suggested, confidence = planning.suggest_rating(
                len(scale["levels"]), severity=row.severity, extent_pct=row.extent_pct, intensity=row.intensity
            )
            row.suggested_rating = suggested
            row.suggestion_confidence = confidence if suggested else None
        await self.session.flush()
        return row

    async def delete_assessment(self, row: ConditionAssessment) -> None:
        await self.session.delete(row)
        await self.session.flush()

    # ── Actions ──────────────────────────────────────────────────────────

    async def create_action(self, data: ActionCreate, user_id: str | None) -> ConditionAction:
        """A manual action is a human decision, so it starts approved."""
        if data.assessment_id is not None:
            assessment = await self.get_assessment(data.assessment_id)
            if assessment.project_id != data.project_id:
                raise HTTPException(status_code=404, detail="Assessment not found")
        row = ConditionAction(
            **data.model_dump(),
            status="approved",
            source="manual",
            decided_by=user_id,
            metadata_={},
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_action(self, action_id: uuid.UUID) -> ConditionAction:
        row = await self.session.get(ConditionAction, action_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Action not found")
        return row

    async def update_action(self, row: ConditionAction, data: ActionUpdate, user_id: str | None) -> ConditionAction:
        patch = data.model_dump(exclude_unset=True)
        for key, value in patch.items():
            setattr(row, key, value)
        if "status" in patch:
            row.decided_by = user_id
        await self.session.flush()
        return row

    async def delete_action(self, row: ConditionAction) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def derive(self, project_id: uuid.UUID, base_year: int | None, user_id: str | None) -> dict[str, Any]:
        """Propose actions from the latest rating of every asset or element.

        Idempotent: an assessment that already has a live (not rejected)
        derived action of the same type gets no second one.
        """
        year = base_year or datetime.now(UTC).year
        latest = await self.repo.latest_assessments(project_id)
        existing = await self.repo.derived_keys(project_id)
        scale_cache: dict[str, dict[str, Any]] = {}
        created: list[ConditionAction] = []
        skipped = 0
        for a in latest:
            if a.scale_key not in scale_cache:
                try:
                    scale_cache[a.scale_key] = await self.get_scale(project_id, a.scale_key)
                except HTTPException:
                    skipped += 1
                    continue
            proposals = planning.derive_actions(
                {
                    "rating": a.rating,
                    "severity": a.severity,
                    "extent_pct": a.extent_pct,
                    "intensity": a.intensity,
                    "quantity": a.quantity,
                    "unit": a.unit,
                    "unit_cost": a.unit_cost,
                },
                scale_cache[a.scale_key],
                base_year=year,
            )
            if not proposals:
                skipped += 1
                continue
            for p in proposals:
                if (a.id, p["action_type"]) in existing:
                    skipped += 1
                    continue
                row = ConditionAction(
                    project_id=project_id,
                    assessment_id=a.id,
                    asset_kind=a.asset_kind,
                    asset_ref=a.asset_ref,
                    element_name=a.element_name,
                    area=a.area,
                    action_type=p["action_type"],
                    description=p["description"],
                    first_year=p["first_year"],
                    interval_years=p["interval_years"],
                    quantity=Decimal(p["quantity"]) if p["quantity"] is not None else None,
                    unit=p["unit"],
                    unit_cost=Decimal(p["unit_cost"]) if p["unit_cost"] is not None else None,
                    currency=a.currency,
                    priority=p["priority"],
                    status="proposed",
                    source="derived",
                    confidence=p["confidence"],
                    metadata_={"rating": a.rating, "scale_key": a.scale_key, "derived_by": user_id},
                )
                self.session.add(row)
                created.append(row)
        await self.session.flush()
        return {"created": len(created), "skipped": skipped, "actions": created}

    # ── Plan ─────────────────────────────────────────────────────────────

    async def resolve_inflation(self, inflation_rate: Decimal | None, index_series_id: uuid.UUID | None) -> Decimal:
        """Explicit rate wins; otherwise the compound annual growth of a price index series."""
        if inflation_rate is not None:
            return inflation_rate
        if index_series_id is None:
            return Decimal("0")
        try:
            from app.modules.price_index.service import PriceIndexService

            points = await PriceIndexService(self.session).series_points(index_series_id)
        except Exception as exc:  # noqa: BLE001 - price index module absent
            raise HTTPException(status_code=422, detail="Price index series cannot be read") from exc
        rate = planning.annual_rate_from_points(points)
        if rate is None:
            raise HTTPException(status_code=422, detail="Price index series needs two points at least a month apart")
        return rate

    async def plan(
        self,
        project_id: uuid.UUID,
        *,
        start_year: int | None = None,
        horizon_years: int = DEFAULT_HORIZON_YEARS,
        inflation_rate: Decimal | None = None,
        index_series_id: uuid.UUID | None = None,
        discount_rate: Decimal | None = None,
        include_proposed: bool = False,
        area: str | None = None,
        asset_ref: str | None = None,
    ) -> dict[str, Any]:
        """The multi-year maintenance plan in year buckets."""
        statuses = ["approved", "proposed"] if include_proposed else ["approved"]
        rows = await self.repo.list_actions(project_id, statuses=statuses, area=area, asset_ref=asset_ref)
        start = start_year or datetime.now(UTC).year
        rate = await self.resolve_inflation(inflation_rate, index_series_id)
        plan = planning.build_plan(
            [
                {
                    "id": str(r.id),
                    "asset_ref": r.asset_ref,
                    "element_name": r.element_name,
                    "area": r.area,
                    "action_type": r.action_type,
                    "description": r.description,
                    "status": r.status,
                    "priority": r.priority,
                    "first_year": r.first_year,
                    "interval_years": r.interval_years,
                    "quantity": r.quantity,
                    "unit": r.unit,
                    "unit_cost": r.unit_cost,
                    "currency": r.currency,
                }
                for r in rows
            ],
            start_year=start,
            horizon_years=horizon_years,
            inflation_rate=rate,
            discount_rate=discount_rate or Decimal("0"),
        )
        plan["inflation_source"] = (
            "explicit" if inflation_rate is not None else "price_index" if index_series_id else "none"
        )
        currencies = sorted({r.currency for r in rows if r.currency})
        plan["currencies"] = currencies
        return plan

    async def apply_to_assets(self, project_id: uuid.UUID, plan: dict[str, Any]) -> dict[str, Any]:
        """Write the plan's annual figure and latest rating into BIM asset records.

        Only assessments of kind ``bim_element`` whose element belongs to this
        project are touched; ``annual_maintenance_cost`` is the key the
        whole-life cost calculation reads as operating cost.
        """
        try:
            from app.modules.bim_hub.models import BIMElement, BIMModel
            from app.modules.bim_hub.repository import BIMElementRepository
        except Exception as exc:  # noqa: BLE001 - BIM hub absent
            raise HTTPException(status_code=409, detail="The asset register (BIM hub) is not installed") from exc
        latest = {
            a.asset_ref: a for a in await self.repo.latest_assessments(project_id) if a.asset_kind == "bim_element"
        }
        horizon = int(plan.get("horizon_years") or DEFAULT_HORIZON_YEARS)
        by_asset = plan.get("by_asset") or {}
        repo = BIMElementRepository(self.session)
        updated: list[str] = []
        skipped = 0
        for ref, assessment in latest.items():
            element_id = _as_uuid(ref)
            if element_id is None:
                skipped += 1
                continue
            owner = (
                await self.session.execute(
                    select(BIMModel.project_id)
                    .join(BIMElement, BIMElement.model_id == BIMModel.id)
                    .where(BIMElement.id == element_id)
                )
            ).scalar_one_or_none()
            if owner != project_id:
                skipped += 1
                continue
            info: dict[str, Any] = {
                "condition_rating": assessment.rating,
                "condition_scale": assessment.scale_key,
                "condition_assessed_at": assessment.assessed_at.isoformat() if assessment.assessed_at else None,
            }
            total = by_asset.get(ref)
            if total is not None:
                info["annual_maintenance_cost"] = str((Decimal(str(total)) / horizon).quantize(Decimal("0.01")))
            await repo.update_asset_info(element_id, asset_info=info)
            updated.append(ref)
        return {"updated": len(updated), "skipped": skipped, "asset_refs": updated}


def _as_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
