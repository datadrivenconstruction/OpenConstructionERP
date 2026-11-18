# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget, committed, remaining and received per bill position.

The question a buyer and a commercial manager ask of every line of the bill:
how much of it have we bought, how much is left to buy, and how much has
arrived. One row per priced position, quantity and value side by side:

* **budget**: the position's cost budget (:mod:`app.modules.boq.budget_basis`),
  quantity x target rate when the position has one, else quantity x unit rate;
* **committed**: what purchase orders and subcontracts promise against it. An
  order commits once it is issued (``issued``, ``partially_received``,
  ``completed``, the same statuses the cost spine counts). A subcontract is a
  contract with ``counterparty_type = "subcontractor"`` once it is live
  (``active``, ``suspended``, ``completed``); a subcontract agreement that
  carries one names it through ``contract_id``, so the contract is its one
  commitment and nothing is counted twice;
* **remaining**: budget less committed, negative when the line is over-committed;
* **received**: goods confirmed on receipts at the order's unit rate, plus the
  work certified to date on the subcontract lines.

Money follows the cost spine: an order or contract line reaches a position
through the position's ``cost_line_id``, and a line split over several cost
lines is cut by its stored shares, so this grid and the spine rollup never
disagree about which line a commitment belongs to. Every amount is converted to
the project currency with the project's FX table.

``assemble_grid`` is pure and holds all the arithmetic, so the worked examples
in the tests run without a database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.budget_basis import is_priced_line, position_budget

ZERO = Decimal("0")
_MONEY_Q = Decimal("0.01")
_QTY_Q = Decimal("0.0001")

PO_COMMITTED_STATUSES = ("issued", "partially_received", "completed")
SUBCONTRACT_LIVE_STATUSES = ("active", "suspended", "completed")


def _dec(raw: object) -> Decimal:
    if raw is None or raw == "":
        return ZERO
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO
    return value if value.is_finite() else ZERO


@dataclass
class LineFigures:
    """What one cost line carries, in project currency."""

    po_qty: Decimal = ZERO
    po_value: Decimal = ZERO
    sub_qty: Decimal = ZERO
    sub_value: Decimal = ZERO
    received_qty: Decimal = ZERO
    received_value: Decimal = ZERO

    def add(self, other: LineFigures) -> None:
        self.po_qty += other.po_qty
        self.po_value += other.po_value
        self.sub_qty += other.sub_qty
        self.sub_value += other.sub_value
        self.received_qty += other.received_qty
        self.received_value += other.received_value


@dataclass(frozen=True)
class GridRow:
    """One priced bill position in the commitment grid."""

    boq_position_id: uuid.UUID
    boq_id: uuid.UUID | None
    ordinal: str
    description: str
    unit: str
    wbs_id: str | None
    cost_line_id: uuid.UUID | None
    budget_basis: str
    budget_rate: Decimal
    budget_qty: Decimal
    budget_value: Decimal
    po_committed_qty: Decimal
    po_committed_value: Decimal
    subcontract_committed_qty: Decimal
    subcontract_committed_value: Decimal
    committed_qty: Decimal
    committed_value: Decimal
    remaining_qty: Decimal
    remaining_value: Decimal
    received_qty: Decimal
    received_value: Decimal

    @property
    def on_cost_spine(self) -> bool:
        return self.cost_line_id is not None

    @property
    def over_committed_qty(self) -> bool:
        return self.budget_qty > 0 and self.committed_qty > self.budget_qty

    @property
    def over_committed_value(self) -> bool:
        return self.committed_value > self.budget_value


@dataclass
class CommitmentGrid:
    """The grid for one project, with totals over every row."""

    currency: str = ""
    rows: list[GridRow] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, Decimal]:
        out = {
            "budget_value": ZERO,
            "po_committed_value": ZERO,
            "subcontract_committed_value": ZERO,
            "committed_value": ZERO,
            "remaining_value": ZERO,
            "received_value": ZERO,
        }
        for row in self.rows:
            for key in out:
                out[key] += getattr(row, key)
        return {k: v.quantize(_MONEY_Q) for k, v in out.items()}


def assemble_grid(positions: list[object], by_cost_line: dict[str, LineFigures]) -> list[GridRow]:
    """Join the per-cost-line figures onto the priced positions. Pure.

    A position without a cost line gets its budget and zeros: nothing can be
    committed against a line that is not on the spine, and the row says so
    through ``on_cost_spine`` rather than vanishing.
    """
    rows: list[GridRow] = []
    for pos in positions:
        if not is_priced_line(pos):
            continue
        budget = position_budget(pos)
        cost_line_id = getattr(pos, "cost_line_id", None)
        figures = by_cost_line.get(str(cost_line_id), LineFigures()) if cost_line_id else LineFigures()
        committed_qty = figures.po_qty + figures.sub_qty
        committed_value = figures.po_value + figures.sub_value
        rows.append(
            GridRow(
                boq_position_id=pos.id,
                boq_id=getattr(pos, "boq_id", None),
                ordinal=str(getattr(pos, "ordinal", "") or ""),
                description=str(getattr(pos, "description", "") or ""),
                unit=str(getattr(pos, "unit", "") or ""),
                wbs_id=getattr(pos, "wbs_id", None) or None,
                cost_line_id=cost_line_id,
                budget_basis=budget.basis,
                budget_rate=budget.rate,
                budget_qty=budget.quantity.quantize(_QTY_Q),
                budget_value=budget.amount.quantize(_MONEY_Q),
                po_committed_qty=figures.po_qty.quantize(_QTY_Q),
                po_committed_value=figures.po_value.quantize(_MONEY_Q),
                subcontract_committed_qty=figures.sub_qty.quantize(_QTY_Q),
                subcontract_committed_value=figures.sub_value.quantize(_MONEY_Q),
                committed_qty=committed_qty.quantize(_QTY_Q),
                committed_value=committed_value.quantize(_MONEY_Q),
                remaining_qty=(budget.quantity - committed_qty).quantize(_QTY_Q),
                remaining_value=(budget.amount - committed_value).quantize(_MONEY_Q),
                received_qty=figures.received_qty.quantize(_QTY_Q),
                received_value=figures.received_value.quantize(_MONEY_Q),
            )
        )
    return rows


def _spread(
    acc: dict[str, LineFigures],
    vector: object,
    *,
    qty_field: str,
    value_field: str,
    qty: Decimal,
    value: Decimal,
) -> None:
    """Add one source row to its cost line(s), cut by the stored split."""
    from app.modules.costmodel.inheritance import expand

    shares = dict(getattr(vector, "shares", ()) or ())
    for line_id, part in expand(value, vector):  # type: ignore[arg-type]
        if line_id is None:
            continue
        fraction = Decimal(str(shares.get(line_id, 1))) if shares else Decimal("1")
        bucket = acc.setdefault(line_id, LineFigures())
        setattr(bucket, qty_field, getattr(bucket, qty_field) + qty * fraction)
        setattr(bucket, value_field, getattr(bucket, value_field) + part)


async def figures_by_cost_line(session: AsyncSession, project_id: uuid.UUID) -> dict[str, LineFigures]:
    """Committed and received quantity and value per cost line, in project currency."""
    from app.modules.costmodel.inheritance import SOURCE_CONTRACT_LINE, SOURCE_PO_ITEM, row_vectors
    from app.modules.costmodel.repository import BudgetLineRepository, _amount_in_base

    base, fx = await BudgetLineRepository(session)._project_fx_context(project_id)

    def in_base(amount: Decimal, currency: str | None) -> Decimal:
        return _amount_in_base(str(amount), (currency or "").strip().upper(), base, fx)

    acc: dict[str, LineFigures] = {}

    try:
        from app.modules.procurement.models import GoodsReceipt, GoodsReceiptItem, PurchaseOrder, PurchaseOrderItem
    except ImportError:  # pragma: no cover - procurement not installed
        PurchaseOrder = None  # noqa: N806
    if PurchaseOrder is not None:
        po_rows = (
            await session.execute(
                select(
                    PurchaseOrderItem.id,
                    PurchaseOrderItem.cost_line_id,
                    PurchaseOrderItem.quantity,
                    PurchaseOrderItem.amount,
                    PurchaseOrderItem.unit_rate,
                    PurchaseOrder.currency_code,
                )
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.po_id)
                .where(
                    PurchaseOrder.project_id == project_id,
                    PurchaseOrder.status.in_(PO_COMMITTED_STATUSES),
                    PurchaseOrderItem.cost_line_id.is_not(None),
                )
            )
        ).all()
        vectors = await row_vectors(session, SOURCE_PO_ITEM, {r[0]: r[1] for r in po_rows})
        rate_by_item: dict[uuid.UUID, tuple[Decimal, str]] = {}
        for item_id, _line, qty, amount, unit_rate, ccy in po_rows:
            vector = vectors[str(item_id)]
            _spread(
                acc,
                vector,
                qty_field="po_qty",
                value_field="po_value",
                qty=_dec(qty),
                value=in_base(_dec(amount), ccy),
            )
            rate_by_item[item_id] = (_dec(unit_rate), ccy or "")

        if rate_by_item:
            received_rows = (
                await session.execute(
                    select(GoodsReceiptItem.po_item_id, GoodsReceiptItem.quantity_received)
                    .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptItem.receipt_id)
                    .where(
                        GoodsReceipt.status == "confirmed",
                        GoodsReceiptItem.po_item_id.in_(sorted(rate_by_item)),
                    )
                )
            ).all()
            for po_item_id, qty_received in received_rows:
                rate, ccy = rate_by_item[po_item_id]
                qty = _dec(qty_received)
                _spread(
                    acc,
                    vectors[str(po_item_id)],
                    qty_field="received_qty",
                    value_field="received_value",
                    qty=qty,
                    value=in_base(qty * rate, ccy),
                )

    try:
        from app.modules.contracts.models import Contract, ContractLine, ProgressClaimLine
    except ImportError:  # pragma: no cover - contracts not installed
        Contract = None  # noqa: N806
    if Contract is not None:
        sub_rows = (
            await session.execute(
                select(
                    ContractLine.id,
                    ContractLine.cost_line_id,
                    ContractLine.quantity,
                    ContractLine.total_value,
                    ContractLine.unit_rate,
                    Contract.currency,
                )
                .join(Contract, Contract.id == ContractLine.contract_id)
                .where(
                    Contract.project_id == project_id,
                    Contract.counterparty_type == "subcontractor",
                    Contract.status.in_(SUBCONTRACT_LIVE_STATUSES),
                    ContractLine.cost_line_id.is_not(None),
                )
            )
        ).all()
        vectors = await row_vectors(session, SOURCE_CONTRACT_LINE, {r[0]: r[1] for r in sub_rows})
        line_meta: dict[uuid.UUID, tuple[Decimal, str]] = {}
        for line_id, _cl, qty, total, unit_rate, ccy in sub_rows:
            _spread(
                acc,
                vectors[str(line_id)],
                qty_field="sub_qty",
                value_field="sub_value",
                qty=_dec(qty),
                value=in_base(_dec(total), ccy),
            )
            line_meta[line_id] = (_dec(unit_rate), ccy or "")

        if line_meta:
            claim_rows = (
                await session.execute(
                    select(ProgressClaimLine.contract_line_id, ProgressClaimLine.cumulative_completed_value).where(
                        ProgressClaimLine.contract_line_id.in_(sorted(line_meta))
                    )
                )
            ).all()
            # The cumulative column already running-totals earlier claims, so
            # the latest position of a line is its largest cumulative value.
            certified: dict[uuid.UUID, Decimal] = {}
            for contract_line_id, cumulative in claim_rows:
                certified[contract_line_id] = max(certified.get(contract_line_id, ZERO), _dec(cumulative))
            for contract_line_id, value in certified.items():
                rate, ccy = line_meta[contract_line_id]
                qty = (value / rate) if rate > 0 else ZERO
                _spread(
                    acc,
                    vectors[str(contract_line_id)],
                    qty_field="received_qty",
                    value_field="received_value",
                    qty=qty,
                    value=in_base(value, ccy),
                )
    return acc


async def build_commitment_grid(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    boq_id: uuid.UUID | None = None,
) -> CommitmentGrid:
    """The grid for a project (or one of its bills), every priced position."""
    from app.modules.boq.repository import PositionRepository
    from app.modules.costmodel.position_actuals import _project_currency

    repo = PositionRepository(session)
    if boq_id is not None:
        owners = await repo.project_ids_for_boqs([boq_id])
        positions = await repo.list_all_for_boq(boq_id) if owners.get(boq_id) == project_id else []
    else:
        positions = await repo.list_for_project(project_id)

    grid = CommitmentGrid(currency=await _project_currency(session, project_id))
    if not positions:
        return grid
    grid.rows = assemble_grid(list(positions), await figures_by_cost_line(session, project_id))
    return grid
