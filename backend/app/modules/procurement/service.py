# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement service - business logic for purchase orders and goods receipts.

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
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.sql_numeric import numeric_value
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.procurement.cost_spine import resolve_cost_line_ids
from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    MaterialRequisition,
    MaterialRequisitionItem,
    PORetainageRelease,
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.modules.procurement.otif import (
    DeliveryPerformance,
    ReceiptRecord,
    compute_project_delivery_performance,
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
    POItemCreate,
    POUpdate,
    ProcurementStatsResponse,
    ProjectDeliveryPerformanceResponse,
    SupplierDeliveryPerformance,
)

#: Rule set run against a purchase order. Registered in
#: ``app.core.validation.rules.register_builtin_rules`` and passed explicitly by
#: :meth:`ProcurementService._validate_po` -- a rule set nobody passes never runs.
PROCUREMENT_RULE_SET = "procurement"


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
    """Best-effort event publish - never blocks the caller on failure."""
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

#: Statuses from which cancelling still has to release a budget commitment.
#: Budget is committed at ``approved`` and is NOT released by moving on to
#: ``issued`` or ``partially_received`` - the money stays committed while the
#: order is live. So a PO voided out of any of these still carries a
#: ``committed_from_po`` marker in finance, and the compensating event has to
#: fire for all three, not only for ``approved``.
_PO_COMMITTED_STATUSES = frozenset({"approved", "issued", "partially_received"})

#: The only status in which a purchase order's amounts, currency, vendor and
#: line items may still change in place. Approval is given to a sum, a vendor
#: and a list of lines, and finance takes the commitment at that moment and
#: later releases exactly what it took. Changing the figures afterwards would
#: walk around the approval, and it would leave the finance commitment and the
#: committed cost report (which reads the live lines) telling two different
#: stories about the same order.
_PO_EDITABLE_STATUSES = frozenset({"draft"})

#: What a purchase order that has left draft is told to do instead of editing
#: its figures in place, by the status it is in. Every remedy is a path the
#: status machine really offers from there.
_PO_FROZEN_REMEDIES = {
    "approved": "Return it to draft to correct it (in the same request if you like) and approve it again.",
    "issued": (
        "Cancel it and reopen it as a draft to correct it, or raise a separate purchase order "
        "for the difference if deliveries or invoices already refer to it."
    ),
    "partially_received": "Raise a separate purchase order for the difference.",
    "completed": "Raise a separate purchase order for the difference.",
    "cancelled": "Reopen it as a draft to correct it, in the same request if you like.",
}

#: Holder kinds a removal refusal can name, in the order a reader wants them:
#: what was delivered, what was billed, what was paid out, what asked for it.
#: The values are the repository method that counts each kind.
_PO_HOLDER_COUNTERS = (
    ("goods_receipt", "count_goods_receipts"),
    ("payable_invoice", "count_payable_invoices"),
    ("retainage_release", "count_retainage_releases"),
    ("requisition", "count_requisitions"),
)

#: Human-readable singular names for the holder kinds, used to build the
#: English fallback sentence carried in the 409 body. The UI renders its own
#: translated text from the structured ``holders`` list; this sentence is for
#: everything that is not this UI - an API client, a log line, a curl.
_PO_HOLDER_LABELS = {
    "goods_receipt": "goods receipt",
    "payable_invoice": "payable invoice",
    "retainage_release": "retainage release",
    "requisition": "material requisition",
}


def _describe_holders(holders: dict[str, int]) -> str:
    """Render ``{kind: count}`` as an English list, e.g. "2 goods receipts, 1 payable invoice"."""
    parts: list[str] = []
    for kind, count in holders.items():
        label = _PO_HOLDER_LABELS.get(kind, kind.replace("_", " "))
        parts.append(f"{count} {label}" if count == 1 else f"{count} {label}s")
    return ", ".join(parts)


def _agreeing_verb(holders: dict[str, int], singular: str, plural: str) -> str:
    """Pick the verb form that agrees with ``_describe_holders(holders)``.

    The rendered phrase is one grammatical subject even when it names several
    kinds ("2 goods receipts, 1 payable invoice"), and a coordinated subject
    takes the plural regardless of how each part is counted. Only a single
    holder of a single kind is singular.
    """
    return singular if sum(holders.values()) == 1 else plural


def _holders_conflict(code: str, message: str, remediation: str, holders: dict[str, int]) -> HTTPException:
    """Build the 409 a removal refusal returns.

    The body is structured on purpose. ``holders`` lets a caller say "2 goods
    receipts and 1 payable invoice" in its own language, and ``message`` is
    the English fallback for every caller that will not. Both are always
    present, so no reader has to parse prose to find out what is in the way.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": code,
            "message": message,
            "remediation": remediation,
            "holders": [{"kind": kind, "count": count} for kind, count in holders.items()],
        },
    )


def _parse_decimal(value: str, field_name: str = "value") -> Decimal:
    """Parse a string to Decimal, raising a clear error on failure."""
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


def _cents(value: object) -> Decimal:
    """A money figure rounded to the cent, so ``"1800"`` and ``"1800.00"`` compare equal."""
    return _to_decimal(value).quantize(Decimal("0.01"))


def _plain(value: object) -> str:
    """A quantity or rate as one canonical string, whatever trailing zeros it arrived with."""
    return format(_to_decimal(value).normalize(), "f")


def _po_line_signature(
    description: object,
    unit: object,
    quantity: object,
    unit_rate: object,
    amount: object,
    cost_line_id: object,
    wbs_id: object,
    cost_category: object,
) -> tuple[str, ...]:
    """Everything a purchase order line commits to, in a form that compares by value.

    An amount of zero means "derive it", the same rule the write path applies,
    so a line sent back without its amount matches the stored line it came from.
    """
    effective = _to_decimal(amount)
    if effective == 0:
        effective = _to_decimal(quantity) * _to_decimal(unit_rate)
    return (
        str(description or "").strip(),
        str(unit or "").strip(),
        _plain(quantity),
        _plain(unit_rate),
        str(_cents(effective)),
        str(cost_line_id or ""),
        str(wbs_id or ""),
        str(cost_category or ""),
    )


def _frozen_po_changes(
    po: PurchaseOrder,
    fields: dict[str, Any],
    new_items: list[POItemCreate] | None,
    new_item_cost_line_ids: list[uuid.UUID | None],
) -> list[str]:
    """Name what a PATCH would really change among the figures approval fixed.

    Only real changes count. A client that sends back the stored amounts, the
    same currency in another case or the same lines in another order is not
    changing anything, and is not refused for it.
    """
    changed: list[str] = []
    if any(
        name in fields and _cents(fields[name]) != _cents(getattr(po, name, None))
        for name in ("amount_subtotal", "tax_amount", "amount_total")
    ):
        changed.append("amounts")
    if (
        "currency_code" in fields
        and (fields["currency_code"] or "").strip().upper() != (po.currency_code or "").strip().upper()
    ):
        changed.append("currency")
    if (
        "vendor_contact_id" in fields
        and str(fields["vendor_contact_id"] or "").strip().lower() != str(po.vendor_contact_id or "").strip().lower()
    ):
        changed.append("vendor")
    if new_items is not None:
        stored = sorted(
            _po_line_signature(
                it.description,
                it.unit,
                it.quantity,
                it.unit_rate,
                it.amount,
                it.cost_line_id,
                it.wbs_id,
                it.cost_category,
            )
            for it in (po.items or [])
        )
        incoming = sorted(
            _po_line_signature(
                it.description,
                it.unit,
                it.quantity,
                it.unit_rate,
                it.amount,
                cost_line_id,
                it.wbs_id,
                it.cost_category,
            )
            for it, cost_line_id in zip(new_items, new_item_cost_line_ids, strict=True)
        )
        if stored != incoming:
            changed.append("line items")
    return changed


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


def _parse_iso_date(value: str | None) -> date | None:
    """Parse a YYYY-MM-DD string to a date, or None when absent/malformed.

    PO delivery_date and GR receipt_date are stored as free-form strings; this
    turns them into real ``date`` objects so the OTIF helper compares dates and
    subtracts durations directly (rather than lexicographically).
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _rate_str(value: Decimal | None) -> str | None:
    """Render a guarded rate/duration Decimal as a canonical string, or None."""
    return None if value is None else str(value)


def _perf_to_schema(perf: DeliveryPerformance) -> SupplierDeliveryPerformance:
    """Map a pure-helper DeliveryPerformance onto its response schema.

    Rates come across as Decimal-or-None from the helper and are serialised as
    strings so they never leak onto the wire as JSON floats.
    """
    return SupplierDeliveryPerformance(
        supplier_contact_id=perf.supplier_id,
        supplier_name=perf.supplier_name,
        total_receipts=perf.total_receipts,
        scheduled_receipts=perf.scheduled_receipts,
        unscheduled_receipts=perf.unscheduled_receipts,
        on_time_count=perf.on_time_count,
        late_count=perf.late_count,
        in_full_count=perf.in_full_count,
        otif_count=perf.otif_count,
        on_time_rate=_rate_str(perf.on_time_rate),
        in_full_rate=_rate_str(perf.in_full_rate),
        otif_rate=_rate_str(perf.otif_rate),
        avg_days_late=_rate_str(perf.avg_days_late),
    )


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
        * an expired / revoked / missing required compliance document. Same
          treatment as prequal: a warning, not a block. A purchase order that
          succeeded yesterday and 409s today because a certificate lapsed
          overnight is an interface change, and the subcontract-award and
          payment gates - which are what "award" means - already hard-block on
          it. Promoting this to a block is a policy decision, not a bug fix.

        Expiry is judged as at ``date.today()``, server-local, which is the
        same convention ``next_payment_blocked`` already applies by default.
        One clock convention across the three gates matters more than which
        one: two gates disagreeing about whether a document had lapsed on a
        given day would be worse than either answer being off by an offset.
        Only calendar dates are compared, never a date against a timestamp.

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

            from app.modules.subcontractors.models import Certificate, Subcontractor
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
            if sub is None:
                return False, []
            certs = list(
                (
                    await self.session.execute(
                        select(Certificate).where(Certificate.subcontractor_id == sub.id),
                    )
                )
                .scalars()
                .all(),
            )
        except Exception:  # noqa: BLE001 - resolution is non-critical
            return False, []
        verdict = subcontractor_award_block(sub, certificates=certs, as_at=date.today())
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

        # Resolve every line's cost-spine link before the PO row exists, so a
        # bad or foreign position id is a 404 over a request that wrote
        # nothing, rather than a 404 with a numbered PO already behind it. The
        # answer is frozen here and copied onto the items below: an order
        # commits against the scope as it stood on the day it was raised, and
        # re-pointing the position tomorrow must not rewrite that.
        item_cost_line_ids = await resolve_cost_line_ids(
            self.session,
            data.project_id,
            [(item.cost_line_id, item.boq_position_id) for item in data.items],
        )

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
                cost_line_id=item_cost_line_ids[idx],
                sort_order=item_data.sort_order if item_data.sort_order else idx,
            )
            await self.po_item_repo.create(item)

        # Reload the PO so the freshly inserted line items are populated on the
        # ``items`` relationship. ``po_repo.create`` refreshed the PO BEFORE the
        # items existed, caching an empty ``items`` collection on the
        # identity-mapped instance; ``po_repo.get`` re-reads it with
        # ``populate_existing`` so ``selectinload`` overwrites that stale empty
        # collection (a plain selectinload would keep the cached one), giving
        # the create response its line items (BUG-015).
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
        for _ in range(_MAX_RETRIES):
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
        subtotal or tax are changed. A PATCH that moves the PO into
        ``approved`` runs the same blocking ``procurement`` rule set as
        :meth:`approve_po`, so approval cannot be reached ungated.

        Outside draft the amounts, currency, vendor and line items are frozen
        (409 naming the way to correct them), unless the same PATCH returns the
        order to draft. ``issued`` is reached only through :meth:`issue_po`.
        """
        po = await self.get_po(po_id)  # 404 check
        prior_status = po.status

        fields = data.model_dump(exclude_unset=True, exclude={"items"})
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(po, "metadata_", None), _incoming) if isinstance(_incoming, dict) else _incoming
            )

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
            # Cancelling is a removal verb, so it runs the same holder guard
            # as ``cancel_po``. There are two doors into ``cancelled`` - this
            # PATCH and the dedicated verb - and a guard on only one of them
            # is a guard anybody can walk around. Same failure the module
            # already fixed for the two doors into ``approved``, and the same
            # remedy: one check, called from both.
            if new_status == "cancelled" and po.status != "cancelled":
                await self._refuse_if_po_is_held(po, action="cancel")
            # ``issued`` has its own verb, and the verb is what re-checks the
            # vendor's hard block at the moment the order goes out, writes the
            # audit row and tells the listeners. A PATCH straight into
            # ``issued`` did none of the three, so it is refused and pointed
            # at the verb rather than taught to repeat it.
            if new_status == "issued" and po.status != "issued":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A purchase order is issued through its issue action, which re-checks the vendor "
                        "and records the issue. Use that action instead of changing the status directly."
                    ),
                )

        # Guard the destructive replace: ``delete_by_po`` hard-deletes the
        # existing PO line rows, and ``GoodsReceiptItem.po_item_id`` is an
        # ``ON DELETE SET NULL`` FK back to them. So replacing items on a PO
        # that already has goods receipts silently NULLs the po_item_id link
        # on every received line, orphaning the received-quantity linkage and
        # corrupting the over-receipt cap, the 3-way match, and the
        # fully-received rollup (received quantities can no longer be tied to
        # any PO line). Once deliveries exist the line items are no longer
        # safe to mutate - refuse the replace with a 409. It is checked before
        # anything is written and before the frozen-figures check below,
        # because it is the more specific of the two explanations.
        if data.items is not None and po.goods_receipts:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot replace line items on a purchase order that already has goods receipts; "
                    "the received quantities are linked to the existing line items."
                ),
            )

        # Resolve the spine links before the existing rows are destroyed, for
        # the same reason create_po resolves before the PO exists: a foreign
        # position id must refuse the PATCH rather than take the old line items
        # down with it. The frozen-figures check below compares the resolved
        # links too, so it happens before that check as well.
        #
        # This replace is why the resolution cannot live only in create_po.
        # The rows are rebuilt from scratch, so a rebuild that did not resolve
        # would strip the cost line off every line of the order the first time
        # somebody corrected a quantity, and that order would drop out of the
        # committed report for good. The link has to be re-derived on every
        # write that recreates the row, not only on the first one.
        item_cost_line_ids: list[uuid.UUID | None] = []
        if data.items is not None:
            item_cost_line_ids = await resolve_cost_line_ids(
                self.session,
                po.project_id,
                [(item.cost_line_id, item.boq_position_id) for item in data.items],
            )

        # Once an order leaves draft its amounts, currency, vendor and lines
        # are the ones it was approved with, and finance holds a commitment for
        # exactly that sum. A PATCH may still correct them on the way back to
        # draft (the re-approval then gates and commits the corrected order),
        # but not while the order stays approved, issued, received or
        # cancelled. Notes, dates and payment terms stay editable throughout.
        resulting_status = fields.get("status") or po.status
        if po.status not in _PO_EDITABLE_STATUSES and resulting_status not in _PO_EDITABLE_STATUSES:
            changed = _frozen_po_changes(po, fields, data.items, item_cost_line_ids)
            if changed:
                what = changed[0] if len(changed) == 1 else f"{', '.join(changed[:-1])} and {changed[-1]}"
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Purchase order {po.po_number} is {po.status.replace('_', ' ')}, so its {what} can no "
                        f"longer change in place. {_PO_FROZEN_REMEDIES.get(po.status, '')}"
                    ).strip(),
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

        # Replace items if provided. The goods-receipt refusal and the cost
        # line resolution for this replace both run above, before any write.
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
                    cost_line_id=item_cost_line_ids[idx],
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

        # The same gate :meth:`approve_po` applies. PATCH is a second door into
        # ``approved`` (``_PO_STATUS_TRANSITIONS`` allows ``draft -> approved``
        # and ``cancelled -> draft -> approved``), so leaving it ungated would
        # let a caller commit an arithmetically broken PO to the budget by
        # avoiding one endpoint. A gate with a second door is not a gate.
        #
        # It runs on the POST-patch state, not on the PO as it was read: a PATCH
        # that repairs the amounts and approves in the same call is legitimate
        # and must pass. Raising here rolls the whole PATCH back, since the
        # request session commits only on a clean return and the repository
        # flushes rather than commits, and it happens before any event is
        # published so no listener sees a change that was undone.
        if prior_status != "approved" and updated.status == "approved":
            await self._validate_po_or_raise(updated, operation="approve")

        await _safe_publish(
            "procurement.po.updated",
            {
                "po_id": str(po_id),
                "project_id": str(updated.project_id),
                "updated_fields": list(fields.keys()),
                "status": updated.status,
            },
        )

        # Entering ``approved`` through PATCH must commit the budget exactly as
        # :meth:`approve_po` does. Without this the ledger was asymmetric: only
        # ``approve_po`` published ``procurement.po.approved``, while the block
        # below published the compensating event from either path. So a PATCH
        # into ``approved`` followed by a PATCH back to ``draft`` decremented
        # ``ProjectBudget.committed`` by an amount that was never committed, and
        # a PO approved this way was issuable while finance had never seen the
        # exposure at all.
        #
        # Guarded on the transition, not on the resulting state: a PATCH that
        # touches an already-approved PO must not commit the amount a second
        # time. Same condition, same payload and same audit row as
        # ``approve_po``, so the two doors into ``approved`` are indistinguishable
        # to every subscriber. ``approver_id`` is empty here because PATCH
        # carries no approver, which is what ``approve_po`` also sends when it
        # is called without one.
        if prior_status != "approved" and updated.status == "approved":
            try:
                from app.core.audit_log import log_activity

                await log_activity(
                    self.session,
                    actor_id=None,
                    entity_type="purchase_order",
                    entity_id=str(po_id),
                    action="status_changed",
                    from_status=prior_status,
                    to_status="approved",
                    reason="PO approved via update_po()",
                    metadata={"po_number": updated.po_number},
                )
            except Exception:
                # This path reads a freshly re-fetched ``updated``, so it does
                # not have the expired-attribute problem the other two doors
                # into ``approved`` had. It is still logged at WARNING: an
                # audit row that never lands is a compliance gap, and at
                # production INFO a debug line is not there to be found.
                logger.warning(
                    "FSM audit log FAILED for PO approve via PATCH (po_id=%s)",
                    po_id,
                    exc_info=True,
                )

            await _safe_publish(
                "procurement.po.approved",
                {
                    "po_id": str(po_id),
                    "project_id": str(updated.project_id),
                    "po_number": updated.po_number,
                    "amount_total": updated.amount_total,
                    "currency_code": updated.currency_code or "",
                    "approver_id": "",
                },
            )

        # Max-Audit #10: when a PO leaves a COMMITTED state its budget
        # commitment must be reversed. The PO FSM allows ``approved -> draft``
        # (revert) and a cancel out of ``approved``, ``issued`` and
        # ``partially_received``; publish a compensating event carrying
        # ``amount_total`` so finance can decrement ``committed`` by exactly
        # what this PO committed. Without this the commitment ledger only ever
        # grows and phantom commitments corrupt the dashboard / EVM.
        #
        # The condition used to read ``prior_status == "approved"``, which is
        # where the commitment is ADDED - but not the only state it is held
        # in. ``approved -> issued`` does not release anything, so a PO
        # cancelled out of ``issued`` or ``partially_received`` kept its
        # commitment for good and the committed figure never came back down.
        # ``_on_po_decommitted`` is idempotent on the marker it clears, so a
        # widened condition cannot double-decrement.
        if prior_status in _PO_COMMITTED_STATUSES and updated.status != prior_status:
            if updated.status == "cancelled":
                _decommit_event = "procurement.po.cancelled"
            elif updated.status == "draft":
                _decommit_event = "procurement.po.reverted"
            else:
                _decommit_event = None
            if _decommit_event is not None:
                await _safe_publish(
                    _decommit_event,
                    {
                        "po_id": str(po_id),
                        "project_id": str(updated.project_id),
                        "po_number": updated.po_number,
                        "amount_total": updated.amount_total,
                        "currency_code": updated.currency_code or "",
                        "prior_status": prior_status,
                        "status": updated.status,
                    },
                )

        updated.vendor_warnings = vendor_warnings  # type: ignore[attr-defined]

        logger.info("PO updated: %s", po_id)
        return updated

    # ── Removal: cancel (void) and delete ────────────────────────────────────
    #
    # A purchase order is a commercial document, so "get rid of it" is three
    # operations, not one, and which applies is decided by what the document
    # has already done rather than by who is asking:
    #
    # * a draft PO that never left draft and that nothing points at may be
    #   DELETED. Budget commits at ``approved``, so such a PO has no finance
    #   marker to compensate, no audit trail hanging off it and no number any
    #   supplier has seen. This is the duplicate, the mistyped one, the row
    #   somebody opened by accident.
    # * a PO that has been approved or issued is CANCELLED. The row stays, the
    #   ``po_number`` stays, the status becomes ``cancelled`` and the reason is
    #   recorded. The number is what the supplier quotes and a gap in the
    #   sequence is what an auditor asks about, so it is never reused and never
    #   reclaimed.
    # * a PO that goods receipts, payable invoices, retainage releases or
    #   requisitions point at is REFUSED, 409, naming every holder by kind and
    #   count. Deleting it would take an audit trail with it; cancelling it
    #   would void a commitment that other records are still measuring
    #   themselves against.
    #
    # A PO that has been delivered against and now has to stop is closed, not
    # voided: the FSM already allows ``issued -> completed`` and
    # ``partially_received -> completed``, which records that the order ended
    # where it ended. Cancelling would claim it never happened.

    async def _collect_po_holders(self, po: PurchaseOrder) -> dict[str, int]:
        """Count every record that points at this PO, by kind.

        Only non-zero kinds are returned, so an empty dict means nothing is in
        the way. Line items are deliberately absent: they belong to the PO
        rather than referring to it, and they go wherever it goes.
        """
        holders: dict[str, int] = {}
        for kind, method in _PO_HOLDER_COUNTERS:
            counter = getattr(self.po_repo, method)
            count = await (counter(po.id, po.project_id) if kind == "payable_invoice" else counter(po.id))
            if count:
                holders[kind] = int(count)
        return holders

    async def _refuse_if_po_is_held(self, po: PurchaseOrder, *, action: str) -> None:
        """Raise 409 when anything still points at this PO.

        Takes a row-level write lock on the PO first, so the count and the
        removal that follows it are one critical section. Without the lock this
        is a read followed by a write: the counts come back empty, a goods
        receipt is inserted against the PO, and the delete then CASCADEs it away
        without an error - ``GoodsReceipt.po_id`` and ``PORetainageRelease.po_id``
        are both ``ondelete="CASCADE"``, so the database would not object, and a
        retainage release is money already paid out.

        What the lock buys, precisely. ``FOR UPDATE`` on the PO row conflicts
        with the ``FOR KEY SHARE`` that PostgreSQL's referential-integrity
        trigger takes on a parent row when a child carrying a foreign key to it
        is inserted. So a concurrent insert of a goods receipt, a retainage
        release or a material requisition either blocks until this transaction
        ends, or committed before the lock was granted and is therefore visible
        to the counts below. Both outcomes are correct; neither loses a row.

        Payable invoices are the exception that the database cannot cover:
        finance is an optional module and its ``Invoice`` carries no foreign
        key to a PO, only a ``metadata_["po_id"]`` stamp, so inserting one
        takes no lock on this row and no referential-integrity trigger fires.
        That kind is serialised by cooperation instead - the invoice-creation
        endpoint takes this same lock before it reads the PO, so whichever of
        the two transactions arrives second waits and then sees the other's
        committed result. If a second way to raise an invoice against a PO is
        ever added, it has to take the lock too; nothing in the schema will
        enforce it the way it does for the three kinds above.

        The lock is taken here rather than in each caller so that no removal
        door can be added later that counts without it - the same reasoning
        that put the guard itself in one place and called it from all three.
        Re-taking it in a transaction that already holds it is a no-op, so a
        caller that locks earlier for its own reasons costs nothing.

        Args:
            po: The purchase order being cancelled or deleted.
            action: ``"cancel"`` or ``"delete"`` - only shapes the wording, the
                rule is the same for both. What holds a document holds it
                regardless of which verb is trying to remove it.
        """
        await self.po_repo.lock_for_update(po.id)
        holders = await self._collect_po_holders(po)
        if not holders:
            return
        described = _describe_holders(holders)
        raise _holders_conflict(
            code="purchase_order_has_dependents",
            message=(
                f"Purchase order {po.po_number} cannot be {'cancelled' if action == 'cancel' else 'deleted'}: "
                f"{described} still {_agreeing_verb(holders, 'refers', 'refer')} to it."
            ),
            remediation=(
                "Reverse or detach those records first, or close the purchase order short "
                "so the register keeps what was actually ordered and received."
            ),
            holders=holders,
        )

    async def cancel_po(
        self,
        po_id: uuid.UUID,
        reason: str | None = None,
        actor_id: str | None = None,
    ) -> PurchaseOrder:
        """Void a purchase order, keeping the row and its number.

        Args:
            po_id: The purchase order to void.
            reason: Why it is being voided. Stored on the PO and in the audit
                trail; optional, because a mandatory field only guarantees a
                full stop gets typed.
            actor_id: The user voiding it, for the audit row.

        Returns:
            The cancelled purchase order, re-read after the write.

        Raises:
            HTTPException: 404 if the PO does not exist, 409 if it is already
                terminal or if any record still points at it.
        """
        # Same critical section as ``delete_po``: lock first, then read, so the
        # status this cancel is decided on and the holders counted below are
        # the same version the write lands on. ``prior_status`` in particular
        # chooses which compensating event fires, and a stale read there would
        # release a budget commitment twice or not at all.
        await self.po_repo.lock_for_update(po_id)
        po = await self.get_po(po_id)
        prior_status = po.status
        po_number = po.po_number
        project_id = po.project_id
        amount_total = po.amount_total
        currency_code = po.currency_code or ""

        if prior_status == "cancelled":
            raise _holders_conflict(
                code="purchase_order_already_cancelled",
                message=f"Purchase order {po_number} is already cancelled.",
                remediation="Nothing to do.",
                holders={},
            )
        if "cancelled" not in _PO_STATUS_TRANSITIONS.get(prior_status, set()):
            raise _holders_conflict(
                code="purchase_order_not_cancellable",
                message=(
                    f"Purchase order {po_number} is in status '{prior_status}' and cannot be cancelled; "
                    "a completed order records what was actually bought."
                ),
                remediation="Raise a credit note or a variation against it instead.",
                holders={},
            )

        await self._refuse_if_po_is_held(po, action="cancel")

        cancellation = {
            "reason": reason or "",
            "cancelled_at": datetime.now(UTC).isoformat(),
            "cancelled_by": actor_id or "",
            "prior_status": prior_status,
        }
        await self.po_repo.update(
            po_id,
            status="cancelled",
            metadata_=merge_metadata(getattr(po, "metadata_", None), {"cancellation": cancellation}),
        )

        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="purchase_order",
                entity_id=str(po_id),
                action="status_changed",
                from_status=prior_status,
                to_status="cancelled",
                reason=reason or "PO cancelled via cancel_po()",
                metadata={"po_number": po_number},
            )
        except Exception:
            # Same treatment as the approve and issue doors: a missing audit
            # row on a voided commercial document is a compliance gap, and at
            # production INFO a debug line is not there to be found.
            logger.warning("FSM audit log FAILED for PO cancel (po_id=%s)", po_id, exc_info=True)

        updated = await self.po_repo.get(po_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )

        await _safe_publish(
            "procurement.po.cancelled" if prior_status in _PO_COMMITTED_STATUSES else "procurement.po.updated",
            {
                "po_id": str(po_id),
                "project_id": str(project_id),
                "po_number": po_number,
                "amount_total": amount_total,
                "currency_code": currency_code,
                "prior_status": prior_status,
                "status": "cancelled",
            },
        )

        logger.info("PO cancelled: %s (from %s)", po_number, prior_status)
        return updated

    async def delete_po(self, po_id: uuid.UUID) -> None:
        """Delete a draft purchase order that never left draft.

        Args:
            po_id: The purchase order to delete.

        Raises:
            HTTPException: 404 if the PO does not exist, 409 if it is not a
                never-issued draft or if any record still points at it.
        """
        # Lock before the first check rather than leaving it to the holder
        # guard further down. Every question this method asks - the status, the
        # audit trail, the holders - has to be answered about the same version
        # of the PO that the delete then acts on, and ``has_left_draft`` reads
        # the status-change trail that a concurrent approval writes. Locking
        # here puts all three under one critical section; the guard takes the
        # same lock again, which is free once this transaction holds it.
        await self.po_repo.lock_for_update(po_id)
        po = await self.get_po(po_id)

        if po.status != "draft":
            raise _holders_conflict(
                code="purchase_order_not_deletable",
                message=(
                    f"Purchase order {po.po_number} is in status '{po.status}' and cannot be deleted; "
                    "a purchase order that has been approved or issued keeps its record and its number."
                ),
                remediation="Cancel it instead - the row survives and the number stays out of circulation.",
                holders={},
            )

        # Current status is not enough on its own. The FSM allows
        # ``cancelled -> draft``, so a PO that was approved, issued, cancelled
        # and reopened is sitting in ``draft`` with its number already in a
        # supplier's inbox. The status-change audit trail is the record of
        # that history and every door into ``approved`` and ``issued`` writes
        # one.
        if await self.po_repo.has_left_draft(po_id):
            raise _holders_conflict(
                code="purchase_order_not_deletable",
                message=(
                    f"Purchase order {po.po_number} has been approved or issued before and cannot be deleted, "
                    "even though it is back in draft."
                ),
                remediation="Cancel it instead - the row survives and the number stays out of circulation.",
                holders={},
            )

        await self._refuse_if_po_is_held(po, action="delete")

        await self.po_repo.delete(po_id)
        await _safe_publish(
            "procurement.po.deleted",
            {
                "po_id": str(po_id),
                "project_id": str(po.project_id),
                "po_number": po.po_number,
            },
        )
        logger.info("PO deleted: %s", po.po_number)

    # ── Validation ───────────────────────────────────────────────────────────

    def _validation_payload(self, po: PurchaseOrder) -> dict[str, object]:
        """Flatten a PO and its lines into the dict the ``procurement`` rules read.

        Rules never touch the ORM, so everything they need is copied out here.
        Amounts stay Decimal strings exactly as stored -- the rules parse them
        themselves and report an unparseable amount rather than coercing it.
        """
        return {
            "id": str(po.id),
            "project_id": str(po.project_id),
            "po_number": po.po_number,
            "status": po.status,
            "currency_code": po.currency_code or "",
            "amount_subtotal": po.amount_subtotal,
            "tax_amount": po.tax_amount,
            "amount_total": po.amount_total,
            "retention_percent": str(po.retention_percent if po.retention_percent is not None else "0"),
            "issue_date": po.issue_date,
            "delivery_date": po.delivery_date,
            "vendor_contact_id": po.vendor_contact_id,
            "items": [
                {
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "unit_rate": item.unit_rate,
                    "amount": item.amount,
                    "wbs_id": item.wbs_id,
                    "cost_category": item.cost_category,
                    "cost_line_id": (str(item.cost_line_id) if item.cost_line_id else None),
                    "sort_order": item.sort_order,
                }
                for item in sorted(po.items, key=lambda i: (i.sort_order, str(i.id)))
            ],
        }

    async def _validate_po(self, po: PurchaseOrder, *, operation: str) -> ValidationReport:
        """Run the ``procurement`` rule set against a purchase order."""
        return await validation_engine.validate(
            data=self._validation_payload(po),
            rule_sets=[PROCUREMENT_RULE_SET],
            target_type="purchase_order",
            target_id=str(po.id),
            project_id=str(po.project_id),
            metadata={"locale": get_locale(), "operation": operation},
        )

    async def _validate_po_or_raise(self, po: PurchaseOrder, *, operation: str) -> ValidationReport:
        """Run validation and raise HTTP 422 when any ERROR-severity rule fails.

        The detail carries every failing rule, not just the first, so the buyer
        fixes the purchase order once instead of rediscovering the next problem
        on the next attempt.
        """
        report = await self._validate_po(po, operation=operation)
        if report.has_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": (
                        f"This purchase order has problems that must be fixed before you can "
                        f"{operation} it. See the errors listed below, correct each one, then try again."
                    ),
                    "report": report.summary(),
                    "errors": [
                        {
                            "rule_id": r.rule_id,
                            "message": r.message,
                            "element_ref": r.element_ref,
                            "suggestion": r.suggestion,
                        }
                        for r in report.errors
                    ],
                },
            )
        return report

    @staticmethod
    def _po_report_to_dict(report: ValidationReport) -> dict[str, object]:
        """Flatten a ValidationReport into the API response shape."""
        summary = report.summary()
        return {
            "status": summary["status"],
            "score": summary["score"],
            "counts": summary["counts"],
            "results": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "severity": r.severity.value,
                    "category": r.category.value,
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
                for r in report.results
            ],
        }

    async def validate_po(self, po_id: uuid.UUID) -> dict[str, object]:
        """Run the procurement rule set and return the report (read-only).

        Lets a buyer see what approval would refuse before trying it, so the
        gate below is never the first time the problem is mentioned.
        """
        po = await self.get_po(po_id)
        report = await self._validate_po(po, operation="read")
        return self._po_report_to_dict(report)

    async def approve_po(self, po_id: uuid.UUID, approver_id: str | None = None) -> PurchaseOrder:
        """Approve a draft PO so it can be issued (TOP-30 #10).

        Approval is the commitment moment: it transitions ``draft -> approved``
        and publishes ``procurement.po.approved`` so finance commits the amount
        against the project budget. Issuing the PO to the vendor is a separate
        downstream step that requires this approval first.

        Because nothing downstream re-derives the committed amount, the
        ``procurement`` rule set runs here and ERROR-severity findings block the
        transition (422). A PO whose subtotal disagrees with its own lines would
        otherwise commit one number to the budget and show another to the buyer.
        WARNING findings (uncoded lines, a delivery date before issue) do not
        block; they are returned by :meth:`validate_po` for the buyer to see.
        """
        po = await self.get_po(po_id)
        prior_status = po.status
        # Read the number before the update below. ``PORepository.update`` ends
        # in ``session.expire_all()``, so every loaded instance including this
        # one is expired, and reading an expired attribute on the async session
        # re-issues a sync SELECT and raises MissingGreenlet. The audit call is
        # the only read here that is not preceded by a re-fetch, and its
        # failure is swallowed, so the row would just go missing.
        po_number = po.po_number
        if prior_status == "approved":
            return po  # idempotent
        if prior_status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot approve PO in status '{prior_status}'",
            )
        await self._validate_po_or_raise(po, operation="approve")
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
                metadata={"po_number": po_number},
            )
        except Exception:
            logger.warning(
                "FSM audit log FAILED for PO approve (po_id=%s)",
                po_id,
                exc_info=True,
            )

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
        # Same reason as in ``approve_po``: the update below expires every
        # loaded instance, and the audit call is the one read that is not
        # preceded by a re-fetch.
        po_number = po.po_number
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
                metadata={"po_number": po_number},
            )
        except Exception:
            logger.warning(
                "FSM audit log FAILED for PO issue (po_id=%s)",
                po_id,
                exc_info=True,
            )

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

        # Serialise the cap-check + increment against concurrent releases.
        # ``retainage_released_amount`` is a Decimal-STRING column, so it cannot
        # be incremented atomically in SQL (no ``col = col + :amt``). Without a
        # lock, two concurrent releases both read the same ``released_sum``, both
        # pass the held-balance cap, and both write the same new total - a lost
        # update that over-releases retainage (two audit rows, but the PO shows
        # only one release). Take a row-level write lock on the PO, then re-read
        # it FRESH under the lock so the cap and the write are one critical
        # section. The lock releases at request-transaction commit.
        await self.po_repo.lock_for_update(po_id)
        locked = await self.po_repo.get(po_id)
        # retainage_amount depends only on amount_total / retention_percent,
        # which this path never mutates; the freshly-locked row is authoritative
        # for the cumulative released total. ``retainage_held`` already floors at
        # zero, so a concurrent release that drained the balance first leaves
        # held=0 here and the cap below rejects this one.
        held = (locked or po).retainage_held()
        if release_amount > held:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Release amount {release_amount} exceeds held retainage {held}",
            )

        released_sum = _to_decimal((locked or po).retainage_released_amount)
        new_released = released_sum + release_amount
        # Capture the scalar PO fields the audit row + event need BEFORE the
        # update: ``po_repo.update`` calls ``expire_all()``, after which reading
        # ``po.project_id`` / ``po.po_number`` / ``po.currency_code`` would
        # trigger a lazy reload from sync context (MissingGreenlet on the async
        # session).
        src = locked or po
        po_project_id = src.project_id
        po_number = src.po_number
        po_currency = src.currency_code or ""
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
                    "po_number": po_number,
                    "release_amount": str(release_amount),
                    "currency_code": po_currency,
                    "retainage_released_total": str(new_released),
                },
            )
        except Exception:
            logger.debug("Audit log skipped for PO %s retainage release", po_id)

        await _safe_publish(
            "procurement.po.retainage_released",
            {
                "po_id": str(po_id),
                "project_id": str(po_project_id),
                "po_number": po_number,
                "release_amount": str(release_amount),
                "currency_code": po_currency,
                "released_by": str(user_id) if user_id else None,
                "release_reason": reason,
                "retainage_released_total": str(new_released),
            },
        )

        logger.info(
            "Retainage released on PO %s: amount=%s %s",
            po_number,
            release_amount,
            po_currency,
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
        # A goods receipt always enters its FSM at "draft"; confirmation is a
        # separate step via confirm_goods_receipt(), which is the ONLY path that
        # runs the confirm-time over-receipt cap, rolls the PO up to
        # partially_received/completed, and publishes ``procurement.gr.confirmed``
        # so finance moves the committed slice to actual. ``GRCreate.status`` has
        # no enum guard, so a caller could otherwise POST a GR already
        # ``status="confirmed"`` and strand the PO + budget in an inconsistent
        # state (the receipt counts as confirmed for over-receipt math but the PO
        # never flips and no finance event fires). Reject it here, mirroring the
        # draft-only entry guard on create_po().
        if data.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"A goods receipt must be created in 'draft' status, not '{data.status}'. "
                    "Use the confirm action to advance it."
                ),
            )

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

        # Capture po_id while ``gr`` is attached and fresh. confirm_if_draft()
        # below calls session.expire_all(); afterwards even a scalar read like
        # ``gr.po_id`` would lazy-load from a sync context and raise
        # MissingGreenlet on the async session. Reusing this local keeps the
        # post-confirm re-fetch off the expired instance.
        po_id = gr.po_id

        # Re-apply the cumulative over-receipt cap at confirm time: prior
        # confirmed receipts on the same po_item_id plus this receipt's lines
        # must not exceed the ordered quantity. ``exclude_receipt_id`` keeps
        # this GR out of the prior sum so it is not counted against itself.
        po = await self.get_po(po_id)
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

        # Flip draft -> confirmed atomically. The conditional UPDATE (WHERE
        # status='draft') is the idempotency guard against a double-confirm
        # race: two concurrent confirm requests both pass the read-time
        # ``gr.status != "draft"`` check above (separate READ COMMITTED
        # transactions), but only ONE wins the conditional write. The loser
        # gets won=False and 409s instead of re-publishing
        # ``procurement.gr.confirmed`` and re-running the PO rollup (which would
        # double-count this receipt against the budget).
        won = await self.gr_repo.confirm_if_draft(gr_id)
        if not won:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Goods receipt was already confirmed by a concurrent request.",
            )

        # confirm_if_draft() calls session.expire_all(), which expires EVERY
        # instance in the session - including ``gr`` and the ``po`` fetched
        # above. Any later synchronous attribute read on an expired instance
        # (a relationship, or even a scalar like ``gr.po_id``/``po.po_number``)
        # would lazy-load from a sync context and raise MissingGreenlet on the
        # async session, so we re-fetch off the ``po_id`` captured before the
        # confirm. This re-fetch also sees the GR just flipped to confirmed.
        po = await self.get_po(po_id)
        # Snapshot the scalar PO field used in the log lines below: po_repo.update()
        # also calls expire_all(), so reading po.po_number after it would hit the
        # same MissingGreenlet trap.
        po_number = po.po_number

        # Update PO status based on total received quantities.
        status_changed = False
        if po.status in ("issued", "partially_received"):
            all_fully_received = self._check_po_fully_received(po)
            if all_fully_received:
                await self.po_repo.update(po.id, status="completed")
                logger.info("PO %s fully received, status -> completed", po_number)
                status_changed = True
            elif po.status == "issued":
                await self.po_repo.update(po.id, status="partially_received")
                logger.info("PO %s partially received", po_number)
                status_changed = True

        # po_repo.update() expired the session again; re-fetch a fresh, fully
        # eager-loaded PO so the receipt-value computation and the event payload
        # below read live relationship/column data instead of lazy-loading from
        # a sync context.
        if status_changed:
            po = await self.get_po(po_id)

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

            # Find invoices whose JSON metadata.po_id == this PO id. Fetch the
            # id AND metadata_ together so the link filter needs no second pass
            # over the same id set (previously a separate ``meta_stmt`` re-read
            # the metadata for every id this query already returned).
            inv_stmt = _select(Invoice.id, Invoice.metadata_).where(
                Invoice.project_id == po.project_id,
                Invoice.invoice_direction == "payable",
            )
            inv_rows = (await self.session.execute(inv_stmt)).all()
            linked_invoice_ids: set[uuid.UUID] = {
                inv_id for inv_id, meta in inv_rows if isinstance(meta, dict) and str(meta.get("po_id")) == str(po_id)
            }
            if linked_invoice_ids:
                # Pull line items only for the invoices actually linked to this
                # PO, not every payable invoice in the project - both fewer rows
                # over the wire and a tighter IN clause.
                line_stmt = _select(
                    InvoiceLineItem.sort_order,
                    InvoiceLineItem.quantity,
                ).where(InvoiceLineItem.invoice_id.in_(linked_invoice_ids))
                line_rows = (await self.session.execute(line_stmt)).all()

                for sort_order, qty in line_rows:
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
        accessible_project_ids: set[uuid.UUID] | None = None,
    ) -> dict:
        """Return supplier KPIs for the trailing window.

        Returns a dict shaped like :class:`SupplierScorecardResponse`. All
        rates are 0.0-1.0; a supplier with zero POs gets all-zero fields
        instead of raising (no division-by-zero crash).

        ``project_id`` scopes the query to a single project (used by the
        UI when the user opens a scorecard from a project's PO list).

        ``accessible_project_ids`` scopes the cross-project overview (when
        ``project_id`` is omitted) to only the projects the caller may see.
        ``None`` is the "do not filter" sentinel (admin / single-project
        path already gated by ``project_id``); a SET restricts the
        aggregate to those project ids. An EMPTY set means the caller can
        reach no project, so every aggregate must come back empty rather
        than leaking a supplier's PO totals across other tenants' projects
        (IDOR on the cross-project supplier overview). Mirrors the
        ``app.dependencies.accessible_project_ids`` contract.
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
        elif accessible_project_ids is not None:
            # Cross-project overview for a non-admin: restrict to the
            # caller's own projects. An empty set yields ``IN ()`` which
            # matches nothing, so the supplier's totals never leak across
            # tenants the caller cannot access.
            po_filters.append(PurchaseOrder.project_id.in_(accessible_project_ids))
        # Trailing window: filter by created_at (PO ``issue_date`` is a
        # free-form string and may be NULL).
        po_filters.append(PurchaseOrder.created_at >= datetime.fromisoformat(cutoff))

        # Single PO scan: count, value+currency, ids, and the delivery-date
        # lookup all derive from the same filtered row set. Previously these
        # were four separate queries (COUNT, amount+currency, ids, deliveries)
        # that re-applied the identical ``po_filters`` four times; folding them
        # into one SELECT cuts three round trips per scorecard read.
        po_rows = (
            await self.session.execute(
                _select(
                    PurchaseOrder.id,
                    PurchaseOrder.amount_total,
                    PurchaseOrder.currency_code,
                    PurchaseOrder.delivery_date,
                ).where(_and(*po_filters))
            )
        ).all()

        total_po_count = len(po_rows)
        po_ids: list[uuid.UUID] = []
        # PO delivery-date lookup (string ISO dates compare lexicographically
        # when both are YYYY-MM-DD); drives the on-time check below.
        po_delivery_map: dict[uuid.UUID, str | None] = {}
        # Group PO value per currency so a cross-project overview never blends
        # different currencies into one meaningless total (a supplier can hold
        # POs in a EUR project and a GBP project). Report the dominant currency's
        # total and flag the rest via ``mixed_currency``.
        value_by_currency: dict[str, Decimal] = {}
        for po_row_id, amt, cur, delivery in po_rows:
            po_ids.append(po_row_id)
            po_delivery_map[po_row_id] = delivery
            value_by_currency[cur or ""] = value_by_currency.get(cur or "", Decimal("0")) + _to_decimal(amt)
        # Headline = the (non-blank) currency with the largest aggregate value;
        # fall back to the blank-currency bucket only when that is all there is.
        _named = {c: v for c, v in value_by_currency.items() if c}
        if _named:
            # Tie-break on the currency code so two identical calls always report
            # the same headline currency when aggregates are exactly equal (the
            # PO scan has no ORDER BY, so row order is otherwise DB-dependent).
            currency, total_po_value = max(_named.items(), key=lambda kv: (kv[1], kv[0]))
        else:
            currency, total_po_value = "", value_by_currency.get("", Decimal("0"))
        mixed_currency = len(_named) > 1

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
                GoodsReceipt.po_id,
                GoodsReceipt.receipt_date,
                GoodsReceipt.status,
            ).where(GoodsReceipt.po_id.in_(po_ids))
            gr_rows = (await self.session.execute(gr_stmt)).all()

            for gr_po_id, receipt_date, gr_status in gr_rows:
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
            "mixed_currency": mixed_currency,
            "on_time_delivery_pct": on_time_pct,
            "qty_variance_pct": qty_variance_pct,
            "gr_rejection_rate": rejection_rate,
            "total_gr_count": total_gr_count,
            "on_time_count": on_time_count,
            "unscheduled_count": unscheduled_count,
        }

    # -- Supplier delivery performance / OTIF (project view) --------------

    async def get_delivery_performance(
        self,
        project_id: uuid.UUID,
    ) -> ProjectDeliveryPerformanceResponse:
        """Compute the project OTIF (on-time-in-full) delivery-performance view.

        Loads every purchase order in the project, its CONFIRMED goods receipts,
        and their line items, then hands the arithmetic to the pure
        :func:`app.modules.procurement.otif.compute_project_delivery_performance`
        helper. Promised date is the PO ``delivery_date``; received date is the
        goods-receipt ``receipt_date``; ordered and received quantities are
        summed per receipt from its line items. Only confirmed receipts count -
        a draft receipt is not yet an accepted delivery. Vendor display names
        are left to the router (the same lookup the PO list uses).
        """
        from sqlalchemy import select as _select

        # -- POs in the project: promised date + vendor, in one scan ---------
        po_rows = (
            await self.session.execute(
                _select(
                    PurchaseOrder.id,
                    PurchaseOrder.vendor_contact_id,
                    PurchaseOrder.delivery_date,
                ).where(PurchaseOrder.project_id == project_id)
            )
        ).all()
        po_meta: dict[uuid.UUID, tuple[str | None, str | None]] = {
            po_id: (vendor, delivery) for po_id, vendor, delivery in po_rows
        }

        records: list[ReceiptRecord] = []
        po_ids = list(po_meta.keys())
        if po_ids:
            # -- Confirmed goods receipts against those POs ------------------
            gr_rows = (
                await self.session.execute(
                    _select(
                        GoodsReceipt.id,
                        GoodsReceipt.po_id,
                        GoodsReceipt.receipt_date,
                    )
                    .where(GoodsReceipt.po_id.in_(po_ids))
                    .where(GoodsReceipt.status == "confirmed")
                )
            ).all()
            gr_ids = [gr_id for gr_id, _, _ in gr_rows]

            # -- Sum ordered / received per receipt from its line items ------
            ordered_by_gr: dict[uuid.UUID, Decimal] = {}
            received_by_gr: dict[uuid.UUID, Decimal] = {}
            if gr_ids:
                item_rows = (
                    await self.session.execute(
                        _select(
                            GoodsReceiptItem.receipt_id,
                            GoodsReceiptItem.quantity_ordered,
                            GoodsReceiptItem.quantity_received,
                        ).where(GoodsReceiptItem.receipt_id.in_(gr_ids))
                    )
                ).all()
                for receipt_id, ordered_raw, received_raw in item_rows:
                    ordered_by_gr[receipt_id] = ordered_by_gr.get(receipt_id, Decimal("0")) + _to_decimal(ordered_raw)
                    received_by_gr[receipt_id] = received_by_gr.get(receipt_id, Decimal("0")) + _to_decimal(
                        received_raw
                    )

            for gr_id, gr_po_id, receipt_date in gr_rows:
                received = _parse_iso_date(receipt_date)
                if received is None:
                    # No usable receipt date - cannot place the delivery in time.
                    continue
                vendor, delivery = po_meta.get(gr_po_id, (None, None))
                records.append(
                    ReceiptRecord(
                        supplier_id=vendor,
                        received_date=received,
                        promised_date=_parse_iso_date(delivery),
                        ordered_qty=ordered_by_gr.get(gr_id, Decimal("0")),
                        received_qty=received_by_gr.get(gr_id, Decimal("0")),
                    )
                )

        perf = compute_project_delivery_performance(records)
        return ProjectDeliveryPerformanceResponse(
            project_id=project_id,
            overall=_perf_to_schema(perf.overall),
            suppliers=[_perf_to_schema(s) for s in perf.suppliers],
        )

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

    async def committed_by_position(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """One page of the committed rollup per BOQ position, and its size.

        Joins PO items -> cost spine -> BOQ positions to show what has been
        ordered against each estimated line item.

        The page and the total come off one list rather than out of two
        queries. The collapse from cost line to bill position happens here in
        Python and not in SQL - several cost lines can name the same position,
        so the number of rows the caller will see is not known until they have
        been folded together. A second query counting distinct positions would
        have to repeat that fold, and the day the two folds stopped agreeing
        the total would be wrong with nothing to notice it. Building the whole
        list, counting it and slicing the page out of it cannot drift, because
        there is only one list.

        The sort is explicit for the same reason the slice needs it: the rows
        arrive in whatever order the database returned them, which it is free
        to change between two identical requests. Paging an unordered set
        skips rows and repeats others.

        Args:
            project_id: The project whose purchase orders are read.
            limit: How many positions the page holds.
            offset: How many positions to skip before it starts.

        Returns:
            The page, and the number of positions with commitments in all.
        """
        from sqlalchemy import select

        from app.modules.procurement.cost_spine import positions_for_cost_lines
        from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem

        # Every live PO line in the project, with the cost line it commits
        # against. The amounts are added up below rather than by SQL, because
        # they are stored as text and the portable way to sum text here is
        # ``numeric_value``, which goes through double precision. That is
        # acceptable for a quantity and wrong for money, which this repository
        # carries as Decimal from end to end.
        stmt = (
            select(
                PurchaseOrderItem.cost_line_id,
                PurchaseOrderItem.quantity,
                PurchaseOrderItem.amount,
            )
            .join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id)
            .where(PurchaseOrder.project_id == project_id)
            .where(PurchaseOrder.status != "cancelled")
            .where(PurchaseOrderItem.cost_line_id.is_not(None))
        )
        committed = (await self.session.execute(stmt)).all()

        cost_line_ids = [row.cost_line_id for row in committed if row.cost_line_id]
        position_map = await positions_for_cost_lines(self.session, cost_line_ids) if cost_line_ids else {}

        # Keyed by the position id as text, and normalised on the way in. The
        # map answers with a UUID while the fallback is a cost line id already
        # in text, so a dict accepting both spellings would file one position
        # under two keys and split its rollup in half without ever failing.
        totals: dict[str, tuple[Decimal, Decimal]] = {}
        for row in committed:
            cost_line_id = str(row.cost_line_id)
            position_id = str(position_map.get(cost_line_id, cost_line_id))
            committed_qty, committed_value = totals.get(position_id, (Decimal("0"), Decimal("0")))
            totals[position_id] = (
                committed_qty + _to_decimal(row.quantity),
                committed_value + _to_decimal(row.amount),
            )

        ordered = sorted(totals.items())
        rows = [
            {
                "boq_position_id": position_id,
                "committed_qty": str(committed_qty),
                "committed_value": str(committed_value),
            }
            for position_id, (committed_qty, committed_value) in ordered[offset : offset + limit]
        ]
        return rows, len(ordered)


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
        for _ in range(_MAX_RETRIES):
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
                   An item may also carry ``boq_position_id`` or ``cost_line_id``
                   to link the line to the cost spine, resolved on write by
                   :func:`app.modules.procurement.cost_spine.resolve_cost_line_ids`
                   exactly as a purchase-order line is.

        Requisition lines take their spine link from a dict rather than from a
        schema because this path has no schema and no HTTP surface: the module
        exposes no requisition endpoint, so there is no ``RequisitionItemCreate``
        to add a field to. The resolution is wired here so the link is already
        correct on the day the endpoint lands, rather than being a second
        omission to discover then.
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
            cost_line_ids = await resolve_cost_line_ids(
                self.session,
                project_id,
                [(item.get("cost_line_id"), item.get("boq_position_id")) for item in items],
            )
            for idx, item_data in enumerate(items):
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
                    cost_line_id=cost_line_ids[idx],
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
