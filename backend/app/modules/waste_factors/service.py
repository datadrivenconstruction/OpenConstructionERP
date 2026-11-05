# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Waste-factor business logic: factor-library CRUD plus net-to-gross apply.

Centralises the small amount of data access and the bridge to the pure
:mod:`app.modules.waste_factors.waste_math` engine so the router stays thin.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
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
        #: Non-blocking findings of the latest write, for the router to report.
        self.warnings: list[dict[str, Any]] = []

    async def _context(
        self, *, factor_id: uuid.UUID | None, category: str, label: str, factor: Decimal, tenant_id: uuid.UUID | None
    ) -> dict[str, Any]:
        """The rule payload: the row as it would be stored plus the other rows of the same category."""
        stmt = select(WasteFactor.id, WasteFactor.category, WasteFactor.tenant_id).where(
            func.lower(func.trim(WasteFactor.category)) == category.strip().lower()
        )
        if factor_id is not None:
            stmt = stmt.where(WasteFactor.id != factor_id)
        siblings = [
            {"id": str(i), "category": c, "tenant_id": str(t) if t else ""}
            for i, c, t in (await self.session.execute(stmt)).all()
        ]
        head = {
            "id": str(factor_id) if factor_id else "",
            "category": category,
            "label": label,
            "factor": factor,
            "tenant_id": str(tenant_id) if tenant_id else "",
        }
        return {"factor": head, "siblings": siblings}

    async def _gate(self, context: dict[str, Any], before: dict[str, Any] | None, target_id: str) -> None:
        """Run the waste factor rules: errors the write introduces raise a coded 422, warnings are kept."""
        from app.core.validation.cost_gate import raise_on_introduced, run_rule_set, warnings_of  # noqa: PLC0415
        from app.modules.waste_factors.validators import WASTE_FACTORS_RULE_SET  # noqa: PLC0415

        def run(payload: dict[str, Any]):
            return run_rule_set(WASTE_FACTORS_RULE_SET, payload, target_type="waste_factor", target_id=target_id)

        report = await run(context)
        await raise_on_introduced(
            report, (lambda: run(before)) if before is not None else None, error="waste_factors_rules_failed"
        )
        self.warnings = warnings_of(report)

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
        await self._gate(
            await self._context(
                factor_id=None, category=obj.category, label=obj.label, factor=obj.factor, tenant_id=obj.tenant_id
            ),
            None,
            obj.category,
        )
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
        changes = {
            k: v for k, v in data.model_dump(exclude_unset=True).items() if not (v is None and k in _REQUIRED_FIELDS)
        }

        async def context(**over: Any) -> dict[str, Any]:
            return await self._context(
                factor_id=obj.id,
                category=over.get("category", obj.category),
                label=over.get("label", obj.label),
                factor=over.get("factor", obj.factor),
                tenant_id=over.get("tenant_id", obj.tenant_id),
            )

        await self._gate(await context(**changes), await context(), str(factor_id))
        for field_name, value in changes.items():
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
