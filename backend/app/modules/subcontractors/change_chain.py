# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontract changes and the owner-to-subcontract change chain.

An owner change (a variation order in ``variations`` or a change order in
``changeorders``) is passed down to one or more subcontractors as
:class:`SubcontractChange` rows against their agreements. One owner change then
shows the value the owner grants beside the cost the subcontractors claim, and
the margin between them.

Approval is the only write that moves money: it adds the change amount to the
agreement value once, re-runs the finance budget sync (the same call activation
makes, so the commitment in cost control follows) and publishes
``subcontractors.change.approved``. Owner-side records are only read, never
written.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.core.i18n import get_locale
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.subcontractors.models import SubcontractAgreement, SubcontractChange

logger = logging.getLogger(__name__)

#: Rule set for subcontract changes, registered in ``register_builtin_rules``.
SUBCONTRACT_CHANGE_RULE_SET = "subcontract_change"

OWNER_CHANGE_TYPES = ("variation_order", "change_order")
_OWNER_PATTERN = r"^(variation_order|change_order)$"

#: Statuses whose amount counts against the owner change (rejected and withdrawn do not).
_LIVE_STATUSES = ("draft", "submitted", "approved")

_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted", "withdrawn"},
    "submitted": {"approved", "rejected", "withdrawn"},
    "approved": set(),
    "rejected": {"draft"},
    "withdrawn": set(),
}


# ── Schemas ──────────────────────────────────────────────────────────────


class SubcontractChangeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    agreement_id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    amount: Decimal = Field(max_digits=18, decimal_places=2)
    back_to_back: bool = True
    owner_change_type: str | None = Field(default=None, pattern=_OWNER_PATTERN)
    owner_change_id: uuid.UUID | None = None


class SubcontractChangeUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    back_to_back: bool | None = None
    owner_change_type: str | None = Field(default=None, pattern=_OWNER_PATTERN)
    owner_change_id: uuid.UUID | None = None


class SpawnLine(BaseModel):
    agreement_id: uuid.UUID
    amount: Decimal = Field(max_digits=18, decimal_places=2)
    title: str = Field(default="", max_length=500)
    back_to_back: bool = True


class SpawnFromOwnerChange(BaseModel):
    """Pass one owner change down to several subcontractors at once."""

    owner_change_type: str = Field(pattern=_OWNER_PATTERN)
    owner_change_id: uuid.UUID
    lines: list[SpawnLine] = Field(min_length=1, max_length=50)


class SubcontractChangeDecision(BaseModel):
    note: str = Field(default="", max_length=5000)


class SubcontractChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    agreement_id: uuid.UUID
    project_id: uuid.UUID
    code: str
    title: str
    description: str = ""
    amount: str
    currency: str = ""
    status: str
    back_to_back: bool
    owner_change_type: str | None = None
    owner_change_id: uuid.UUID | None = None
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str = ""
    applied_amount: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, row: SubcontractChange) -> SubcontractChangeResponse:
        data = {c: getattr(row, c) for c in cls.model_fields if hasattr(row, c)}
        data["amount"] = str(row.amount)
        data["applied_amount"] = str(row.applied_amount) if row.applied_amount is not None else None
        return cls.model_validate(data)


class OwnerChangeChainResponse(BaseModel):
    """One owner change, its subcontract changes and the margin between them."""

    owner_change_type: str
    owner_change_id: uuid.UUID
    owner_code: str = ""
    owner_title: str = ""
    owner_status: str = ""
    currency: str = ""
    owner_value: str
    sub_cost_approved: str
    sub_cost_pending: str
    sub_cost_total: str
    margin: str
    margin_percent: str | None = None
    changes: list[SubcontractChangeResponse]


# ── Service ──────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


class SubcontractChangeService:
    """Create, decide and report subcontract changes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _agreement(self, agreement_id: uuid.UUID) -> SubcontractAgreement:
        agreement = await self.session.get(SubcontractAgreement, agreement_id)
        if agreement is None:
            raise HTTPException(status_code=404, detail="Subcontract agreement not found")
        return agreement

    async def get(self, change_id: uuid.UUID) -> SubcontractChange:
        row = await self.session.get(SubcontractChange, change_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Subcontract change not found")
        return row

    async def owner_change(self, owner_type: str, owner_id: uuid.UUID) -> dict[str, Any] | None:
        """Read the owner change (never written here): project, value, code, status, currency."""
        if owner_type == "variation_order":
            from app.modules.variations.models import VariationOrder  # noqa: PLC0415

            vo = await self.session.get(VariationOrder, owner_id)
            if vo is None:
                return None
            return {
                "project_id": vo.project_id,
                "value": Decimal(str(vo.final_cost_impact or 0)),
                "code": vo.code,
                "title": vo.title,
                "status": vo.status,
                "currency": vo.currency or "",
            }
        if owner_type == "change_order":
            from app.modules.changeorders.models import ChangeOrder  # noqa: PLC0415

            co = await self.session.get(ChangeOrder, owner_id)
            if co is None:
                return None
            value = co.approved_amount if co.approved_amount is not None else co.cost_impact
            return {
                "project_id": co.project_id,
                "value": Decimal(str(value or 0)),
                "code": co.code,
                "title": co.title,
                "status": co.status,
                "currency": co.currency or "",
            }
        return None

    async def _assert_owner_link(
        self, owner_type: str | None, owner_id: uuid.UUID | None, project_id: uuid.UUID
    ) -> None:
        if owner_id is None and owner_type is None:
            return
        if owner_id is None or owner_type is None:
            raise HTTPException(status_code=422, detail="owner_change_type and owner_change_id go together")
        owner = await self.owner_change(owner_type, owner_id)
        if owner is None or owner["project_id"] != project_id:
            raise HTTPException(status_code=422, detail="The owner change must exist on the agreement's project")

    async def _next_code(self, agreement_id: uuid.UUID) -> str:
        count = (
            await self.session.execute(
                select(func.count())
                .select_from(SubcontractChange)
                .where(SubcontractChange.agreement_id == agreement_id)
            )
        ).scalar_one()
        return f"SCO-{int(count) + 1:03d}"

    async def create(self, data: SubcontractChangeCreate, user_id: str | None = None) -> SubcontractChange:
        agreement = await self._agreement(data.agreement_id)
        if agreement.status in ("completed", "terminated"):
            raise HTTPException(status_code=409, detail=f"Cannot change a '{agreement.status}' agreement")
        await self._assert_owner_link(data.owner_change_type, data.owner_change_id, agreement.project_id)
        row = SubcontractChange(
            agreement_id=agreement.id,
            project_id=agreement.project_id,
            code=await self._next_code(agreement.id),
            title=data.title,
            description=data.description,
            amount=data.amount,
            currency=agreement.currency or "",
            status="draft",
            back_to_back=data.back_to_back,
            owner_change_type=data.owner_change_type,
            owner_change_id=data.owner_change_id,
            created_by=user_id,
            metadata_={},
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def spawn_from_owner_change(
        self, data: SpawnFromOwnerChange, user_id: str | None = None
    ) -> list[SubcontractChange]:
        """Create one subcontract change per line, each linked to the owner change."""
        owner = await self.owner_change(data.owner_change_type, data.owner_change_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="Owner change not found")
        rows: list[SubcontractChange] = []
        for line in data.lines:
            rows.append(
                await self.create(
                    SubcontractChangeCreate(
                        agreement_id=line.agreement_id,
                        title=(line.title or f"{owner['code']} {owner['title']}".strip())[:500] or owner["code"],
                        amount=line.amount,
                        back_to_back=line.back_to_back,
                        owner_change_type=data.owner_change_type,
                        owner_change_id=data.owner_change_id,
                    ),
                    user_id=user_id,
                )
            )
        return rows

    async def update(self, change_id: uuid.UUID, data: SubcontractChangeUpdate) -> SubcontractChange:
        row = await self.get(change_id)
        if row.status not in ("draft", "rejected"):
            raise HTTPException(status_code=409, detail=f"A '{row.status}' change cannot be edited")
        fields = data.model_dump(exclude_unset=True)
        owner_type = fields.get("owner_change_type", row.owner_change_type)
        owner_id = fields.get("owner_change_id", row.owner_change_id)
        if "owner_change_type" in fields or "owner_change_id" in fields:
            await self._assert_owner_link(owner_type, owner_id, row.project_id)
        for key, value in fields.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def transition(
        self, change_id: uuid.UUID, new_status: str, user_id: str | None = None, note: str = ""
    ) -> SubcontractChange:
        row = await self.get(change_id)
        if new_status == row.status and new_status == "approved":
            return row  # replayed approval: nothing moves twice
        if new_status not in _TRANSITIONS.get(row.status, set()):
            raise HTTPException(status_code=409, detail=f"Cannot move a change from '{row.status}' to '{new_status}'")
        row.status = new_status
        if new_status == "submitted":
            row.submitted_at = _now()
        if new_status in ("approved", "rejected", "withdrawn"):
            row.decided_at = _now()
            row.decided_by = user_id
            row.decision_note = note
        if new_status == "approved":
            await self._apply_to_agreement(row)
        await self.session.flush()
        return row

    async def _apply_to_agreement(self, row: SubcontractChange) -> None:
        """Add the approved amount to the agreement value once and let the commitment follow."""
        if row.applied_amount is not None:
            return
        agreement = await self._agreement(row.agreement_id)
        agreement.total_value = Decimal(str(agreement.total_value or 0)) + Decimal(str(row.amount))
        row.applied_amount = row.amount
        await self.session.flush()
        try:
            from app.modules.finance.service import FinanceService  # noqa: PLC0415

            await FinanceService(self.session).sync_project_budget(agreement.project_id)
        except ImportError:  # pragma: no cover - finance is a core module
            logger.debug("finance absent; commitment not synced for change %s", row.id)
        publish_after_commit(
            self.session,
            "subcontractors.change.approved",
            {
                "change_id": str(row.id),
                "agreement_id": str(agreement.id),
                "project_id": str(agreement.project_id),
                "amount": str(row.amount),
                "currency": row.currency,
                "agreement_total_value": str(agreement.total_value),
                "owner_change_type": row.owner_change_type or "",
                "owner_change_id": str(row.owner_change_id) if row.owner_change_id else "",
            },
            source_module="subcontractors",
        )

    async def list_for_agreement(self, agreement_id: uuid.UUID) -> list[SubcontractChange]:
        stmt = (
            select(SubcontractChange)
            .where(SubcontractChange.agreement_id == agreement_id)
            .order_by(SubcontractChange.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_owner_change(self, owner_type: str, owner_id: uuid.UUID) -> list[SubcontractChange]:
        stmt = (
            select(SubcontractChange)
            .where(SubcontractChange.owner_change_type == owner_type, SubcontractChange.owner_change_id == owner_id)
            .order_by(SubcontractChange.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def chain(self, owner_type: str, owner_id: uuid.UUID) -> OwnerChangeChainResponse:
        """Owner value vs subcontract cost and margin for one owner change."""
        owner = await self.owner_change(owner_type, owner_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="Owner change not found")
        changes = await self.list_for_owner_change(owner_type, owner_id)
        approved = sum((Decimal(str(c.amount)) for c in changes if c.status == "approved"), Decimal("0"))
        pending = sum((Decimal(str(c.amount)) for c in changes if c.status in ("draft", "submitted")), Decimal("0"))
        total = approved + pending
        value: Decimal = owner["value"]
        margin = value - total
        pct = f"{(margin / value * 100).quantize(Decimal('0.01'))}" if value != 0 else None
        return OwnerChangeChainResponse(
            owner_change_type=owner_type,
            owner_change_id=owner_id,
            owner_code=owner["code"] or "",
            owner_title=owner["title"] or "",
            owner_status=owner["status"] or "",
            currency=owner["currency"],
            owner_value=str(value),
            sub_cost_approved=str(approved),
            sub_cost_pending=str(pending),
            sub_cost_total=str(total),
            margin=str(margin),
            margin_percent=pct,
            changes=[SubcontractChangeResponse.of(c) for c in changes],
        )

    async def validation_payload(self, row: SubcontractChange) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": row.code,
            "title": row.title,
            "amount": str(row.amount),
            "currency": row.currency,
            "back_to_back": bool(row.back_to_back),
            "owner_change_type": row.owner_change_type,
            "owner_change_id": str(row.owner_change_id) if row.owner_change_id else None,
        }
        if row.owner_change_type and row.owner_change_id:
            owner = await self.owner_change(row.owner_change_type, row.owner_change_id)
            if owner is not None:
                siblings = await self.list_for_owner_change(row.owner_change_type, row.owner_change_id)
                payload["owner_change_value"] = str(owner["value"])
                payload["linked_sub_total"] = str(
                    sum((Decimal(str(c.amount)) for c in siblings if c.status in _LIVE_STATUSES), Decimal("0"))
                )
        return payload

    async def validate(self, change_id: uuid.UUID) -> ValidationReport:
        row = await self.get(change_id)
        return await validation_engine.validate(
            data=await self.validation_payload(row),
            rule_sets=[SUBCONTRACT_CHANGE_RULE_SET],
            target_type="subcontract_change",
            target_id=str(row.id),
            project_id=str(row.project_id),
            metadata={"locale": get_locale(), "operation": "read"},
        )
