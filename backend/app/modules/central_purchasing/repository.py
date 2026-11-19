# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for central purchasing bundles and the records they read from other modules."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.central_purchasing.models import AwardSplit, Bundle, BundleProject


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


class BundleRepository:
    """Bundles, their projects and splits; reads of projects, entities, cost lines and budgets."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, bundle_id: uuid.UUID) -> Bundle | None:
        return await self.session.get(Bundle, bundle_id)

    async def list(self) -> list[Bundle]:
        rows = await self.session.execute(select(Bundle).order_by(Bundle.created_at.desc()))
        return list(rows.scalars().all())

    async def code_taken(self, code: str) -> bool:
        found = await self.session.execute(select(Bundle.id).where(Bundle.code == code).limit(1))
        return found.scalar_one_or_none() is not None

    async def next_code(self) -> str:
        count = (await self.session.execute(select(func.count(Bundle.id)))).scalar() or 0
        seq = int(count) + 1
        while await self.code_taken(f"CPB-{seq:04d}"):
            seq += 1
        return f"CPB-{seq:04d}"

    async def splits(self, bundle_id: uuid.UUID) -> list[AwardSplit]:
        rows = await self.session.execute(select(AwardSplit).where(AwardSplit.bundle_id == bundle_id))
        return list(rows.scalars().all())

    async def memberships(self, project_id: uuid.UUID) -> list[BundleProject]:
        rows = await self.session.execute(select(BundleProject).where(BundleProject.project_id == project_id))
        return list(rows.scalars().all())

    async def projects(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
        from app.modules.projects.models import Project

        if not ids:
            return {}
        rows = await self.session.execute(select(Project).where(Project.id.in_(ids)))
        return {p.id: p for p in rows.scalars().all()}

    async def entities(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
        from app.modules.legal_entities.models import LegalEntity

        wanted = [i for i in ids if i is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(select(LegalEntity).where(LegalEntity.id.in_(wanted)))
        return {e.id: e for e in rows.scalars().all()}

    async def entities_exist(self) -> bool:
        from app.modules.legal_entities.models import LegalEntity

        found = await self.session.execute(select(LegalEntity.id).where(LegalEntity.is_active.is_(True)).limit(1))
        return found.scalar_one_or_none() is not None

    async def entity_countries(self) -> list[str]:
        from app.modules.legal_entities.models import LegalEntity

        rows = await self.session.execute(
            select(LegalEntity.country_code)
            .where(LegalEntity.is_active.is_(True))
            .order_by(LegalEntity.is_default.desc())
        )
        return [r for r in rows.scalars().all() if r]

    async def cost_lines(self, project_id: uuid.UUID) -> list[Any]:
        from app.modules.costmodel.models import CostLine

        rows = await self.session.execute(
            select(CostLine).where(CostLine.project_id == project_id).order_by(CostLine.code)
        )
        return list(rows.scalars().all())

    async def cost_line_codes(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        from app.modules.costmodel.models import CostLine

        wanted = [i for i in ids if i is not None]
        if not wanted:
            return {}
        rows = await self.session.execute(select(CostLine.id, CostLine.code).where(CostLine.id.in_(wanted)))
        return {r[0]: r[1] for r in rows.all()}

    async def planned_budget(self, project_id: uuid.UUID, cost_line_ids: list[uuid.UUID]) -> Decimal | None:
        """F4 budget: planned amount on the share cost lines of one project; ``None`` when none is planned."""
        from app.modules.costmodel.models import BudgetLine

        wanted = [i for i in cost_line_ids if i is not None]
        if not wanted:
            return None
        rows = await self.session.execute(
            select(BudgetLine.planned_amount).where(
                BudgetLine.project_id == project_id, BudgetLine.cost_line_id.in_(wanted)
            )
        )
        amounts = [_dec(a) for a in rows.scalars().all()]
        return sum(amounts, Decimal("0")) if amounts else None

    async def subcontractor(self, subcontractor_id: uuid.UUID | None) -> Any | None:
        if subcontractor_id is None:
            return None
        try:
            from app.modules.subcontractors.models import Subcontractor
        except ImportError:
            return None
        return await self.session.get(Subcontractor, subcontractor_id)
