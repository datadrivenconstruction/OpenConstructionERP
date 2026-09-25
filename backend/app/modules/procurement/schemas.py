# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement Pydantic schemas - request/response models."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Same ``YYYY-MM-DD`` shape POCreate.issue_date / delivery_date pin via their
# field ``pattern``. Reused by POUpdate's date validator so the update path
# cannot accept a date shape the create path would reject.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_non_negative_decimal(v: str) -> str:
    """Validate that a string is a valid non-negative decimal number."""
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value: {v!r}") from exc
    if d < 0:
        raise ValueError(f"Value must be non-negative, got {v!r}")
    return v


# ── Purchase Order ───────────────────────────────────────────────────────────


class POItemCreate(BaseModel):
    """Create a line item within a purchase order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=500)
    quantity: str = Field(default="1", max_length=50)
    unit: str | None = Field(default=None, max_length=20)
    unit_rate: str = Field(default="0", max_length=50)
    amount: str = Field(default="0", max_length=50)
    wbs_id: str | None = Field(default=None, max_length=36)
    cost_category: str | None = Field(default=None, max_length=100)
    # ── Cost Spine linkage ───────────────────────────────────────────────
    # An input field, deliberately not a column. The buyer picks a bill
    # position because that is the language of the job; the money row stores
    # only the cost line that position rolls up into, resolved when the item
    # is written. app.modules.procurement.cost_spine holds the full reasoning
    # and the reason a money table never grows a boq_position_id column.
    boq_position_id: str | None = Field(
        default=None,
        max_length=36,
        description="BoQ position this line is bought against. Resolved to a cost line on write.",
    )
    cost_line_id: str | None = Field(
        default=None,
        max_length=36,
        description="Cost line to commit against. Takes precedence over boq_position_id.",
    )
    sort_order: int = Field(default=0, ge=0)

    @field_validator("quantity", "unit_rate", "amount")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class POCreate(BaseModel):
    """Create a new purchase order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    vendor_contact_id: str | None = Field(default=None, max_length=36)
    po_number: str | None = Field(default=None, max_length=50)
    po_type: str = Field(default="standard", max_length=50)
    issue_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    delivery_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    # Empty by default - the service inherits the parent project's currency
    # when the caller does not supply one. Never hardcode EUR (task #217).
    currency_code: str = Field(default="", max_length=10)
    amount_subtotal: str = Field(default="0", max_length=50)
    tax_amount: str = Field(default="0", max_length=50)
    amount_total: str = Field(default="0", max_length=50)
    status: str = Field(default="draft", max_length=50)
    payment_terms: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[POItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount_subtotal", "tax_amount", "amount_total")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class InvoiceCheckLine(BaseModel):
    """One line of an invoice being checked against its order."""

    description: str = Field(default="", max_length=500)
    quantity: str = Field(default="0", max_length=50)


class InvoiceCheckRequest(BaseModel):
    """A supplier invoice, saved or not yet, to check against the order it bills.

    ``invoice_id`` names the saved invoice being edited, so its own earlier
    figures are not counted as "invoiced before".
    """

    amount_subtotal: str = Field(default="0", max_length=50)
    line_items: list[InvoiceCheckLine] = Field(default_factory=list)
    invoice_id: UUID | None = None
    invoice_number: str | None = Field(default=None, max_length=50)


class POUpdate(BaseModel):
    """Partial update for a purchase order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    vendor_contact_id: str | None = Field(default=None, max_length=36)
    po_type: str | None = Field(default=None, max_length=50)
    issue_date: str | None = Field(default=None, max_length=20)
    delivery_date: str | None = Field(default=None, max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)
    amount_subtotal: str | None = Field(default=None, max_length=50)
    tax_amount: str | None = Field(default=None, max_length=50)
    amount_total: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, max_length=50)
    payment_terms: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[POItemCreate] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("amount_subtotal", "tax_amount", "amount_total")
    @classmethod
    def _check_non_negative_decimal(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_non_negative_decimal(v)

    @field_validator("issue_date", "delivery_date")
    @classmethod
    def _check_iso_date(cls, v: str | None) -> str | None:
        """Enforce ``YYYY-MM-DD`` on dates supplied via PATCH.

        POCreate already pins this format; the update schema omitted it, so a
        malformed delivery_date (e.g. "2026/04/10") could slip in and silently
        break the supplier-scorecard on-time check, which compares the PO
        delivery_date against the receipt_date LEXICOGRAPHICALLY (only valid
        when both are zero-padded ISO dates). An empty string is left as-is
        (callers omit the field rather than clear it, but never reject a clear).
        """
        if v is None or v == "":
            return v
        if not _ISO_DATE_RE.match(v):
            raise ValueError(f"Date must be in YYYY-MM-DD format, got {v!r}")
        return v


# ── Purchase Order responses ─────────────────────────────────────────────────


class POItemResponse(BaseModel):
    """PO item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    po_id: UUID
    description: str
    quantity: str = "1"
    unit: str | None = None
    unit_rate: str = "0"
    amount: str = "0"
    wbs_id: str | None = None
    cost_category: str | None = None
    # Read back so the caller can tell a line that reached the cost spine from
    # one that did not. A position on a project whose spine has not been
    # generated resolves to null, which is a legitimate outcome rather than an
    # error, and silence about it is what let the committed report read zero
    # for as long as it did.
    cost_line_id: UUID | None = None
    # The position behind that cost line, derived rather than stored: the money
    # row holds no position column, by design. Returned because ``POItemCreate``
    # accepts a position, and a field a caller may write but never read back is
    # how an edit form loses the choice the user made. Absent for a line off the
    # bill, and for one whose cost line was generated from no position.
    boq_position_id: UUID | None = None
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class POCancelRequest(BaseModel):
    """Void a purchase order, keeping the row and its number.

    A cancellation is a fact about a commercial document, so it carries a
    reason: the PO survives with ``status="cancelled"`` and the reason stored
    beside it, and the next person to open the register can see why a number
    in the sequence buys nothing. The field is optional because a cancel that
    refused to proceed without prose would only teach people to type a full
    stop.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str | None = Field(default=None, max_length=1000)


class POResponse(BaseModel):
    """Purchase order returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    vendor_contact_id: str | None = None
    vendor_name: str | None = None
    po_number: str
    po_type: str = "standard"
    issue_date: str | None = None
    delivery_date: str | None = None
    currency_code: str = ""  # empty until set - never assume EUR (task #217)
    amount_subtotal: str = "0"
    tax_amount: str = "0"
    amount_total: str = "0"
    status: str = "draft"
    payment_terms: str | None = None
    notes: str | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    items: list[POItemResponse] = Field(default_factory=list)
    # ── Retainage (Gap F) ────────────────────────────────────────────────
    # ``retention_percent`` / ``retain_on_receipt`` are persisted columns;
    # ``retainage_amount`` / ``retainage_held`` are computed by the ORM model
    # as METHODS (``po.retainage_amount()``). With ``from_attributes`` pydantic
    # reads the bound method object, which is not a string. The before-validator
    # below collapses any callable to "0" so model_validate succeeds; the router
    # then stamps the real computed values via ``po.retainage_amount()``.
    # Decimal-as-string, always in this PO's ``currency_code``.
    retention_percent: str = "0.00"
    retain_on_receipt: bool = False
    retainage_amount: str = "0"
    retainage_held: str = "0"
    # ── Vendor prequalification gate (TOP-30 #20) ────────────────────────
    # Non-blocking warnings about the PO's vendor (e.g. a rejected/suspended
    # prequalification). A hard-blocked vendor never reaches this response -
    # the service raises 409 before the PO is written. Empty for clean or
    # ad-hoc vendors. Stamped by the router from the service gate; not a
    # persisted column.
    vendor_warnings: list[str] = Field(default_factory=list)
    # ── Invoiced against this order ──────────────────────────────────────
    # Supplier invoices linked to this order (``pending`` onwards, not
    # cancelled or credited), net of VAT, in the order's currency, so it reads
    # against ``amount_subtotal``. Computed on read, not a column.
    invoiced_net: str = "0"
    invoice_count: int = 0
    created_at: datetime
    updated_at: datetime

    @field_validator("retention_percent", mode="before")
    @classmethod
    def _coerce_retention_percent(cls, v: Any) -> str:
        """Numeric(5,2) arrives as a Decimal from the ORM - render as string."""
        if v is None:
            return "0.00"
        return str(v)

    @field_validator("retainage_amount", "retainage_held", mode="before")
    @classmethod
    def _coerce_retainage(cls, v: Any) -> str:
        """These are ORM *methods*, not columns. ``from_attributes`` hands us
        the bound method object - collapse any callable (or None) to "0"; the
        router stamps the real computed value after validation."""
        if v is None or callable(v):
            return "0"
        return str(v)


class PORetainageReleaseResponse(BaseModel):
    """A single retainage-release audit-log entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    po_id: UUID
    release_date: str
    release_amount: str
    release_reason: str | None = None
    released_by_id: UUID | None = None
    created_at: datetime

    @field_validator("release_amount", mode="before")
    @classmethod
    def _coerce_release_amount(cls, v: Any) -> str:
        """Numeric(18,4) arrives as a Decimal from the ORM - render as string."""
        if v is None:
            return "0"
        return str(v)


class PORetainageReleaseRequest(BaseModel):
    """Request body for releasing withheld retainage on a PO."""

    model_config = ConfigDict(str_strip_whitespace=True)

    amount: str = Field(..., max_length=50)
    reason: str | None = Field(default=None, max_length=255)

    @field_validator("amount")
    @classmethod
    def _check_positive_decimal(cls, v: str) -> str:
        """A release must be a strictly positive decimal amount."""
        try:
            d = Decimal(v)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"Invalid decimal value: {v!r}") from exc
        if d <= 0:
            raise ValueError(f"Release amount must be positive, got {v!r}")
        return v


class PORetainageReleaseListResponse(BaseModel):
    """Paginated list of retainage-release records for a PO.

    ``offset`` / ``limit`` echo the pagination window the caller requested so
    the envelope matches :class:`POListResponse`. They default (additive) so
    existing constructions that pass only ``items`` / ``total`` still validate.
    """

    items: list[PORetainageReleaseResponse]
    total: int
    offset: int = 0
    limit: int = 100


class POInvoiceCreatedResponse(BaseModel):
    """Result of converting a PO into a draft payable invoice.

    Returned by ``POST /{po_id}/create-invoice/``. The endpoint previously
    returned an untyped ``dict`` whose ``amount_total`` carried the ORM
    ``Decimal`` straight onto the wire, which FastAPI's ``jsonable_encoder``
    renders as a JSON *number* - violating the Decimal-as-string money
    contract every other money field on this API follows. Pinning the
    response shape here also makes the endpoint appear in the OpenAPI schema.
    Field names are unchanged, so existing consumers are unaffected.
    """

    invoice_id: UUID
    invoice_number: str
    po_id: UUID
    po_number: str
    # Decimal-as-string, in the PO's own currency - never a float.
    amount_total: str = "0"

    @field_validator("amount_total", mode="before")
    @classmethod
    def _coerce_amount_total(cls, v: Any) -> str:
        """The ORM hands us a ``Decimal`` - render it as a canonical string."""
        if v is None:
            return "0"
        return str(v)


class POListResponse(BaseModel):
    """Paginated list of purchase orders."""

    items: list[POResponse]
    total: int
    offset: int
    limit: int


# ── Goods Receipt ────────────────────────────────────────────────────────────


class GRItemCreate(BaseModel):
    """Create a goods receipt line item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    po_item_id: UUID | None = None
    quantity_ordered: str = Field(default="0", max_length=50)
    quantity_received: str = Field(default="0", max_length=50)
    quantity_rejected: str = Field(default="0", max_length=50)
    rejection_reason: str | None = None

    @field_validator("quantity_ordered", "quantity_received", "quantity_rejected")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class GRCreate(BaseModel):
    """Create a goods receipt against a PO."""

    model_config = ConfigDict(str_strip_whitespace=True)

    po_id: UUID
    receipt_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    received_by_id: UUID | None = None
    delivery_note_number: str | None = Field(default=None, max_length=100)
    status: str = Field(default="draft", max_length=50)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[GRItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Goods Receipt responses ──────────────────────────────────────────────────


class GRItemResponse(BaseModel):
    """GR item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    receipt_id: UUID
    po_item_id: UUID | None = None
    quantity_ordered: str = "0"
    quantity_received: str = "0"
    quantity_rejected: str = "0"
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class GRResponse(BaseModel):
    """Goods receipt returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    po_id: UUID
    receipt_date: str
    received_by_id: UUID | None = None
    delivery_note_number: str | None = None
    status: str = "draft"
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    items: list[GRItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    # api-HIGH (GR tab): the frontend Goods-Receipts table renders these
    # fields, but they were missing from the response and rendered blank.
    # All ADDITIVE + OPTIONAL - existing consumers are unaffected.
    #   * gr_reference   - friendly label, aliased from delivery_note_number
    #   * po_number      - parent PO number (populated by the router/service)
    #   * received_qty   - Σ items[].quantity_received  (Decimal-as-string)
    #   * ordered_qty    - Σ items[].quantity_ordered   (Decimal-as-string)
    #   * description    - passthrough notes/summary for the row
    gr_reference: str | None = Field(
        default=None,
        # ``delivery_note_number`` is the natural reference shown to the user;
        # populate gr_reference from it when serialising from the ORM model.
        validation_alias="delivery_note_number",
    )
    po_number: str | None = None
    # Decimal quantities MUST serialise as STRING (never float) - mirrors
    # quantity_received / quantity_ordered on GRItemResponse.
    received_qty: str | None = None
    ordered_qty: str | None = None
    description: str | None = Field(default=None, validation_alias="notes")

    @model_validator(mode="after")
    def _aggregate_item_quantities(self) -> "GRResponse":
        """Aggregate received_qty / ordered_qty from the GR line items.

        api-HIGH (GR tab): the FE shows per-receipt received vs ordered
        totals. We sum the already-serialised string quantities on
        ``items`` so the aggregate is computed from exactly what the API
        returns. Both totals are emitted as canonical Decimal STRINGS
        (never floats). Only fills the aggregates when they were not set
        explicitly, so it stays purely additive.
        """
        if self.received_qty is None or self.ordered_qty is None:
            received = Decimal("0")
            ordered = Decimal("0")
            for item in self.items:
                try:
                    received += Decimal(item.quantity_received or "0")
                except (InvalidOperation, ValueError, TypeError):
                    pass
                try:
                    ordered += Decimal(item.quantity_ordered or "0")
                except (InvalidOperation, ValueError, TypeError):
                    pass
            if self.received_qty is None:
                self.received_qty = format(received, "f")
            if self.ordered_qty is None:
                self.ordered_qty = format(ordered, "f")
        return self


class GRListResponse(BaseModel):
    """Paginated list of goods receipts.

    ``offset`` / ``limit`` echo the requested pagination window so the envelope
    matches :class:`POListResponse`. Both default (additive) so existing
    constructions that pass only ``items`` / ``total`` keep validating.
    """

    items: list[GRResponse]
    total: int
    offset: int = 0
    limit: int = 50


# ── Stats ────────────────────────────────────────────────────────────────


class ProcurementStatsResponse(BaseModel):
    """Aggregate statistics for procurement within a project."""

    total_pos: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    total_committed: str = "0"
    total_received: int = 0
    pending_delivery_count: int = 0


# ── 3-way match status (Wave 2 / T4) ─────────────────────────────────────


# The closed set of 3-way-match tags the service emits (see
# ``ProcurementService._classify_line_match`` + the overall-precedence rollup).
# Pinning it here validates the response and keeps the wire contract in lock-step
# with the frontend ``POLineMatchTag`` union in ``features/procurement/api.ts``.
POLineMatchTag = Literal[
    "ok",
    "partial",
    "unmatched",
    "over_received",
    "over_invoiced",
]


class POLineMatchStatus(BaseModel):
    """Per-PO-line 3-way match summary.

    ``match_status`` collapses the PO/GR/Invoice quantity comparison into
    one tag the UI badge consumes:

    * ``ok``             - invoiced and received quantities cover the order.
    * ``partial``        - some quantity received or invoiced, more pending.
    * ``unmatched``      - nothing received or invoiced yet.
    * ``over_received``  - confirmed GR quantity exceeds the PO line.
    * ``over_invoiced``  - invoiced quantity exceeds received quantity.
    """

    model_config = ConfigDict(from_attributes=True)

    line_id: UUID
    description: str
    ordered_qty: str = "0"
    received_qty: str = "0"
    invoiced_qty: str = "0"
    match_status: POLineMatchTag = "unmatched"


class POMatchStatusResponse(BaseModel):
    """Aggregate 3-way match envelope for a single PO."""

    po_id: UUID
    po_number: str
    overall_status: POLineMatchTag = "unmatched"
    lines: list[POLineMatchStatus] = Field(default_factory=list)


# ── Supplier scorecard (Wave 2 / T4) ─────────────────────────────────────


class SupplierScorecardResponse(BaseModel):
    """Trailing-window supplier performance KPIs.

    ``on_time_delivery_pct`` / ``qty_variance_pct`` / ``gr_rejection_rate``
    are decimals in 0.0-1.0 (frontend renders as ``x 100`` percentages).
    ``total_po_value`` is summed across the trailing window in the supplier
    or project currency, returned as a string-Decimal for compatibility
    with the PO ``amount_total`` model field.
    """

    model_config = ConfigDict(from_attributes=True)

    supplier_contact_id: str
    supplier_name: str | None = None
    project_id: UUID | None = None
    period_days: int = 365
    total_po_count: int = 0
    total_po_value: str = "0"
    currency: str = ""
    # True when the supplier's POs in this window span more than one currency
    # (cross-project overview). ``total_po_value`` then reports the dominant
    # currency's total only - figures are never blended across currencies.
    mixed_currency: bool = False
    on_time_delivery_pct: float = 0.0
    qty_variance_pct: float = 0.0
    gr_rejection_rate: float = 0.0
    total_gr_count: int = 0
    # Number of GRs counted as on-time (numerator of on_time_delivery_pct).
    on_time_count: int = 0
    # GRs whose parent PO had no delivery_date - excluded from on-time
    # denominator so unscheduled POs do not inflate the score (P0-2).
    unscheduled_count: int = 0


# -- Supplier delivery performance / OTIF (project view) --------------------


class SupplierDeliveryPerformance(BaseModel):
    """On-time-in-full KPIs for one supplier, or the project-wide rollup.

    Rates are 0.0-1.0 Decimals rendered as STRINGS (never floats), or null when
    their denominator is zero (no receipts to measure) so the UI can tell "no
    data" apart from a real zero. ``on_time_rate`` / ``otif_rate`` are measured
    over the SCHEDULED receipts (those whose PO carries a promised date);
    ``in_full_rate`` is measured over ALL receipts. ``avg_days_late`` is a
    Decimal-string number of days averaged over only the late receipts, or null
    when none were late. Counts are plain integers. ``supplier_contact_id`` is
    null on the overall rollup row.
    """

    model_config = ConfigDict(from_attributes=True)

    supplier_contact_id: str | None = None
    supplier_name: str | None = None
    total_receipts: int = 0
    scheduled_receipts: int = 0
    unscheduled_receipts: int = 0
    on_time_count: int = 0
    late_count: int = 0
    in_full_count: int = 0
    otif_count: int = 0
    on_time_rate: str | None = None
    in_full_rate: str | None = None
    otif_rate: str | None = None
    avg_days_late: str | None = None


class ProjectDeliveryPerformanceResponse(BaseModel):
    """Project OTIF delivery-performance view: an overall rollup plus one row
    per supplier, computed from stored PO promised dates and confirmed goods
    receipts."""

    project_id: UUID
    overall: SupplierDeliveryPerformance
    suppliers: list[SupplierDeliveryPerformance] = Field(default_factory=list)


# -- Committed vs remaining by BOQ position ---------------------------------


class CommittedByPositionRow(BaseModel):
    """What one BOQ position has been ordered against, across every PO.

    ``boq_position_id`` is the position the money rolls up to. It falls back
    to the cost line's own id for a line whose cost line names no position,
    which is the ordinary state of a project whose spine was generated before
    the bill was finished; the field is therefore an id of one kind or the
    other and is carried as text rather than as a ``UUID``.

    Both amounts are Decimal-as-string, like every other money field on this
    API. ``committed_qty`` is a quantity rather than money but travels the
    same way, because it is summed from the same Decimal columns and a float
    would round it.
    """

    boq_position_id: str
    committed_qty: str
    committed_value: str


class CommittedByPositionListResponse(BaseModel):
    """A page of the committed-by-position rollup, and its full size.

    ``total`` is the number of positions the project has commitments against,
    not the number on the page. A buyer comparing committed quantities with
    the bill is deciding what still has to be bought, and a page that could
    not say it was a page would have them order against scope that is already
    on order.

    ``offset`` / ``limit`` default to the window the route applies, matching
    :class:`PORetainageReleaseListResponse`.
    """

    items: list[CommittedByPositionRow]
    total: int
    offset: int = 0
    limit: int = 100
