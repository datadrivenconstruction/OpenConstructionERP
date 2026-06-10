"""‌⁠‍Procurement service - business logic for purchase orders and goods receipts.

Stateless service layer.

Event publishing (slice E):
    procurement.po.created      - new PO row inserted
    procurement.po.updated      - PO fields changed (incl. status transition)
    procurement.po.issued       - PO transitioned to 'issued'
    procurement.gr.created      - new goods receipt inserted
    procurement.gr.confirmed    - goods receipt confirmed (may flip PO status)
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.sql_numeric import numeric_value
from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    MaterialRequisition,
    MaterialRequisitionItem,
    PORetainageRelease,
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.modules.procurement.repository import (
    GoodsReceiptRepository,
    GRItemRepository,
    POItemRepository,
    PORetainageReleaseRepository,
    PurchaseOrderRepository,
)
from app.modules.procurement.schemas import (
    GRCreate,
    POCreate,
    POUpdate,
    ProcurementStatsResponse,
)

# ── Material Requisition FSM (R7) ─────────────────────────────────────────────


def _safe_decimal_str(v: object) -> str:
    """Coerce *v* to a canonical decimal string; return '0' on error."""
    try:
        return format(Decimal(str(v)), "f")
    except (InvalidOperation, ValueError, TypeError):
        return "0"


_MR_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"approved", "rejected", "draft"},
    "approved": {"ordered", "cancelled"},
    "ordered": {"received", "cancelled"},
    "received": {"consumed"},
    "consumed": set(),  # terminal
    "rejected": {"draft"},  # allow re-draft after rejection
    "cancelled": set(),  # terminal
}


def _mr_assert_transition(current: str, target: str) -> None:
    """Raise 409 if the requisition FSM does not allow current → target.

    Self-transitions (same status) are always allowed as no-ops.
    """
    if current == target:
        return  # idempotent write - always legal
    allowed = _MR_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Invalid requisition transition: '{current}' → '{target}'. "
                f"Allowed: {sorted(allowed) or 'none (terminal state)'}."
            ),
        )


def _compute_delivery_date(required_date: str | None, lead_time_days: int) -> str | None:
    """Compute estimated delivery date = required_date - lead_time_days.

    Returns an ISO-8601 date string, or None if inputs are invalid.
    Zero lead_time means "deliver on the required date" - returns None to
    signal that no meaningful pre-order window exists.
    Note: uses calendar days, not working-day calendar.
    """
    if not required_date or lead_time_days <= 0:
        return None
    try:
        req = date.fromisoformat(required_date)
        est = req - timedelta(days=lead_time_days)
        return est.isoformat()
    except (ValueError, TypeError):
        return None


def _mr_reconcile(
    items: "MaterialRequisitionItem | list[MaterialRequisitionItem]",
) -> dict[str, Decimal]:
    """Return aggregate quantity reconciliation across requisition items.

    Accepts either a single item or a list of items.

    Returns:
        requested, ordered, received, consumed, undelivered, unconsumed
        - all clamped at zero to avoid negative counters from data errors.
    """
    # Normalize: single item → one-element list
    if not isinstance(items, list):
        items = [items]

    def _d(v: object) -> Decimal:
        try:
            return max(Decimal(str(v)), Decimal("0"))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0")

    requested = sum((_d(i.quantity_requested) for i in items), Decimal("0"))
    ordered = sum((_d(i.quantity_ordered) for i in items), Decimal("0"))
    received = sum((_d(i.quantity_received) for i in items), Decimal("0"))
    consumed = sum((_d(i.quantity_consumed) for i in items), Decimal("0"))
    return {
        "requested": requested,
        "ordered": ordered,
        "received": received,
        "consumed": consumed,
        "undelivered": max(ordered - received, Decimal("0")),
        "unconsumed": max(received - consumed, Decimal("0")),
    }


logger = logging.getLogger(__name__)
_logger_ev = logging.getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "oe_procurement") -> None:
    """‌⁠‍Best-effort event publish - never blocks the caller on failure."""
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


# ── Allowed PO status transitions ───────────────────────────────────────────

_PO_STATUS_TRANSITIONS: dict[str, set[str]] = {
    # A PO is committed money, so it must be approved before it can be issued
    # to a vendor (TOP-30 #10). Budget is committed at approval, not issue.
    "draft": {"approved", "cancelled"},
    "approved": {"issued", "draft", "cancelled"},
    "issued": {"partially_received", "completed", "cancelled"},
    "partially_received": {"completed", "cancelled"},
    "completed": set(),  # terminal
    "cancelled": {"draft"},  # allow re-opening
}

_VALID_PO_STATUSES = set(_PO_STATUS_TRANSITIONS.keys())


def _parse_decimal(value: str, field_name: str = "value") -> Decimal:
    """‌⁠‍Parse a string to Decimal, raising a clear error on failure."""
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid numeric value for {field_name}: {value!r}",
        ) from exc


def _compute_po_total(subtotal: str, tax: str) -> str:
    """Compute amount_total = amount_subtotal + tax_amount."""
    s = _parse_decimal(subtotal, "amount_subtotal")
    t = _parse_decimal(tax, "tax_amount")
    return str(s + t)


def _validate_3way_match(
    po: PurchaseOrder,
    invoice_lines: list[dict],
) -> list[dict]:
    """Run 3-way match (PO ↔ GR ↔ Invoice) per PO line.

    For each PO line, sums ``quantity_received`` over GR items belonging to
    confirmed goods receipts. Any invoice line whose proposed quantity exceeds
    the matched received quantity is reported.

    ``invoice_lines`` is a list of dicts with keys:
        - ``po_item_id``: UUID of the PO line being invoiced (None = unmatched)
        - ``quantity``: proposed invoice quantity (string-decimal)
        - ``description``: line description (for the error payload)
        - ``ordinal``: 0-based index in the invoice (for the error payload)

    Returns a list of violation dicts (empty list = clean match). Lines without
    a ``po_item_id`` are skipped (free-text additions are out of scope).

    Each violation carries a ``reason`` field. The router maps:
        * ``reason == "no_confirmed_grs"`` → 400 (caller must explicitly force)
        * any other ``reason`` → 422 (quantity-mismatch / over-invoicing)

    The ``no_confirmed_grs`` reason fires only when goods receipts exist
    but none are confirmed (i.e. only draft GRs). When NO GR exists at all
    we still report it so over-invoicing is blocked.
    """
    received_by_po_item: dict[uuid.UUID, Decimal] = {}
    has_draft_grs = False
    has_any_grs = False
    for gr in po.goods_receipts or []:
        has_any_grs = True
        if gr.status != "confirmed":
            if gr.status == "draft":
                has_draft_grs = True
            continue
        for gr_item in gr.items or []:
            if gr_item.po_item_id is None:
                continue
            try:
                qty = Decimal(str(gr_item.quantity_received or "0"))
            except (InvalidOperation, ValueError, TypeError):
                qty = Decimal("0")
            received_by_po_item[gr_item.po_item_id] = received_by_po_item.get(gr_item.po_item_id, Decimal("0")) + qty

    po_items_by_id = {item.id: item for item in (po.items or [])}

    has_invoice_qty = any(
        (line.get("po_item_id") is not None and _to_decimal(line.get("quantity")) > Decimal("0"))
        for line in invoice_lines
    )

    # "No confirmed GRs" gate: fired when PO has line items, the invoice
    # carries positive quantities, and no confirmed GR exists yet. The
    # explicit ``no_confirmed_grs`` reason lets the router emit a 400 so
    # the user knows the workflow problem is the missing GR, not an
    # arithmetic mismatch (which would be 422).
    if not received_by_po_item and (po.items or []) and has_invoice_qty:
        message = (
            "Only draft goods receipts exist for this PO; confirm them or pass force=true to invoice without GR match."
            if has_draft_grs
            else "No goods receipts exist for this PO; pass force=true to invoice without GR match."
        )
        return [
            {
                "ordinal": None,
                "po_item_id": None,
                "description": None,
                "requested_qty": None,
                "received_qty": "0",
                "reason": "no_confirmed_grs",
                "has_draft_grs": has_draft_grs,
                "has_any_grs": has_any_grs,
                "message": message,
            }
        ]

    violations: list[dict] = []
    for line in invoice_lines:
        po_item_id = line.get("po_item_id")
        if po_item_id is None:
            continue
        po_item = po_items_by_id.get(po_item_id)
        if po_item is None:
            continue
        requested = _to_decimal(line.get("quantity"))
        received = received_by_po_item.get(po_item_id, Decimal("0"))
        if requested > received:
            violations.append(
                {
                    "ordinal": line.get("ordinal"),
                    "po_item_id": str(po_item_id),
                    "description": po_item.description,
                    "requested_qty": _fmt_qty(requested),
                    "received_qty": _fmt_qty(received),
                    "reason": "qty_exceeds_received",
                }
            )

    return violations


# Small rounding tolerance when comparing cumulative received vs ordered, so
# trailing-decimal noise on quantity strings does not spuriously reject a
# receipt that completes a line exactly.
_RECEIPT_TOLERANCE = Decimal("0.001")


def _to_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _fmt_qty(value: object) -> str:
    """Render a quantity uniformly, regardless of source.

    Quantities reach us as plain strings ("100"), but a SQL ``SUM`` over a
    ``numeric_value`` column comes back as a float (100.0). Without
    normalisation the same logical quantity renders two ways in one response
    ("ordered 100" vs "received 100.0"). ``Decimal.normalize`` strips the
    spurious trailing zeros and ``format(..., "f")`` keeps large values out of
    scientific notation (normalize alone yields ``1E+2``).
    """
    return format(_to_decimal(value).normalize(), "f")


class ProcurementService:
    """Business logic for procurement operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.po_repo = PurchaseOrderRepository(session)
        self.po_item_repo = POItemRepository(session)
        self.gr_repo = GoodsReceiptRepository(session)
        self.gr_item_repo = GRItemRepository(session)
        self.retainage_repo = PORetainageReleaseRepository(session)

    # ── Vendor prequalification gate (TOP-30 #20) ───────────────────────────

    async def _vendor_block_status(
        self,
        vendor_contact_id: str | None,
    ) -> tuple[bool, list[str]]:
        """Resolve a PO vendor's prequalification / block verdict.

        Maps the PO's CRM ``vendor_contact_id`` to the linked subcontractor
        (the unified vendor master is ``Subcontractor.contact_id``) and reads
        the same award-block reasons the subcontractors module computes:

        * ``subcontractor_blocked`` - the vendor is hard-flagged ``is_blocked``;
          the gate raises 409 (a blocked vendor must never receive a PO).
        * ``prequalification_<status>`` - the vendor's prequal is rejected /
          suspended; the gate does NOT block, it returns a non-blocking
          warning so the buyer can still raise the PO with eyes open.

        Returns ``(is_blocked, reasons)``. An unknown / ad-hoc vendor (no
        linked subcontractor, or no contact at all) yields ``(False, [])`` -
        never gated. The lookup is best-effort and never 500s a PO write: a
        failed resolution degrades to "no gate".
        """
        if not vendor_contact_id:
            return False, []
        try:
            contact_uuid = uuid.UUID(str(vendor_contact_id))
        except (ValueError, TypeError):
            return False, []
        try:
            from sqlalchemy import select

            from app.modules.subcontractors.models import Subcontractor
            from app.modules.subcontractors.service import subcontractor_award_block

            stmt = (
                select(Subcontractor)
                .where(
                    Subcontractor.contact_id == contact_uuid,
                    Subcontractor.is_active.is_(True),
                )
                .order_by(Subcontractor.created_at.desc())
                .limit(1)
            )
            sub = (await self.session.execute(stmt)).scalar_one_or_none()
        except Exception:  # noqa: BLE001 - resolution is non-critical
            return False, []
        if sub is None:
            return False, []
        verdict = subcontractor_award_block(sub)
        is_blocked = "subcontractor_blocked" in verdict.reasons
        return is_blocked, verdict.reasons

    async def _enforce_vendor_gate(
        self,
        vendor_contact_id: str | None,
    ) -> list[str]:
        """Apply the vendor prequalification gate, returning warnings.

        Hard-blocks (409) a vendor flagged ``is_blocked``; otherwise returns
        the non-blocking warning reasons (e.g. a rejected prequal) for the
        caller to surface in the PO response. Empty list = vendor is clean
        or ad-hoc.
        """
        is_blocked, reasons = await self._vendor_block_status(vendor_contact_id)
        if is_blocked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "vendor_blocked",
                    "message": (
                        "This vendor is blocked and cannot receive a purchase order. "
                        "Clear the block on the subcontractor record first."
                    ),
                    "reasons": reasons,
                },
            )
        return reasons

    # ── Purchase Orders ──────────────────────────────────────────────────────

    async def create_po(
        self,
        data: POCreate,
        user_id: str | None = None,
    ) -> PurchaseOrder:
        """Create a new purchase order with optional line items.

        Automatically computes amount_total = amount_subtotal + tax_amount.
        When ``items`` are supplied, ``amount_subtotal`` is re-aggregated as
        ``sum(quantity * unit_rate)`` so the PO totals always agree with the
        line items the caller actually persisted (BUG-015).
        """
        # Validate initial status - a PO always enters the FSM at "draft".
        # Allowing a caller to create one already "approved"/"issued"/"completed"
        # would bypass the approval gate that commits budget (TOP-30 #10). The
        # only legal entry state is "draft"; advance it via approve_po/issue_po.
        if data.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"A purchase order must be created in 'draft' status, not '{data.status}'. "
                    "Use the approve and issue actions to advance it through the workflow."
                ),
            )

        # Vendor prequalification gate (TOP-30 #20): hard-block a vendor
        # flagged ``is_blocked`` (409 here); a non-prequalified vendor is a
        # non-blocking warning stamped onto the PO below.
        vendor_warnings = await self._enforce_vendor_gate(data.vendor_contact_id)

        # Re-aggregate subtotal from items when items are supplied. Each item's
        # own ``amount`` is also normalised to ``quantity * unit_rate`` if the
        # caller passed the schema default of "0".
        item_amounts: list[Decimal] = []
        for item_data in data.items:
            qty = _parse_decimal(item_data.quantity, "item.quantity")
            rate = _parse_decimal(item_data.unit_rate, "item.unit_rate")
            line_total = qty * rate
            existing = _parse_decimal(item_data.amount, "item.amount")
            if existing == Decimal("0"):
                item_data.amount = str(line_total)
            item_amounts.append(line_total)

        if data.items:
            aggregated_subtotal = str(sum(item_amounts, Decimal("0")))
            data.amount_subtotal = aggregated_subtotal

        # Server-side total computation
        computed_total = _compute_po_total(data.amount_subtotal, data.tax_amount)

        # Inherit the parent project's currency when the caller did not
        # supply one - never hardcode EUR (task #217).
        currency_code = data.currency_code
        if not currency_code:
            from sqlalchemy import select

            from app.modules.projects.models import Project

            # Best-effort, mirrors boq ``_resolve_project_currency``: a
            # failed/unavailable lookup must never 500 a PO create - fall
            # back to "" (honest unknown, never a wrong hardcoded EUR -
            # task #217).
            try:
                proj_currency = (
                    await self.session.execute(select(Project.currency).where(Project.id == data.project_id))
                ).scalar_one_or_none()
            except Exception:  # noqa: BLE001 - lookup is non-critical
                proj_currency = None
            currency_code = proj_currency or ""

        explicit_po_number = data.po_number
        # Mirrors changeorders BUG-354: MAX(po_number)+1 is not atomic, so two
        # concurrent creates can compute the same suffix and one would 500 on
        # the uq_procurement_po_project_number constraint. Retry by re-reading
        # MAX for auto-numbered POs. Explicit numbers do not retry - a
        # collision there is a 409 client error.
        po = await self._create_po_with_retry(
            data=data,
            explicit_po_number=explicit_po_number,
            currency_code=currency_code,
            computed_total=computed_total,
            user_id=user_id,
        )

        # Create line items
        for idx, item_data in enumerate(data.items):
            item = PurchaseOrderItem(
                po_id=po.id,
                description=item_data.description,
                quantity=item_data.quantity,
                unit=item_data.unit,
                unit_rate=item_data.unit_rate,
                amount=item_data.amount,
                wbs_id=item_data.wbs_id,
                cost_category=item_data.cost_category,
                sort_order=item_data.sort_order if item_data.sort_order else idx,
            )
            await self.po_item_repo.create(item)

        # Reload the PO so the freshly inserted line items are populated on the
        # ``items`` relationship. ``po_repo.create`` refreshed the PO BEFORE the
        # items were inserted, so without this re-fetch the response would carry
        # an empty ``items: []`` collection (BUG-015).
        if data.items:
            reloaded = await self.po_repo.get(po.id)
            if reloaded is not None:
                po = reloaded

        await _safe_publish(
            "procurement.po.created",
            {
                "po_id": str(po.id),
                "project_id": str(po.project_id),
                "po_number": po.po_number,
                "po_type": po.po_type,
                "status": po.status,
                "vendor_contact_id": str(po.vendor_contact_id) if po.vendor_contact_id else None,
                "amount_total": po.amount_total,
                "currency_code": po.currency_code,
                "item_count": len(data.items),
            },
        )

        # Transient (non-persisted) attribute the router reads to surface the
        # non-blocking vendor-prequalification warnings on the response.
        po.vendor_warnings = vendor_warnings  # type: ignore[attr-defined]

        logger.info("PO created: %s (type=%s)", po.po_number, po.po_type)
        return po

    async def _create_po_with_retry(
        self,
        *,
        data: POCreate,
        explicit_po_number: str | None,
        currency_code: str,
        computed_total: str,
        user_id: str | None,
    ) -> PurchaseOrder:
        """Insert a PurchaseOrder row, retrying on auto-number collisions.

        Single break-on-success control flow:
          * explicit po_number collision → 409 immediately (no retry - caller
            asked for a specific number and a unique row already owns it).
          * auto-number collision → re-read MAX(po_number) and retry up to
            ``_MAX_RETRIES`` times.
          * retries exhausted → 503 with the last IntegrityError as cause.
        """
        _MAX_RETRIES = 5
        last_exc: IntegrityError | None = None
        for _attempt in range(_MAX_RETRIES):
            po_number = explicit_po_number or await self.po_repo.next_po_number(
                data.project_id,
            )
            po = PurchaseOrder(
                project_id=data.project_id,
                vendor_contact_id=data.vendor_contact_id,
                po_number=po_number,
                po_type=data.po_type,
                issue_date=data.issue_date,
                delivery_date=data.delivery_date,
                currency_code=currency_code,
                amount_subtotal=data.amount_subtotal,
                tax_amount=data.tax_amount,
                amount_total=computed_total,
                status=data.status,
                payment_terms=data.payment_terms,
                notes=data.notes,
                created_by=uuid.UUID(user_id) if user_id else None,
                metadata_=data.metadata,
            )
            try:
                return await self.po_repo.create(po)
            except IntegrityError as exc:
                last_exc = exc
                await self.session.rollback()
                if explicit_po_number:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(f"Purchase order number '{explicit_po_number}' already exists for this project."),
                    ) from exc
                # else: auto-number collision - try again with a fresh MAX read.

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not generate a unique PO number after "
                f"{_MAX_RETRIES} attempts (concurrent contention). Please retry."
            ),
        ) from last_exc

    async def get_po(self, po_id: uuid.UUID) -> PurchaseOrder:
        """Get PO by ID. Raises 404 if not found."""
        po = await self.po_repo.get(po_id)
        if po is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )
        return po

    async def list_pos(
        self,
        *,
        project_id: uuid.UUID | None = None,
        po_status: str | None = None,
        vendor_contact_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PurchaseOrder], int]:
        """List POs with filters."""
        return await self.po_repo.list(
            project_id=project_id,
            status=po_status,
            vendor_contact_id=vendor_contact_id,
            limit=limit,
            offset=offset,
        )

    async def update_po(
        self,
        po_id: uuid.UUID,
        data: POUpdate,
    ) -> PurchaseOrder:
        """Update PO fields and optionally replace items.

        Validates status transitions and recomputes amount_total when
        subtotal or tax are changed.
        """
        po = await self.get_po(po_id)  # 404 check

        fields = data.model_dump(exclude_unset=True, exclude={"items"})
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Re-apply the vendor prequalification gate (TOP-30 #20) only when the
        # PATCH actually changes the vendor - re-gate the NEW vendor, hard-block
        # if blocked, collect the non-blocking warnings for the response.
        vendor_warnings: list[str] = []
        if "vendor_contact_id" in fields:
            vendor_warnings = await self._enforce_vendor_gate(fields["vendor_contact_id"])

        # Validate status transition if status is being changed
        if "status" in fields and fields["status"] is not None:
            new_status = fields["status"]
            if new_status not in _VALID_PO_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"Invalid PO status: '{new_status}'. Allowed: {', '.join(sorted(_VALID_PO_STATUSES))}"),
                )
            allowed = _PO_STATUS_TRANSITIONS.get(po.status, set())
            if new_status != po.status and new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition PO from '{po.status}' to '{new_status}'. "
                        f"Allowed transitions: {', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        # Recompute total if subtotal or tax changed
        new_subtotal = fields.get("amount_subtotal", po.amount_subtotal)
        new_tax = fields.get("tax_amount", po.tax_amount)
        if "amount_subtotal" in fields or "tax_amount" in fields:
            fields["amount_total"] = _compute_po_total(
                new_subtotal or po.amount_subtotal,
                new_tax or po.tax_amount,
            )

        if fields:
            await self.po_repo.update(po_id, **fields)

        # Replace items if provided
        if data.items is not None:
            await self.po_item_repo.delete_by_po(po_id)
            item_amounts: list[Decimal] = []
            for idx, item_data in enumerate(data.items):
                # R8: recompute each line's amount from qty × rate so the
                # header totals stay consistent even when the caller omits
                # amount_subtotal / tax_amount from the PATCH body.
                try:
                    qty = Decimal(str(item_data.quantity or "0"))
                    rate = Decimal(str(item_data.unit_rate or "0"))
                except (InvalidOperation, ValueError, TypeError):
                    qty = Decimal("0")
                    rate = Decimal("0")
                line_total = qty * rate
                # If caller supplied amount == "0" (schema default), derive
                # it from the computed total; otherwise respect their value.
                if _to_decimal(item_data.amount) == Decimal("0"):
                    item_data.amount = str(line_total)
                item_amounts.append(line_total)
                item = PurchaseOrderItem(
                    po_id=po_id,
                    description=item_data.description,
                    quantity=item_data.quantity,
                    unit=item_data.unit,
                    unit_rate=item_data.unit_rate,
                    amount=item_data.amount,
                    wbs_id=item_data.wbs_id,
                    cost_category=item_data.cost_category,
                    sort_order=item_data.sort_order if item_data.sort_order else idx,
                )
                await self.po_item_repo.create(item)

            # Recompute PO header totals from new line items when the PATCH
            # body did not include explicit subtotal / tax overrides.
            # Without this, editing line quantities/rates via items=[...] left
            # amount_subtotal and amount_total stale (R8 bug).
            if "amount_subtotal" not in fields and "tax_amount" not in fields:
                new_subtotal_from_items = str(sum(item_amounts, Decimal("0")))
                current_tax = po.tax_amount or "0"
                recomputed_total = _compute_po_total(new_subtotal_from_items, current_tax)
                await self.po_repo.update(
                    po_id,
                    amount_subtotal=new_subtotal_from_items,
                    amount_total=recomputed_total,
                )

        updated = await self.po_repo.get(po_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )

        await _safe_publish(
            "procurement.po.updated",
            {
                "po_id": str(po_id),
                "project_id": str(updated.project_id),
                "updated_fields": list(fields.keys()),
                "status": updated.status,
            },
        )

        updated.vendor_warnings = vendor_warnings  # type: ignore[attr-defined]

        logger.info("PO updated: %s", po_id)
        return updated

    async def approve_po(self, po_id: uuid.UUID, approver_id: str | None = None) -> PurchaseOrder:
        """Approve a draft PO so it can be issued (TOP-30 #10).

        Approval is the commitment moment: it transitions ``draft -> approved``
        and publishes ``procurement.po.approved`` so finance commits the amount
        against the project budget. Issuing the PO to the vendor is a separate
        downstream step that requires this approval first.
        """
        po = await self.get_po(po_id)
        prior_status = po.status
        if prior_status == "approved":
            return po  # idempotent
        if prior_status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot approve PO in status '{prior_status}'",
            )
        await self.po_repo.update(po_id, status="approved")

        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=approver_id,
                entity_type="purchase_order",
                entity_id=str(po_id),
                action="status_changed",
                from_status=prior_status,
                to_status="approved",
                reason="PO approved via approve_po()",
                metadata={"po_number": po.po_number},
            )
        except Exception:
            logger.debug("FSM audit log skipped for PO %s approve", po_id)

        updated = await self.po_repo.get(po_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )

        await _safe_publish(
            "procurement.po.approved",
            {
                "po_id": str(po_id),
                "project_id": str(updated.project_id),
                "po_number": updated.po_number,
                "amount_total": updated.amount_total,
                "currency_code": updated.currency_code or "",
                "approver_id": approver_id or "",
            },
        )
        logger.info("PO approved: %s", updated.po_number)
        return updated

    async def issue_po(self, po_id: uuid.UUID) -> PurchaseOrder:
        """Transition PO to issued status (requires prior approval - TOP-30 #10)."""
        po = await self.get_po(po_id)
        prior_status = po.status
        if prior_status != "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot issue PO in status '{prior_status}'; a purchase order must be approved before it is issued"
                ),
            )
        # Re-check the hard block at issue time (TOP-30 #20): a vendor that was
        # blocked AFTER the PO was created must not receive live work. A
        # non-prequalified (but not blocked) vendor still issues - we re-surface
        # the warning on the issue response so the buyer sees it at the moment
        # the PO actually goes out, not only at create time.
        vendor_warnings = await self._enforce_vendor_gate(po.vendor_contact_id)
        await self.po_repo.update(po_id, status="issued")

        # FSM audit row - PO lifecycle is closely tied to the RFQ FSM (see
        # rfq.po_issued event). PO is not one of the six core FSMs but it
        # benefits from the same audit-log substrate for compliance.
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=None,
                entity_type="purchase_order",
                entity_id=str(po_id),
                action="status_changed",
                from_status=prior_status,
                to_status="issued",
                reason="PO issued via issue_po()",
                metadata={"po_number": po.po_number},
            )
        except Exception:
            logger.debug("FSM audit log skipped for PO %s issue", po_id)

        updated = await self.po_repo.get(po_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )

        await _safe_publish(
            "procurement.po.issued",
            {
                "po_id": str(po_id),
                "project_id": str(updated.project_id),
                "po_number": updated.po_number,
                "amount_total": updated.amount_total,
                "currency_code": updated.currency_code or "",
            },
        )

        updated.vendor_warnings = vendor_warnings  # type: ignore[attr-defined]
        logger.info("PO issued: %s", po.po_number)
        return updated

    # ── Retainage (Gap F) ─────────────────────────────────────────────────────

    # Statuses from which retainage may be released. A draft / approved /
    # cancelled PO has not yet committed money to a vendor, so there is
    # nothing legitimate to release.
    _RETAINAGE_RELEASABLE_STATUSES = ("issued", "partially_received", "completed")

    async def release_po_retainage(
        self,
        po_id: uuid.UUID,
        release_amount: Decimal,
        reason: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> PORetainageRelease:
        """Release withheld retainage on a PO and audit-log the transaction.

        Validation:
            * 404 if the PO does not exist.
            * 409 if the PO is in a status that cannot release retainage
              (draft / approved / cancelled).
            * 400 if the requested amount is non-positive or exceeds the
              currently-held balance.

        On success ``PurchaseOrder.retainage_released_amount`` is incremented,
        a :class:`PORetainageRelease` audit row is written, and the
        ``procurement.po.retainage_released`` event is published. The release
        amount is kept in the PO's own currency (never blended).
        """
        po = await self.po_repo.get(po_id)
        if po is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )

        if po.status not in self._RETAINAGE_RELEASABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot release retainage from a PO in status '{po.status}'. "
                    f"Allowed: {', '.join(self._RETAINAGE_RELEASABLE_STATUSES)}."
                ),
            )

        if release_amount <= Decimal("0"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Release amount must be positive",
            )

        held = po.retainage_held()
        if release_amount > held:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Release amount {release_amount} exceeds held retainage {held}",
            )

        released_sum = _to_decimal(po.retainage_released_amount)
        new_released = released_sum + release_amount
        await self.po_repo.update(po_id, retainage_released_amount=str(new_released))

        now = datetime.now(UTC).isoformat()
        release = PORetainageRelease(
            po_id=po_id,
            release_date=now,
            release_amount=release_amount,
            release_reason=reason,
            released_by_id=user_id,
        )
        release = await self.retainage_repo.create(release)

        # FSM-style audit row - mirrors the PO approve/issue audit hooks so
        # the release leaves the same evidence trail compliance expects.
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=str(user_id) if user_id else None,
                entity_type="purchase_order",
                entity_id=str(po_id),
                action="retainage_released",
                reason=reason or "Retainage released via release_po_retainage()",
                metadata={
                    "po_number": po.po_number,
                    "release_amount": str(release_amount),
                    "currency_code": po.currency_code or "",
                    "retainage_released_total": str(new_released),
                },
            )
        except Exception:
            logger.debug("Audit log skipped for PO %s retainage release", po_id)

        await _safe_publish(
            "procurement.po.retainage_released",
            {
                "po_id": str(po_id),
                "project_id": str(po.project_id),
                "po_number": po.po_number,
                "release_amount": str(release_amount),
                "currency_code": po.currency_code or "",
                "released_by": str(user_id) if user_id else None,
                "release_reason": reason,
                "retainage_released_total": str(new_released),
            },
        )

        logger.info(
            "Retainage released on PO %s: amount=%s %s",
            po.po_number,
            release_amount,
            po.currency_code or "",
        )
        return release

    async def get_po_retainage_releases(
        self,
        po_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[PORetainageRelease], int]:
        """List the retainage-release audit log for a PO (404 if PO missing)."""
        await self.get_po(po_id)  # 404 if the PO does not exist
        return await self.retainage_repo.list_for_po(po_id, offset=offset, limit=limit)

    # ── Goods Receipts ───────────────────────────────────────────────────────

    async def _confirmed_received_by_item(
        self,
        po_item_ids: list[uuid.UUID],
        *,
        exclude_receipt_id: uuid.UUID | None = None,
    ) -> dict[uuid.UUID, Decimal]:
        """Sum quantity_received on confirmed GR lines, grouped by po_item_id.

        Used to enforce a cumulative over-receipt cap: prior confirmed receipts
        count against the PO line's ordered quantity. ``exclude_receipt_id``
        drops one receipt from the sum (used at confirm time so the GR being
        confirmed is not double-counted against itself).
        """
        if not po_item_ids:
            return {}
        from sqlalchemy import func as _func
        from sqlalchemy import select as _select

        stmt = (
            _select(
                GoodsReceiptItem.po_item_id,
                _func.coalesce(_func.sum(numeric_value(GoodsReceiptItem.quantity_received)), 0),
            )
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptItem.receipt_id)
            .where(GoodsReceipt.status == "confirmed")
            .where(GoodsReceiptItem.po_item_id.in_(po_item_ids))
            .group_by(GoodsReceiptItem.po_item_id)
        )
        if exclude_receipt_id is not None:
            stmt = stmt.where(GoodsReceiptItem.receipt_id != exclude_receipt_id)
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: _to_decimal(row[1]) for row in rows}

    async def create_goods_receipt(
        self,
        data: GRCreate,
        user_id: str | None = None,
    ) -> GoodsReceipt:
        """Create a goods receipt against a PO.

        Validates:
        - PO exists and is in a receivable status (issued or partially_received)
        - received_qty <= ordered_qty for each GR item (when po_item_id provided)
        """
        po = await self.get_po(data.po_id)  # 404 check

        # PO must be in a status that accepts goods receipts
        if po.status not in ("issued", "partially_received"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot create goods receipt for PO in status '{po.status}'. "
                    "PO must be issued or partially_received."
                ),
            )

        # Validate GR item quantities against PO items. The cap is cumulative:
        # quantity already received on prior confirmed GRs for the same
        # po_item_id counts against the ordered quantity, so a 100-unit line
        # cannot be over-received across two separate receipts (over-receipt bug).
        po_items_by_id = {item.id: item for item in po.items}
        linked_ids = [it.po_item_id for it in data.items if it.po_item_id is not None]
        already_received = await self._confirmed_received_by_item(linked_ids)
        for item_data in data.items:
            if item_data.po_item_id is not None:
                po_item = po_items_by_id.get(item_data.po_item_id)
                if po_item is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(f"PO item {item_data.po_item_id} not found in purchase order {data.po_id}"),
                    )
                # Validate received quantity does not exceed ordered quantity
                try:
                    ordered = Decimal(po_item.quantity)
                    received = Decimal(item_data.quantity_received)
                except (InvalidOperation, ValueError, TypeError):
                    continue  # let DB-level validation handle bad numbers
                prior = already_received.get(item_data.po_item_id, Decimal("0"))
                if prior + received > ordered + _RECEIPT_TOLERANCE:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Received quantity ({prior + received}) exceeds ordered quantity "
                            f"({ordered}) for PO item '{po_item.description}'"
                        ),
                    )

        gr = GoodsReceipt(
            po_id=data.po_id,
            receipt_date=data.receipt_date,
            received_by_id=data.received_by_id or (uuid.UUID(user_id) if user_id else None),
            delivery_note_number=data.delivery_note_number,
            status=data.status,
            notes=data.notes,
            metadata_=data.metadata,
        )
        gr = await self.gr_repo.create(gr)

        # Create GR items
        for item_data in data.items:
            item = GoodsReceiptItem(
                receipt_id=gr.id,
                po_item_id=item_data.po_item_id,
                quantity_ordered=item_data.quantity_ordered,
                quantity_received=item_data.quantity_received,
                quantity_rejected=item_data.quantity_rejected,
                rejection_reason=item_data.rejection_reason,
            )
            await self.gr_item_repo.create(item)

        gr_id = gr.id
        await _safe_publish(
            "procurement.gr.created",
            {
                "gr_id": str(gr_id),
                "po_id": str(gr.po_id),
                "project_id": str(po.project_id),
                "status": gr.status,
                "item_count": len(data.items),
            },
        )

        logger.info("GR created for PO %s (date=%s)", data.po_id, data.receipt_date)
        # The freshly-flushed ``gr`` has no ``items`` collection loaded -
        # ``selectin`` only fires on a query, not on a pending instance. The
        # router serialises ``GRResponse`` (which includes ``items``), so a
        # lazy load would be attempted outside the async greenlet
        # (MissingGreenlet 500). Re-fetch so the relationship is hydrated.
        self.session.expunge(gr)
        refreshed = await self.gr_repo.get(gr_id)
        return refreshed if refreshed is not None else gr

    async def get_goods_receipt(self, gr_id: uuid.UUID) -> GoodsReceipt:
        """Get goods receipt by ID. Raises 404 if not found."""
        gr = await self.gr_repo.get(gr_id)
        if gr is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Goods receipt not found",
            )
        return gr

    async def list_goods_receipts(
        self,
        *,
        po_id: uuid.UUID | None = None,
        gr_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GoodsReceipt], int]:
        """List goods receipts with optional filters."""
        return await self.gr_repo.list(po_id=po_id, status=gr_status, limit=limit, offset=offset)

    async def list_goods_receipts_by_project(
        self,
        *,
        project_id: uuid.UUID,
        gr_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[GoodsReceipt, str]], int]:
        """List goods receipts across every PO in a project.

        api-HIGH (GR tab): the frontend Goods-Receipts tab filters by the
        active ``project_id`` (not a single PO), so this returns each GR
        paired with its parent ``po_number`` for display.
        """
        return await self.gr_repo.list_by_project(
            project_id=project_id,
            status=gr_status,
            limit=limit,
            offset=offset,
        )

    async def confirm_goods_receipt(self, gr_id: uuid.UUID) -> GoodsReceipt:
        """Confirm a goods receipt and update the PO status accordingly.

        After confirmation, checks whether ALL PO items are fully received:
        - If fully received -> PO status = 'completed'
        - If partially received -> PO status = 'partially_received'
        """
        gr = await self.get_goods_receipt(gr_id)
        if gr.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot confirm goods receipt in status '{gr.status}'",
            )

        # Re-apply the cumulative over-receipt cap at confirm time: prior
        # confirmed receipts on the same po_item_id plus this receipt's lines
        # must not exceed the ordered quantity. ``exclude_receipt_id`` keeps
        # this GR out of the prior sum so it is not counted against itself.
        po = await self.get_po(gr.po_id)
        po_items_by_id = {item.id: item for item in po.items}
        linked_ids = [it.po_item_id for it in gr.items if it.po_item_id is not None]
        already_received = await self._confirmed_received_by_item(
            linked_ids,
            exclude_receipt_id=gr_id,
        )
        this_receipt: dict[uuid.UUID, Decimal] = {}
        for gr_item in gr.items:
            if gr_item.po_item_id is None:
                continue
            this_receipt[gr_item.po_item_id] = this_receipt.get(gr_item.po_item_id, Decimal("0")) + _to_decimal(
                gr_item.quantity_received
            )
        for po_item_id, new_received in this_receipt.items():
            po_item = po_items_by_id.get(po_item_id)
            if po_item is None:
                continue
            ordered = _to_decimal(po_item.quantity)
            prior = already_received.get(po_item_id, Decimal("0"))
            if prior + new_received > ordered + _RECEIPT_TOLERANCE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Received quantity ({prior + new_received}) exceeds ordered quantity "
                        f"({ordered}) for PO item '{po_item.description}'"
                    ),
                )

        await self.gr_repo.update(gr_id, status="confirmed")

        # gr_repo.update() calls session.expire_all(), which detaches the
        # eager-loaded relationships on the ``po`` fetched above for the cap
        # check; a later synchronous attribute/relationship access would then
        # lazy-load from sync context and raise MissingGreenlet on the async
        # session. Re-fetch a fresh, fully eager-loaded PO for the status
        # rollup and the receipt-value computation below (this also sees the
        # GR just flipped to confirmed).
        po = await self.get_po(gr.po_id)

        # Update PO status based on total received quantities
        if po.status in ("issued", "partially_received"):
            all_fully_received = self._check_po_fully_received(po)
            if all_fully_received:
                await self.po_repo.update(po.id, status="completed")
                logger.info("PO %s fully received, status -> completed", po.po_number)
            elif po.status == "issued":
                await self.po_repo.update(po.id, status="partially_received")
                logger.info("PO %s partially received", po.po_number)

        updated = await self.gr_repo.get(gr_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Goods receipt not found",
            )

        # Compute the value of this receipt as Σ(quantity_received × po_item.unit_rate).
        # Finance subscribers need this to flip the matching slice of
        # ProjectBudget.committed → actual on each GR.
        po_items_by_id: dict[uuid.UUID, PurchaseOrderItem] = {it.id: it for it in po.items}
        gr_amount = Decimal("0")
        for gr_item in updated.items:
            if gr_item.po_item_id is None:
                continue
            po_item = po_items_by_id.get(gr_item.po_item_id)
            if po_item is None:
                continue
            try:
                qty = Decimal(str(gr_item.quantity_received or "0"))
                rate = Decimal(str(po_item.unit_rate or "0"))
            except (InvalidOperation, ValueError, TypeError):
                continue
            gr_amount += qty * rate

        await _safe_publish(
            "procurement.gr.confirmed",
            {
                "gr_id": str(gr_id),
                "po_id": str(updated.po_id),
                "project_id": str(po.project_id),
                "amount": str(gr_amount),
                "currency_code": po.currency_code or "",
            },
        )

        logger.info("GR confirmed: %s", gr_id)
        return updated

    # ── Stats ───────────────────────────────────────────────────────────────

    async def get_stats(self, project_id: uuid.UUID) -> ProcurementStatsResponse:
        """Return aggregate procurement statistics for a project."""
        raw = await self.po_repo.stats_for_project(project_id)
        return ProcurementStatsResponse(
            total_pos=raw["total_pos"],
            by_status=raw["by_status"],
            total_committed=raw["total_committed"],
            total_received=raw["total_received"],
            pending_delivery_count=raw["pending_delivery_count"],
        )

    # ── 3-way match status (Wave 2 / T4) ────────────────────────────────

    async def get_match_status(self, po_id: uuid.UUID) -> dict:
        """Return per-line 3-way match status for a PO.

        Aggregates confirmed goods-receipt quantities and any payable
        invoice line totals tagged with ``metadata_.po_id == po_id`` (the
        link the existing ``create-invoice`` endpoint stamps onto each
        invoice).

        Avoids N+1 by issuing exactly:

        * one PO+items eager-load (via ``po_repo.get``),
        * one GR-items aggregate (SUM grouped by ``po_item_id``),
        * one invoice line-items pull (filtered by metadata-derived ids).

        ``po_item_id`` is the join key for GRs. Invoices do NOT carry a
        direct ``po_item_id`` FK, so we match by ``sort_order`` to the PO
        line: ``create-invoice`` copies items in order and stamps the same
        ``sort_order`` for each line, which is unique within an invoice.
        """
        from sqlalchemy import func as _func
        from sqlalchemy import select as _select

        po = await self.get_po(po_id)  # 404 if missing

        # ── Received quantities (confirmed GRs only) - one query ─────────
        gr_stmt = (
            _select(
                GoodsReceiptItem.po_item_id,
                # quantity_received is String(50) - sum it numerically (PG-safe
                # via numeric_value) and coalesce the empty-group SUM to 0.
                _func.coalesce(_func.sum(numeric_value(GoodsReceiptItem.quantity_received)), 0),
            )
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptItem.receipt_id)
            .where(GoodsReceipt.po_id == po_id)
            .where(GoodsReceipt.status == "confirmed")
            .where(GoodsReceiptItem.po_item_id.is_not(None))
            .group_by(GoodsReceiptItem.po_item_id)
        )
        gr_rows = (await self.session.execute(gr_stmt)).all()
        # numeric_value already returns a float; convert to Decimal defensively.
        received_by_item: dict[uuid.UUID, Decimal] = {row[0]: _to_decimal(row[1]) for row in gr_rows}

        # ── Invoiced quantities - best-effort, optional finance module ──
        invoiced_by_sort: dict[int, Decimal] = {}
        try:
            from app.modules.finance.models import Invoice, InvoiceLineItem

            # Find invoices whose JSON metadata.po_id == this PO id. Plain
            # equality on the JSON-rendered string is SQLite-portable.
            inv_stmt = _select(Invoice.id).where(
                Invoice.project_id == po.project_id,
                Invoice.invoice_direction == "payable",
            )
            inv_ids = [row[0] for row in (await self.session.execute(inv_stmt)).all()]
            if inv_ids:
                line_stmt = _select(
                    InvoiceLineItem.invoice_id,
                    InvoiceLineItem.sort_order,
                    InvoiceLineItem.quantity,
                ).where(InvoiceLineItem.invoice_id.in_(inv_ids))
                line_rows = (await self.session.execute(line_stmt)).all()

                # Filter invoices that explicitly link to this PO via metadata.
                # We re-fetch the metadata_ column in bulk to avoid loading
                # full Invoice objects.
                meta_stmt = _select(Invoice.id, Invoice.metadata_).where(
                    Invoice.id.in_(inv_ids),
                )
                meta_rows = (await self.session.execute(meta_stmt)).all()
                linked_invoice_ids: set[uuid.UUID] = set()
                for inv_id, meta in meta_rows:
                    if isinstance(meta, dict) and str(meta.get("po_id")) == str(po_id):
                        linked_invoice_ids.add(inv_id)

                for inv_id, sort_order, qty in line_rows:
                    if inv_id not in linked_invoice_ids:
                        continue
                    invoiced_by_sort[sort_order] = invoiced_by_sort.get(sort_order, Decimal("0")) + _to_decimal(qty)
        except Exception:  # noqa: BLE001 - finance is optional
            logger.debug("Finance lookup skipped for PO %s match-status", po_id)

        # ── Compose per-line statuses ───────────────────────────────────
        lines: list[dict] = []
        overall_kinds: set[str] = set()
        for po_item in sorted(po.items or [], key=lambda it: it.sort_order):
            ordered = _to_decimal(po_item.quantity)
            received = received_by_item.get(po_item.id, Decimal("0"))
            invoiced = invoiced_by_sort.get(po_item.sort_order, Decimal("0"))

            status_tag = self._classify_line_match(ordered, received, invoiced)
            overall_kinds.add(status_tag)
            lines.append(
                {
                    "line_id": po_item.id,
                    "description": po_item.description,
                    "ordered_qty": _fmt_qty(ordered),
                    "received_qty": _fmt_qty(received),
                    "invoiced_qty": _fmt_qty(invoiced),
                    "match_status": status_tag,
                }
            )

        # Overall: worst case wins (over_invoiced > over_received >
        # unmatched > partial > ok).
        precedence = ("over_invoiced", "over_received", "unmatched", "partial", "ok")
        overall = next((p for p in precedence if p in overall_kinds), "ok")
        if not lines:
            overall = "unmatched"

        return {
            "po_id": po_id,
            "po_number": po.po_number,
            "overall_status": overall,
            "lines": lines,
        }

    @staticmethod
    def _classify_line_match(
        ordered: Decimal,
        received: Decimal,
        invoiced: Decimal,
    ) -> str:
        """Collapse three quantities into a single PO-line match tag."""
        zero = Decimal("0")
        if invoiced > received and invoiced > zero:
            return "over_invoiced"
        if received > ordered and ordered > zero:
            return "over_received"
        if received <= zero and invoiced <= zero:
            return "unmatched"
        if received >= ordered and invoiced >= ordered and ordered > zero:
            return "ok"
        return "partial"

    # ── Supplier scorecard (Wave 2 / T4) ─────────────────────────────────

    async def get_supplier_scorecard(
        self,
        supplier_contact_id: str,
        project_id: uuid.UUID | None = None,
        period_days: int = 365,
    ) -> dict:
        """Return supplier KPIs for the trailing window.

        Returns a dict shaped like :class:`SupplierScorecardResponse`. All
        rates are 0.0–1.0; a supplier with zero POs gets all-zero fields
        instead of raising (no division-by-zero crash).

        ``project_id`` scopes the query to a single project (used by the
        UI when the user opens a scorecard from a project's PO list).
        """
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import and_ as _and
        from sqlalchemy import func as _func
        from sqlalchemy import select as _select

        cutoff = (datetime.now(UTC) - timedelta(days=period_days)).isoformat()

        # ── PO aggregates ────────────────────────────────────────────────
        po_filters = [PurchaseOrder.vendor_contact_id == supplier_contact_id]
        if project_id is not None:
            po_filters.append(PurchaseOrder.project_id == project_id)
        # Trailing window: filter by created_at (PO ``issue_date`` is a
        # free-form string and may be NULL).
        po_filters.append(PurchaseOrder.created_at >= datetime.fromisoformat(cutoff))

        po_count_stmt = _select(_func.count()).select_from(PurchaseOrder).where(_and(*po_filters))
        total_po_count = (await self.session.execute(po_count_stmt)).scalar_one() or 0

        # SUM amount_total as Python Decimal (string column).
        po_value_stmt = _select(PurchaseOrder.amount_total, PurchaseOrder.currency_code).where(_and(*po_filters))
        po_value_rows = (await self.session.execute(po_value_stmt)).all()
        total_po_value = Decimal("0")
        currency = ""
        for amt, cur in po_value_rows:
            total_po_value += _to_decimal(amt)
            if not currency and cur:
                currency = cur

        # PO ids in scope - drives the GR + line-variance queries.
        po_ids_stmt = _select(PurchaseOrder.id).where(_and(*po_filters))
        po_ids = [row[0] for row in (await self.session.execute(po_ids_stmt)).all()]

        # ── GR aggregates (on-time + rejection) ─────────────────────────
        # ``on_time_count`` covers GRs whose parent PO had a delivery_date AND
        # the receipt was on/before it. GRs against POs with NO delivery_date
        # (unscheduled) cannot be evaluated, so they are tracked in a separate
        # ``unscheduled_count`` and excluded from the on-time denominator -
        # otherwise scoring inflates with every unscheduled PO (P0-2).
        total_gr_count = 0
        on_time_count = 0
        unscheduled_count = 0
        rejected_count = 0
        if po_ids:
            gr_stmt = _select(
                GoodsReceipt.id,
                GoodsReceipt.po_id,
                GoodsReceipt.receipt_date,
                GoodsReceipt.status,
            ).where(GoodsReceipt.po_id.in_(po_ids))
            gr_rows = (await self.session.execute(gr_stmt)).all()

            # Build PO delivery-date lookup once (string ISO dates compare
            # lexicographically when both are YYYY-MM-DD).
            po_deliveries_stmt = _select(PurchaseOrder.id, PurchaseOrder.delivery_date).where(
                PurchaseOrder.id.in_(po_ids)
            )
            po_delivery_map = {row[0]: row[1] for row in (await self.session.execute(po_deliveries_stmt)).all()}

            for _gr_id, gr_po_id, receipt_date, gr_status in gr_rows:
                total_gr_count += 1
                if gr_status == "rejected":
                    rejected_count += 1
                expected = po_delivery_map.get(gr_po_id)
                if not expected:
                    # PO has no delivery_date → cannot evaluate on-time.
                    unscheduled_count += 1
                    continue
                if receipt_date and receipt_date <= expected:
                    on_time_count += 1

        # ── Quantity-variance across PO line items ───────────────────────
        qty_variance_pct = 0.0
        if po_ids:
            line_stmt = _select(
                PurchaseOrderItem.id,
                PurchaseOrderItem.quantity,
            ).where(PurchaseOrderItem.po_id.in_(po_ids))
            line_rows = (await self.session.execute(line_stmt)).all()

            # SUM(received) per po_item_id across confirmed GRs.
            recv_stmt = (
                _select(
                    GoodsReceiptItem.po_item_id,
                    # quantity_received is String(50) - sum it numerically
                    # (PG-safe via numeric_value); coalesce empty group to 0.
                    _func.coalesce(_func.sum(numeric_value(GoodsReceiptItem.quantity_received)), 0),
                )
                .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptItem.receipt_id)
                .where(GoodsReceipt.po_id.in_(po_ids))
                .where(GoodsReceipt.status == "confirmed")
                .where(GoodsReceiptItem.po_item_id.is_not(None))
                .group_by(GoodsReceiptItem.po_item_id)
            )
            recv_map = {row[0]: _to_decimal(row[1]) for row in (await self.session.execute(recv_stmt)).all()}

            line_variances: list[Decimal] = []
            for line_id, ordered_raw in line_rows:
                ordered = _to_decimal(ordered_raw)
                if ordered <= Decimal("0"):
                    continue
                received = recv_map.get(line_id, Decimal("0"))
                line_variances.append(abs((received - ordered) / ordered))
            if line_variances:
                qty_variance_pct = float(sum(line_variances) / Decimal(len(line_variances)))

        # On-time denominator excludes unscheduled GRs (P0-2). Rejection
        # rate keeps the full GR count as the denominator - a rejected
        # delivery is still a delivery, scheduled or not.
        scheduled_gr_count = total_gr_count - unscheduled_count
        on_time_pct = (on_time_count / scheduled_gr_count) if scheduled_gr_count else 0.0
        rejection_rate = (rejected_count / total_gr_count) if total_gr_count else 0.0

        return {
            "supplier_contact_id": supplier_contact_id,
            "supplier_name": None,
            "project_id": project_id,
            "period_days": period_days,
            "total_po_count": total_po_count,
            "total_po_value": str(total_po_value),
            "currency": currency,
            "on_time_delivery_pct": on_time_pct,
            "qty_variance_pct": qty_variance_pct,
            "gr_rejection_rate": rejection_rate,
            "total_gr_count": total_gr_count,
            "on_time_count": on_time_count,
            "unscheduled_count": unscheduled_count,
        }

    @staticmethod
    def _check_po_fully_received(po: PurchaseOrder) -> bool:
        """Check if all PO items have been fully received across confirmed GRs."""
        if not po.items:
            return True

        # Sum confirmed received quantities per PO item
        received_by_item: dict[uuid.UUID, Decimal] = {}
        for gr in po.goods_receipts:
            if gr.status != "confirmed":
                continue
            for gr_item in gr.items:
                if gr_item.po_item_id is not None:
                    try:
                        qty = Decimal(gr_item.quantity_received)
                    except (InvalidOperation, ValueError, TypeError):
                        qty = Decimal("0")
                    received_by_item[gr_item.po_item_id] = received_by_item.get(gr_item.po_item_id, Decimal("0")) + qty

        # Check each PO item
        for po_item in po.items:
            try:
                ordered = Decimal(po_item.quantity)
            except (InvalidOperation, ValueError, TypeError):
                ordered = Decimal("0")
            received = received_by_item.get(po_item.id, Decimal("0"))
            if received < ordered:
                return False

        return True


# ── MaterialRequisitionService ────────────────────────────────────────────────


class MaterialRequisitionService:
    """Service for material requisition CRUD and FSM lifecycle.

    Keeps business logic separate from the ProcurementService so the
    requisition flow can be tested independently.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _next_req_number(self, project_id: uuid.UUID) -> str:
        """Generate the next "MR-<digits>" number for a project.

        Uses the NUMERIC MAX of the existing requisition suffixes (not a
        COUNT+1) so generation stays correct under concurrency and past
        MR-9999. Only canonical ``MR-<digits>`` rows are cast.
        """
        from sqlalchemy import Integer as _SAInteger
        from sqlalchemy import cast as _cast
        from sqlalchemy import func as _func
        from sqlalchemy import select as _select

        stmt = _select(
            _func.coalesce(
                _func.max(_cast(_func.substr(MaterialRequisition.req_number, 4), _SAInteger)),
                0,
            )
        ).where(
            MaterialRequisition.project_id == project_id,
            MaterialRequisition.req_number.regexp_match("^MR-[0-9]+$"),
        )
        max_suffix = (await self.session.execute(stmt)).scalar_one()
        return f"MR-{max_suffix + 1:04d}"

    async def _create_req_with_retry(
        self,
        *,
        project_id: uuid.UUID,
        requester_id: str | None,
        title: str | None,
        required_date: str | None,
        lead_time_days: int,
        estimated_delivery_date: str | None,
        notes: str | None,
    ) -> MaterialRequisition:
        """Insert a MaterialRequisition row, retrying on req_number collisions.

        Mirrors ``_create_po_with_retry``: re-read MAX(req_number) and retry up
        to ``_MAX_RETRIES`` times on a unique-constraint IntegrityError; 503
        when retries are exhausted.
        """
        _MAX_RETRIES = 5
        last_exc: IntegrityError | None = None
        for _attempt in range(_MAX_RETRIES):
            req_number = await self._next_req_number(project_id)
            req = MaterialRequisition(
                project_id=project_id,
                req_number=req_number,
                requester_id=requester_id,
                status="draft",
                title=title,
                required_date=required_date,
                lead_time_days=lead_time_days,
                estimated_delivery_date=estimated_delivery_date,
                notes=notes,
            )
            self.session.add(req)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                last_exc = exc
                await self.session.rollback()
                continue  # collision - try again with a fresh MAX read
            return req

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not generate a unique requisition number after "
                f"{_MAX_RETRIES} attempts (concurrent contention). Please retry."
            ),
        ) from last_exc

    async def create_requisition(
        self,
        project_id: uuid.UUID,
        *,
        title: str | None = None,
        required_date: str | None = None,
        lead_time_days: int = 0,
        requester_id: str | None = None,
        notes: str | None = None,
        items: list[dict] | None = None,
    ) -> MaterialRequisition:
        """Create a new material requisition in 'draft' state.

        Args:
            project_id: the project this requisition belongs to.
            items: optional list of dicts with keys description, quantity_requested,
                   unit_cost - extended_cost is computed as qty * unit_cost.
        """
        est_delivery = _compute_delivery_date(required_date, lead_time_days)
        # Insert the requisition with a per-project sequential req_number, retrying
        # on the unique-constraint collision a concurrent insert can cause. The
        # number is derived from the NUMERIC MAX of existing "MR-<digits>" rows
        # (not a non-atomic COUNT+1) so it stays correct past MR-9999.
        req = await self._create_req_with_retry(
            project_id=project_id,
            requester_id=requester_id,
            title=title,
            required_date=required_date,
            lead_time_days=lead_time_days,
            estimated_delivery_date=est_delivery,
            notes=notes,
        )

        # Optionally create line items
        if items:
            for item_data in items:
                qty = _safe_decimal_str(item_data.get("quantity_requested", "0"))
                ucost = _safe_decimal_str(item_data.get("unit_cost", "0"))
                extended = str(Decimal(qty) * Decimal(ucost) if (qty and ucost) else Decimal("0"))
                mr_item = MaterialRequisitionItem(
                    requisition_id=req.id,
                    description=item_data.get("description", ""),
                    quantity_requested=qty,
                    unit_cost=Decimal(ucost) if ucost else Decimal("0"),
                    extended_cost=Decimal(extended),
                    currency_code=item_data.get("currency_code", ""),
                )
                self.session.add(mr_item)
            await self.session.flush()

        return req

    async def get_requisition(self, requisition_id: uuid.UUID) -> MaterialRequisition:
        """Get requisition by ID - 404 if not found."""
        req = await self.session.get(MaterialRequisition, requisition_id)
        if req is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MaterialRequisition {requisition_id} not found.",
            )
        return req

    async def transition_requisition(
        self,
        requisition_id: uuid.UUID,
        target_status: str,
        *,
        approver_id: str | None = None,
        po_id: uuid.UUID | None = None,
    ) -> MaterialRequisition:
        """FSM transition with optional side effects.

        Side effects:
        * approved → stamps approver_id
        * ordered  → stamps po_id if provided
        """
        req = await self.get_requisition(requisition_id)
        _mr_assert_transition(req.status, target_status)

        req.status = target_status
        if target_status == "approved" and approver_id is not None:
            req.approver_id = approver_id
        if target_status == "ordered" and po_id is not None:
            req.po_id = po_id

        await self.session.flush()
        return req

    async def reconcile(self, requisition_id: uuid.UUID) -> dict:
        """Return quantity reconciliation for a requisition."""
        req = await self.get_requisition(requisition_id)
        result = _mr_reconcile(req.items)
        return {k: str(v) for k, v in result.items()}
