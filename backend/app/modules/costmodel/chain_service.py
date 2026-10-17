# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The chain panel of cost control: suspense buckets, the chain rules, and their fixes.

Three things a controller does with the money below the bill, served together
so the screen needs one request:

* **Suspense.** Everything that carries money and sits on no cost line, by
  kind: contract lines, order items and contracts without a schedule (these
  are the "not on any cost line" row of the report, the same amounts), and
  change order items and supplier invoice lines (informative: their money
  reaches the report through the contract lines they post to). Each row says
  whether it can inherit an account, so one action can fill all of those.
* **Findings** of rules V6 to V10 and V15 (:mod:`.chain_rules`), messages in
  the reader's language.
* **Fixes**: take accounts from the bill for every row that can inherit one;
  put one row on an account by hand (see
  :func:`~app.modules.costmodel.inheritance_service.set_vector`); record a
  supplier invoice without a contract as a direct cost on one account.

All money is converted to the project currency, the way the report does it.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.chain_rules import PAYLOAD_KEY, RULE_SET
from app.modules.costmodel.cost_control_data import (
    APPROVED_CHANGE_STATUSES,
    PENDING_CHANGE_STATUSES,
    load_control_data,
)
from app.modules.costmodel.inheritance import (
    FROM_CONTRACT_LINE,
    SOURCE_CONTRACT_LINE,
    SOURCE_INVOICE_LINE,
    first_inherited,
    lines_in_project,
    row_vectors,
    write_split,
)
from app.modules.costmodel.inheritance_service import (
    KIND_CHANGE_ITEM,
    KIND_CONTRACT,
    KIND_CONTRACT_LINE,
    KIND_INVOICE_LINE,
    KIND_PO_ITEM,
    apply_change_item_inheritance,
    change_item_inherits,
    contract_line_candidates,
    inherit_contract_lines,
    set_contract_account,
)
from app.modules.costmodel.repository import CostSpineRepository, _amount_in_base
from app.modules.costmodel.structure_schemas import StructureFinding

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

#: Contracts whose value binds the project (the commitment rules' view, without drafts).
BOUND_STATUSES: tuple[str, ...] = ("active", "suspended", "completed")
#: Claims whose figures count as measured: anything put forward and not thrown out.
MEASURED_CLAIM_STATUSES: tuple[str, ...] = ("submitted", "approved", "certified", "paid")
#: Invoice states that no longer ask for money.
CLOSED_INVOICE_STATUSES: tuple[str, ...] = ("cancelled",)
#: Suspense rows returned per bucket; the bucket's count and amount are always for all of them.
BUCKET_ROW_LIMIT = 200

#: The order the buckets are shown in.
BUCKET_KINDS: tuple[str, ...] = (KIND_CONTRACT_LINE, KIND_CONTRACT, KIND_PO_ITEM, KIND_CHANGE_ITEM, KIND_INVOICE_LINE)
#: Buckets whose money is in the report's "not on any cost line" row.
COMMITTED_KINDS = frozenset({KIND_CONTRACT_LINE, KIND_CONTRACT, KIND_PO_ITEM})


def _dec(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw if raw not in (None, "") else "0"))
    except ArithmeticError:
        return ZERO
    return value if value.is_finite() else ZERO


def _uuid(raw: object) -> uuid.UUID | None:
    if raw in (None, ""):
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _is_lump_sum_unit(unit: object) -> bool:
    try:
        from app.modules.boq.units import is_lump_sum_unit
    except ImportError:  # pragma: no cover - the bill module is core
        return str(unit or "").strip().lower() in {"ls", "lsum", "lump sum"}
    return is_lump_sum_unit(str(unit or ""))


def _leaves(lines: list[Any]) -> list[Any]:
    """The billable lines: those no other line names as its parent."""
    parents = {ln.parent_line_id for ln in lines if ln.parent_line_id is not None}
    return [ln for ln in lines if ln.id not in parents]


class CostChainService:
    """Suspense, chain rules and their fixes for one project."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Payload of the chain rules ───────────────────────────────────────

    async def payload(self, project_id: uuid.UUID, data: Any | None = None) -> dict[str, Any]:
        """Everything rules V6 to V10 and V15 read, as plain data in the project currency."""
        from app.modules.boq.models import Position
        from app.modules.changeorders.models import ChangeOrder
        from app.modules.contracts.models import (
            Contract,
            ContractLine,
            ProgressClaim,
            ProgressClaimLine,
            SovAdjustment,
        )
        from app.modules.costmodel.models import ControlAccount, CostLine
        from app.modules.finance.models import Invoice, InvoiceLineItem

        data = data or await load_control_data(self.session, project_id)
        base, fx = await CostSpineRepository(self.session)._fx_context(project_id)

        contracts = (
            (
                await self.session.execute(
                    select(Contract).where(
                        Contract.project_id == project_id,
                        Contract.counterparty_type == "subcontractor",
                        Contract.status.in_(BOUND_STATUSES),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {c.id: c for c in contracts}
        lines = (
            (await self.session.execute(select(ContractLine).where(ContractLine.contract_id.in_(list(by_id)))))
            .scalars()
            .all()
            if by_id
            else []
        )
        lines_of: dict[uuid.UUID, list[Any]] = {}
        for ln in lines:
            lines_of.setdefault(ln.contract_id, []).append(ln)

        # What is measured on each line: the latest cumulative value and the sum of measured quantities.
        measured_value: dict[uuid.UUID, Decimal] = {}
        measured_qty: dict[uuid.UUID, Decimal] = {}
        if lines:
            rows = (
                await self.session.execute(
                    select(
                        ProgressClaimLine.contract_line_id,
                        ProgressClaimLine.cumulative_completed_value,
                        ProgressClaimLine.period_completed_qty,
                    )
                    .join(ProgressClaim, ProgressClaim.id == ProgressClaimLine.progress_claim_id)
                    .where(
                        ProgressClaim.contract_id.in_(list(by_id)),
                        ProgressClaim.status.in_(MEASURED_CLAIM_STATUSES),
                    )
                )
            ).all()
            for line_id, cumulative, qty in rows:
                value = _dec(cumulative)
                if value > measured_value.get(line_id, ZERO):
                    measured_value[line_id] = value
                measured_qty[line_id] = measured_qty.get(line_id, ZERO) + _dec(qty)

        # The bill each contract was let from: the totals of the positions its lines bill against.
        pos_ids = {
            pid for ln in lines if (pid := _uuid((ln.metadata_ or {}).get("boq_position_id") if ln.metadata_ else None))
        }
        pos_total: dict[uuid.UUID, Decimal] = {}
        if pos_ids:
            pos_total = {
                pid: _dec(total)
                for pid, total in (
                    await self.session.execute(select(Position.id, Position.total).where(Position.id.in_(pos_ids)))
                ).all()
            }

        # Changes: their status, and which ones a contract already carries.
        orders = (
            (await self.session.execute(select(ChangeOrder).where(ChangeOrder.project_id == project_id)))
            .scalars()
            .all()
        )
        posted = {
            str(sid)
            for (sid,) in (
                await self.session.execute(
                    select(SovAdjustment.source_id)
                    .join(Contract, Contract.id == SovAdjustment.contract_id)
                    .where(Contract.project_id == project_id, SovAdjustment.source_id.is_not(None))
                )
            ).all()
        }
        approved_unposted: dict[uuid.UUID, Decimal] = {}
        status_of: dict[str, tuple[str, str]] = {}
        for co in orders:
            status_of[str(co.id)] = (co.code or "", co.status or "")
            cid = _uuid((co.metadata_ or {}).get("contract_id"))
            if co.status in APPROVED_CHANGE_STATUSES and cid in by_id and str(co.id) not in posted:
                amount = co.approved_amount if co.approved_amount is not None else co.cost_impact
                approved_unposted[cid] = approved_unposted.get(cid, ZERO) + _amount_in_base(
                    str(_dec(amount)), (co.currency or "").strip().upper(), base, fx
                )

        contract_rows: list[dict[str, Any]] = []
        line_rows: list[dict[str, Any]] = []
        billed_unapproved: list[dict[str, Any]] = []
        for c in contracts:
            ccy = (c.currency or "").strip().upper()
            leaves = _leaves(lines_of.get(c.id, []))
            lines_total = sum((_dec(ln.total_value) for ln in leaves), ZERO)
            linked = [pos_total[p] for ln in leaves if (p := _uuid((ln.metadata_ or {}).get("boq_position_id")))]
            total = _amount_in_base(str(_dec(c.total_value)), ccy, base, fx)
            contract_rows.append(
                {
                    "id": str(c.id),
                    "code": c.code or "",
                    "contract_type": c.contract_type or "",
                    "status": c.status or "",
                    "total_value": str(total),
                    "line_count": len(leaves),
                    "lines_total": str(_amount_in_base(str(lines_total), ccy, base, fx)),
                    # The bill target only when every priced line came from a position; a partial
                    # link would compare the whole contract with part of its bill.
                    "target": str(sum(linked, ZERO)) if linked and len(linked) == len(leaves) else "0",
                    "committed": str(total + approved_unposted.get(c.id, ZERO)),
                    "measured_value": str(
                        _amount_in_base(
                            str(sum((measured_value.get(ln.id, ZERO) for ln in leaves), ZERO)), ccy, base, fx
                        )
                    ),
                }
            )
            for ln in leaves:
                if _dec(ln.quantity) > 0 and not _is_lump_sum_unit(ln.unit):
                    line_rows.append(
                        {
                            "id": str(ln.id),
                            "code": ln.code or "",
                            "contract_code": c.code or "",
                            "unit": ln.unit or "",
                            "quantity": str(_dec(ln.quantity)),
                            "measured_quantity": str(measured_qty.get(ln.id, ZERO)),
                        }
                    )
                key = str(ln.source_key or "")
                if (ln.origin or "") == "change_order" and key.startswith("change_order:"):
                    code, co_status = status_of.get(key.split(":", 1)[1], ("", ""))
                    billed = measured_value.get(ln.id, ZERO)
                    if co_status and co_status not in APPROVED_CHANGE_STATUSES and billed > 0:
                        billed_unapproved.append(
                            {
                                "line_id": str(ln.id),
                                "contract_code": c.code or "",
                                "change_code": code,
                                "change_status": co_status,
                                "billed": str(_amount_in_base(str(billed), ccy, base, fx)),
                            }
                        )

        change_rows = [
            {
                "id": str(co.id),
                "code": co.code or "",
                "status": co.status or "",
                "approved_amount": str(co.approved_amount) if co.approved_amount is not None else None,
                "approved_at": co.approved_at or "",
            }
            for co in orders
        ]

        # Accounts: commitment per account against its plan.
        acct_rows = (
            await self.session.execute(
                select(ControlAccount.id, ControlAccount.code, ControlAccount.own_amount).where(
                    ControlAccount.project_id == project_id
                )
            )
        ).all()
        line_acct = dict(
            (
                await self.session.execute(
                    select(CostLine.id, CostLine.control_account_id).where(CostLine.project_id == project_id)
                )
            ).all()
        )
        committed_by_acct: dict[str, Decimal] = {}
        planned_by_acct: dict[str, Decimal] = {}
        for lid, acct in line_acct.items():
            if acct is None:
                continue
            key = str(lid)
            committed_by_acct[str(acct)] = committed_by_acct.get(str(acct), ZERO) + data.committed.get(key, ZERO)
            plan = data.budget.get(key, ZERO) or data.estimate.get(key, ZERO)
            planned_by_acct[str(acct)] = planned_by_acct.get(str(acct), ZERO) + plan
        account_rows = [
            {
                "id": str(aid),
                "code": code or "",
                "committed": str(committed_by_acct.get(str(aid), ZERO)),
                "planned": str(planned_by_acct.get(str(aid), ZERO) + _dec(own)),
            }
            for aid, code, own in acct_rows
            if committed_by_acct.get(str(aid), ZERO) != ZERO
        ]

        # Supplier invoices that name no contract, contract line, order or claim.
        invoices = (
            await self.session.execute(
                select(
                    Invoice.id,
                    Invoice.invoice_number,
                    Invoice.amount_subtotal,
                    Invoice.currency_code,
                    Invoice.metadata_,
                ).where(
                    Invoice.project_id == project_id,
                    Invoice.invoice_direction == "payable",
                    Invoice.status.not_in(CLOSED_INVOICE_STATUSES),
                    Invoice.purchase_order_id.is_(None),
                    Invoice.source_claim_id.is_(None),
                )
            )
        ).all()
        with_lines = set()
        if invoices:
            with_lines = {
                iid
                for (iid,) in (
                    await self.session.execute(
                        select(InvoiceLineItem.invoice_id)
                        .where(
                            InvoiceLineItem.invoice_id.in_([r[0] for r in invoices]),
                            InvoiceLineItem.contract_line_id.is_not(None),
                        )
                        .distinct()
                    )
                ).all()
            }
        loose_invoices = [
            {
                "id": str(iid),
                "number": number or "",
                "amount": str(_amount_in_base(str(_dec(net)), (ccy or "").strip().upper(), base, fx)),
            }
            for iid, number, net, ccy, meta in invoices
            if iid not in with_lines and not (isinstance(meta, dict) and str(meta.get("contract_id") or "").strip())
        ]

        return {
            "currency": base,
            "contracts": contract_rows,
            "lines": line_rows,
            "change_orders": change_rows,
            "billed_unapproved": billed_unapproved,
            "accounts": account_rows,
            "invoices_without_contract": loose_invoices,
        }

    async def findings(self, project_id: uuid.UUID, payload: dict[str, Any], *, locale: str) -> list[StructureFinding]:
        """Run the ``cost_chain`` rule set on the payload, worst first."""
        from app.core.validation.engine import ValidationContext, rule_registry

        context = ValidationContext(
            data={PAYLOAD_KEY: payload}, project_id=str(project_id), metadata={"locale": locale}
        )
        out: list[StructureFinding] = []
        for rule in rule_registry.get_rules_for_sets([RULE_SET]):
            if not rule.enabled:
                continue
            for r in await rule.validate(context):
                if r.passed:
                    continue
                out.append(
                    StructureFinding(
                        rule_id=r.rule_id,
                        severity=r.severity.value,  # type: ignore[arg-type]
                        message=r.message,
                        suggestion=r.suggestion or "",
                        element_ref=r.element_ref,
                        details=dict(r.details),
                    )
                )
        order = {"error": 0, "warning": 1, "info": 2}
        out.sort(key=lambda f: (order.get(f.severity, 3), f.rule_id, str(f.details.get("code") or "")))
        return out

    # ── Suspense ─────────────────────────────────────────────────────────

    async def suspense(self, project_id: uuid.UUID, data: Any | None = None) -> list[dict[str, Any]]:
        """Every row with money and no cost line, in buckets by kind."""
        from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
        from app.modules.contracts.models import Contract, ContractLine
        from app.modules.finance.models import Invoice, InvoiceLineItem

        data = data or await load_control_data(self.session, project_id)
        base, fx = await CostSpineRepository(self.session)._fx_context(project_id)
        rows: dict[str, list[dict[str, Any]]] = {k: [] for k in BUCKET_KINDS}

        # From the report: the same rows and amounts as "not on any cost line".
        line_ids = [uuid.UUID(e.id) for e in data.unassigned_items if e.kind == KIND_CONTRACT_LINE]
        inheritable: set[str] = set()
        if line_ids:
            lines = (
                (await self.session.execute(select(ContractLine).where(ContractLine.id.in_(line_ids)))).scalars().all()
            )
            by_contract: dict[uuid.UUID, list[Any]] = {}
            for ln in lines:
                by_contract.setdefault(ln.contract_id, []).append(ln)
            for cid, group in by_contract.items():
                contract = await self.session.get(Contract, cid)
                if contract is None:
                    continue
                candidates = await contract_line_candidates(self.session, contract, group)
                inheritable.update(k for k, cands in candidates.items() if not first_inherited(cands).vector.empty)
        for e in data.unassigned_items:
            rows[e.kind].append(
                {
                    "kind": e.kind,
                    "id": e.id,
                    "group_id": e.group_id,
                    "group_code": e.group_code,
                    "group_title": e.group_title,
                    "code": e.code,
                    "description": e.description,
                    "amount": e.amount,
                    "can_inherit": e.kind == KIND_CONTRACT_LINE and e.id in inheritable,
                }
            )

        # Change order items still to decide or decided, on no cost line.
        items = (
            await self.session.execute(
                select(ChangeOrderItem, ChangeOrder)
                .join(ChangeOrder, ChangeOrder.id == ChangeOrderItem.change_order_id)
                .where(
                    ChangeOrder.project_id == project_id,
                    ChangeOrder.status.in_(PENDING_CHANGE_STATUSES + APPROVED_CHANGE_STATUSES),
                    ChangeOrderItem.cost_line_id.is_(None),
                )
                .order_by(ChangeOrder.code, ChangeOrderItem.sort_order)
            )
        ).all()
        for item, order in items:
            amount = _amount_in_base(str(_dec(item.cost_delta)), (order.currency or "").strip().upper(), base, fx)
            if amount == ZERO:
                continue
            picked = await change_item_inherits(self.session, order, dict(item.metadata_ or {}))
            rows[KIND_CHANGE_ITEM].append(
                {
                    "kind": KIND_CHANGE_ITEM,
                    "id": str(item.id),
                    "group_id": str(order.id),
                    "group_code": order.code or "",
                    "group_title": order.title or "",
                    "code": "",
                    "description": item.description or "",
                    "amount": amount,
                    "can_inherit": not picked.vector.empty,
                }
            )

        # Supplier invoice lines on no cost line.
        inv_rows = (
            await self.session.execute(
                select(InvoiceLineItem, Invoice)
                .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
                .where(
                    Invoice.project_id == project_id,
                    Invoice.invoice_direction == "payable",
                    Invoice.status.not_in(CLOSED_INVOICE_STATUSES),
                    InvoiceLineItem.cost_line_id.is_(None),
                )
                .order_by(Invoice.invoice_number, InvoiceLineItem.sort_order)
            )
        ).all()
        mains = {}
        wanted = {line.contract_line_id for line, _ in inv_rows if line.contract_line_id is not None}
        if wanted:
            mains = dict(
                (
                    await self.session.execute(
                        select(ContractLine.id, ContractLine.cost_line_id).where(ContractLine.id.in_(wanted))
                    )
                ).all()
            )
        for line, invoice in inv_rows:
            amount = _amount_in_base(str(_dec(line.amount)), (invoice.currency_code or "").strip().upper(), base, fx)
            if amount == ZERO:
                continue
            rows[KIND_INVOICE_LINE].append(
                {
                    "kind": KIND_INVOICE_LINE,
                    "id": str(line.id),
                    "group_id": str(invoice.id),
                    "group_code": invoice.invoice_number or "",
                    "group_title": "",
                    "code": "",
                    "description": line.description or "",
                    "amount": amount,
                    "can_inherit": mains.get(line.contract_line_id) is not None,
                }
            )

        return [
            {
                "kind": kind,
                "count": len(rows[kind]),
                "amount": sum((r["amount"] for r in rows[kind]), ZERO),
                "inheritable": sum(1 for r in rows[kind] if r["can_inherit"]),
                "in_report": kind in COMMITTED_KINDS,
                "items": rows[kind][:BUCKET_ROW_LIMIT],
            }
            for kind in BUCKET_KINDS
        ]

    async def report(self, project_id: uuid.UUID, *, locale: str) -> dict[str, Any]:
        """Suspense buckets and chain findings, from one read of the figures."""
        data = await load_control_data(self.session, project_id)
        payload = await self.payload(project_id, data)
        return {
            "project_id": project_id,
            "currency": data.currency,
            "buckets": await self.suspense(project_id, data),
            "findings": await self.findings(project_id, payload, locale=locale),
        }

    # ── Fixes ────────────────────────────────────────────────────────────

    async def inherit_missing(self, project_id: uuid.UUID) -> dict[str, int]:
        """Give every row that can inherit an account and has none the account it inherits.

        Rows already on a cost line are never touched. Returns how many rows of
        each kind got one.
        """
        from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
        from app.modules.contracts.models import Contract, ContractLine
        from app.modules.finance.models import Invoice, InvoiceLineItem

        counts = {KIND_CONTRACT_LINE: 0, KIND_CHANGE_ITEM: 0, KIND_INVOICE_LINE: 0}
        contracts = (
            (
                await self.session.execute(
                    select(Contract)
                    .join(ContractLine, ContractLine.contract_id == Contract.id)
                    .where(Contract.project_id == project_id, ContractLine.cost_line_id.is_(None))
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        for contract in contracts:
            counts[KIND_CONTRACT_LINE] += await inherit_contract_lines(self.session, contract)

        items = (
            await self.session.execute(
                select(ChangeOrderItem, ChangeOrder)
                .join(ChangeOrder, ChangeOrder.id == ChangeOrderItem.change_order_id)
                .where(ChangeOrder.project_id == project_id, ChangeOrderItem.cost_line_id.is_(None))
            )
        ).all()
        for item, order in items:
            await apply_change_item_inheritance(self.session, order, item)
            if item.cost_line_id is not None:
                counts[KIND_CHANGE_ITEM] += 1

        lines = (
            (
                await self.session.execute(
                    select(InvoiceLineItem)
                    .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
                    .where(
                        Invoice.project_id == project_id,
                        InvoiceLineItem.cost_line_id.is_(None),
                        InvoiceLineItem.contract_line_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if lines:
            mains = dict(
                (
                    await self.session.execute(
                        select(ContractLine.id, ContractLine.cost_line_id).where(
                            ContractLine.id.in_({ln.contract_line_id for ln in lines})
                        )
                    )
                ).all()
            )
            vectors = await row_vectors(self.session, SOURCE_CONTRACT_LINE, mains)
            for ln in lines:
                vector = vectors.get(str(ln.contract_line_id))
                if vector is None or vector.empty:
                    continue
                ln.cost_line_id = await write_split(
                    self.session,
                    project_id=project_id,
                    source_type=SOURCE_INVOICE_LINE,
                    source_id=ln.id,
                    vector=vector,
                )
                counts[KIND_INVOICE_LINE] += 1
        await self.session.flush()
        logger.info("Accounts inherited in project %s: %s", project_id, counts)
        return counts

    async def direct_cost_contract(
        self, project_id: uuid.UUID, invoice_id: uuid.UUID, cost_line_id: uuid.UUID, user_id: str | None
    ) -> dict[str, Any]:
        """Record a supplier invoice that has no contract as a direct cost on one account.

        Creates an active lump-sum contract for the invoice's net amount with
        the supplier as counterparty, puts it on ``cost_line_id`` (one schedule
        line for the whole value), and points every line of the invoice at that
        schedule line and account. The commitment then exists, on an account,
        and rule V15 is satisfied by the record rather than silenced.
        """
        from app.modules.contracts.models import Contract, ContractLine
        from app.modules.finance.models import Invoice, InvoiceLineItem

        invoice = await self.session.get(Invoice, invoice_id)
        if invoice is None or invoice.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
        if invoice.invoice_direction != "payable":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "problem": "not_a_supplier_invoice",
                    "message": "Only a supplier invoice can be a direct cost.",
                },
            )
        meta = dict(invoice.metadata_ or {})
        if str(meta.get("contract_id") or "").strip() or invoice.purchase_order_id or invoice.source_claim_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"problem": "invoice_has_contract", "message": "This invoice already belongs to a commitment."},
            )
        if not await lines_in_project(self.session, project_id, [cost_line_id]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"problem": "cost_line_not_found", "message": "Cost line not found"},
            )

        base_code = f"DC-{(invoice.invoice_number or invoice.id.hex[:8])}"[:76]
        code = base_code
        for n in range(2, 1000):
            taken = (await self.session.execute(select(func.count()).where(Contract.code == code))).scalar_one()
            if not taken:
                break
            code = f"{base_code}-{n}"
        net = _dec(invoice.amount_subtotal)
        contract = Contract(
            code=code,
            title=(invoice.invoice_number or code)[:500],
            contract_type="lump_sum",
            counterparty_type="subcontractor",
            counterparty_id=_uuid(invoice.contact_id),
            project_id=project_id,
            total_value=net,
            original_contract_value=net,
            currency=(invoice.currency_code or "")[:3],
            retention_percent=Decimal("0"),
            status="active",
            terms={},
            created_by=user_id,
        )
        contract.metadata_ = {"source": "direct_cost", "invoice_id": str(invoice.id)}
        self.session.add(contract)
        await self.session.flush()
        await set_contract_account(self.session, contract, cost_line_id, user_id)
        line_id = (
            await self.session.execute(select(ContractLine.id).where(ContractLine.contract_id == contract.id).limit(1))
        ).scalar_one_or_none()

        for item in (
            (await self.session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id)))
            .scalars()
            .all()
        ):
            item.contract_line_id = line_id
            item.cost_line_id = cost_line_id
        meta["contract_id"] = str(contract.id)
        invoice.metadata_ = meta
        await self.session.flush()
        logger.info("Invoice %s recorded as direct cost contract %s", invoice.invoice_number, contract.code)
        return {
            "contract_id": str(contract.id),
            "contract_code": contract.code,
            "contract_line_id": str(line_id) if line_id else None,
            "source": FROM_CONTRACT_LINE,
        }
