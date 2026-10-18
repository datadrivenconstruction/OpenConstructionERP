# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost control: read every figure the report needs, in the project currency.

The commitment rules are not repeated here. ``CostSpineRepository.committed_by_cost_line``
already decides what binds the project (subcontract lines, issued purchase
orders, a terminated contract only for what was certified, one award counted
once), and this module splits that figure into what was awarded and what
approved changes added, so the award plus the changes always equals the
commitment the rest of the platform reports.

Changes are the schedule-of-values lines an approved change order or
variation added (``ContractLine.origin``) plus the growth a change put on an
original line (``total_value`` above the frozen ``original_value``).

An approved change order counts as a change "on no contract" only when no
contract carries it: not by ``metadata.contract_id``, not in a contract's
applied ``change_order_ids``, not as a posted schedule adjustment, and, for a
change order that mirrors a variation, not through that variation either.
Otherwise the same money would sit on its contract line and on the loose row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.cost_control import CENT
from app.modules.costmodel.inheritance import (
    SOURCE_CONTRACT_LINE,
    SOURCE_INVOICE_LINE,
    SOURCE_PO_ITEM,
    expand,
    row_vectors,
)
from app.modules.costmodel.repository import (
    _CLAIM_CERTIFIED_STATUSES,
    _CONTRACT_UNBOUND_STATUSES,
    _PO_COMMITTED_STATUSES,
    CostSpineRepository,
    _amount_in_base,
)

ZERO = Decimal("0")

#: Claim states that certify value: the same pair the commitment rules use for a
#: terminated contract, so "certified" means one thing across the spine.
CERTIFIED_CLAIM_STATUSES: tuple[str, ...] = _CLAIM_CERTIFIED_STATUSES
PAID_CLAIM_STATUSES: tuple[str, ...] = ("paid",)

#: Change orders waiting for a decision, and those decided in the project's favour of paying.
PENDING_CHANGE_STATUSES: tuple[str, ...] = ("submitted",)
APPROVED_CHANGE_STATUSES: tuple[str, ...] = ("approved", "executed")

CONTRACT_COMPLETED = "completed"
CONTRACT_TERMINATED = "terminated"


@dataclass(slots=True)
class ContractFigures:
    """One bound subcontract and the money on it, in the project currency."""

    contract_id: str
    code: str
    title: str
    status: str
    awarded: Decimal = ZERO
    changes: Decimal = ZERO
    certified: Decimal = ZERO
    paid: Decimal = ZERO
    pending_changes: Decimal = ZERO
    pending_count: int = 0
    cost_line_ids: set[str] = field(default_factory=set)
    measured: Decimal = ZERO
    invoiced: Decimal = ZERO


@dataclass(slots=True)
class UnassignedEntry:
    """One contract line or order item whose money is on no cost line yet."""

    # "contract_line", "po_item" or "contract" (a bound contract with no schedule line,
    # whose whole value is on no cost line until it gets an account).
    kind: str
    id: str
    group_id: str
    group_code: str
    group_title: str
    code: str
    description: str
    amount: Decimal


@dataclass(slots=True)
class ControlData:
    """Everything the report is built from."""

    currency: str
    budget: dict[str, Decimal]
    estimate: dict[str, Decimal]
    committed: dict[str, Decimal]
    changes: dict[str, Decimal]
    certified: dict[str, Decimal]
    paid: dict[str, Decimal]
    final_lines: set[str]
    contracts: list[ContractFigures]
    unassigned_committed: Decimal
    unassigned_certified: Decimal
    unassigned_paid: Decimal
    approved_changes_without_contract: Decimal
    approved_changes_without_contract_count: int
    pending_changes: Decimal
    pending_count: int
    unassigned_items: list[UnassignedEntry] = field(default_factory=list)
    # Measured (quantity times contract rate) and invoiced (supplier invoices, net) per cost line.
    measured: dict[str, Decimal] = field(default_factory=dict)
    invoiced: dict[str, Decimal] = field(default_factory=dict)
    unassigned_measured: Decimal = ZERO
    unassigned_invoiced: Decimal = ZERO
    # Change orders waiting for a decision, per cost line, from the lines of those orders.
    pending_by_line: dict[str, Decimal] = field(default_factory=dict)


def _dec(value: object) -> str:
    return str(value) if value is not None else "0"


def _meta_str(metadata: object, key: str) -> str | None:
    if isinstance(metadata, dict):
        raw = str(metadata.get(key) or "").strip()
        return raw or None
    return None


def _contract_id_of(metadata: object) -> str | None:
    return _meta_str(metadata, "contract_id")


def _paid_share(retention_held: object, completed: object) -> Decimal:
    """Share of a paid claim's value that reached the contractor, retention held back.

    Read from the claim's own to-date figures. A claim that does not carry them
    is taken as paid in full, the figure the claim itself certifies.
    """
    try:
        held = Decimal(str(retention_held)) if retention_held is not None else ZERO
        done = Decimal(str(completed)) if completed is not None else ZERO
    except ArithmeticError:
        return Decimal("1")
    if done <= ZERO or held <= ZERO or held >= done:
        return Decimal("1")
    return (done - held) / done


async def _line_billing(session: AsyncSession, project_id: uuid.UUID) -> Any | None:
    """Measured, invoiced and paid per schedule line from the payment release module, if installed."""
    try:
        from app.modules.payment_release.billing import line_billing, load_billing
    except ImportError:  # pragma: no cover - an install without the module shows no invoice figures
        return None
    return line_billing(await load_billing(session, project_id))


async def load_control_data(session: AsyncSession, project_id: uuid.UUID) -> ControlData:
    """Read every figure for one project. A fixed number of queries, none per line."""
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine, SovAdjustment
    from app.modules.costmodel.models import CostLine
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
    from app.modules.variations.models import VariationOrder

    spine = CostSpineRepository(session)
    base, fx = await spine._fx_context(project_id)

    budget_rows = await spine.budget_aggregate_by_cost_line(project_id)
    budget = {k: v.get("planned", ZERO) for k, v in budget_rows.items()}
    committed = await spine.committed_by_cost_line(project_id)

    # A cost line may carry its estimate in its own currency, like every other figure.
    estimate_rows = (
        await session.execute(
            select(CostLine.id, CostLine.estimate_amount, CostLine.currency).where(CostLine.project_id == project_id)
        )
    ).all()
    estimate = {
        str(lid): _amount_in_base(_dec(amount), (ccy or "").strip().upper(), base, fx)
        for lid, amount, ccy in estimate_rows
    }

    # ── Bound subcontracts and their lines ────────────────────────────────
    contract_rows = (
        await session.execute(
            select(
                Contract.id, Contract.code, Contract.title, Contract.status, Contract.currency, Contract.total_value
            ).where(
                Contract.project_id == project_id,
                Contract.counterparty_type == "subcontractor",
                Contract.status.not_in(_CONTRACT_UNBOUND_STATUSES),
            )
        )
    ).all()
    contracts: dict[str, ContractFigures] = {}
    contract_ccy: dict[str, str] = {}
    contract_sum: dict[str, object] = {}
    for cid, code, title, status_, ccy, total_value in contract_rows:
        key = str(cid)
        contracts[key] = ContractFigures(
            contract_id=key, code=code or "", title=title or "", status=(status_ or "").strip().lower()
        )
        contract_ccy[key] = (ccy or "").strip().upper()
        contract_sum[key] = total_value

    line_rows = (
        (
            await session.execute(
                select(
                    ContractLine.id,
                    ContractLine.contract_id,
                    ContractLine.cost_line_id,
                    ContractLine.total_value,
                    ContractLine.original_value,
                    ContractLine.origin,
                    ContractLine.code,
                    ContractLine.description,
                ).where(ContractLine.contract_id.in_([uuid.UUID(k) for k in contracts]))
            )
        ).all()
        if contracts
        else []
    )

    # ── Certified and paid, per contract line: the latest cumulative value ─
    certified_by_cl: dict[str, Decimal] = {}
    paid_by_cl: dict[str, Decimal] = {}
    if line_rows:
        claim_rows = (
            await session.execute(
                select(
                    ProgressClaimLine.contract_line_id,
                    ProgressClaimLine.cumulative_completed_value,
                    ProgressClaim.status,
                    ProgressClaim.contract_id,
                    ProgressClaim.retention_held_to_date,
                    ProgressClaim.completed_stored_to_date,
                )
                .join(ProgressClaim, ProgressClaim.id == ProgressClaimLine.progress_claim_id)
                .where(
                    ProgressClaim.contract_id.in_([uuid.UUID(k) for k in contracts]),
                    ProgressClaim.status.in_(CERTIFIED_CLAIM_STATUSES),
                )
            )
        ).all()
        for cl_id, cumulative, claim_status, contract_id, held, done in claim_rows:
            key = str(cl_id)
            value = _amount_in_base(_dec(cumulative), contract_ccy.get(str(contract_id), ""), base, fx)
            if value > certified_by_cl.get(key, ZERO):
                certified_by_cl[key] = value
            if (claim_status or "") in PAID_CLAIM_STATUSES:
                # Paid is money that left the project: the retention held on the claim stays owed.
                cash = (value * _paid_share(held, done)).quantize(CENT)
                if cash > paid_by_cl.get(key, ZERO):
                    paid_by_cl[key] = cash

    # Measured, invoiced and paid on supplier invoices, per schedule line (payment release module).
    billing = await _line_billing(session, project_id)

    changes: dict[str, Decimal] = {}
    certified: dict[str, Decimal] = {}
    paid: dict[str, Decimal] = {}
    measured: dict[str, Decimal] = {}
    invoiced: dict[str, Decimal] = {}
    unassigned_measured = ZERO
    unassigned_invoiced = ZERO
    open_lines: set[str] = set()
    lines_with_contracts: set[str] = set()
    unassigned_committed = ZERO
    unassigned_certified = ZERO
    unassigned_paid = ZERO
    unassigned_items: list[UnassignedEntry] = []

    # A schedule line inherited from a split position carries money to several cost lines.
    line_vectors = await row_vectors(
        session, SOURCE_CONTRACT_LINE, {row[0]: row[2] for row in line_rows if row[2] is not None}
    )

    for cl_id, contract_id, cost_line_id, total_value, original_value, origin, line_code, line_desc in line_rows:
        ckey = str(contract_id)
        figures = contracts[ckey]
        ccy = contract_ccy.get(ckey, "")
        total = _amount_in_base(_dec(total_value), ccy, base, fx)
        terminated = figures.status == CONTRACT_TERMINATED
        if (origin or "original") != "original":
            change = total
        elif original_value is not None:
            change = total - _amount_in_base(_dec(original_value), ccy, base, fx)
        else:
            change = ZERO
        cert = certified_by_cl.get(str(cl_id), ZERO)
        meas = billing.measured.get(str(cl_id), ZERO) if billing else ZERO
        inv = billing.invoiced.get(str(cl_id), ZERO) if billing else ZERO
        # The same money can be marked paid on the claim and paid on its invoice: take it once.
        pay = max(paid_by_cl.get(str(cl_id), ZERO), billing.paid.get(str(cl_id), ZERO) if billing else ZERO)
        # A terminated contract binds only what was certified; nothing of it is a change any more.
        bound = cert if terminated else total
        if terminated:
            change = ZERO

        figures.awarded += bound - change
        figures.changes += change
        figures.certified += cert
        figures.paid += pay
        figures.measured += meas
        figures.invoiced += inv

        if cost_line_id is None:
            unassigned_committed += bound
            unassigned_certified += cert
            unassigned_paid += pay
            unassigned_measured += meas
            unassigned_invoiced += inv
            if bound != ZERO or cert != ZERO:
                unassigned_items.append(
                    UnassignedEntry(
                        kind="contract_line",
                        id=str(cl_id),
                        group_id=ckey,
                        group_code=figures.code,
                        group_title=figures.title,
                        code=line_code or "",
                        description=line_desc or "",
                        amount=bound,
                    )
                )
            continue
        vector = line_vectors[str(cl_id)]
        for figure, acc in ((change, changes), (cert, certified), (pay, paid), (meas, measured), (inv, invoiced)):
            for key, part in expand(figure, vector):
                acc[str(key)] = acc.get(str(key), ZERO) + part
        for key in vector.lines:
            figures.cost_line_ids.add(key)
            lines_with_contracts.add(key)
            if figures.status != CONTRACT_COMPLETED:
                open_lines.add(key)

    # A bound contract with no schedule at all: its whole value is committed and on no cost line.
    with_lines = {str(row[1]) for row in line_rows}
    for ckey, figures in contracts.items():
        if ckey in with_lines or figures.status == CONTRACT_TERMINATED:
            continue
        value = _amount_in_base(_dec(contract_sum.get(ckey)), contract_ccy.get(ckey, ""), base, fx)
        if value == ZERO:
            continue
        figures.awarded += value
        unassigned_committed += value
        unassigned_items.append(
            UnassignedEntry(
                kind="contract",
                id=ckey,
                group_id=ckey,
                group_code=figures.code,
                group_title=figures.title,
                code=figures.code,
                description=figures.title,
                amount=value,
            )
        )

    # Supplier invoice money on no bound schedule line goes to the invoice line's own cost line.
    if billing is not None and billing.direct:
        direct_vectors = await row_vectors(
            session, SOURCE_INVOICE_LINE, {line_id: lid for line_id, lid, _i, _p in billing.direct if lid}
        )
        for line_id, lid, inv, pay in billing.direct:
            vector = direct_vectors.get(line_id) if lid else None
            if vector is None or vector.empty:
                unassigned_invoiced += inv
                unassigned_paid += pay
                continue
            for figure, acc in ((inv, invoiced), (pay, paid)):
                for key, part in expand(figure, vector):
                    acc[str(key)] = acc.get(str(key), ZERO) + part

    # Purchase-order money with no cost line is unaccounted for too. A line that
    # also carries an order is never "final" from its contracts alone: the
    # order's money would drop out of the forecast.
    po_rows = (
        await session.execute(
            select(
                PurchaseOrderItem.amount,
                PurchaseOrderItem.cost_line_id,
                PurchaseOrder.currency_code,
                PurchaseOrderItem.id,
                PurchaseOrderItem.description,
                PurchaseOrder.id,
                PurchaseOrder.po_number,
            )
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.po_id)
            .where(
                PurchaseOrder.project_id == project_id,
                PurchaseOrder.status.in_(_PO_COMMITTED_STATUSES),
            )
        )
    ).all()
    lines_with_orders: set[str] = set()
    po_vectors = await row_vectors(session, SOURCE_PO_ITEM, {row[3]: row[1] for row in po_rows if row[1] is not None})
    for amount, po_cost_line_id, ccy, item_id, item_desc, po_id, po_number in po_rows:
        if po_cost_line_id is not None:
            lines_with_orders.update(po_vectors[str(item_id)].lines)
            continue
        value = _amount_in_base(_dec(amount), (ccy or "").strip().upper(), base, fx)
        unassigned_committed += value
        if value != ZERO:
            unassigned_items.append(
                UnassignedEntry(
                    kind="po_item",
                    id=str(item_id),
                    group_id=str(po_id),
                    group_code=po_number or "",
                    group_title="",
                    code="",
                    description=item_desc or "",
                    amount=value,
                )
            )

    # ── Which changes some contract already carries ───────────────────────
    # Every contract of the project counts here, the client side too: a
    # change applied to any contract is not a change "on no contract".
    applied_changes: set[str] = set()
    applied_variations: set[str] = set()
    for (meta,) in (await session.execute(select(Contract.metadata_).where(Contract.project_id == project_id))).all():
        if isinstance(meta, dict):
            applied_changes.update(str(x) for x in meta.get("change_order_ids") or [])
            applied_variations.update(str(x) for x in meta.get("variation_ids") or [])
    posted = (
        await session.execute(
            select(SovAdjustment.source_kind, SovAdjustment.source_id)
            .join(Contract, Contract.id == SovAdjustment.contract_id)
            .where(Contract.project_id == project_id, SovAdjustment.source_id.is_not(None))
        )
    ).all()
    for kind, source_id in posted:
        (applied_variations if kind == "variation_order" else applied_changes).add(str(source_id))

    # ── Change orders: waiting for a decision, or approved with no contract ─
    co_rows = (
        await session.execute(
            select(
                ChangeOrder.id,
                ChangeOrder.status,
                ChangeOrder.cost_impact,
                ChangeOrder.contractor_amount,
                ChangeOrder.approved_amount,
                ChangeOrder.currency,
                ChangeOrder.metadata_,
            ).where(
                ChangeOrder.project_id == project_id,
                ChangeOrder.status.in_(PENDING_CHANGE_STATUSES + APPROVED_CHANGE_STATUSES),
            )
        )
    ).all()
    mirrored_ids = {m for row in co_rows if (m := _meta_str(row[6], "variation_order_id"))}
    variations_on_contract: set[str] = set()
    if mirrored_ids:
        valid = []
        for raw in mirrored_ids:
            try:
                valid.append(uuid.UUID(raw))
            except ValueError:
                continue
        if valid:
            variations_on_contract = {
                str(vid)
                for (vid,) in (
                    await session.execute(
                        select(VariationOrder.id).where(
                            VariationOrder.id.in_(valid), VariationOrder.affected_contract_id.is_not(None)
                        )
                    )
                ).all()
            }

    pending_total = ZERO
    pending_count = 0
    pending_ids: dict[uuid.UUID, str] = {}
    loose_total = ZERO
    loose_count = 0
    for co_id, co_status, impact, contractor_amount, approved_amount, ccy, meta in co_rows:
        code = (ccy or "").strip().upper()
        linked = _contract_id_of(meta)
        if co_status in PENDING_CHANGE_STATUSES:
            raw = contractor_amount if contractor_amount is not None else impact
            value = _amount_in_base(_dec(raw), code, base, fx)
            pending_total += value
            pending_count += 1
            pending_ids[co_id] = code
            if linked and linked in contracts:
                contracts[linked].pending_changes += value
                contracts[linked].pending_count += 1
            continue
        mirrored = _meta_str(meta, "variation_order_id")
        on_contract = (
            linked is not None
            or str(co_id) in applied_changes
            or (mirrored is not None and (mirrored in applied_variations or mirrored in variations_on_contract))
        )
        if not on_contract:
            raw = approved_amount if approved_amount is not None else impact
            loose_total += _amount_in_base(_dec(raw), code, base, fx)
            loose_count += 1

    # The lines of the waiting orders say which cost line each part of the money would land on.
    pending_by_line: dict[str, Decimal] = {}
    if pending_ids:
        from app.modules.changeorders.models import ChangeOrderItem

        item_rows = (
            await session.execute(
                select(ChangeOrderItem.change_order_id, ChangeOrderItem.cost_line_id, ChangeOrderItem.cost_delta).where(
                    ChangeOrderItem.change_order_id.in_(list(pending_ids)),
                    ChangeOrderItem.cost_line_id.is_not(None),
                )
            )
        ).all()
        for co_id, item_line, delta in item_rows:
            value = _amount_in_base(_dec(delta), pending_ids.get(co_id, ""), base, fx)
            pending_by_line[str(item_line)] = pending_by_line.get(str(item_line), ZERO) + value

    return ControlData(
        currency=base,
        budget=budget,
        estimate=estimate,
        committed=committed,
        changes=changes,
        certified=certified,
        paid=paid,
        final_lines=lines_with_contracts - open_lines - lines_with_orders,
        contracts=sorted(contracts.values(), key=lambda c: c.code),
        unassigned_committed=unassigned_committed,
        unassigned_certified=unassigned_certified,
        unassigned_paid=unassigned_paid,
        approved_changes_without_contract=loose_total,
        approved_changes_without_contract_count=loose_count,
        pending_changes=pending_total,
        pending_count=pending_count,
        unassigned_items=sorted(unassigned_items, key=lambda e: (e.kind, e.group_code, e.code, e.description)),
        measured=measured,
        invoiced=invoiced,
        unassigned_measured=unassigned_measured,
        unassigned_invoiced=unassigned_invoiced,
        pending_by_line=pending_by_line,
    )
