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

Pass-through economics (deterministic, no AI): a back-to-back change carries the
owner amount less the GC markup, a time impact in days, and cannot be approved
until the owner change it mirrors is approved. ``chain()`` shows what the GC
absorbs when subcontractors claim more than the owner granted.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
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

#: Owner change-order statuses that count as approved (variation orders reuse the
#: variations module's agreed-value statuses).
_CO_APPROVED_STATUSES = frozenset({"approved", "executed"})

#: Error code of the 409 raised when a back-to-back change is approved before the owner change.
OWNER_NOT_APPROVED_CODE = "subcontract.change_owner_not_approved"

_CENT = Decimal("0.01")

_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted", "withdrawn"},
    "submitted": {"approved", "rejected", "withdrawn"},
    "approved": set(),
    "rejected": {"draft"},
    "withdrawn": set(),
}


def pass_through(owner_amount: Decimal, markup_pct: Decimal, back_to_back: bool) -> Decimal:
    """Subcontract amount for an owner amount: back-to-back keeps the GC markup, otherwise it is entered freely."""
    owner = Decimal(str(owner_amount))
    if not back_to_back:
        return owner.quantize(_CENT, rounding=ROUND_HALF_UP)
    factor = Decimal(1) - Decimal(str(markup_pct)) / Decimal(100)
    return (owner * factor).quantize(_CENT, rounding=ROUND_HALF_UP)


def owner_change_is_approved(owner_type: str | None, status: str | None) -> bool:
    """True when the owner variation order or change order has reached an approved state."""
    code = (status or "").lower()
    if owner_type == "change_order":
        return code in _CO_APPROVED_STATUSES
    if owner_type == "variation_order":
        from app.modules.variations.service import AGREED_VALUE_STATUSES  # noqa: PLC0415

        return code in AGREED_VALUE_STATUSES
    return False


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
    owner_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    markup_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=3)
    time_impact_days: int = Field(default=0, ge=-3650, le=3650)
    owner_time_days: int | None = Field(default=None, ge=-3650, le=3650)


class SubcontractChangeUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    back_to_back: bool | None = None
    owner_change_type: str | None = Field(default=None, pattern=_OWNER_PATTERN)
    owner_change_id: uuid.UUID | None = None
    owner_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    markup_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=3)
    time_impact_days: int | None = Field(default=None, ge=-3650, le=3650)
    owner_time_days: int | None = Field(default=None, ge=-3650, le=3650)


class SpawnLine(BaseModel):
    """One subcontractor's share of an owner change.

    Back-to-back with no ``amount``: it is computed from ``owner_share`` (the whole
    owner value when this is the only line) less ``markup_pct``.
    """

    agreement_id: uuid.UUID
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    owner_share: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    markup_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=3)
    time_impact_days: int = Field(default=0, ge=-3650, le=3650)
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
    owner_amount: str | None = None
    markup_pct: str = "0"
    time_impact_days: int = 0
    owner_time_days: int | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, row: SubcontractChange) -> SubcontractChangeResponse:
        data = {c: getattr(row, c) for c in cls.model_fields if hasattr(row, c)}
        data["amount"] = str(row.amount)
        data["applied_amount"] = str(row.applied_amount) if row.applied_amount is not None else None
        data["owner_amount"] = str(row.owner_amount) if row.owner_amount is not None else None
        data["markup_pct"] = str(row.markup_pct if row.markup_pct is not None else 0)
        data["time_impact_days"] = int(row.time_impact_days or 0)
        return cls.model_validate(data)


class SubcontractChangeListResponse(BaseModel):
    items: list[SubcontractChangeResponse]
    total: int
    offset: int = 0
    limit: int = 200


class MarkBilled(BaseModel):
    application_id: uuid.UUID


class SovChangeLine(BaseModel):
    """An approved, not yet billed change offered as a payment application line."""

    change_id: uuid.UUID
    code: str
    title: str
    amount: str
    currency: str = ""
    markup_pct: str = "0"
    time_impact_days: int = 0

    @classmethod
    def of(cls, row: SubcontractChange) -> SovChangeLine:
        return cls(
            change_id=row.id,
            code=row.code,
            title=row.title,
            amount=str(row.applied_amount if row.applied_amount is not None else row.amount),
            currency=row.currency,
            markup_pct=str(row.markup_pct if row.markup_pct is not None else 0),
            time_impact_days=int(row.time_impact_days or 0),
        )


class SovChangeLineListResponse(BaseModel):
    items: list[SovChangeLine]
    total: int
    offset: int = 0
    limit: int = 200


class OwnerChangeChainResponse(BaseModel):
    """One owner change, its subcontract changes and the margin between them."""

    owner_change_type: str
    owner_change_id: uuid.UUID
    owner_code: str = ""
    owner_title: str = ""
    owner_status: str = ""
    #: True once the owner variation or change order is approved (the gate for back-to-back approval).
    owner_approved: bool = False
    currency: str = ""
    owner_value: str
    sub_cost_approved: str
    sub_cost_pending: str
    sub_cost_total: str
    margin: str
    margin_percent: str | None = None
    approved_sub_total: str = "0"
    markup_retained: str = "0"
    #: owner value - approved sub total - GC markup kept; negative = the GC absorbs the difference.
    leakage: str = "0"
    days_owner: int | None = None
    days_sub_total: int = 0
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
                "days": int(vo.final_schedule_days or 0),
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
                "days": co.approved_time_days if co.approved_time_days is not None else co.time_impact_days,
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
        owner_amount, owner_time_days = data.owner_amount, data.owner_time_days
        if data.owner_change_type and data.owner_change_id and (owner_amount is None or owner_time_days is None):
            owner = await self.owner_change(data.owner_change_type, data.owner_change_id)
            alone = not await self.list_for_owner_change(data.owner_change_type, data.owner_change_id)
            if owner is not None and alone:
                owner_amount = owner["value"] if owner_amount is None else owner_amount
                owner_time_days = owner["days"] if owner_time_days is None else owner_time_days
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
            owner_amount=owner_amount,
            markup_pct=data.markup_pct,
            time_impact_days=data.time_impact_days,
            owner_time_days=owner_time_days,
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
            share = line.owner_share
            if share is None and len(data.lines) == 1:
                share = owner["value"]
            amount = line.amount
            if amount is None:
                if not line.back_to_back or share is None:
                    raise HTTPException(
                        status_code=422, detail="A line needs an amount, or an owner_share to pass down"
                    )
                amount = pass_through(share, line.markup_pct, True)
            rows.append(
                await self.create(
                    SubcontractChangeCreate(
                        agreement_id=line.agreement_id,
                        title=(line.title or f"{owner['code']} {owner['title']}".strip())[:500] or owner["code"],
                        amount=amount,
                        back_to_back=line.back_to_back,
                        owner_change_type=data.owner_change_type,
                        owner_change_id=data.owner_change_id,
                        owner_amount=share,
                        markup_pct=line.markup_pct,
                        time_impact_days=line.time_impact_days,
                        owner_time_days=owner["days"],
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
            if key in ("markup_pct", "time_impact_days") and value is None:
                continue
            setattr(row, key, value)
        recompute = ("owner_amount" in fields or "markup_pct" in fields) and "amount" not in fields
        if recompute and row.back_to_back and row.owner_amount is not None:
            row.amount = pass_through(row.owner_amount, row.markup_pct or Decimal("0"), True)
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
        if new_status == "approved":
            await self._assert_owner_approved(row)
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

    async def _assert_owner_approved(self, row: SubcontractChange) -> None:
        """A back-to-back change is paid only once the owner has approved what it mirrors."""
        if not row.back_to_back or not (row.owner_change_type and row.owner_change_id):
            return
        owner = await self.owner_change(row.owner_change_type, row.owner_change_id)
        status = (owner["status"] if owner is not None else "") or ""
        if owner is None or not owner_change_is_approved(row.owner_change_type, status):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": OWNER_NOT_APPROVED_CODE,
                    "owner_status": status,
                    "message": "Owner change not approved yet",
                },
            )

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
                "markup_pct": str(row.markup_pct if row.markup_pct is not None else 0),
                "time_impact_days": int(row.time_impact_days or 0),
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

    async def page_for_agreement(
        self, agreement_id: uuid.UUID, *, offset: int = 0, limit: int = 200
    ) -> tuple[list[SubcontractChange], int]:
        where = SubcontractChange.agreement_id == agreement_id
        stmt = (
            select(SubcontractChange)
            .where(where)
            .order_by(SubcontractChange.created_at, SubcontractChange.id)
            .offset(offset)
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        total = (await self.session.execute(select(func.count()).select_from(SubcontractChange).where(where))).scalar()
        return rows, int(total or 0)

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
        retained = sum(
            (
                Decimal(str(c.owner_amount)) * Decimal(str(c.markup_pct or 0)) / Decimal(100)
                for c in changes
                if c.status == "approved" and c.back_to_back and c.owner_amount is not None
            ),
            Decimal("0"),
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
        leakage = value - approved - retained
        live_days = sum(int(c.time_impact_days or 0) for c in changes if c.status in _LIVE_STATUSES)
        pct = f"{(margin / value * 100).quantize(Decimal('0.01'))}" if value != 0 else None
        return OwnerChangeChainResponse(
            owner_change_type=owner_type,
            owner_change_id=owner_id,
            owner_code=owner["code"] or "",
            owner_title=owner["title"] or "",
            owner_status=owner["status"] or "",
            owner_approved=owner_change_is_approved(owner_type, owner["status"]),
            currency=owner["currency"],
            owner_value=str(value),
            sub_cost_approved=str(approved),
            sub_cost_pending=str(pending),
            sub_cost_total=str(total),
            margin=str(margin),
            margin_percent=pct,
            approved_sub_total=str(approved),
            markup_retained=str(retained),
            leakage=str(leakage),
            days_owner=owner.get("days"),
            days_sub_total=live_days,
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
            "time_impact_days": int(row.time_impact_days or 0),
        }
        if row.owner_change_type and row.owner_change_id:
            owner = await self.owner_change(row.owner_change_type, row.owner_change_id)
            if owner is not None:
                payload["owner_change_status"] = owner["status"] or ""
                payload["owner_change_approved"] = owner_change_is_approved(row.owner_change_type, owner["status"])
                owner_days = row.owner_time_days if row.owner_time_days is not None else owner.get("days")
                siblings = await self.list_for_owner_change(row.owner_change_type, row.owner_change_id)
                payload["owner_change_value"] = str(owner["value"])
                if owner_days is not None:
                    payload["owner_time_days"] = int(owner_days)
                    payload["linked_time_days"] = sum(
                        int(c.time_impact_days or 0) for c in siblings if c.status in _LIVE_STATUSES
                    )
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

    async def sov_lines(self, agreement_id: uuid.UUID) -> list[SubcontractChange]:
        """Approved changes not yet billed: candidate lines for the next payment application."""
        rows = await self.list_for_agreement(agreement_id)
        return [
            r
            for r in rows
            if r.status == "approved" and r.applied_amount is not None and not (r.metadata_ or {}).get("billed_in")
        ]

    async def mark_billed(self, change_id: uuid.UUID, application_id: uuid.UUID) -> SubcontractChange:
        """Record the payment application that billed an approved change, once."""
        from app.modules.subcontractors.models import PaymentApplication  # noqa: PLC0415

        row = await self.get(change_id)
        if row.status != "approved" or row.applied_amount is None:
            raise HTTPException(status_code=409, detail="Only an approved change can be billed")
        application = await self.session.get(PaymentApplication, application_id)
        if application is None or application.agreement_id != row.agreement_id:
            raise HTTPException(status_code=422, detail="The payment application must belong to the same agreement")
        meta = dict(row.metadata_ or {})
        billed = meta.get("billed_in")
        if billed == str(application_id):
            return row
        if billed:
            raise HTTPException(status_code=409, detail="This change is already billed in another application")
        meta["billed_in"] = str(application_id)
        row.metadata_ = meta
        await self.session.flush()
        return row
