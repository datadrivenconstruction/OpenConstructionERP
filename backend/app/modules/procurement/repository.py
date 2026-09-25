# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement data access layer.

All database queries for procurement entities live here.
No business logic - pure data access.
"""

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.orm_write import apply_update
from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    MaterialRequisition,
    PORetainageRelease,
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)

#: Statuses a PO can only reach by leaving ``draft``. Recorded in the
#: status-change audit trail, they are what proves a PO was once live even
#: after ``cancelled -> draft`` has put it back in ``draft``.
_POST_DRAFT_PO_STATUSES = ("approved", "issued", "partially_received", "completed")


class PurchaseOrderRepository:
    """Data access for PurchaseOrder model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, po_id: uuid.UUID) -> PurchaseOrder | None:
        """Get PO by ID (with items and GRs via selectin).

        Uses ``selectinload`` to eagerly load items and goods_receipts
        so they are available outside the async context.
        """
        from sqlalchemy.orm import selectinload

        # ``populate_existing`` forces the eager loaders to overwrite any
        # already-cached column values and relationship collections on an
        # identity-mapped instance. Without it, a PO that is still in the
        # session with an ``items`` collection that was loaded empty (e.g. a
        # freshly created PO whose line items were inserted afterwards, or a PO
        # whose items were just replaced) would keep that stale empty/old
        # collection, since ``selectinload`` will not clobber an already-loaded
        # one. This makes ``get`` an authoritative "current state" read.
        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.items),
                selectinload(PurchaseOrder.goods_receipts),
            )
            .where(PurchaseOrder.id == po_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        vendor_contact_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PurchaseOrder], int]:
        """List POs with filters and pagination.

        The PO list response (``POResponse``) never serialises
        ``goods_receipts``, but the relationship defaults to ``lazy="selectin"``
        on the model, so a plain ``select(PurchaseOrder)`` would still fire an
        extra batched SELECT for every listed PO's goods receipts AND a second
        one for their line items - pure waste on a hot list path. ``noload``
        suppresses that GR eager-load for the list only (``items`` is kept
        because the response includes it); the detail ``get`` still eager-loads
        both relationships.
        """
        from sqlalchemy.orm import noload

        base = select(PurchaseOrder).options(noload(PurchaseOrder.goods_receipts))

        if project_id is not None:
            base = base.where(PurchaseOrder.project_id == project_id)
        if status is not None:
            base = base.where(PurchaseOrder.status == status)
        if vendor_contact_id is not None:
            base = base.where(PurchaseOrder.vendor_contact_id == vendor_contact_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PurchaseOrder.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, po: PurchaseOrder) -> PurchaseOrder:
        """Insert a new PO.

        After flush we refresh to eagerly load ``selectin`` relationships
        (items, goods_receipts) so the caller can safely serialize the object
        outside the async greenlet context.
        """
        self.session.add(po)
        await self.session.flush()
        await self.session.refresh(po)
        return po

    async def update(self, po_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a PO.

        Reconciles only this PO. The previous ``expire_all()`` marked every
        loaded instance stale, so the next attribute read anywhere in the
        session became a lazy load from async code and raised MissingGreenlet.
        """
        await apply_update(self.session, PurchaseOrder, po_id, **fields)

    async def lock_for_update(self, po_id: uuid.UUID) -> None:
        """Take a row-level write lock on a PO for the rest of the transaction.

        A concurrent transaction that calls this for the same PO blocks until
        this transaction commits, serialising read-modify-write critical
        sections (e.g. incrementing the cumulative ``retainage_released_amount``
        string column, which cannot be incremented atomically in SQL). ``FOR
        UPDATE`` is honoured on PostgreSQL, the only supported backend. Mirrors
        the ``with_for_update`` pattern in cde/property_dev repositories.
        """
        await self.session.execute(select(PurchaseOrder.id).where(PurchaseOrder.id == po_id).with_for_update())

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        """Compute aggregate procurement statistics for a project.

        Returns dict with total_pos, by_status, total_committed,
        total_received (confirmed GR count), pending_delivery_count.
        """
        # Total POs
        total_stmt = select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.project_id == project_id)
        total_pos = (await self.session.execute(total_stmt)).scalar_one()

        # By status
        status_stmt = (
            select(PurchaseOrder.status, func.count())
            .where(PurchaseOrder.project_id == project_id)
            .group_by(PurchaseOrder.status)
        )
        status_rows = (await self.session.execute(status_stmt)).all()
        by_status = {row[0]: row[1] for row in status_rows}

        # Total committed = SUM(amount_total) for non-cancelled POs
        # amount_total is stored as string, so we cast in Python after fetching
        committed_stmt = (
            select(PurchaseOrder.amount_total)
            .where(PurchaseOrder.project_id == project_id)
            .where(PurchaseOrder.status != "cancelled")
        )
        committed_rows = (await self.session.execute(committed_stmt)).all()
        from decimal import InvalidOperation

        total_committed = Decimal("0")
        for row in committed_rows:
            try:
                total_committed += Decimal(row[0])
            except (InvalidOperation, ValueError, TypeError):
                pass

        # Count of confirmed goods receipts
        from app.modules.procurement.models import GoodsReceipt

        received_stmt = (
            select(func.count())
            .select_from(GoodsReceipt)
            .join(PurchaseOrder, GoodsReceipt.po_id == PurchaseOrder.id)
            .where(PurchaseOrder.project_id == project_id)
            .where(GoodsReceipt.status == "confirmed")
        )
        total_received = (await self.session.execute(received_stmt)).scalar_one()

        # POs pending delivery (issued or partially_received)
        pending_stmt = (
            select(func.count())
            .select_from(PurchaseOrder)
            .where(PurchaseOrder.project_id == project_id)
            .where(PurchaseOrder.status.in_(("issued", "partially_received")))
        )
        pending_delivery = (await self.session.execute(pending_stmt)).scalar_one()

        return {
            "total_pos": total_pos,
            "by_status": by_status,
            "total_committed": str(total_committed),
            "total_received": total_received,
            "pending_delivery_count": pending_delivery,
        }

    async def next_po_number(self, project_id: uuid.UUID) -> str:
        """Generate the next PO number for a project.

        Uses the NUMERIC MAX of the existing PO suffixes (not a lexicographic
        string MAX) to avoid race conditions where COUNT-based generation would
        produce duplicates under concurrency, and to keep ordering correct past
        PO-999 (a string MAX ranks 'PO-999' above 'PO-1000'). Only canonical
        ``PO-<digits>`` rows are cast: a plain ``LIKE 'PO-%'`` filter still
        admits ``PO-`` or ``PO-DRAFT`` rows whose suffix PostgreSQL refuses to
        cast (``invalid input syntax for type integer``), so the numeric regex
        filter is required for correctness, not cosmetic.
        """
        from sqlalchemy import Integer as SAInteger
        from sqlalchemy import cast
        from sqlalchemy.sql import func as sqlfunc

        stmt = select(
            sqlfunc.coalesce(
                sqlfunc.max(
                    cast(
                        func.substr(PurchaseOrder.po_number, 4),
                        SAInteger,
                    )
                ),
                0,
            )
        ).where(
            PurchaseOrder.project_id == project_id,
            PurchaseOrder.po_number.regexp_match("^PO-[0-9]+$"),
        )
        max_suffix = (await self.session.execute(stmt)).scalar_one()
        return f"PO-{max_suffix + 1:03d}"

    # ── Removal support: who is holding this PO ──────────────────────────
    #
    # Counting queries, one per holder kind, so a refusal can name what is in
    # the way instead of saying "in use". They are separate rather than one
    # UNION because the kinds do not share a table and a caller that only
    # needs one should not pay for the rest.

    async def count_goods_receipts(self, po_id: uuid.UUID) -> int:
        """Number of goods receipts booked against this PO, any status."""
        stmt = select(func.count()).select_from(GoodsReceipt).where(GoodsReceipt.po_id == po_id)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def count_retainage_releases(self, po_id: uuid.UUID) -> int:
        """Number of retainage releases already paid out against this PO."""
        stmt = select(func.count()).select_from(PORetainageRelease).where(PORetainageRelease.po_id == po_id)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def count_requisitions(self, po_id: uuid.UUID) -> int:
        """Number of material requisitions this PO was raised from.

        ``MaterialRequisition.po_id`` is ``ON DELETE SET NULL``, so a raw
        delete of the PO does not fail here - it silently unlinks the
        requisition and the requisition's own history stops explaining what
        was bought against it. That silence is exactly why it is counted.
        """
        stmt = select(func.count()).select_from(MaterialRequisition).where(MaterialRequisition.po_id == po_id)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def linked_payable_invoices(self, po_id: uuid.UUID, project_id: uuid.UUID) -> Sequence[Any]:
        """The payable invoices that bill against this PO, any status.

        Finance is an optional module and its ``Invoice`` carries no foreign
        key to a PO. The link is ``Invoice.purchase_order_id``, or, on invoices
        ``create_invoice_from_po`` raised before that column existed, the
        ``metadata_["po_id"]`` stamp (``finance.po_link`` says why both). A
        reader of only one of the two would report zero for half the invoices.

        The stamp is matched in Python because the JSON key lookup is not
        portable across the backends the test suite runs on, and the candidate
        set is one project's payables. Empty when finance is not installed.
        """
        try:
            from app.modules.finance.models import Invoice
            from app.modules.finance.po_link import invoice_po_link
        except Exception:  # noqa: BLE001 - finance is an optional module
            logger.debug("Finance module unavailable; PO %s invoices not read", po_id)
            return []

        stmt = select(Invoice).where(
            Invoice.project_id == project_id,
            Invoice.invoice_direction == "payable",
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [inv for inv in rows if invoice_po_link(inv.purchase_order_id, inv.metadata_) == po_id]

    async def invoiced_net_by_po(
        self, project_id: uuid.UUID, pos: Sequence[PurchaseOrder]
    ) -> dict[uuid.UUID, tuple[Decimal, int]]:
        """Net invoiced to date and invoice count per order, for one project's orders.

        Counts the invoices the finance dashboard counts as invoiced
        (``finance.cost_position.INVOICED_STATUSES``) and only those in the
        order's own currency, so the figure reads against the order's net.
        One query for the whole page of orders.
        """
        wanted = {po.id: (po.currency_code or "").strip().upper() for po in pos}
        if not wanted:
            return {}
        try:
            from app.modules.finance.cost_position import INVOICED_STATUSES
            from app.modules.finance.models import Invoice
            from app.modules.finance.po_link import invoice_po_link
        except Exception:  # noqa: BLE001 - finance is an optional module
            return {}
        stmt = select(
            Invoice.purchase_order_id,
            Invoice.metadata_,
            Invoice.currency_code,
            Invoice.amount_subtotal,
        ).where(
            Invoice.project_id == project_id,
            Invoice.invoice_direction == "payable",
            Invoice.status.in_(INVOICED_STATUSES),
        )
        out: dict[uuid.UUID, tuple[Decimal, int]] = {}
        for column, meta, currency, subtotal in (await self.session.execute(stmt)).all():
            po_id = invoice_po_link(column, meta)
            if po_id not in wanted or (currency or "").strip().upper() != wanted[po_id]:
                continue
            net, count = out.get(po_id, (Decimal("0"), 0))
            out[po_id] = (net + Decimal(str(subtotal or 0)), count + 1)
        return out

    async def count_payable_invoices(self, po_id: uuid.UUID, project_id: uuid.UUID) -> int:
        """Number of payable invoices raised against this PO (see ``linked_payable_invoices``)."""
        return len(await self.linked_payable_invoices(po_id, project_id))

    async def has_left_draft(self, po_id: uuid.UUID) -> bool:
        """True when this PO has ever been approved, issued or received against.

        Current status cannot answer this on its own. The PO state machine
        allows ``cancelled -> draft``, so a PO that was approved, issued,
        cancelled and then reopened sits in ``draft`` again while its number
        is already in a supplier's inbox. The status-change audit trail is the
        only record of that history, and every door into ``approved`` and
        ``issued`` writes one.
        """
        from app.core.audit_log import ActivityLog

        stmt = (
            select(func.count())
            .select_from(ActivityLog)
            .where(
                ActivityLog.entity_type == "purchase_order",
                ActivityLog.entity_id == str(po_id),
                ActivityLog.to_status.in_(_POST_DRAFT_PO_STATUSES),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0) > 0

    async def delete(self, po_id: uuid.UUID) -> None:
        """Hard-delete a PO and, by cascade, its own line items.

        Callers must have cleared :meth:`count_goods_receipts` and friends
        first. This is the raw verb; the decision about whether a PO may be
        deleted at all belongs to the service.
        """
        await self.session.execute(delete(PurchaseOrder).where(PurchaseOrder.id == po_id))
        await self.session.flush()


class POItemRepository:
    """Data access for PurchaseOrderItem model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, item: PurchaseOrderItem) -> PurchaseOrderItem:
        """Insert a new PO item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete_by_po(self, po_id: uuid.UUID) -> None:
        """Delete all items for a PO."""
        stmt = delete(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po_id)
        await self.session.execute(stmt)
        await self.session.flush()


class GoodsReceiptRepository:
    """Data access for GoodsReceipt model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, gr_id: uuid.UUID) -> GoodsReceipt | None:
        """Get goods receipt by ID (with items via selectin).

        Uses an explicit ``selectinload`` + ``populate_existing`` rather than a
        bare ``session.get`` so ``items`` is authoritatively (re)loaded even
        when the row is already in the identity map in an expired state - e.g.
        straight after ``confirm_if_draft``/``update`` call
        ``session.expire_all()``. Without it a later synchronous ``.items``
        access (or response serialisation) could lazy-load from a sync context
        and raise MissingGreenlet on the async session.
        """
        from sqlalchemy.orm import selectinload

        stmt = (
            select(GoodsReceipt)
            .options(selectinload(GoodsReceipt.items))
            .where(GoodsReceipt.id == gr_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        po_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GoodsReceipt], int]:
        """List goods receipts with filters."""
        base = select(GoodsReceipt)

        if po_id is not None:
            base = base.where(GoodsReceipt.po_id == po_id)
        if status is not None:
            base = base.where(GoodsReceipt.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(GoodsReceipt.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def list_by_project(
        self,
        *,
        project_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        # NOTE: annotation is quoted (lazy) on purpose - this class defines a
        # method named ``list`` above, which shadows the ``list`` builtin inside
        # the class-body namespace, so an *eagerly evaluated* ``list[...]`` here
        # raises "'function' object is not subscriptable" at import time.
    ) -> "tuple[list[tuple[GoodsReceipt, str]], int]":
        """List goods receipts across ALL POs of a project.

        api-HIGH (GR tab): the frontend lists GRs by ``project_id`` (the
        active project) rather than by a single ``po_id``. We join
        GoodsReceipt -> PurchaseOrder so we can both scope to the project
        and carry each GR's parent ``po_number`` back to the response,
        without an N+1 lookup. Eager-loads ``items`` so the response
        aggregates can serialise outside the async greenlet.

        Returns ``([(GoodsReceipt, po_number), ...], total)``.
        """
        from sqlalchemy.orm import selectinload

        base = (
            select(GoodsReceipt, PurchaseOrder.po_number)
            .join(PurchaseOrder, GoodsReceipt.po_id == PurchaseOrder.id)
            .where(PurchaseOrder.project_id == project_id)
        )
        if status is not None:
            base = base.where(GoodsReceipt.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.options(selectinload(GoodsReceipt.items))
            .order_by(GoodsReceipt.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows], total

    async def create(self, gr: GoodsReceipt) -> GoodsReceipt:
        """Insert a new goods receipt."""
        self.session.add(gr)
        await self.session.flush()
        return gr

    async def update(self, gr_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a goods receipt.

        Reconciles only this receipt, for the reason given on
        :meth:`PORepository.update`.
        """
        await apply_update(self.session, GoodsReceipt, gr_id, **fields)

    async def confirm_if_draft(self, gr_id: uuid.UUID) -> bool:
        """Atomically flip a goods receipt draft -> confirmed.

        Returns True only when THIS call performed the transition (the row was
        still ``draft``). The ``WHERE status = 'draft'`` predicate makes a
        concurrent second confirm a no-op at the DB level, so two requests
        racing on the same GR cannot both flip it and double-publish
        ``procurement.gr.confirmed`` (which would let finance double-count the
        receipt against the budget). Mirrors the conditional-update idempotency
        guard used for status transitions elsewhere.
        """
        stmt = (
            update(GoodsReceipt)
            .where(GoodsReceipt.id == gr_id, GoodsReceipt.status == "draft")
            .values(status="confirmed")
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()
        return (result.rowcount or 0) > 0


class GRItemRepository:
    """Data access for GoodsReceiptItem model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, item: GoodsReceiptItem) -> GoodsReceiptItem:
        """Insert a new GR item."""
        self.session.add(item)
        await self.session.flush()
        return item


class PORetainageReleaseRepository:
    """Data access for PORetainageRelease - the retainage-release audit log."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, record: PORetainageRelease) -> PORetainageRelease:
        """Insert a new retainage-release record."""
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def list_for_po(
        self,
        po_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[PORetainageRelease], int]:
        """List release records for a PO, newest first, with the total count."""
        base = select(PORetainageRelease).where(PORetainageRelease.po_id == po_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PORetainageRelease.release_date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total
