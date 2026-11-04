# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget ledger: transfers between cost lines and owner-approved budget modifications.

Both go draft -> submitted -> approved or rejected. Only approved entries change the revised budget the
cost control rows show; an approved or rejected entry is never edited or deleted. Every step is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.costmodel.budget_ledger_models import (
    BudgetLedgerAudit,
    BudgetModification,
    BudgetTransfer,
    BudgetTransferLeg,
)
from app.modules.costmodel.budget_ledger_rules import PAYLOAD_KEY, RULE_SET
from app.modules.costmodel.budget_ledger_schemas import (
    AuditOut,
    BudgetLedger,
    LegOut,
    LineEffect,
    ModificationIn,
    ModificationOut,
    TransferIn,
    TransferOut,
)
from app.modules.costmodel.models import CostLine

ZERO = Decimal("0")
Q = Decimal("0.01")
FINAL = ("approved", "rejected")
CODE_RETRIES = 5

# action -> (statuses it may start from, status it ends in)
STEPS: dict[str, tuple[tuple[str, ...], str]] = {
    "submit": (("draft",), "submitted"),
    "approve": (("submitted",), "approved"),
    "reject": (("submitted",), "rejected"),
}


async def approved_budget_delta(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Decimal]:
    """Net approved transfer legs plus approved modifications per cost line id (two queries)."""
    out: dict[str, Decimal] = {}
    legs = await session.execute(
        select(BudgetTransferLeg.cost_line_id, BudgetTransferLeg.amount)
        .join(BudgetTransfer, BudgetTransfer.id == BudgetTransferLeg.transfer_id)
        .where(BudgetTransfer.project_id == project_id, BudgetTransfer.status == "approved")
    )
    mods = await session.execute(
        select(BudgetModification.cost_line_id, BudgetModification.amount).where(
            BudgetModification.project_id == project_id, BudgetModification.status == "approved"
        )
    )
    for line_id, amount in [*legs.all(), *mods.all()]:
        out[str(line_id)] = out.get(str(line_id), ZERO) + Decimal(amount)
    return out


def _detail(results: list[Any]) -> list[dict[str, str]]:
    return [
        {"rule_id": r.rule_id, "msg": r.message, "message": r.message, "suggestion": r.suggestion or ""}
        for r in results
    ]


def _err(status_code: int, code: str, message: str, **params: Any) -> HTTPException:
    """An HTTP error whose ``detail`` carries a translatable key (``api_errors.budget_ledger_<code>``)."""
    return HTTPException(
        status_code,
        detail={
            "code": f"budget_ledger_{code}",
            "message": message,
            "params": params,
        },
    )


def _no_zero(amount: Decimal) -> Decimal:
    amount = amount.quantize(Q)
    if amount == 0:
        raise _err(422, "amount_zero", "The amount must not be zero")
    return amount


class BudgetLedgerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── validation ────────────────────────────────────────────────────────

    async def _refuse_on_errors(self, payload: dict[str, Any], project_id: uuid.UUID, locale: str) -> None:
        context = ValidationContext(
            data={PAYLOAD_KEY: payload}, project_id=str(project_id), metadata={"locale": locale}
        )
        failed = []
        for rule in rule_registry.get_rules_for_sets([RULE_SET]):
            if rule.enabled:
                failed += [r for r in await rule.validate(context) if not r.passed]
        if failed:
            raise HTTPException(422, detail=_detail(failed))

    async def _spine(self, project_id: uuid.UUID) -> tuple[Any, str, dict[str, Decimal], dict[str, Decimal]]:
        from app.modules.costmodel.repository import CostSpineRepository

        spine = CostSpineRepository(self.session)
        base, _fx = await spine._fx_context(project_id)
        original = {
            k: v.get("planned", ZERO) for k, v in (await spine.budget_aggregate_by_cost_line(project_id)).items()
        }
        return spine, base, original, await spine.committed_by_cost_line(project_id)

    async def _codes(self, project_id: uuid.UUID) -> dict[str, str]:
        rows = await self.session.execute(select(CostLine.id, CostLine.code).where(CostLine.project_id == project_id))
        return {str(i): c for i, c in rows.all()}

    async def _payload(
        self, project_id: uuid.UUID, kind: str, action: str, legs: list[tuple[uuid.UUID, Decimal]], entry: Any = None
    ) -> dict[str, Any]:
        """The rule payload; budgets are the revised figures now, without this entry's own effect."""
        _spine, base, planned, committed = await self._spine(project_id)
        for k, v in (await approved_budget_delta(self.session, project_id)).items():
            planned[k] = planned.get(k, ZERO) + v
        codes = await self._codes(project_id)
        if any(str(i) not in codes for i, _ in legs):
            raise _err(status.HTTP_404_NOT_FOUND, "cost_line_not_found", "Cost line not found in this project")
        return {
            "kind": kind,
            "action": action,
            "status": entry.status if entry is not None else "draft",
            "code": entry.code if entry is not None else "",
            "currency": base,
            "legs": [
                {
                    "cost_line_id": str(i),
                    "code": codes[str(i)],
                    "amount": str(a),
                    "budget": str(planned.get(str(i), ZERO)),
                    "committed": str(committed.get(str(i), ZERO)),
                }
                for i, a in legs
            ],
        }

    # ── helpers ───────────────────────────────────────────────────────────

    async def _next_code(self, model: Any, prefix: str, project_id: uuid.UUID, skip: int = 0) -> str:
        rows = await self.session.execute(select(model.code).where(model.project_id == project_id))
        used = [int(c.rsplit("-", 1)[-1]) for (c,) in rows.all() if c.rsplit("-", 1)[-1].isdigit()]
        return f"{prefix}-{max(used, default=0) + 1 + skip:03d}"

    async def _add_coded(self, model: Any, prefix: str, project_id: uuid.UUID, **fields: Any) -> Any:
        """Insert a row under the next free code; a concurrent writer taking it first makes us take the next one."""
        for attempt in range(CODE_RETRIES):
            row = model(project_id=project_id, code=await self._next_code(model, prefix, project_id, attempt), **fields)
            try:
                async with self.session.begin_nested():
                    self.session.add(row)
                    await self.session.flush()
            except IntegrityError:
                continue
            return row
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Could not allocate a free entry code, try again")

    def _audit(
        self,
        project_id: uuid.UUID,
        kind: str,
        entity_id: uuid.UUID,
        action: str,
        frm: str,
        to: str,
        actor: str | None,
        note: str = "",
    ) -> None:
        self.session.add(
            BudgetLedgerAudit(
                project_id=project_id,
                entity_kind=kind,
                entity_id=entity_id,
                action=action,
                from_status=frm,
                to_status=to,
                actor=actor,
                note=note,
            )
        )

    async def _get(self, model: Any, project_id: uuid.UUID, entry_id: uuid.UUID) -> Any:
        row = await self.session.get(model, entry_id)
        if row is None or row.project_id != project_id:
            raise _err(status.HTTP_404_NOT_FOUND, "entry_not_found", "Entry not found")
        return row

    async def _legs(self, transfer_id: uuid.UUID) -> list[BudgetTransferLeg]:
        rows = await self.session.execute(
            select(BudgetTransferLeg)
            .where(BudgetTransferLeg.transfer_id == transfer_id)
            .order_by(BudgetTransferLeg.created_at, BudgetTransferLeg.amount)
        )
        return list(rows.scalars())

    async def _guard(self, kind: str, entry: Any, action: str, locale: str) -> None:
        """The immutability rule for an edit or delete; a draft is the only thing that may change."""
        payload = {"kind": kind, "action": action, "guard": True, "status": entry.status, "code": entry.code}
        await self._refuse_on_errors(payload, entry.project_id, locale)
        if entry.status != "draft":
            raise _err(status.HTTP_409_CONFLICT, "draft_only", "Only a draft can be changed")

    async def _step(
        self,
        kind: str,
        model: Any,
        project_id: uuid.UUID,
        entry_id: uuid.UUID,
        action: str,
        user_id: str | None,
        note: str,
        locale: str,
    ) -> Any:
        allowed, to = STEPS[action]
        entry = await self._get(model, project_id, entry_id)
        await self._guard_final(kind, entry, locale)
        if entry.status not in allowed:
            raise _err(
                status.HTTP_409_CONFLICT,
                "step_not_allowed",
                "This entry cannot be moved to that step from its current status",
            )
        if action == "reject" and not note.strip():
            raise _err(422, "reject_reason_required", "A rejection needs a reason")
        if action in ("submit", "approve"):
            if kind == "transfer":
                legs = [(g.cost_line_id, g.amount) for g in await self._legs(entry.id)]
            else:
                legs = [(entry.cost_line_id, entry.amount)]
            if action == "approve":
                # Serialise approvals on the same lines so two reductions cannot both pass the committed check.
                await self.session.execute(
                    select(CostLine.id).where(CostLine.id.in_(sorted({i for i, _ in legs}))).with_for_update()
                )
            await self._refuse_on_errors(await self._payload(project_id, kind, action, legs, entry), project_id, locale)
        before, entry.status = entry.status, to
        now = datetime.now(UTC)
        if action == "submit":
            entry.submitted_at = now
        if action in ("approve", "reject"):
            entry.decided_by, entry.decided_at, entry.decision_note = user_id, now, note.strip()
        self._audit(project_id, kind, entry.id, action, before, to, user_id, note.strip())
        await self.session.flush()
        return entry

    async def _guard_final(self, kind: str, entry: Any, locale: str) -> None:
        """A decided entry takes no further step; the rule says why."""
        if entry.status in FINAL:
            payload = {"kind": kind, "action": "edit", "guard": True, "status": entry.status, "code": entry.code}
            await self._refuse_on_errors(payload, entry.project_id, locale)

    # ── transfers ─────────────────────────────────────────────────────────

    async def create_transfer(
        self, project_id: uuid.UUID, body: TransferIn, user_id: str | None, locale: str
    ) -> TransferOut:
        legs = [(g.cost_line_id, g.amount.quantize(Q)) for g in body.legs]
        await self._refuse_on_errors(await self._payload(project_id, "transfer", "create", legs), project_id, locale)
        transfer = await self._add_coded(
            BudgetTransfer,
            "BT",
            project_id,
            reason=body.reason.strip(),
            requested_by=user_id,
            status="draft",
            decision_note="",
        )
        for line_id, amount in legs:
            self.session.add(BudgetTransferLeg(transfer_id=transfer.id, cost_line_id=line_id, amount=amount))
        self._audit(project_id, "transfer", transfer.id, "create", "", "draft", user_id)
        await self.session.flush()
        return await self._transfer_out(transfer)

    async def update_transfer(
        self, project_id: uuid.UUID, entry_id: uuid.UUID, body: TransferIn, user_id: str | None, locale: str
    ) -> TransferOut:
        transfer = await self._get(BudgetTransfer, project_id, entry_id)
        await self._guard("transfer", transfer, "edit", locale)
        legs = [(g.cost_line_id, g.amount.quantize(Q)) for g in body.legs]
        payload = await self._payload(project_id, "transfer", "edit", legs, transfer)
        await self._refuse_on_errors(payload, project_id, locale)
        await self.session.execute(delete(BudgetTransferLeg).where(BudgetTransferLeg.transfer_id == transfer.id))
        for line_id, amount in legs:
            self.session.add(BudgetTransferLeg(transfer_id=transfer.id, cost_line_id=line_id, amount=amount))
        transfer.reason = body.reason.strip()
        self._audit(project_id, "transfer", transfer.id, "edit", "draft", "draft", user_id)
        await self.session.flush()
        return await self._transfer_out(transfer)

    async def delete_transfer(
        self, project_id: uuid.UUID, entry_id: uuid.UUID, user_id: str | None, locale: str
    ) -> None:
        transfer = await self._get(BudgetTransfer, project_id, entry_id)
        await self._guard("transfer", transfer, "delete", locale)
        self._audit(project_id, "transfer", transfer.id, "delete", "draft", "", user_id)
        await self.session.delete(transfer)
        await self.session.flush()

    async def transfer_step(
        self, project_id: uuid.UUID, entry_id: uuid.UUID, action: str, user_id: str | None, note: str, locale: str
    ) -> TransferOut:
        entry = await self._step("transfer", BudgetTransfer, project_id, entry_id, action, user_id, note, locale)
        return await self._transfer_out(entry)

    # ── modifications ─────────────────────────────────────────────────────

    async def create_modification(
        self, project_id: uuid.UUID, body: ModificationIn, user_id: str | None, locale: str
    ) -> ModificationOut:
        amount = _no_zero(body.amount)
        payload = await self._payload(project_id, "modification", "create", [(body.cost_line_id, amount)])
        await self._refuse_on_errors(payload, project_id, locale)
        mod = await self._add_coded(
            BudgetModification,
            "BM",
            project_id,
            cost_line_id=body.cost_line_id,
            amount=amount,
            reason=body.reason.strip(),
            approval_ref=body.approval_ref.strip(),
            requested_by=user_id,
            status="draft",
            decision_note="",
        )
        self._audit(project_id, "modification", mod.id, "create", "", "draft", user_id)
        await self.session.flush()
        return self._mod_out(mod, await self._codes(project_id))

    async def update_modification(
        self, project_id: uuid.UUID, entry_id: uuid.UUID, body: ModificationIn, user_id: str | None, locale: str
    ) -> ModificationOut:
        mod = await self._get(BudgetModification, project_id, entry_id)
        await self._guard("modification", mod, "edit", locale)
        amount = _no_zero(body.amount)
        payload = await self._payload(project_id, "modification", "edit", [(body.cost_line_id, amount)], mod)
        await self._refuse_on_errors(payload, project_id, locale)
        mod.cost_line_id, mod.amount = body.cost_line_id, amount
        mod.reason, mod.approval_ref = body.reason.strip(), body.approval_ref.strip()
        self._audit(project_id, "modification", mod.id, "edit", "draft", "draft", user_id)
        await self.session.flush()
        return self._mod_out(mod, await self._codes(project_id))

    async def delete_modification(
        self, project_id: uuid.UUID, entry_id: uuid.UUID, user_id: str | None, locale: str
    ) -> None:
        mod = await self._get(BudgetModification, project_id, entry_id)
        await self._guard("modification", mod, "delete", locale)
        self._audit(project_id, "modification", mod.id, "delete", "draft", "", user_id)
        await self.session.delete(mod)
        await self.session.flush()

    async def modification_step(
        self, project_id: uuid.UUID, entry_id: uuid.UUID, action: str, user_id: str | None, note: str, locale: str
    ) -> ModificationOut:
        entry = await self._step(
            "modification", BudgetModification, project_id, entry_id, action, user_id, note, locale
        )
        return self._mod_out(entry, await self._codes(project_id))

    # ── reading ───────────────────────────────────────────────────────────

    @staticmethod
    def _transfer_view(t: BudgetTransfer, legs: list[BudgetTransferLeg], codes: dict[str, str]) -> TransferOut:
        return TransferOut(
            id=t.id,
            code=t.code,
            status=t.status,
            reason=t.reason,
            legs=[
                LegOut(cost_line_id=g.cost_line_id, code=codes.get(str(g.cost_line_id), ""), amount=g.amount)
                for g in legs
            ],
            moved=sum((g.amount for g in legs if g.amount > 0), ZERO),
            requested_by=t.requested_by,
            submitted_at=t.submitted_at,
            decided_by=t.decided_by,
            decided_at=t.decided_at,
            decision_note=t.decision_note,
            created_at=t.created_at,
        )

    async def _transfer_out(self, t: BudgetTransfer) -> TransferOut:
        return self._transfer_view(t, await self._legs(t.id), await self._codes(t.project_id))

    @staticmethod
    def _mod_out(m: BudgetModification, codes: dict[str, str]) -> ModificationOut:
        return ModificationOut(
            id=m.id,
            code=m.code,
            status=m.status,
            cost_line_id=m.cost_line_id,
            line_code=codes.get(str(m.cost_line_id), ""),
            amount=m.amount,
            reason=m.reason,
            approval_ref=m.approval_ref,
            requested_by=m.requested_by,
            submitted_at=m.submitted_at,
            decided_by=m.decided_by,
            decided_at=m.decided_at,
            decision_note=m.decision_note,
            created_at=m.created_at,
        )

    async def ledger(self, project_id: uuid.UUID) -> BudgetLedger:
        _spine, base, original, committed = await self._spine(project_id)
        codes = await self._codes(project_id)
        transfers = list(
            (
                await self.session.execute(
                    select(BudgetTransfer)
                    .where(BudgetTransfer.project_id == project_id)
                    .order_by(BudgetTransfer.created_at.desc())
                )
            ).scalars()
        )
        mods = list(
            (
                await self.session.execute(
                    select(BudgetModification)
                    .where(BudgetModification.project_id == project_id)
                    .order_by(BudgetModification.created_at.desc())
                )
            ).scalars()
        )
        legs_by_transfer: dict[uuid.UUID, list[BudgetTransferLeg]] = {}
        if transfers:
            rows = await self.session.execute(
                select(BudgetTransferLeg)
                .where(BudgetTransferLeg.transfer_id.in_([t.id for t in transfers]))
                .order_by(BudgetTransferLeg.created_at, BudgetTransferLeg.amount)
            )
            for g in rows.scalars():
                legs_by_transfer.setdefault(g.transfer_id, []).append(g)
        by_transfer: dict[str, Decimal] = {}
        by_mod: dict[str, Decimal] = {}
        for t in transfers:
            if t.status == "approved":
                for g in legs_by_transfer.get(t.id, []):
                    by_transfer[str(g.cost_line_id)] = by_transfer.get(str(g.cost_line_id), ZERO) + g.amount
        for m in mods:
            if m.status == "approved":
                by_mod[str(m.cost_line_id)] = by_mod.get(str(m.cost_line_id), ZERO) + m.amount
        lines = [
            LineEffect(
                cost_line_id=uuid.UUID(k),
                code=codes.get(k, ""),
                original=original.get(k, ZERO),
                transfers=by_transfer.get(k, ZERO),
                modifications=by_mod.get(k, ZERO),
                revised=original.get(k, ZERO) + by_transfer.get(k, ZERO) + by_mod.get(k, ZERO),
                committed=committed.get(k, ZERO),
            )
            for k in sorted(set(by_transfer) | set(by_mod), key=lambda x: codes.get(x, x))
        ]
        audit = (
            await self.session.execute(
                select(BudgetLedgerAudit)
                .where(BudgetLedgerAudit.project_id == project_id)
                .order_by(BudgetLedgerAudit.created_at.desc())
                .limit(200)
            )
        ).scalars()
        return BudgetLedger(
            project_id=project_id,
            currency=base,
            transfers=[self._transfer_view(t, legs_by_transfer.get(t.id, []), codes) for t in transfers],
            modifications=[self._mod_out(m, codes) for m in mods],
            lines=lines,
            pending_transfers=sum(1 for t in transfers if t.status == "submitted"),
            pending_modifications=sum(1 for m in mods if m.status == "submitted"),
            audit=[AuditOut.model_validate(a, from_attributes=True) for a in audit],
        )
