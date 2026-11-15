# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Storage and operations for user-owned estimate templates.

Built-in templates stay in code and are read only: ``duplicate`` makes a row
the user can edit. Rows are private to their owner.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, BOQTemplate
from app.modules.boq.repository import MarkupRepository, PositionRepository
from app.modules.boq.template_schemas import TemplateFromBOQRequest, TemplateWrite
from app.modules.boq.templates import TEMPLATES
from app.modules.boq.user_templates import (
    builtin_to_detail,
    cost_per_area,
    count_positions,
    markups_from_rows,
    sections_from_positions,
    validate_template,
)

#: Cap on templates one user may keep; a guard against a runaway client, not a product limit.
MAX_TEMPLATES_PER_USER = 500


def row_to_detail(row: BOQTemplate) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "builtin": False,
        "name": row.name,
        "description": row.description,
        "icon": row.icon,
        "classification_standard": row.classification_standard,
        "origin": row.origin,
        "copied_from": row.copied_from,
        "sections": row.sections or [],
        "markups": row.markups or [],
    }


def with_warnings(detail: dict[str, Any]) -> dict[str, Any]:
    return {**detail, "warnings": validate_template(detail)}


def summary(detail: dict[str, Any]) -> dict[str, Any]:
    sections = detail["sections"]
    return {
        "id": detail["id"],
        "name": detail["name"],
        "description": detail["description"],
        "icon": detail["icon"],
        "section_count": len(sections),
        "position_count": count_positions(sections),
        "builtin": detail["builtin"],
        "classification_standard": detail["classification_standard"],
        "origin": detail["origin"],
        "avg_cost_per_m2": round(cost_per_area(sections) or 0.0, 2),
        "currency": "",
    }


class TemplateService:
    """CRUD, duplicate and create-from-estimate for user templates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── reads ────────────────────────────────────────────────────────────

    async def list_rows(self, owner_id: str) -> list[BOQTemplate]:
        stmt = select(BOQTemplate).where(BOQTemplate.owner_id == owner_id).order_by(BOQTemplate.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_row(self, template_id: str, owner_id: str) -> BOQTemplate | None:
        """The user's own template, or ``None``; another user's template reads as missing."""
        try:
            key = uuid.UUID(template_id)
        except ValueError:
            return None
        row = await self.session.get(BOQTemplate, key)
        if row is None or row.owner_id != owner_id:
            return None
        return row

    async def get_detail(self, template_id: str, owner_id: str) -> dict[str, Any]:
        if template_id in TEMPLATES:
            return builtin_to_detail(template_id, TEMPLATES[template_id])
        row = await self.get_row(template_id, owner_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        return row_to_detail(row)

    # ── writes ───────────────────────────────────────────────────────────

    async def _ensure_room(self, owner_id: str) -> None:
        if len(await self.list_rows(owner_id)) >= MAX_TEMPLATES_PER_USER:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Template limit reached")

    async def create(
        self,
        owner_id: str,
        body: TemplateWrite,
        *,
        origin: str = "manual",
        copied_from: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_room(owner_id)
        data = body.model_dump()
        row = BOQTemplate(
            owner_id=owner_id,
            name=data["name"] or "Template",
            description=data["description"],
            icon=data["icon"],
            classification_standard=data["classification_standard"],
            origin=origin,
            copied_from=copied_from,
            sections=data["sections"],
            markups=data["markups"],
        )
        self.session.add(row)
        await self.session.flush()
        return with_warnings(row_to_detail(row))

    async def update(self, template_id: str, owner_id: str, body: TemplateWrite) -> dict[str, Any]:
        if template_id in TEMPLATES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Built-in templates are read only; duplicate it to edit a copy",
            )
        row = await self.get_row(template_id, owner_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        data = body.model_dump()
        row.name = data["name"] or row.name
        row.description = data["description"]
        row.icon = data["icon"]
        row.classification_standard = data["classification_standard"]
        row.sections = data["sections"]
        row.markups = data["markups"]
        await self.session.flush()
        return with_warnings(row_to_detail(row))

    async def delete(self, template_id: str, owner_id: str) -> None:
        if template_id in TEMPLATES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Built-in templates cannot be deleted")
        row = await self.get_row(template_id, owner_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        await self.session.delete(row)
        await self.session.flush()

    async def duplicate(self, template_id: str, owner_id: str, name: str | None = None) -> dict[str, Any]:
        source = await self.get_detail(template_id, owner_id)
        body = TemplateWrite(
            name=name or source["name"],
            description=source["description"],
            icon=source["icon"],
            classification_standard=source["classification_standard"],
            sections=source["sections"],
            markups=source["markups"],
        )
        return await self.create(
            owner_id,
            body,
            origin="copy",
            copied_from=template_id if source["builtin"] else source.get("copied_from"),
        )

    async def create_from_boq(
        self,
        boq: BOQ,
        owner_id: str,
        req: TemplateFromBOQRequest,
        *,
        ungrouped_name: str = "General",
    ) -> dict[str, Any]:
        """Copy the structure of an existing estimate into a new template."""
        positions = await PositionRepository(self.session).list_all_for_boq(boq.id)
        sections = sections_from_positions(
            positions,
            keep_quantities=req.keep_quantities,
            keep_rates=req.keep_rates,
            renumber_positions=req.renumber,
            ungrouped_name=ungrouped_name,
        )
        markups = []
        if req.include_markups:
            markups = markups_from_rows(await MarkupRepository(self.session).list_for_boq(boq.id))
        body = TemplateWrite.model_validate(
            {
                "name": req.name or boq.name,
                "description": req.description if req.description is not None else boq.description,
                "classification_standard": req.classification_standard,
                "sections": sections,
                "markups": markups,
            }
        )
        return await self.create(owner_id, body, origin="boq")
