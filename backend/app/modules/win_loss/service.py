# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger service: CRUD, validation and the summary."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.dependencies import accessible_project_ids, verify_project_access
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
        self.session = session

    async def list_entries(
        self, user_id: str, *, outcome: str | None = None, client: str | None = None, limit: int = 500, offset: int = 0
    ) -> tuple[list[BidOutcome], int]:
        """One page of entries the caller may see, and how many matched the filters."""
        ids = await accessible_project_ids(self.session, user_id)
        rows = await self.repo.list_all(outcome=outcome, client=client, limit=limit, project_ids=ids, offset=offset)
        return rows, await self.repo.count_all(outcome=outcome, client=client, project_ids=ids)

    async def get_for_user(self, entry_id: uuid.UUID, user_id: str) -> BidOutcome:
        """Load an entry; one linked to a project needs access to that project."""
        entry = await self.get(entry_id)
        if entry.project_id is not None:
            await verify_project_access(entry.project_id, user_id, self.session)
        return entry

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
        try:
            async with self.session.begin_nested():
                return await self.repo.create(entry)
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="This tender already has an outcome record") from exc

    async def for_tender(self, tender_id: uuid.UUID) -> BidOutcome | None:
        """The single outcome record of a tender, if any."""
        return await self.repo.get_by_tender(tender_id)

    async def update(self, entry_id: uuid.UUID, data: BidOutcomeUpdate, user_id: str) -> BidOutcome:
        entry = await self.get_for_user(entry_id, user_id)
        fields = data.model_dump(exclude_unset=True)
        expected = fields.pop("version", None)
        if expected is not None and expected != entry.version:
            raise HTTPException(status_code=409, detail="The entry was changed by someone else since you loaded it")
        for required in ("title", "outcome", "our_price", "currency", "client_name", "trade", "notes"):
            if required in fields and fields[required] is None:
                del fields[required]
        fields["version"] = entry.version + 1
        try:
            async with self.session.begin_nested():
                await self.repo.update_fields(entry_id, **fields)
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="This tender already has an outcome record") from exc
        await self.repo.session.refresh(entry)
        return entry

    async def delete(self, entry_id: uuid.UUID, user_id: str) -> None:
        await self.get_for_user(entry_id, user_id)
        await self.repo.delete(entry_id)

    async def summary(self, currency: str | None, user_id: str) -> LedgerSummary:
        """Hit rate and money left on the table, in one currency (the most used by default)."""
        rows, _ = await self.list_entries(user_id, limit=10000)
        currencies = sorted({r.currency or "" for r in rows})
        chosen = currency.upper() if currency is not None else dominant_currency(rows)
        stats = summarize([r for r in rows if (r.currency or "") == chosen])
        return LedgerSummary(currency=chosen, currencies=currencies, **stats)
