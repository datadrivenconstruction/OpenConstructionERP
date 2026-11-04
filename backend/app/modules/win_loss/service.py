# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger service: CRUD, validation and the summary."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.modules.win_loss.analytics import dominant_currency, price_gap, size_band, summarize
from app.modules.win_loss.models import BidOutcome
from app.modules.win_loss.repository import BidOutcomeRepository
from app.modules.win_loss.schemas import (
    BidOutcomeCreate,
    BidOutcomeResponse,
    BidOutcomeUpdate,
    LedgerSummary,
    ValidationFinding,
)

_PAYLOAD_FIELDS = (
    "title",
    "outcome",
    "currency",
    "our_price",
    "winning_price",
    "second_price",
    "competitor_count",
    "lost_reason",
)


class WinLossService:
    """Business logic of the bid outcome ledger."""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = BidOutcomeRepository(session)

    async def validate(self, entry: BidOutcome) -> list[ValidationFinding]:
        """Run the ``bid_outcome`` rule set; a clean entry returns no warnings."""
        payload: dict[str, Any] = {name: getattr(entry, name) for name in _PAYLOAD_FIELDS}
        report = await validation_engine.validate(
            data=payload,
            rule_sets=["bid_outcome"],
            target_type="bid_outcome",
            target_id=str(entry.id),
            metadata={"locale": get_locale()},
        )
        return [
            ValidationFinding(rule_id=r.rule_id, severity=r.severity.value, message=r.message, suggestion=r.suggestion)
            for r in report.results
            if not r.passed and not r.is_engine_error
        ]

    async def to_response(self, entry: BidOutcome, *, with_warnings: bool = False) -> BidOutcomeResponse:
        """Entry plus its derived price gap and, on request, its validation warnings."""
        out = BidOutcomeResponse.model_validate(entry)
        out.size_band = size_band(entry.our_price)
        for name, value in price_gap(entry).items():
            setattr(out, name, value)
        if with_warnings:
            out.warnings = await self.validate(entry)
        return out

    async def get(self, entry_id: uuid.UUID) -> BidOutcome:
        entry = await self.repo.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Bid outcome not found")
        return entry

    async def create(self, data: BidOutcomeCreate, user_id: str) -> BidOutcome:
        entry = BidOutcome(**data.model_dump(), created_by=uuid.UUID(str(user_id)))
        return await self.repo.create(entry)

    async def update(self, entry_id: uuid.UUID, data: BidOutcomeUpdate) -> BidOutcome:
        entry = await self.get(entry_id)
        fields = data.model_dump(exclude_unset=True)
        for required in ("title", "outcome", "our_price"):
            if required in fields and fields[required] is None:
                del fields[required]
        await self.repo.update_fields(entry_id, **fields)
        await self.repo.session.refresh(entry)
        return entry

    async def delete(self, entry_id: uuid.UUID) -> None:
        await self.get(entry_id)
        await self.repo.delete(entry_id)

    async def summary(self, currency: str | None) -> LedgerSummary:
        """Hit rate and money left on the table, in one currency (the most used by default)."""
        rows = await self.repo.list_all()
        currencies = sorted({r.currency or "" for r in rows})
        chosen = currency if currency is not None else dominant_currency(rows)
        stats = summarize([r for r in rows if (r.currency or "") == chosen])
        return LedgerSummary(currency=chosen, currencies=currencies, **stats)
