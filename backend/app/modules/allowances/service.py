# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Allowances register service - business logic, no HTTP.

Stateless service layer over the two tables. Handles allowance and drawdown CRUD
(money parsed to a 2dp-quantized :class:`decimal.Decimal` on the way in, never a
float) and composes the per-currency, per-type register summary from the pure
:mod:`app.modules.allowances.allowance_math` engine.

The service does the database work (add / mutate / delete + flush) and leaves the
transaction ``commit`` to the router, matching the CVR module. Every read that
needs the drawdowns loads the allowance through :meth:`get_allowance`, whose
``select`` triggers the ``selectin`` relationship so ``allowance.drawdowns`` is
always populated before it is read (no async lazy-load surprise).
"""

import logging
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.allowances.allowance_math import (
    AllowanceLine,
    RegisterSummary,
    quantize_money,
    roll_up_register,
    to_decimal,
)
from app.modules.allowances.models import Allowance, AllowanceDrawdown
from app.modules.allowances.schemas import (
    AllowanceCreate,
    AllowanceUpdate,
    DrawdownCreate,
)

logger = logging.getLogger(__name__)


def _money(value: object) -> Decimal:
    """Parse an incoming money value to a 2dp-quantized Decimal."""
    return quantize_money(to_decimal(value))


def _norm_currency(value: str | None) -> str:
    """Normalise a currency code: trimmed, upper-cased, empty when unset."""
    return (value or "").strip().upper()


class AllowanceService:
    """Business logic for the allowances & contingency register."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Allowances ────────────────────────────────────────────────────────

    async def create_allowance(
        self,
        project_id: uuid.UUID,
        data: AllowanceCreate,
        user_id: str | None = None,
    ) -> Allowance:
        """Create an allowance in a project and return it fully loaded."""
        allowance = Allowance(
            project_id=project_id,
            label=data.label,
            allowance_type=data.allowance_type,
            held_amount=_money(data.held_amount),
            currency=_norm_currency(data.currency),
            notes=data.notes,
            created_by=user_id,
        )
        self.session.add(allowance)
        await self.session.flush()
        logger.info(
            "Allowance created: %s (%s) project=%s",
            data.label,
            data.allowance_type,
            project_id,
        )
        return await self.get_allowance(allowance.id)

    async def get_allowance(self, allowance_id: uuid.UUID) -> Allowance:
        """Get an allowance (with its drawdowns) by id. Raises 404 if missing."""
        result = await self.session.execute(
            select(Allowance).where(Allowance.id == allowance_id),
        )
        allowance = result.scalar_one_or_none()
        if allowance is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allowance not found")
        return allowance

    async def list_allowances(self, project_id: uuid.UUID) -> list[Allowance]:
        """List a project's allowances (with drawdowns), type then oldest first."""
        result = await self.session.execute(
            select(Allowance)
            .where(Allowance.project_id == project_id)
            .order_by(Allowance.allowance_type, Allowance.created_at),
        )
        return list(result.scalars().all())

    async def update_allowance(self, allowance_id: uuid.UUID, data: AllowanceUpdate) -> Allowance:
        """Apply a partial update to an allowance and return it fully loaded."""
        allowance = await self.get_allowance(allowance_id)
        fields = data.model_dump(exclude_unset=True)
        if "label" in fields and fields["label"] is not None:
            allowance.label = fields["label"]
        if "allowance_type" in fields and fields["allowance_type"] is not None:
            allowance.allowance_type = fields["allowance_type"]
        if "held_amount" in fields and fields["held_amount"] is not None:
            allowance.held_amount = _money(fields["held_amount"])
        if "currency" in fields and fields["currency"] is not None:
            allowance.currency = _norm_currency(fields["currency"])
        if "notes" in fields:
            allowance.notes = fields["notes"]
        await self.session.flush()
        return await self.get_allowance(allowance_id)

    async def delete_allowance(self, allowance_id: uuid.UUID) -> None:
        """Delete an allowance (its drawdowns cascade away)."""
        allowance = await self.get_allowance(allowance_id)
        await self.session.delete(allowance)
        await self.session.flush()

    # ── Drawdowns ─────────────────────────────────────────────────────────

    async def add_drawdown(
        self,
        allowance_id: uuid.UUID,
        data: DrawdownCreate,
        user_id: str | None = None,
    ) -> AllowanceDrawdown:
        """Record a drawdown against an allowance (verifies it exists first).

        Over-drawing past the held amount is deliberately permitted; the register
        surfaces it as an advisory flag, never a hard error, so a provisional sum
        that turned out too small can still be tracked honestly.
        """
        await self.get_allowance(allowance_id)
        drawdown = AllowanceDrawdown(
            allowance_id=allowance_id,
            amount=_money(data.amount),
            note=data.note,
            created_by=user_id,
        )
        self.session.add(drawdown)
        await self.session.flush()
        await self.session.refresh(drawdown)
        return drawdown

    async def get_drawdown(self, drawdown_id: uuid.UUID) -> AllowanceDrawdown:
        """Get a drawdown by id. Raises 404 if missing."""
        result = await self.session.execute(
            select(AllowanceDrawdown).where(AllowanceDrawdown.id == drawdown_id),
        )
        drawdown = result.scalar_one_or_none()
        if drawdown is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawdown not found")
        return drawdown

    async def list_drawdowns(self, allowance_id: uuid.UUID) -> list[AllowanceDrawdown]:
        """List an allowance's drawdowns, oldest first (verifies it exists)."""
        allowance = await self.get_allowance(allowance_id)
        return list(allowance.drawdowns)

    async def delete_drawdown(self, drawdown_id: uuid.UUID) -> None:
        """Delete a single drawdown."""
        drawdown = await self.get_drawdown(drawdown_id)
        await self.session.delete(drawdown)
        await self.session.flush()

    # ── Register summary ──────────────────────────────────────────────────

    async def build_register_summary(self, project_id: uuid.UUID) -> RegisterSummary:
        """Compose the project's per-currency, per-type allowances roll-up."""
        allowances = await self.list_allowances(project_id)
        lines = [
            AllowanceLine(
                allowance_type=a.allowance_type,
                currency=a.currency,
                held=to_decimal(a.held_amount),
                drawdowns=tuple(to_decimal(d.amount) for d in a.drawdowns),
            )
            for a in allowances
        ]
        return roll_up_register(lines)
