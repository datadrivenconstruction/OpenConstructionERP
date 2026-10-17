# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Writers of the inherited cost line, one per link of the chain, and the hand override.

Every module that creates a cost-carrying row downstream of the bill calls
into here when it writes the row: bid management for scope lines, the two
award paths for contract lines (and procurement for the order items of the
same award), change orders for their items, finance for invoice lines. The
rules of precedence live in one place:

* bid line:      the bill position
* contract line: its bid line, else its bill position, else the contract's own account
* change item:   the schedule line it changes, else its bill position, else the
                 contract's own account, else the one cost line the whole contract is on
* invoice line:  the schedule line it bills

A row that already names a cost line keeps it: inheritance fills what is
missing and never overwrites a person's choice. A person who puts a row on a
line outside what it inherits must give a reason, and the override is kept on
the row (``metadata.cost_line_override``), which is what rule V5 reads.

Imports of other modules' models stay inside the functions: they are plugins.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.inheritance import (
    FROM_BID_LINE,
    FROM_CONTRACT,
    FROM_CONTRACT_LINE,
    FROM_MANUAL,
    FROM_POSITION,
    NO_VECTOR,
    OVERRIDE_META_KEY,
    SOURCE_BID_LINE,
    SOURCE_CONTRACT_LINE,
    SOURCE_INVOICE_LINE,
    SOURCE_PO_ITEM,
    Inherited,
    Vector,
    drop_splits,
    first_inherited,
    lines_in_project,
    position_vectors,
    row_vector,
    row_vectors,
    write_split,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

#: ``ContractLine.metadata_`` key recording where the line's cost line came from.
SOURCE_META_KEY = "cost_line_source"

#: Kinds of row a person can put on a cost line from cost control.
KIND_CONTRACT_LINE = "contract_line"
KIND_PO_ITEM = "po_item"
KIND_CONTRACT = "contract"
KIND_CHANGE_ITEM = "change_order_item"
KIND_INVOICE_LINE = "invoice_line"
KIND_BID_LINE = "bid_line"
VECTOR_KINDS: tuple[str, ...] = (
    KIND_CONTRACT_LINE,
    KIND_PO_ITEM,
    KIND_CONTRACT,
    KIND_CHANGE_ITEM,
    KIND_INVOICE_LINE,
    KIND_BID_LINE,
)

#: A lump-sum line written for a contract that has no schedule: its unit.
LUMP_SUM_UNIT = "LS"

#: The shortest reason an override is accepted with, the same floor the manual forecast uses.
MIN_REASON_LENGTH = 3


def _problem(code: int, problem: str, message: str, **params: Any) -> HTTPException:
    return HTTPException(status_code=code, detail={"problem": problem, "message": message, **params})


def _uuid(raw: object) -> uuid.UUID | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _meta(row: Any) -> dict[str, Any]:
    raw = getattr(row, "metadata_", None)
    return dict(raw) if isinstance(raw, dict) else {}


async def _contract_default(session: AsyncSession, contract: Any) -> Vector:
    """A contract's own account, as a vector (empty when it has none)."""
    return Vector(main=str(contract.cost_line_id)) if getattr(contract, "cost_line_id", None) else NO_VECTOR


async def _sole_line_vector(session: AsyncSession, contract_id: uuid.UUID) -> Vector:
    """The one cost line every costed schedule line of the contract sits on, if there is exactly one."""
    from app.modules.contracts.models import ContractLine

    rows = await session.execute(
        select(ContractLine.cost_line_id)
        .where(ContractLine.contract_id == contract_id, ContractLine.cost_line_id.is_not(None))
        .distinct()
        .limit(2)
    )
    found = [r[0] for r in rows.all()]
    return Vector(main=str(found[0])) if len(found) == 1 else NO_VECTOR


# ── Bid lines ────────────────────────────────────────────────────────────────


async def inherit_bid_lines(session: AsyncSession, project_id: uuid.UUID, lines: list[Any]) -> int:
    """Give scope lines made from bill positions their position's cost line and split.

    Lines already on a cost line, or without a position, are left alone.
    Returns how many lines got a cost line.
    """
    todo = [
        ln
        for ln in lines
        if getattr(ln, "cost_line_id", None) is None and getattr(ln, "boq_position_id", None) is not None
    ]
    if not todo:
        return 0
    vectors = await position_vectors(session, [ln.boq_position_id for ln in todo])
    done = 0
    for ln in todo:
        vector = vectors.get(str(ln.boq_position_id), NO_VECTOR)
        if vector.empty:
            continue
        ln.cost_line_id = await write_split(
            session, project_id=project_id, source_type=SOURCE_BID_LINE, source_id=ln.id, vector=vector
        )
        done += 1
    await session.flush()
    return done


# ── Contract lines ───────────────────────────────────────────────────────────


async def contract_line_candidates(
    session: AsyncSession, contract: Any, lines: list[Any]
) -> dict[str, list[tuple[str, Vector | None]]]:
    """What each contract line would inherit, per source, in order of precedence."""
    from app.modules.bid_management.models import BidPackageLineItem

    bid_ids = {lid for ln in lines if (lid := _uuid(_meta(ln).get("bid_package_line_id")))}
    pos_ids = {pid for ln in lines if (pid := _uuid(_meta(ln).get("boq_position_id")))}
    bid_vectors: dict[str, Vector] = {}
    if bid_ids:
        mains = dict(
            (
                await session.execute(
                    select(BidPackageLineItem.id, BidPackageLineItem.cost_line_id).where(
                        BidPackageLineItem.id.in_(bid_ids)
                    )
                )
            ).all()
        )
        bid_vectors = await row_vectors(session, SOURCE_BID_LINE, mains)
    pos_vectors = await position_vectors(session, pos_ids)
    default = await _contract_default(session, contract)
    out: dict[str, list[tuple[str, Vector | None]]] = {}
    for ln in lines:
        meta = _meta(ln)
        bid = _uuid(meta.get("bid_package_line_id"))
        pos = _uuid(meta.get("boq_position_id"))
        out[str(ln.id)] = [
            (FROM_BID_LINE, bid_vectors.get(str(bid)) if bid else None),
            (FROM_POSITION, pos_vectors.get(str(pos)) if pos else None),
            (FROM_CONTRACT, default),
        ]
    return out


async def inherit_contract_lines(session: AsyncSession, contract: Any, lines: list[Any] | None = None) -> int:
    """Put the contract's lines that have no cost line on what they inherit.

    ``lines`` defaults to every line of the contract. A line already on a cost
    line keeps it. Returns how many lines got a cost line.
    """
    from app.modules.contracts.models import ContractLine

    if lines is None:
        lines = list(
            (await session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id))).scalars()
        )
    todo = [ln for ln in lines if ln.cost_line_id is None]
    if not todo:
        return 0
    candidates = await contract_line_candidates(session, contract, todo)
    done = 0
    for ln in todo:
        picked = first_inherited(candidates[str(ln.id)])
        if picked.vector.empty:
            continue
        ln.cost_line_id = await write_split(
            session,
            project_id=contract.project_id,
            source_type=SOURCE_CONTRACT_LINE,
            source_id=ln.id,
            vector=picked.vector,
        )
        meta = _meta(ln)
        meta[SOURCE_META_KEY] = picked.source
        ln.metadata_ = meta
        done += 1
    await session.flush()
    return done


async def copy_line_split(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID,
    source_main: object,
    target_type: str,
    target_id: uuid.UUID,
) -> uuid.UUID | None:
    """Give a new row the vector of the row it was made from; returns its main cost line."""
    vector = await row_vector(session, source_type, source_id, source_main)
    if vector.empty:
        return None
    return await write_split(
        session, project_id=project_id, source_type=target_type, source_id=target_id, vector=vector
    )


# ── Order items of an award ──────────────────────────────────────────────────


async def split_po_items_like_positions(
    session: AsyncSession, project_id: uuid.UUID, items_and_positions: list[tuple[Any, object]]
) -> int:
    """Give order items the split of the position they were priced against.

    The order item already holds the position's main cost line
    (:func:`~app.modules.procurement.cost_spine.resolve_cost_line_ids`). When
    the position is split, the item takes the split too, so the order and the
    contract of the same award fall on the same lines and the commitment rules
    can count the pair once on each of them. Returns how many items got a split.
    """
    wanted = [(item, pos) for item, pos in items_and_positions if pos and item.cost_line_id is not None]
    if not wanted:
        return 0
    vectors = await position_vectors(session, [pos for _, pos in wanted])
    done = 0
    for item, pos in wanted:
        vector = vectors.get(str(pos), NO_VECTOR)
        if not vector.is_split or str(item.cost_line_id) not in vector.lines:
            continue
        item.cost_line_id = await write_split(
            session, project_id=project_id, source_type=SOURCE_PO_ITEM, source_id=item.id, vector=vector
        )
        done += 1
    return done


# ── Change order items ───────────────────────────────────────────────────────


async def _order_contract(session: AsyncSession, order: Any) -> Any | None:
    from app.modules.contracts.models import Contract

    contract_id = _uuid(_meta(order).get("contract_id"))
    if contract_id is None:
        return None
    contract = await session.get(Contract, contract_id)
    if contract is None or contract.project_id != order.project_id:
        return None
    return contract


async def change_item_inherits(session: AsyncSession, order: Any, item_metadata: dict[str, Any]) -> Inherited:
    """What a change order item inherits, from the references in its metadata.

    The schedule line named by ``contract_line_id`` counts only when it is on
    the change order's own contract (or, for a change order on no contract, on
    a contract of the same project); a bill position only when it is in the
    same project.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.contracts.models import Contract, ContractLine

    contract = await _order_contract(session, order)
    candidates: list[tuple[str, Vector | None]] = []

    line_id = _uuid(item_metadata.get("contract_line_id"))
    line_vector: Vector | None = None
    if line_id is not None:
        row = (
            await session.execute(
                select(ContractLine.id, ContractLine.cost_line_id, ContractLine.contract_id, Contract.project_id)
                .join(Contract, Contract.id == ContractLine.contract_id)
                .where(ContractLine.id == line_id)
            )
        ).first()
        if row is not None and row[3] == order.project_id and (contract is None or row[2] == contract.id):
            line_vector = Vector(main=str(row[1])) if row[1] else None
    candidates.append((FROM_CONTRACT_LINE, line_vector))

    pos_id = _uuid(item_metadata.get("boq_position_id"))
    pos_vector: Vector | None = None
    if pos_id is not None:
        project = (
            await session.execute(
                select(BOQ.project_id).join(Position, Position.boq_id == BOQ.id).where(Position.id == pos_id)
            )
        ).scalar_one_or_none()
        if project == order.project_id:
            vec = (await position_vectors(session, [pos_id])).get(str(pos_id))
            # A change item carries one account: the position's main line.
            pos_vector = Vector(main=vec.main) if vec is not None and vec.main else None
    candidates.append((FROM_POSITION, pos_vector))

    if contract is not None:
        default = await _contract_default(session, contract)
        if default.empty:
            default = await _sole_line_vector(session, contract.id)
        candidates.append((FROM_CONTRACT, default))
    return first_inherited(candidates)


async def apply_change_item_inheritance(session: AsyncSession, order: Any, item: Any) -> None:
    """Fill a change item's cost line from what it inherits, unless it already has one."""
    if item.cost_line_id is not None:
        if not item.cost_line_source:
            item.cost_line_source = FROM_MANUAL
        return
    picked = await change_item_inherits(session, order, _meta(item))
    if picked.vector.main:
        item.cost_line_id = uuid.UUID(picked.vector.main)
        item.cost_line_source = picked.source


# ── Invoice lines ────────────────────────────────────────────────────────────


async def resolve_invoice_contract_lines(session: AsyncSession, project_id: uuid.UUID, items: list[Any]) -> None:
    """Check each line's ``contract_line_id`` and fill its ``cost_line_id`` from the schedule line.

    Refused (422) when the schedule line is not on a contract of the invoice's
    project, and when the line names a cost line the schedule line does not
    carry: that is two answers to one question, the same refusal a bill
    position gets. A schedule line on no cost line leaves the invoice line on
    none, where cost control lists it.
    """
    from app.modules.contracts.models import Contract, ContractLine

    wanted = {i.contract_line_id for i in items if getattr(i, "contract_line_id", None) is not None}
    if not wanted:
        return
    rows = (
        await session.execute(
            select(ContractLine.id, ContractLine.cost_line_id, Contract.project_id)
            .join(Contract, Contract.id == ContractLine.contract_id)
            .where(ContractLine.id.in_(wanted))
        )
    ).all()
    found = {r[0]: (r[1], r[2]) for r in rows}
    vectors = await row_vectors(session, SOURCE_CONTRACT_LINE, {lid: v[0] for lid, v in found.items()})
    for item in items:
        line_id = getattr(item, "contract_line_id", None)
        if line_id is None:
            continue
        if line_id not in found or found[line_id][1] != project_id:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "contract_line_not_in_project",
                "The contract line is not on a contract of this invoice's project.",
            )
        vector = vectors.get(str(line_id), NO_VECTOR)
        if item.cost_line_id is None:
            item.cost_line_id = uuid.UUID(vector.main) if vector.main else None
        elif vector.lines and str(item.cost_line_id) not in vector.lines:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "cost_line_conflicts_with_contract_line",
                "This line names a contract line and a cost line that contract line is not on. Send one of them.",
            )


async def split_invoice_lines(session: AsyncSession, project_id: uuid.UUID, invoice_id: uuid.UUID) -> int:
    """Give the invoice's lines that bill a split schedule line that split, once the lines exist."""
    from app.modules.contracts.models import ContractLine
    from app.modules.finance.models import InvoiceLineItem

    rows = (
        (
            await session.execute(
                select(InvoiceLineItem).where(
                    InvoiceLineItem.invoice_id == invoice_id, InvoiceLineItem.contract_line_id.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    mains = dict(
        (
            await session.execute(
                select(ContractLine.id, ContractLine.cost_line_id).where(
                    ContractLine.id.in_({r.contract_line_id for r in rows})
                )
            )
        ).all()
    )
    vectors = await row_vectors(session, SOURCE_CONTRACT_LINE, mains)
    done = 0
    for r in rows:
        vector = vectors.get(str(r.contract_line_id), NO_VECTOR)
        if vector.is_split and r.cost_line_id is not None and str(r.cost_line_id) == vector.main:
            await write_split(
                session, project_id=project_id, source_type=SOURCE_INVOICE_LINE, source_id=r.id, vector=vector
            )
            done += 1
        else:
            await drop_splits(session, SOURCE_INVOICE_LINE, [r.id])
    await session.flush()
    return done


# ── A lump-sum contract's single account ─────────────────────────────────────


async def set_contract_account(
    session: AsyncSession, contract: Any, cost_line_id: uuid.UUID | None, user_id: str | None
) -> dict[str, int]:
    """Put a contract on one account.

    A contract with no schedule gets one lump-sum line for its whole value on
    that account, so the money is committed somewhere the cost report sees
    (lines are what commitment is summed from). A contract with a schedule
    keeps it, and its lines that have no cost line yet take this one. Clearing
    the account leaves every line where it is.
    """
    from app.modules.contracts.models import ContractLine

    if cost_line_id is not None and not await lines_in_project(session, contract.project_id, [cost_line_id]):
        raise _problem(status.HTTP_404_NOT_FOUND, "cost_line_not_found", "Cost line not found")
    if contract.status in ("terminated", "completed") and cost_line_id is not None:
        # The money of a closed contract is history; re-coding it is a correction a person makes line by line.
        lines_count = (
            await session.execute(select(func.count()).where(ContractLine.contract_id == contract.id))
        ).scalar_one()
        if not lines_count:
            raise _problem(
                status.HTTP_409_CONFLICT,
                "contract_closed",
                "This contract is closed, so no schedule line can be added to it.",
            )
    contract.cost_line_id = cost_line_id
    created = filled = 0
    if cost_line_id is None:
        await session.flush()
        return {"lines_created": 0, "lines_filled": 0}
    lines = list((await session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id))).scalars())
    if not lines:
        if Decimal(str(contract.total_value or 0)) != ZERO:
            line = ContractLine(
                contract_id=contract.id,
                code="LS",
                description=(contract.title or contract.code or "")[:2000],
                line_type="work",
                unit=LUMP_SUM_UNIT,
                quantity=Decimal("1"),
                unit_rate=Decimal(str(contract.total_value)),
                total_value=Decimal(str(contract.total_value)),
                # A line that restates the contract sum moves nothing, so it is part of the contract as signed.
                original_value=Decimal(str(contract.total_value)) if contract.status != "draft" else None,
                order_index=0,
                cost_line_id=cost_line_id,
            )
            line.metadata_ = {SOURCE_META_KEY: FROM_CONTRACT, "lump_sum_account": True}
            session.add(line)
            created = 1
    else:
        for ln in lines:
            if ln.cost_line_id is None:
                ln.cost_line_id = cost_line_id
                meta = _meta(ln)
                meta[SOURCE_META_KEY] = FROM_CONTRACT
                ln.metadata_ = meta
                filled += 1
    await session.flush()
    logger.info(
        "Contract %s put on cost line %s by %s (%d line created, %d filled)",
        contract.code,
        cost_line_id,
        user_id,
        created,
        filled,
    )
    return {"lines_created": created, "lines_filled": filled}


# ── The hand override ────────────────────────────────────────────────────────


async def _load_target(session: AsyncSession, project_id: uuid.UUID, kind: str, target_id: uuid.UUID) -> Any:
    """The row behind ``kind``/``target_id``, refused with 404 unless it belongs to ``project_id``."""
    not_found = _problem(status.HTTP_404_NOT_FOUND, "target_not_found", "Target not found")
    if kind == KIND_CONTRACT_LINE:
        from app.modules.contracts.models import Contract, ContractLine

        row = await session.get(ContractLine, target_id)
        contract = await session.get(Contract, row.contract_id) if row is not None else None
        if contract is None or contract.project_id != project_id:
            raise not_found
        return row
    if kind == KIND_CONTRACT:
        from app.modules.contracts.models import Contract

        row = await session.get(Contract, target_id)
        if row is None or row.project_id != project_id:
            raise not_found
        return row
    if kind == KIND_PO_ITEM:
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

        row = await session.get(PurchaseOrderItem, target_id)
        po = await session.get(PurchaseOrder, row.po_id) if row is not None else None
        if po is None or po.project_id != project_id:
            raise not_found
        return row
    if kind == KIND_CHANGE_ITEM:
        from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem

        row = await session.get(ChangeOrderItem, target_id)
        order = await session.get(ChangeOrder, row.change_order_id) if row is not None else None
        if order is None or order.project_id != project_id:
            raise not_found
        return row
    if kind == KIND_INVOICE_LINE:
        from app.modules.finance.models import Invoice, InvoiceLineItem

        row = await session.get(InvoiceLineItem, target_id)
        invoice = await session.get(Invoice, row.invoice_id) if row is not None else None
        if invoice is None or invoice.project_id != project_id:
            raise not_found
        return row
    if kind == KIND_BID_LINE:
        from app.modules.bid_management.models import BidPackage, BidPackageLineItem

        row = await session.get(BidPackageLineItem, target_id)
        package = await session.get(BidPackage, row.package_id) if row is not None else None
        if package is None or package.project_id != project_id:
            raise not_found
        return row
    raise _problem(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_kind", "Unknown kind", kind=kind)


async def inherited_for(session: AsyncSession, kind: str, row: Any) -> Inherited:
    """What ``row`` inherits from the record above it in the chain (empty when nothing)."""
    if kind == KIND_CONTRACT_LINE:
        from app.modules.contracts.models import Contract

        contract = await session.get(Contract, row.contract_id)
        if contract is None:
            return Inherited()
        return first_inherited((await contract_line_candidates(session, contract, [row]))[str(row.id)])
    if kind == KIND_CHANGE_ITEM:
        from app.modules.changeorders.models import ChangeOrder

        order = await session.get(ChangeOrder, row.change_order_id)
        return await change_item_inherits(session, order, _meta(row)) if order is not None else Inherited()
    if kind == KIND_INVOICE_LINE:
        from app.modules.contracts.models import ContractLine

        if row.contract_line_id is None:
            return Inherited()
        line = await session.get(ContractLine, row.contract_line_id)
        if line is None:
            return Inherited()
        vector = await row_vector(session, SOURCE_CONTRACT_LINE, line.id, line.cost_line_id)
        return Inherited(vector=vector, source=FROM_CONTRACT_LINE) if not vector.empty else Inherited()
    if kind == KIND_BID_LINE:
        if row.boq_position_id is None:
            return Inherited()
        vector = (await position_vectors(session, [row.boq_position_id])).get(str(row.boq_position_id), NO_VECTOR)
        return Inherited(vector=vector, source=FROM_POSITION) if not vector.empty else Inherited()
    return Inherited()


#: Rows without metadata to keep an override on: a bid line follows its position, an invoice line its schedule line.
_NO_OVERRIDE_KINDS = frozenset({KIND_BID_LINE, KIND_INVOICE_LINE})

_SPLIT_SOURCE = {
    KIND_CONTRACT_LINE: SOURCE_CONTRACT_LINE,
    KIND_PO_ITEM: SOURCE_PO_ITEM,
    KIND_INVOICE_LINE: SOURCE_INVOICE_LINE,
    KIND_BID_LINE: SOURCE_BID_LINE,
}


async def set_vector(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    kind: str,
    target_id: uuid.UUID,
    mode: str,
    cost_line_id: uuid.UUID | None,
    reason: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    """Put one row on a cost line, take back what it inherits, or clear it.

    ``mode``: ``set`` puts the row whole on ``cost_line_id``; ``inherit`` gives
    it what it inherits (its split included) and drops any override; ``clear``
    takes it off every line, into suspense. A ``set`` onto a line outside what
    the row inherits is an override and needs a ``reason``; it is recorded on
    the row with who and when.

    Returns ``{"cost_line_id", "source", "override"}`` as the row now stands.
    """
    if kind not in VECTOR_KINDS:
        raise _problem(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_kind", "Unknown kind", kind=kind)
    row = await _load_target(session, project_id, kind, target_id)
    if kind == KIND_CONTRACT:
        if mode == "inherit":
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing_to_inherit", "A contract inherits no account."
            )
        result = await set_contract_account(session, row, cost_line_id if mode == "set" else None, user_id)
        return {
            "cost_line_id": str(row.cost_line_id) if row.cost_line_id else None,
            "source": FROM_MANUAL if row.cost_line_id else None,
            "override": False,
            **result,
        }

    split_type = _SPLIT_SOURCE.get(kind)
    inherited = await inherited_for(session, kind, row)
    meta = _meta(row) if hasattr(row, "metadata_") else {}
    override = False

    if mode == "inherit":
        if inherited.vector.empty:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "nothing_to_inherit",
                "Nothing above this row names a cost line yet.",
            )
        vector = inherited.vector if split_type else Vector(main=inherited.vector.main)
        if split_type:
            row.cost_line_id = await write_split(
                session, project_id=project_id, source_type=split_type, source_id=row.id, vector=vector
            )
        else:
            row.cost_line_id = uuid.UUID(vector.main) if vector.main else None
        meta.pop(OVERRIDE_META_KEY, None)
        source = inherited.source
    elif mode == "set":
        if cost_line_id is None:
            raise _problem(status.HTTP_422_UNPROCESSABLE_CONTENT, "cost_line_required", "Choose a cost line.")
        if not await lines_in_project(session, project_id, [cost_line_id]):
            raise _problem(status.HTTP_404_NOT_FOUND, "cost_line_not_found", "Cost line not found")
        override = bool(inherited.vector.lines) and str(cost_line_id) not in inherited.vector.lines
        if override and kind in _NO_OVERRIDE_KINDS:
            # These rows keep no record to audit an override on: they follow the row above them.
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "override_not_allowed",
                "This row follows the record it was made from; change the cost line there.",
            )
        clean_reason = (reason or "").strip()
        if override and len(clean_reason) < MIN_REASON_LENGTH:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "override_reason_required",
                "This row inherits another cost line. Say why it goes on this one.",
            )
        if split_type:
            await drop_splits(session, split_type, [row.id])
        row.cost_line_id = cost_line_id
        if override:
            meta[OVERRIDE_META_KEY] = {
                "reason": clean_reason[:2000],
                "by": user_id,
                "at": datetime.now(UTC).isoformat(),
                "inherited": inherited.vector.main,
            }
        else:
            meta.pop(OVERRIDE_META_KEY, None)
        source = FROM_MANUAL if override or inherited.vector.empty else inherited.source
    elif mode == "clear":
        if split_type:
            await drop_splits(session, split_type, [row.id])
        row.cost_line_id = None
        meta.pop(OVERRIDE_META_KEY, None)
        source = None
    else:
        raise _problem(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_mode", "Unknown mode", mode=mode)

    if kind == KIND_CHANGE_ITEM:
        row.cost_line_source = source
    if hasattr(row, "metadata_"):
        if kind == KIND_CONTRACT_LINE:
            if source:
                meta[SOURCE_META_KEY] = source
            else:
                meta.pop(SOURCE_META_KEY, None)
        row.metadata_ = dict(meta)
    await session.flush()
    return {
        "cost_line_id": str(row.cost_line_id) if row.cost_line_id else None,
        "source": source,
        "override": override,
    }
