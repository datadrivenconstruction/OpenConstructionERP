# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the norm pricing module.

The settings are a small block in the project's ``metadata`` JSON under
``estimate_pricing``: no table of their own, so no migration.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SETTINGS_KEY = "estimate_pricing"


class NormPricingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def project_country_and_settings(self, project_id: uuid.UUID) -> tuple[str | None, dict[str, Any]] | None:
        """``(country_code, settings)`` of a project, or ``None`` when it does not exist."""
        from app.modules.projects.models import Project

        row = (
            await self.session.execute(select(Project.country_code, Project.metadata_).where(Project.id == project_id))
        ).first()
        if row is None:
            return None
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        block = meta.get(SETTINGS_KEY)
        return row.country_code, dict(block) if isinstance(block, dict) else {}

    async def save_settings(self, project_id: uuid.UUID, settings: dict[str, Any]) -> None:
        """Replace the project's settings block; other metadata keys are untouched."""
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        if project is None:
            return
        meta = dict(project.metadata_ or {})
        meta[SETTINGS_KEY] = settings
        # A new dict, so the JSON column sees the change without flag_modified.
        project.metadata_ = meta
        await self.session.flush()

    async def boq_project(self, boq_id: uuid.UUID) -> uuid.UUID | None:
        """The project a bill belongs to, or ``None`` when the bill does not exist."""
        from app.modules.boq.models import BOQ

        return (await self.session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).scalar_one_or_none()

    async def boq_lines(self, boq_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every line of a bill with its resources, in bill order (plain values, no ORM rows)."""
        from app.modules.boq.models import Position

        rows = (
            await self.session.execute(
                select(Position.id, Position.ordinal, Position.description, Position.metadata_)
                .where(Position.boq_id == boq_id)
                .order_by(Position.sort_order, Position.ordinal)
            )
        ).all()
        return [
            {
                "id": str(r.id),
                "ordinal": r.ordinal,
                "description": r.description,
                "metadata": dict(r.metadata_) if isinstance(r.metadata_, dict) else {},
            }
            for r in rows
        ]
