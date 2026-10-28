# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Waste-factor business logic: factor-library CRUD plus net-to-gross apply.

Centralises the small amount of data access and the bridge to the pure
:mod:`app.modules.waste_factors.waste_math` engine so the router stays thin.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.waste_factors.models import WasteFactor
from app.modules.waste_factors.schemas import (
    ApplyLineInput,
    WasteFactorCreate,
    WasteFactorUpdate,
)
from app.modules.waste_factors.seed import seed_waste_factors
from app.modules.waste_factors.waste_math import GrossLine, NetLine, batch_net_to_gross

# Columns that are NOT NULL in the table: a PATCH must never null them even if
# the (all-optional) update schema technically allows it.
_REQUIRED_FIELDS = frozenset({"category", "label", "factor"})


class WasteFactorService:
    """Orchestration over the waste-factor table and the pure apply engine."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- CRUD --------------------------------------------------------------

    async def list_factors(
        self,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> list[WasteFactor]:
        """Return factor rows, optionally filtered by exact category."""
        stmt = select(WasteFactor)
        if category:
            stmt = stmt.where(WasteFactor.category == category)
        stmt = stmt.order_by(WasteFactor.category).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, factor_id: uuid.UUID) -> WasteFactor | None:
        """Load one factor row by id, or ``None`` when absent."""
        return await self.session.get(WasteFactor, factor_id)

    async def create(self, data: WasteFactorCreate) -> WasteFactor:
        """Insert a new factor row from a validated create payload."""
        obj = WasteFactor(**data.model_dump())
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update(
        self,
        factor_id: uuid.UUID,
        data: WasteFactorUpdate,
    ) -> WasteFactor | None:
        """Patch a factor row in place; returns ``None`` when it does not exist.

        Only fields the caller actually sent are touched. ``note`` may be
        cleared to ``null``; the NOT NULL columns are never nulled.
        """
        obj = await self.session.get(WasteFactor, factor_id)
        if obj is None:
            return None
        for field_name, value in data.model_dump(exclude_unset=True).items():
            if value is None and field_name in _REQUIRED_FIELDS:
                continue
            setattr(obj, field_name, value)
        await self.session.flush()
        return obj

    async def delete(self, factor_id: uuid.UUID) -> None:
        """Delete a factor row if present (no-op when already gone)."""
        obj = await self.session.get(WasteFactor, factor_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()

    async def seed_defaults(self, *, tenant_id: uuid.UUID | None = None) -> dict[str, int]:
        """Idempotently insert the default factor library for a tenant scope."""
        return await seed_waste_factors(self.session, tenant_id=tenant_id)

    # -- Apply -------------------------------------------------------------

    async def factor_map(self) -> dict[str, Decimal]:
        """Category -> factor mapping for the whole library (last write wins)."""
        stmt = select(WasteFactor.category, WasteFactor.factor)
        rows = (await self.session.execute(stmt)).all()
        return {category: factor for category, factor in rows}

    async def apply(self, lines: list[ApplyLineInput]) -> list[GrossLine]:
        """Convert net lines to gross using the current factor library.

        Categories with no library entry pass through unchanged (factor 1.0)
        and are flagged ``matched=False`` on the returned lines.
        """
        factors = await self.factor_map()
        net_lines = [NetLine(category=line.category, net_qty=line.net_qty) for line in lines]
        return batch_net_to_gross(net_lines, factors)
