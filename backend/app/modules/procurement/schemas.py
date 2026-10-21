# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement Pydantic schemas - request/response models."""

import re
from datetime import date, datetime
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


def _validate_tolerance_pct(v: str | None) -> str | None:
    """An invoice allowance as a percentage of the order: 0 to 100, or unset."""
    if v is None or v == "":
        return None
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid percentage: {v!r}") from exc
    if not d.is_finite() or d < 0 or d > 100:
        raise ValueError(f"Percentage must be between 0 and 100, got {v!r}")
    return v


def _validate_tolerance_abs(v: str | None) -> str | None:
    """An invoice allowance as an amount in the order's currency, or unset."""
    if v is None or v == "":
        return None
    _validate_non_negative_decimal(v)
    if not Decimal(v).is_finite():
        raise ValueError(f"Invalid amount: {v!r}")
    return v


def _validate_tax_rate_pct(v: str | None) -> str | None:
    """A VAT rate as a percentage: 0 to 100, or unset. Empty clears it."""
    if v is None or v == "":
        return None
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid VAT rate: {v!r}") from exc
    if not d.is_finite() or d < 0 or d > 100:
        raise ValueError(f"VAT rate must be between 0 and 100, got {v!r}")
    return v


def _validate_certificate_type(v: str | None) -> str | None:
    """A certificate type code from the catalogue, or unset. Empty clears it."""
    if v is None or not str(v).strip():
        return None
    from app.modules.procurement.certificates import is_known_type

    code = str(v).strip()
    if not is_known_type(code):
        raise ValueError(f"Unknown certificate type: {code!r}")
    return code


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
    # Issue #516: the requisition line this order line was converted from.
    # Only the conversion writes it on a new order; a PATCH that replaces the
    # lines of an order sends it back so the link survives the edit, and the
    # service refuses a link to a requisition that was not converted into
    # this order.
    requisition_item_id: UUID | None = Field(
        default=None,
        description="Requisition line this order line came from. Set by the requisition conversion.",
    )
    sort_order: int = Field(default=0, ge=0)
    # Receiving requirements: the certificate the delivery must carry (a code
    # from the certificate-type catalogue) and whether the site inspects it.
    required_certificate_type: str | None = Field(default=None, max_length=40)
    requires_inspection: bool = False

    @field_validator("quantity", "unit_rate", "amount")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)

    @field_validator("required_certificate_type")
    @classmethod
    def _check_certificate_type(cls, v: str | None) -> str | None:
        return _validate_certificate_type(v)


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
    # The VAT rate in percent. Stated, it drives ``tax_amount`` from the
    # subtotal. Left out with no ``tax_amount`` either, the project's default
    # VAT rate is used. Left out with a ``tax_amount``, that absolute tax is
    # kept and the order carries no rate (issue #515).
    tax_rate_pct: str | None = Field(default=None, max_length=20)
    status: str = Field(default="draft", max_length=50)
    payment_terms: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[POItemCreate] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # How far a supplier invoice may run past this order before the match
    # warns: a percentage, an amount in the order's currency, or both (the
    # smaller band wins). Unset keeps the one-cent rounding band.
    invoice_tolerance_pct: str | None = Field(default=None, max_length=20)
    invoice_tolerance_abs: str | None = Field(default=None, max_length=50)

    @field_validator("amount_subtotal", "tax_amount", "amount_total")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)

    @field_validator("invoice_tolerance_pct")
    @classmethod
    def _check_tolerance_pct(cls, v: str | None) -> str | None:
        return _validate_tolerance_pct(v)

    @field_validator("tax_rate_pct")
    @classmethod
    def _check_tax_rate_pct(cls, v: str | None) -> str | None:
        return _validate_tax_rate_pct(v)

    @field_validator("invoice_tolerance_abs")
    @classmethod
    def _check_tolerance_abs(cls, v: str | None) -> str | None:
        return _validate_tolerance_abs(v)


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
    # A rate re-derives the tax from the subtotal; an empty string or null
    # drops it, after which ``tax_amount`` is absolute again.
    tax_rate_pct: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=50)
    payment_terms: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=5000)
    items: list[POItemCreate] | None = None
    metadata: dict[str, Any] | None = None
    # How far a supplier invoice may run past this order before the match
    # warns: a percentage, an amount in the order's currency, or both (the
    # smaller band wins). Unset keeps the one-cent rounding band.
    invoice_tolerance_pct: str | None = Field(default=None, max_length=20)
    invoice_tolerance_abs: str | None = Field(default=None, max_length=50)

    @field_validator("amount_subtotal", "tax_amount", "amount_total")
    @classmethod
    def _check_non_negative_decimal(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_non_negative_decimal(v)

    @field_validator("invoice_tolerance_pct")
    @classmethod
    def _check_tolerance_pct(cls, v: str | None) -> str | None:
        return _validate_tolerance_pct(v)

    @field_validator("tax_rate_pct")
    @classmethod
    def _check_tax_rate_pct(cls, v: str | None) -> str | None:
        return _validate_tax_rate_pct(v)

    @field_validator("invoice_tolerance_abs")
    @classmethod
    def _check_tolerance_abs(cls, v: str | None) -> str | None:
        return _validate_tolerance_abs(v)

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
    # Issue #516: the requisition line this order line was converted from.
    requisition_item_id: UUID | None = None
    sort_order: int = 0
    required_certificate_type: str | None = None
    requires_inspection: bool = False
    created_at: datetime
    updated_at: datetime


class POItemRequirementsUpdate(BaseModel):
    """Change what the delivery of one order line must arrive with.

    A quality requirement, not a commitment figure: it moves no money, so it
    may be corrected after approval while the line is still being delivered.
    Fields left out stay as they are.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    required_certificate_type: str | None = Field(default=None, max_length=40)
    requires_inspection: bool | None = None

    @field_validator("required_certificate_type")
    @classmethod
    def _check_certificate_type(cls, v: str | None) -> str | None:
        return _validate_certificate_type(v)


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


class POAcknowledgeRequest(BaseModel):
    """The supplier's confirmation of an issued order, as the buyer received it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    supplier_reference: str | None = Field(default=None, max_length=100)
    confirmed_delivery_date: date | None = None


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
    tax_rate_pct: str | None = None
    status: str = "draft"
    supplier_acknowledged_at: str | None = None
    supplier_acknowledged_by: str | None = None
    supplier_reference: str | None = None
    supplier_confirmed_delivery_date: str | None = None
    invoice_tolerance_pct: str | None = None
    invoice_tolerance_abs: str | None = None
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


class GRCertificateCreate(BaseModel):
    """A material certificate delivered with one receipt line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    certificate_type: str = Field(..., min_length=1, max_length=40)
    certificate_number: str = Field(default="", max_length=100)
    issuer: str | None = Field(default=None, max_length=255)
    issue_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", max_length=20)
    document_id: UUID | None = None
    batch_number: str | None = Field(default=None, max_length=100)

    @field_validator("certificate_type")
    @classmethod
    def _check_certificate_type(cls, v: str) -> str:
        code = _validate_certificate_type(v)
        if code is None:
            raise ValueError("certificate_type is required")
        return code


class GRCertificateAdd(GRCertificateCreate):
    """Add a certificate to one line of a draft goods receipt."""

    gr_item_id: UUID


class GRCertificateResponse(BaseModel):
    """A material certificate as stored on a receipt line."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    receipt_id: UUID
    gr_item_id: UUID
    certificate_type: str
    certificate_number: str = ""
    issuer: str | None = None
    issue_date: str | None = None
    document_id: UUID | None = None
    batch_number: str | None = None
    source: str = "site"
    created_at: datetime


class CertificateTypeResponse(BaseModel):
    """One entry of the certificate-type catalogue."""

    code: str
    family: str
    rank: int
    label: str
    standard: str = ""
    designation: str = ""
    specific_inspection: bool = False
    validated_by: str = ""


class GRItemCreate(BaseModel):
    """Create a goods receipt line item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    po_item_id: UUID | None = None
    quantity_ordered: str = Field(default="0", max_length=50)
    quantity_received: str = Field(default="0", max_length=50)
    quantity_rejected: str = Field(default="0", max_length=50)
    rejection_reason: str | None = None
    batch_lot: str | None = Field(default=None, max_length=100)
    serial_numbers: list[str] | None = Field(default=None, max_length=10000)
    certificates: list[GRCertificateCreate] = Field(default_factory=list, max_length=50)

    @field_validator("quantity_ordered", "quantity_received", "quantity_rejected")
    @classmethod
    def _check_non_negative_decimal(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)

    @model_validator(mode="after")
    def _serials_fit_the_received_quantity(self) -> "GRItemCreate":
        """Serial numbers are unique, non-empty and no more than the units received."""
        if not self.serial_numbers:
            return self
        cleaned = [s.strip() for s in self.serial_numbers]
        if any(not s or len(s) > 100 for s in cleaned):
            raise ValueError("serial numbers must be non-empty and at most 100 characters")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("serial numbers on one receipt line must be unique")
        if Decimal(len(cleaned)) > Decimal(self.quantity_received):
            raise ValueError("more serial numbers than units received on this line")
        self.serial_numbers = cleaned
        return self


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
    batch_lot: str | None = None
    serial_numbers: list[str] | None = None
    certificates: list[GRCertificateResponse] = Field(default_factory=list)
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
    # ``site`` or ``supplier_portal``; the portal account behind a supplier submission.
    source: str = "site"
    portal_user_id: UUID | None = None
    # Follow-ups started when the receipt was confirmed.
    approval_instance_id: UUID | None = None
    inspection_id: UUID | None = None
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


class GRConfirmRequest(BaseModel):
    """What the person confirming a receipt chooses to start with it.

    Nothing starts on its own: the confirm dialog shows the configured route and
    whether an inspection is due, and the person confirming ticks each box.
    ``approval_route_id`` picks among several routes; with exactly one route
    configured for goods receipts on the project it may be left out.
    """

    start_approval_route: bool = False
    approval_route_id: UUID | None = None
    create_inspection: bool = False


class GRRouteOption(BaseModel):
    """An approval route the project has configured for goods receipts."""

    id: UUID
    name: str


class GRReadinessLine(BaseModel):
    """One delivered line as the confirm dialog shows it: what it needs and what it brought."""

    gr_item_id: UUID
    label: str
    unit: str = ""
    quantity_received: str = "0"
    batch_lot: str | None = None
    required_certificate_type: str | None = None
    requires_inspection: bool = False
    certificates: list[GRCertificateResponse] = Field(default_factory=list)


class GRReadinessResponse(BaseModel):
    """What confirming a draft receipt would run into, read without changing it."""

    gr_id: UUID
    status: str
    validation: dict[str, Any]
    can_confirm: bool
    approval_routes: list[GRRouteOption] = Field(default_factory=list)
    inspection_due: bool = False
    inspection_lines: list[str] = Field(default_factory=list)
    lines: list[GRReadinessLine] = Field(default_factory=list)


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
    # ── Is the supplier still qualified to buy from ─────────────────────
    # From the contact (prequalification and its end date) and from the same
    # vendor gate the order write path runs, so the card and the gate never
    # disagree. ``qualification_state``: expired / expiring (30 days) /
    # valid / not_stated. Empty when the caller sees none of its orders.
    prequalification_status: str | None = None
    qualified_until: str | None = None
    qualification_state: str = "not_stated"
    compliance_reasons: list[str] = Field(default_factory=list)
    # Issued orders still waiting for the supplier's confirmation.
    unconfirmed_po_count: int = 0


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


# ── Material requisitions ───────────────────────────────────────────────────


#: Every status the requisition FSM in ``service._MR_STATUS_TRANSITIONS`` knows.
RequisitionStatus = Literal[
    "draft", "submitted", "approved", "ordered", "received", "consumed", "rejected", "cancelled"
]


class RequisitionItemSourceIn(BaseModel):
    """One BOQ resource contributing quantity to a requisition line.

    ``quantity`` and ``unit`` are the figures at the source. They are kept as
    sent, so a line whose unit differs from its source is reported by the
    ``procurement_requisition`` rules instead of being silently converted.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID | None = None
    resource_key: str | None = Field(default=None, max_length=200)
    quantity: str = Field(default="0", max_length=50)
    unit: str | None = Field(default=None, max_length=20)
    cost_line_id: UUID | None = None
    # The supplier the BOQ suggested for this source. Left out, the server reads
    # it from the BOQ resource (or its position default); sent, it is kept as
    # sent so an edited draft does not re-read a BOQ that has changed since.
    suggested_vendor_id: UUID | None = None

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class RequisitionItemIn(BaseModel):
    """A requisition line as written by the client.

    A draft may hold a zero quantity while it is being filled in; submission is
    where the ``procurement_requisition`` rules refuse it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=20)
    quantity_requested: str = Field(default="0", max_length=50)
    unit_cost: str = Field(default="0", max_length=50)
    currency_code: str = Field(default="", max_length=10)
    catalog_item_id: UUID | None = None
    cost_line_id: UUID | None = None
    boq_position_id: UUID | None = None
    # The supplier suggested for this line. Left out, the line inherits the one
    # its sources agree on; sent (null included), it is the requester's choice.
    suggested_vendor_id: UUID | None = None
    # When this line is needed. Left out or null, the requisition's
    # ``required_date`` applies. With ``schedule_activity_id`` and no date, the
    # server proposes the activity start minus ``schedule_buffer_days``.
    required_date: date | None = None
    schedule_activity_id: UUID | None = None
    schedule_buffer_days: int | None = Field(default=None, ge=0, le=365)
    # The activity start the date was proposed from, echoed back by the editor
    # so a saved draft keeps it. Left out, the activity's start now is used.
    schedule_anchor_date: date | None = None
    # Why the line goes over the BOQ demand, when it does. Acknowledges the
    # ``procurement.requisition_over_allocated`` warning; never required.
    over_allocation_reason: str | None = Field(default=None, max_length=1000)
    sources: list[RequisitionItemSourceIn] = Field(default_factory=list, max_length=1000)

    @field_validator("quantity_requested", "unit_cost")
    @classmethod
    def _check_non_negative(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class RequisitionCreate(BaseModel):
    """Create a material requisition in ``draft``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str | None = Field(default=None, max_length=500)
    required_date: date | None = None
    lead_time_days: int = Field(default=0, ge=0, le=3650)
    notes: str | None = Field(default=None, max_length=5000)
    # The supplier from the Vendor directory, when the requester already knows it.
    vendor_id: UUID | None = None
    items: list[RequisitionItemIn] = Field(default_factory=list, max_length=1000)
    # Where the orders are placed. Left out, the project's setting applies.
    order_owner: Literal["ocerp", "external"] | None = None
    # Designated approvers in order. Left out, the project's default applies;
    # an empty list means any holder of the approval permission decides alone.
    approval_chain: list[UUID] | None = Field(default=None, max_length=10)
    # Makes the create idempotent: a second create in the project with the same
    # key answers with the requisition the first one made.
    client_request_id: str | None = Field(default=None, min_length=1, max_length=100)


class RequisitionUpdate(BaseModel):
    """Edit a draft requisition. Fields left out are left alone.

    ``items``, when sent, replaces the whole set of lines: the client edits the
    draft as one document, and a partial line merge would have to guess which
    line a source belongs to.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    required_date: date | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    notes: str | None = Field(default=None, max_length=5000)
    # Sent as null, clears the supplier; left out, keeps it.
    vendor_id: UUID | None = None
    items: list[RequisitionItemIn] | None = Field(default=None, max_length=1000)
    order_owner: Literal["ocerp", "external"] | None = None
    # Sent (an empty list included), replaces the designated approvers.
    approval_chain: list[UUID] | None = Field(default=None, max_length=10)


class RequisitionCancel(BaseModel):
    """Optional reason recorded when a requisition is cancelled."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str | None = Field(default=None, max_length=2000)


class RequisitionApprove(BaseModel):
    """An approval, with an optional note from the approver."""

    model_config = ConfigDict(str_strip_whitespace=True)

    comment: str | None = Field(default=None, max_length=2000)


class RequisitionReject(BaseModel):
    """A rejection. The reason is required: the requester has to know what to change."""

    model_config = ConfigDict(str_strip_whitespace=True)

    comment: str = Field(..., min_length=1, max_length=2000)


class RequisitionConvertLine(BaseModel):
    """How much of one requisition line goes on the order, in the line's unit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    requisition_item_id: UUID
    quantity: str = Field(..., max_length=50)

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class RequisitionConvert(BaseModel):
    """Turn approved requisitions of one project into one draft purchase order.

    ``vendor_id`` names the supplier from the Vendor directory. Left out, the
    supplier the requisitions agree on is used; requisitions naming different
    suppliers cannot share an order.

    ``lines`` orders part of the requisitions: each named line with the given
    quantity, nothing else. Left out, every line is ordered with what is still
    to order. ``idempotency_key`` makes a retry safe: a second conversion with
    the same key in the project answers with the order the first one made.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    requisition_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    vendor_id: UUID | None = None
    delivery_date: date | None = None
    notes: str | None = Field(default=None, max_length=5000)
    lines: list[RequisitionConvertLine] | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=100)


class RequisitionConvertResponse(BaseModel):
    """The draft purchase order a conversion created."""

    po_id: UUID
    po_number: str
    project_id: UUID
    requisition_ids: list[UUID]
    line_count: int
    vendor_warnings: list[str] = Field(default_factory=list)
    # True when the idempotency key matched an earlier conversion and nothing new was written.
    replayed: bool = False
    # Requisitions that are now fully ordered; the others still have quantity to order.
    fully_ordered_requisition_ids: list[UUID] = Field(default_factory=list)


class RequisitionPOItemRef(BaseModel):
    """One purchase order line that came from a requisition line."""

    po_item_id: UUID
    po_id: UUID
    po_number: str | None = None
    po_status: str | None = None
    quantity: str = "0"
    unit: str | None = None
    # The supplier's dates, kept apart from the date the material is needed.
    po_delivery_date: str | None = None
    supplier_confirmed_delivery_date: str | None = None
    # Received on confirmed goods receipts for this order line, in the order line's unit.
    quantity_received: str = "0"
    # True when the order line's unit cannot be restated in the requisition line's unit;
    # such a line is shown but not counted.
    unit_mismatch: bool = False


class RequisitionExternalLineResponse(BaseModel):
    """An external order line reported against a requisition line."""

    id: UUID
    external_system: str
    external_order_number: str
    external_line_ref: str = ""
    status: str
    quantity_ordered: str = "0"
    quantity_received: str = "0"
    unit: str | None = None
    expected_delivery_date: str | None = None
    confirmed_delivery_date: str | None = None
    unit_mismatch: bool = False
    updated_at: datetime | None = None


class RequisitionItemSourceResponse(BaseModel):
    """A stored BOQ source of a requisition line."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    boq_position_id: UUID | None = None
    resource_key: str | None = None
    quantity: str = "0"
    unit: str | None = None
    cost_line_id: UUID | None = None
    suggested_vendor_id: UUID | None = None
    suggested_vendor_name: str | None = None


class RequisitionCoverageSource(BaseModel):
    """How much of one BOQ resource the active requisitions hold, in one unit."""

    boq_position_id: UUID
    resource_key: str
    unit: str
    covered_quantity: str = "0"


class RequisitionCoverageResponse(BaseModel):
    """What submitted, approved and later requisitions hold per BOQ resource.

    Drafts, withdrawn, rejected and cancelled requisitions hold nothing. A
    resource held in two units appears as two rows: they are never added.
    """

    project_id: UUID
    sources: list[RequisitionCoverageSource] = Field(default_factory=list)


class RequisitionVendorRef(BaseModel):
    """A Vendor directory entry as a requisition shows it."""

    id: UUID
    name: str | None = None
    status: str | None = None


class RequisitionItemResponse(BaseModel):
    """A requisition line with its purchasing progress.

    ``quantity_outstanding`` is requested minus received and is not clamped: a
    negative figure means more arrived than was asked for, which a buyer needs
    to see rather than have rounded away to zero.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    unit: str | None = None
    quantity_requested: str = "0"
    quantity_ordered: str = "0"
    quantity_received: str = "0"
    quantity_consumed: str = "0"
    quantity_outstanding: str = "0"
    unit_cost: Decimal = Decimal("0")
    extended_cost: Decimal = Decimal("0")
    currency_code: str = ""
    catalog_item_id: UUID | None = None
    cost_line_id: UUID | None = None
    sort_order: int = 0
    # Suggested supplier (issue #516). ``source_suggested_vendors`` lists every
    # distinct supplier the BOQ sources suggested; more than one means they
    # disagree, which ``suggestion_conflict`` states outright.
    suggested_vendor_id: UUID | None = None
    suggested_vendor_name: str | None = None
    suggested_vendor_status: str | None = None
    source_suggested_vendors: list[RequisitionVendorRef] = Field(default_factory=list)
    suggestion_conflict: bool = False
    # Needed-by date. ``effective_required_date`` is the line's own date or the
    # header's; ``required_date_source`` says which (``line``, ``schedule``,
    # ``requisition``) or is null when neither is set. ``latest_order_date`` is
    # the effective date minus the requisition's lead time.
    required_date: str | None = None
    effective_required_date: str | None = None
    required_date_source: str | None = None
    latest_order_date: str | None = None
    schedule_activity_id: UUID | None = None
    schedule_activity_name: str | None = None
    schedule_buffer_days: int | None = None
    schedule_anchor_date: str | None = None
    # The activity start as the schedule holds it now, and whether it moved
    # since the date was proposed. The line's date is never rewritten for it.
    schedule_activity_start: str | None = None
    schedule_moved: bool = False
    over_allocation_reason: str | None = None
    sources: list[RequisitionItemSourceResponse] = Field(default_factory=list)
    # The purchase order lines converted from this line (issue #516).
    po_items: list[RequisitionPOItemRef] = Field(default_factory=list)
    # Order lines placed in an external purchasing system for this line.
    external_orders: list[RequisitionExternalLineResponse] = Field(default_factory=list)
    # Requested minus ordered, never below zero: what can still go on an order.
    quantity_to_order: str = "0"
    # More was ordered than requested on live orders.
    over_ordered: bool = False


class RequisitionOrderRef(BaseModel):
    """A purchase order that holds lines of a requisition."""

    po_id: UUID
    po_number: str | None = None
    status: str | None = None


class RequisitionApprovalStep(BaseModel):
    """One designated approver and where they stand in the current round.

    ``state`` is ``approved`` (done this round), ``next`` (the only one who may
    decide now) or ``waiting``.
    """

    user_id: str
    name: str | None = None
    state: str
    decided_at: str | None = None
    comment: str | None = None


class RequisitionResponse(BaseModel):
    """A material requisition with its lines and quantity reconciliation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    req_number: str | None = None
    status: str
    title: str | None = None
    required_date: str | None = None
    lead_time_days: int = 0
    # The last day to order and still arrive by ``required_date``.
    latest_order_date: str | None = None
    # The delivery date of the order this requisition became; null before.
    estimated_delivery_date: str | None = None
    requester_id: str | None = None
    approver_id: str | None = None
    approver_name: str | None = None
    submitted_by: str | None = None
    decided_at: str | None = None
    decision_comment: str | None = None
    vendor_id: UUID | None = None
    vendor_name: str | None = None
    vendor_status: str | None = None
    # Distinct suppliers the lines suggest. Never applied to ``vendor_id`` on
    # its own: with one entry the requester may adopt it, with several the
    # suppliers differ and a person decides.
    suggested_vendors: list[RequisitionVendorRef] = Field(default_factory=list)
    po_id: UUID | None = None
    po_number: str | None = None
    notes: str | None = None
    # ``ocerp`` or ``external``: where the orders for this requisition are placed.
    order_owner: str = "ocerp"
    # ``none``, ``partial`` or ``full``: how much of the requested quantity is on live orders.
    order_progress: str = "none"
    # Every order with at least one line from this requisition, cancelled ones included.
    purchase_orders: list[RequisitionOrderRef] = Field(default_factory=list)
    # Designated approvers in order with where each stands; empty means one approval by
    # any holder of ``procurement.approve_requisition``.
    approval_chain: list[RequisitionApprovalStep] = Field(default_factory=list)
    approval_step: int = 0
    next_approver_id: str | None = None
    row_version: int = 0
    client_request_id: str | None = None
    items: list[RequisitionItemResponse] = Field(default_factory=list)
    reconciliation: dict[str, str] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RequisitionListResponse(BaseModel):
    """One page of requisitions."""

    items: list[RequisitionResponse]
    total: int
    offset: int
    limit: int


class RequisitionValidationResponse(BaseModel):
    """The ``procurement_requisition`` rule set run against one requisition."""

    status: str
    score: float | None = None
    counts: dict[str, Any] = Field(default_factory=dict)
    results: list[dict[str, Any]] = Field(default_factory=list)


# ── Requisition traceability (issue #516) ───────────────────────────────────


class TracePOLine(BaseModel):
    """A purchase order line reached from a requisition line."""

    po_id: UUID
    po_number: str | None = None
    po_status: str | None = None
    po_item_id: UUID
    quantity: str = "0"
    unit: str | None = None
    po_delivery_date: str | None = None
    supplier_confirmed_delivery_date: str | None = None


class PositionTraceRow(BaseModel):
    """One requisition line fed by a BOQ position, and the order lines it became."""

    requisition_id: UUID
    req_number: str | None = None
    requisition_status: str
    requisition_item_id: UUID
    description: str
    line_unit: str | None = None
    quantity_requested: str = "0"
    quantity_ordered: str = "0"
    resource_key: str | None = None
    source_quantity: str = "0"
    source_unit: str | None = None
    purchase_orders: list[TracePOLine] = Field(default_factory=list)


class PositionTraceResponse(BaseModel):
    """Everything procurement holds against one BOQ position."""

    boq_position_id: UUID
    items: list[PositionTraceRow] = Field(default_factory=list)


class TraceSource(BaseModel):
    """A BOQ source behind an order line, read through its requisition line."""

    boq_position_id: UUID | None = None
    # The position as the bill shows it now, so a reader sees "1.2 Wall"
    # rather than an id. Null when the position has since been deleted.
    position_ordinal: str | None = None
    position_description: str | None = None
    resource_key: str | None = None
    quantity: str = "0"
    unit: str | None = None


class POTraceLine(BaseModel):
    """One order line with the requisition line and BOQ sources it came from."""

    po_item_id: UUID
    description: str
    quantity: str = "0"
    unit: str | None = None
    requisition_item_id: UUID | None = None
    requisition_id: UUID | None = None
    req_number: str | None = None
    sources: list[TraceSource] = Field(default_factory=list)


class POTraceRequisition(BaseModel):
    """A requisition converted into the order."""

    id: UUID
    req_number: str | None = None
    status: str
    title: str | None = None


class POTraceResponse(BaseModel):
    """Where the lines of a purchase order came from."""

    po_id: UUID
    po_number: str | None = None
    po_status: str | None = None
    requisitions: list[POTraceRequisition] = Field(default_factory=list)
    lines: list[POTraceLine] = Field(default_factory=list)


class ScheduleActivityOption(BaseModel):
    """A schedule activity a requisition line can take its needed-by date from."""

    id: UUID
    name: str
    schedule_name: str | None = None
    start_date: str
    end_date: str | None = None
    activity_type: str | None = None


class ScheduleActivityOptionPage(BaseModel):
    """One page of the schedule activities a requisition line can take its date from.

    ``total`` counts every activity of the project, so a reader can tell when
    the page was cut short.
    """

    items: list[ScheduleActivityOption]
    total: int
    offset: int = 0
    limit: int = 500


# ── Requisition order owner, external orders and change feed (issue #516) ─────


class ProcurementSettingsResponse(BaseModel):
    """A project's purchasing settings for requisitions."""

    project_id: UUID
    order_owner: str = "ocerp"
    default_approvers: list[RequisitionApprovalStep] = Field(default_factory=list)


class ProcurementSettingsUpdate(BaseModel):
    """Change a project's purchasing settings. Fields left out are left alone."""

    order_owner: Literal["ocerp", "external"] | None = None
    default_approval_chain: list[UUID] | None = Field(default=None, max_length=10)


class ExternalOrderLineIn(BaseModel):
    """One external order line as the purchasing system reports it.

    Quantities are in ``unit``, or in the requisition line's unit when it is left
    out. A line is identified by the requisition line, the system, the order
    number and ``external_line_ref``; reporting it again updates it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    requisition_item_id: UUID
    external_line_ref: str = Field(default="", max_length=100)
    status: Literal["open", "confirmed", "partially_received", "received", "cancelled"] = "open"
    quantity_ordered: str = Field(..., max_length=50)
    quantity_received: str = Field(default="0", max_length=50)
    unit: str | None = Field(default=None, max_length=20)
    expected_delivery_date: date | None = None
    confirmed_delivery_date: date | None = None

    @field_validator("quantity_ordered", "quantity_received")
    @classmethod
    def _check_quantities(cls, v: str) -> str:
        return _validate_non_negative_decimal(v)


class ExternalOrderReport(BaseModel):
    """An external purchasing system reports an order placed against a requisition."""

    model_config = ConfigDict(str_strip_whitespace=True)

    external_system: str = Field(..., min_length=1, max_length=100)
    external_order_number: str = Field(..., min_length=1, max_length=100)
    lines: list[ExternalOrderLineIn] = Field(..., min_length=1, max_length=1000)


class RequisitionFeedEntry(BaseModel):
    """One change of a requisition, in the order the feed serves them."""

    id: UUID
    cursor: str
    occurred_at: datetime
    requisition_id: UUID
    req_number: str | None = None
    event: str
    status: str
    row_version: int = 0
    actor_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RequisitionFeedPage(BaseModel):
    """One page of the change feed.

    Pass ``next_cursor`` back as ``after`` to continue; it stays where it was
    when the page is empty, so polling with it never skips an entry. Only
    entries older than ``settled_before`` are served, so a change whose
    transaction commits a little after it was written is not jumped over.
    """

    items: list[RequisitionFeedEntry]
    next_cursor: str | None = None
    settled_before: datetime
    has_more: bool = False
