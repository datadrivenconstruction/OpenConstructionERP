# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Supplier Catalogs Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.supplier_catalogs.models import COST_STATE_UNKNOWN
from app.modules.supplier_catalogs.validators import discount_out_of_range, url_problem

ATTACHMENT_KINDS: tuple[str, ...] = ("datasheet", "drawing", "certificate", "other")


def _checked_url(value: str | None) -> str | None:
    """Empty to ``None``; anything but an http(s) address with a host is refused."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    problem = url_problem(value)
    if problem:
        raise ValueError(f"product_url_unsafe:{problem}")
    return value


VALID_KYC_DOC_TYPES: tuple[str, ...] = (
    "w9",
    "vat_cert",
    "gst",
    "trn",
    "coi",
    "iso",
    "other",
)
VALID_COMMODITY_SCHEMES: tuple[str, ...] = ("unspsc", "eclass", "cpv")

# ── Vendor ───────────────────────────────────────────────────────────────────


class VendorContactSchema(BaseModel):
    """A vendor contact person (stored inside Vendor.contacts_json)."""

    name: str
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    primary: bool = False


class VendorCreate(BaseModel):
    """Create a vendor."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=100)
    contact_id: str | None = Field(default=None, max_length=36)
    currency: str = Field(default="EUR", max_length=10)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    country_code: str | None = Field(default=None, max_length=8)
    region: str | None = Field(default=None, max_length=64)
    categories: list[str] = Field(default_factory=list)
    preferred_for: list[str] = Field(default_factory=list)
    contacts: list[VendorContactSchema] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=4000)
    tolerance_profile_name: str = Field(default="default", max_length=64)


class VendorUpdate(BaseModel):
    """Patch a vendor."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=100)
    contact_id: str | None = Field(default=None, max_length=36)
    currency: str | None = Field(default=None, max_length=10)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    country_code: str | None = Field(default=None, max_length=8)
    region: str | None = Field(default=None, max_length=64)
    categories: list[str] | None = None
    preferred_for: list[str] | None = None
    contacts: list[VendorContactSchema] | None = None
    notes: str | None = Field(default=None, max_length=4000)
    tolerance_profile_name: str | None = Field(default=None, max_length=64)


class VendorResponse(BaseModel):
    """Vendor read schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    contact_id: str | None = None
    status: str
    currency: str
    payment_terms_days: int
    rating: int | None = None
    country_code: str | None = None
    region: str | None = None
    categories_json: list[Any] = Field(default_factory=list)
    preferred_for_json: list[Any] = Field(default_factory=list)
    contacts_json: list[Any] = Field(default_factory=list)
    notes: str | None = None
    tolerance_profile_name: str = "default"
    created_at: datetime
    updated_at: datetime


class VendorRatingPayload(BaseModel):
    """Submit a rating (1-5)."""

    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class VendorListResponse(BaseModel):
    """One page of vendors plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    ``status`` and ``country_code`` are applied before the count is taken, so a
    zero here means this question found nothing rather than the supplier base
    holding nothing.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[VendorResponse]
    total: int
    offset: int
    limit: int


# ── Item categories & catalog items ──────────────────────────────────────────


class ItemCategoryCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: UUID | None = None
    level: int = Field(default=0, ge=0, le=10)
    classification_ref: str | None = Field(default=None, max_length=64)


class ItemCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    parent_id: UUID | None = None
    level: int
    classification_ref: str | None = None


class CatalogItemCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    category_id: UUID | None = None
    unit_of_measure: str = Field(default="pcs", max_length=20)
    manufacturer: str | None = Field(default=None, max_length=255)
    mpn: str | None = Field(default=None, max_length=100)
    spec: dict[str, Any] = Field(default_factory=dict)
    hazard_class: str | None = Field(default=None, max_length=50)
    shelf_life_days: int | None = Field(default=None, ge=0)
    reorder_point: Decimal = Field(default=Decimal("0"))
    gtin: str | None = Field(default=None, max_length=20)
    commodity_code: str | None = Field(default=None, max_length=32)
    commodity_scheme: str = Field(default="unspsc", max_length=16)
    product_url: str | None = Field(default=None, max_length=1000)

    @field_validator("product_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _checked_url(v)


class CatalogItemUpdate(BaseModel):
    """Patch a catalog item.

    ``sku`` is absent on purpose, for the same reason ``VendorUpdate`` leaves
    ``code`` out: it is the item's unique business key, and price lists,
    requisition lines and order lines all quote it. Correcting a typo in a
    name or a unit is one operation; rekeying an item every other record
    points at is a different one, and it is not this route.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    category_id: UUID | None = None
    unit_of_measure: str | None = Field(default=None, min_length=1, max_length=20)
    manufacturer: str | None = Field(default=None, max_length=255)
    mpn: str | None = Field(default=None, max_length=100)
    spec: dict[str, Any] | None = None
    hazard_class: str | None = Field(default=None, max_length=50)
    shelf_life_days: int | None = Field(default=None, ge=0)
    reorder_point: Decimal | None = Field(default=None, ge=0)
    gtin: str | None = Field(default=None, max_length=20)
    commodity_code: str | None = Field(default=None, max_length=32)
    commodity_scheme: str | None = Field(default=None, max_length=16)
    active: bool | None = None
    product_url: str | None = Field(default=None, max_length=1000)

    @field_validator("product_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _checked_url(v)


class CatalogItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    description: str | None = None
    category_id: UUID | None = None
    unit_of_measure: str
    manufacturer: str | None = None
    mpn: str | None = None
    spec_json: dict[str, Any]
    hazard_class: str | None = None
    shelf_life_days: int | None = None
    reorder_point: Decimal
    gtin: str | None = None
    commodity_code: str | None = None
    commodity_scheme: str = "unspsc"
    active: bool
    product_url: str | None = None
    attachment_count: int = 0


class CatalogItemListResponse(BaseModel):
    """One page of catalog items plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    ``category_id`` and ``search`` are both applied in SQL before the count is
    taken, so a zero here means this question found nothing rather than the
    catalog holding nothing.

    A supplier catalog is the largest register in this module by row count - a
    price book runs to tens of thousands of lines - and the page asked for
    exactly the route's ceiling of 200, so it could hand back a full page of a
    catalog many times that size with nothing to say so.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[CatalogItemResponse]
    total: int
    offset: int
    limit: int


# ── Price list & entries ─────────────────────────────────────────────────────


class CatalogEntryCreate(BaseModel):
    catalog_item_id: UUID
    vendor_sku: str | None = Field(default=None, max_length=100)
    unit_price: Decimal = Field(..., ge=0)
    min_order_qty: Decimal = Field(default=Decimal("1"), ge=0)
    lead_time_days: int = Field(default=7, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class PriceListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    valid_from: str | None = None
    valid_to: str | None = None
    currency: str = Field(default="EUR", max_length=10)
    entries: list[CatalogEntryCreate] = Field(default_factory=list)


class PriceListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vendor_id: UUID
    name: str
    valid_from: str | None = None
    valid_to: str | None = None
    currency: str
    status: str
    uploaded_by: str | None = None
    entry_count: int = 0
    expired: bool = False


class PriceListEntryRow(BaseModel):
    """One vendor price as the estimator reads it: list price, discount, net."""

    entry_id: UUID
    catalog_item_id: UUID
    sku: str
    name: str
    unit_of_measure: str
    vendor_sku: str | None = None
    mpn: str | None = None
    gtin: str | None = None
    gross_price: Decimal
    net_price: Decimal
    discount_pct: Decimal | None = None
    discount_source: str
    discount_agreement_id: UUID | None = None
    min_order_qty: Decimal
    lead_time_days: int
    product_url: str | None = None
    attachment_count: int = 0


class PriceListEntriesResponse(BaseModel):
    price_list: PriceListResponse
    items: list[PriceListEntryRow]
    total: int
    offset: int
    limit: int


class ImportPresetResponse(BaseModel):
    """A column-mapping preset: the header spellings it recognises per field."""

    name: str
    fields: dict[str, list[str]]


class ImportRowResult(BaseModel):
    """What the import does with one row of the file."""

    row: int
    action: str  # create | update | unchanged | unmatched | error
    matched_by: str | None = None
    catalog_item_id: UUID | None = None
    sku: str | None = None
    item_name: str | None = None
    vendor_sku: str | None = None
    old_price: Decimal | None = None
    new_price: Decimal | None = None
    currency: str | None = None
    errors: list[str] = Field(default_factory=list)


class PriceListImportPreview(BaseModel):
    """Dry run of an import: nothing is written."""

    preset: str
    sheet: str
    headers: list[str]
    mapping: dict[str, str]
    sample: list[list[str]]
    total_rows: int
    counts: dict[str, int]
    duplicate_vendor_skus: list[str] = Field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    currencies: list[str] = Field(default_factory=list)
    rows: list[ImportRowResult]
    rows_truncated: bool = False


class PriceListImportCommitResult(BaseModel):
    price_list_id: UUID
    counts: dict[str, int]
    unmatched: list[ImportRowResult] = Field(default_factory=list)
    changed: list[ImportRowResult] = Field(default_factory=list)


# ── Discounts ────────────────────────────────────────────────────────────────


def _pct_checked(v: Decimal | None) -> Decimal | None:
    if v is not None and discount_out_of_range(v):
        raise ValueError("discount_out_of_range")
    return v


class DiscountAgreementCreate(BaseModel):
    """A discount on the vendor's list prices.

    Leave ``price_list_id``, ``category_id`` and ``catalog_item_id`` empty for
    an overall discount. ``fixed_net_price`` (a net price per unit instead of a
    percentage) needs ``catalog_item_id``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    reference: str | None = Field(default=None, max_length=100)
    price_list_id: UUID | None = None
    category_id: UUID | None = None
    catalog_item_id: UUID | None = None
    discount_pct: Decimal | None = None
    fixed_net_price: Decimal | None = Field(default=None, ge=0)
    valid_from: date | None = None
    valid_to: date | None = None
    active: bool = True
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("discount_pct")
    @classmethod
    def _pct(cls, v: Decimal | None) -> Decimal | None:
        return _pct_checked(v)

    @model_validator(mode="after")
    def _one_basis(self) -> DiscountAgreementCreate:
        if (self.discount_pct is None) == (self.fixed_net_price is None):
            raise ValueError("discount_basis_one_of_pct_or_fixed_net")
        if self.fixed_net_price is not None and self.catalog_item_id is None:
            raise ValueError("fixed_net_needs_item")
        if self.category_id is not None and self.catalog_item_id is not None:
            raise ValueError("discount_scope_category_or_item")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to_before_valid_from")
        return self


class DiscountAgreementUpdate(BaseModel):
    """Patch an agreement. The scope (price list, category, item) is fixed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    reference: str | None = Field(default=None, max_length=100)
    discount_pct: Decimal | None = None
    fixed_net_price: Decimal | None = Field(default=None, ge=0)
    valid_from: date | None = None
    valid_to: date | None = None
    active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("discount_pct")
    @classmethod
    def _pct(cls, v: Decimal | None) -> Decimal | None:
        return _pct_checked(v)


class DiscountAgreementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vendor_id: UUID
    name: str
    reference: str | None = None
    price_list_id: UUID | None = None
    category_id: UUID | None = None
    catalog_item_id: UUID | None = None
    discount_pct: Decimal | None = None
    fixed_net_price: Decimal | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    active: bool
    notes: str | None = None


# ── Item documents ───────────────────────────────────────────────────────────


class ItemAttachmentCreate(BaseModel):
    """Link a file already in Documents to a catalog item."""

    document_id: UUID
    kind: str = Field(default="datasheet")
    title: str | None = Field(default=None, max_length=255)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ATTACHMENT_KINDS:
            raise ValueError("attachment_kind_unknown")
        return v


class ItemAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    catalog_item_id: UUID
    document_id: UUID
    project_id: UUID
    kind: str
    title: str


class PriceListImportResult(BaseModel):
    """Result of bulk CSV import."""

    price_list_id: UUID
    imported_count: int
    skipped_count: int
    errors: list[str] = Field(default_factory=list)


class PriceComparisonRow(BaseModel):
    """One vendor's price for the requested item."""

    vendor_id: UUID
    vendor_code: str
    vendor_name: str
    unit_price: Decimal
    currency: str
    min_order_qty: Decimal
    lead_time_days: int
    price_list_id: UUID
    rating: int | None = None
    gross_price: Decimal | None = None
    net_price: Decimal | None = None
    discount_pct: Decimal | None = None
    discount_source: str | None = None
    entry_id: UUID | None = None
    valid_to: str | None = None


# ── Purchase requisition ─────────────────────────────────────────────────────


class PRLineCreate(BaseModel):
    catalog_item_id: UUID | None = None
    description: str = Field(..., min_length=1, max_length=500)
    quantity: Decimal = Field(..., gt=0)
    unit_of_measure: str = Field(default="pcs", max_length=20)
    # Omitted with a catalog item: the lowest current net price of any vendor.
    estimated_unit_price: Decimal | None = Field(default=None, ge=0)


class PRCreate(BaseModel):
    project_id: UUID
    needed_by: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    currency: str = Field(default="EUR", max_length=10)
    approval_chain: list[str] = Field(default_factory=list)
    lines: list[PRLineCreate] = Field(default_factory=list)


class PRLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pr_id: UUID
    catalog_item_id: UUID | None = None
    description: str
    quantity: Decimal
    unit_of_measure: str
    estimated_unit_price: Decimal
    estimated_total: Decimal
    gross_unit_price: Decimal | None = None
    discount_source: str | None = None


class PRResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    project_id: UUID
    requested_by: str | None = None
    requested_at: str | None = None
    needed_by: str | None = None
    status: str
    total_estimate: Decimal
    currency: str
    notes: str | None = None
    approval_chain_json: list[Any]
    lines: list[PRLineResponse] = Field(default_factory=list)


# ── Purchase order (extended) ────────────────────────────────────────────────


class POLineCreate(BaseModel):
    catalog_item_id: UUID | None = None
    description: str = Field(..., min_length=1, max_length=500)
    ordered_qty: Decimal = Field(..., gt=0)
    unit_of_measure: str = Field(default="pcs", max_length=20)
    # Omitted: the net price of ``catalog_entry_id``, or of the vendor's current
    # price list for ``catalog_item_id``. Given: a hand-agreed price.
    unit_price: Decimal | None = Field(default=None, ge=0)
    catalog_entry_id: UUID | None = None


class POCreateExt(BaseModel):
    """Create an extended supplier-catalogs PO."""

    vendor_id: UUID
    project_id: UUID
    contract_id: str | None = Field(default=None, max_length=36)
    pr_id: UUID | None = None
    order_date: str | None = None
    expected_delivery: str | None = None
    currency: str = Field(default="EUR", max_length=10)
    tax: Decimal = Field(default=Decimal("0"), ge=0)
    terms: str | None = Field(default=None, max_length=4000)
    lines: list[POLineCreate] = Field(default_factory=list)


class POLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    po_id: UUID
    catalog_item_id: UUID | None = None
    description: str
    ordered_qty: Decimal
    unit_of_measure: str
    unit_price: Decimal
    line_total: Decimal
    received_qty: Decimal
    invoiced_qty: Decimal
    gross_unit_price: Decimal | None = None
    discount_pct: Decimal | None = None
    discount_source: str | None = None
    catalog_entry_id: UUID | None = None


class POResponseExt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    vendor_id: UUID
    project_id: UUID
    contract_id: str | None = None
    pr_id: UUID | None = None
    status: str
    order_date: str | None = None
    expected_delivery: str | None = None
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    terms: str | None = None
    lines: list[POLineResponse] = Field(default_factory=list)


# ── Goods receipt ────────────────────────────────────────────────────────────


class GRLineCreate(BaseModel):
    po_line_id: UUID
    received_qty: Decimal = Field(..., ge=0)
    accepted_qty: Decimal | None = None
    rejected_qty: Decimal = Field(default=Decimal("0"), ge=0)
    batch_lot: str | None = Field(default=None, max_length=100)
    serial_numbers: list[str] | None = None
    notes: str | None = Field(default=None, max_length=1000)


class GoodsReceiptCreate(BaseModel):
    po_id: UUID
    warehouse_id: UUID
    received_at: str | None = None
    scan_method: str = Field(default="manual", max_length=20)
    photos: list[str] = Field(default_factory=list)
    discrepancy_notes: str | None = Field(default=None, max_length=4000)
    lines: list[GRLineCreate] = Field(default_factory=list)


class GRLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gr_id: UUID
    po_line_id: UUID
    received_qty: Decimal
    accepted_qty: Decimal
    rejected_qty: Decimal
    batch_lot: str | None = None
    serial_numbers_json: list[Any] | None = None
    notes: str | None = None


class GRResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    po_id: UUID
    warehouse_id: UUID
    received_at: str | None = None
    received_by: str | None = None
    status: str
    scan_method: str
    photos_json: list[Any]
    discrepancy_notes: str | None = None
    lines: list[GRLineResponse] = Field(default_factory=list)


# ── Vendor invoice & match ───────────────────────────────────────────────────


class VendorInvoiceCreate(BaseModel):
    number: str = Field(..., min_length=1, max_length=100)
    vendor_id: UUID
    po_id: UUID | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    currency: str = Field(default="EUR", max_length=10)
    subtotal: Decimal = Field(..., ge=0)
    tax: Decimal = Field(default=Decimal("0"), ge=0)


class VendorInvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    vendor_id: UUID
    po_id: UUID | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    status: str
    three_way_match_status: str
    exception_reason: str | None = None


class MatchResult(BaseModel):
    """Outcome of an invoice 3-way match.

    ``line_results`` carries per-PO-line explanations; empty when the
    invoice has no lines (header-only match).

    The variances are nullable because ``not_comparable`` exists: when the
    invoice and the order are priced in different currencies the subtraction is
    not a small error, it is meaningless, and no number belongs in the field.
    ``Decimal("0")`` would be the worst available answer, since zero variance is
    the exact value that means nothing is wrong.

    ``tolerance_used_pct`` is the profile's percentage and only ever that. The
    band actually applied is the wider of that percentage and the profile's
    absolute floor, so the percentage alone does not explain why a given
    invoice passed. ``tolerance_used_abs`` and ``absolute_tolerance_state``
    say what became of the floor: whether it was zero, applied, or dropped
    because it could not be shown to be in the order's currency.
    """

    invoice_id: UUID
    status: str  # auto_matched / exception / not_comparable
    #: ``None`` when the comparison was not performed. Never zero for that case.
    price_variance: Decimal | None
    qty_variance: Decimal | None
    tolerance_used_pct: Decimal
    #: The absolute floor that actually widened the *header* band, in the
    #: order's currency. ``None`` when no floor applied there - either because
    #: the profile's is zero, or because it was dropped, or because nothing was
    #: compared. Header specifically: the line bands are percentages of unit
    #: prices rather than of the order total, so the same floor can lose the
    #: header comparison and still decide a line status. Read
    #: ``absolute_tolerance_state`` for what became of the floor as such, and
    #: this field only for what set the header band.
    #: Deliberately required-and-nullable rather than defaulted: a default
    #: would let a construction site that forgets it answer "no floor" for a
    #: match where one governed, which is the failure this pair exists to
    #: expose. Missing it is a TypeError instead.
    tolerance_used_abs: Decimal | None
    #: One of the ``ABS_TOLERANCE_*`` constants in ``models``, or ``None`` when
    #: no comparison was performed and there is nothing to report.
    absolute_tolerance_state: str | None
    exception_reason: str | None = None
    tolerance_profile_name: str = "default"
    line_results: list[dict[str, Any]] = Field(default_factory=list)


# ── Warehouse & stock ────────────────────────────────────────────────────────


class WarehouseCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    project_id: UUID | None = None
    address: str | None = Field(default=None, max_length=1000)
    manager_user_id: str | None = Field(default=None, max_length=36)


class WarehouseUpdate(BaseModel):
    """Patch a warehouse.

    Two columns are deliberately out of reach here.

    ``code`` is the unique business key, as ``code`` is on a vendor and
    ``sku`` is on a catalog item.

    ``project_id`` decides who is allowed to read this warehouse's balances
    and costs, so moving it is an access change rather than a correction; it
    would have to be authorised against the project the warehouse is leaving
    as well as the one it is joining, which is a different route from this
    one.

    ``status`` is absent for a third reason, and it is worth writing down:
    nothing in the module reads it. It is written once as ``"active"`` on
    create and no query, service branch or screen ever looks at it again, so
    a field that let a user change it would look like closing a warehouse
    while changing nothing at all.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=1000)
    manager_user_id: str | None = Field(default=None, max_length=36)


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    project_id: UUID | None = None
    address: str | None = None
    manager_user_id: str | None = None
    status: str


class StockBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    warehouse_id: UUID
    catalog_item_id: UUID
    batch_lot: str
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    # None means there is no single-currency average for this balance, not
    # that the average is zero. ``cost_state`` says which case applies:
    # "single" (currency is set and the average is real), "mixed" (receipts
    # in more than one currency), or "unknown" (nothing received, or a
    # receipt with no ISO code).
    unit_cost_avg: Decimal | None = None
    currency: str | None = None
    cost_state: str = COST_STATE_UNKNOWN
    last_movement_at: str | None = None


class StockReservePayload(BaseModel):
    catalog_item_id: UUID
    warehouse_id: UUID
    quantity: Decimal = Field(..., gt=0)
    project_id: UUID | None = None
    batch_lot: str | None = None


class StockIssuePayload(BaseModel):
    catalog_item_id: UUID
    warehouse_id: UUID
    quantity: Decimal = Field(..., gt=0)
    to_project_id: UUID | None = None
    batch_lot: str | None = None
    notes: str | None = Field(default=None, max_length=1000)


class StocktakeCount(BaseModel):
    catalog_item_id: UUID
    counted_qty: Decimal = Field(..., ge=0)
    batch_lot: str | None = None


class StocktakePayload(BaseModel):
    counts: list[StocktakeCount]


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    warehouse_id: UUID
    catalog_item_id: UUID
    movement_type: str
    quantity: Decimal
    # None means the unit cost is not knowable, never that it is zero: a
    # movement out of a balance with no single-currency average has nothing to
    # record, and zero would read as "issued for nothing". The column is
    # nullable for that reason, so the field has to be too - declaring it
    # required turned an ordinary movement into a 500 after the row had
    # already been written. ``currency`` is the ISO code this amount is
    # denominated in; without it the number reaches the caller meaning nothing.
    unit_cost: Decimal | None = None
    currency: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    batch_lot: str | None = None
    project_id: UUID | None = None
    performed_by: str | None = None
    performed_at: str | None = None
    notes: str | None = None


# ── Commodity codes ──────────────────────────────────────────────────────────


class CommodityCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scheme: str
    code: str
    name: str
    description: str | None = None
    parent_code: str | None = None
    level: int
    active: bool


# ── Tolerance profiles ───────────────────────────────────────────────────────


def normalise_floor_currency(price_tolerance_abs: Decimal | None, currency: str | None) -> str | None:
    """Normalise ``currency``, or explain why this pair cannot be stored.

    A nonzero absolute floor is a sum of money, and a profile is applied to
    purchase orders in every currency the tenant trades in. Storing that sum
    without an ISO code is what lets a floor written as 5000 of a small unit
    become a 5000-unit allowance against an order priced in a large one, which
    auto-approves the overbilling it was meant to catch.

    Returns the cleaned ISO code, or ``None`` for "no label needed". Raises
    ``ValueError`` when the floor is nonzero and unlabelled, so both the create
    and the update path get the same answer from the same place.
    """
    code = (currency or "").strip().upper() or None
    if price_tolerance_abs is not None and price_tolerance_abs > 0 and code is None:
        raise ValueError(
            "price_tolerance_abs is an amount of money and needs a currency: "
            "set currency to the ISO code it is written in, or leave the "
            "absolute floor at 0 and rely on price_tolerance_pct, which needs "
            "no label because a percentage of the order is already in the "
            "order's own currency",
        )
    return code


class TolerianceProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    price_tolerance_pct: Decimal = Field(default=Decimal("2.0"), ge=0, le=100)
    price_tolerance_abs: Decimal = Field(default=Decimal("0"), ge=0)
    #: ISO code for ``price_tolerance_abs``. Optional only because the floor
    #: defaults to zero, which is the same amount in every currency.
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    qty_tolerance_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    period_tolerance_days: int = Field(default=7, ge=0, le=365)
    require_gr: bool = True
    is_default: bool = False

    @model_validator(mode="after")
    def _floor_names_its_currency(self) -> TolerianceProfileCreate:
        self.currency = normalise_floor_currency(self.price_tolerance_abs, self.currency)
        return self


class TolerianceProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    price_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100)
    price_tolerance_abs: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    qty_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100)
    period_tolerance_days: int | None = Field(default=None, ge=0, le=365)
    require_gr: bool | None = None
    is_default: bool | None = None

    # No validator here on purpose. This is a partial update, so the pair that
    # has to be legal is the one the row ends up with, not the one the caller
    # happened to send: raising a floor on a profile that already carries a
    # currency is fine, and sending a floor alone is only wrong if the stored
    # currency is NULL. Only the service can see both halves, so the check
    # lives in CatalogService.update_tolerance_profile.


class TolerianceProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    price_tolerance_pct: Decimal
    price_tolerance_abs: Decimal
    #: ``None`` on a row written before the floor was labelled, and on any row
    #: whose floor is zero. Not "any currency" in either case.
    currency: str | None = None
    qty_tolerance_pct: Decimal
    period_tolerance_days: int
    require_gr: bool
    is_default: bool


# ── KYC documents ────────────────────────────────────────────────────────────


class KYCDocumentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    doc_type: str = Field(..., max_length=32)
    document_number: str | None = Field(default=None, max_length=100)
    issued_on: date | None = None
    expires_on: date | None = None
    issuing_country: str | None = Field(default=None, max_length=8)
    issuing_authority: str | None = Field(default=None, max_length=255)
    file_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)


class KYCDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vendor_id: UUID
    doc_type: str
    document_number: str | None = None
    issued_on: date | None = None
    expires_on: date | None = None
    issuing_country: str | None = None
    issuing_authority: str | None = None
    file_url: str | None = None
    status: str
    verified_at: datetime | None = None
    verified_by: str | None = None
    notes: str | None = None


# ── Scorecards ───────────────────────────────────────────────────────────────


class ScorecardWeights(BaseModel):
    """Weights for the composite formula. Must sum to a positive number."""

    delivery: Decimal = Field(default=Decimal("30"), ge=0, le=100)
    quality: Decimal = Field(default=Decimal("30"), ge=0, le=100)
    price: Decimal = Field(default=Decimal("20"), ge=0, le=100)
    esg: Decimal = Field(default=Decimal("20"), ge=0, le=100)


class ScorecardRecomputeRequest(BaseModel):
    period_start: date
    period_end: date
    weights: ScorecardWeights | None = None


class ScorecardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vendor_id: UUID
    period_start: date
    period_end: date
    delivery_score: Decimal
    quality_score: Decimal
    price_score: Decimal
    esg_score: Decimal
    composite_score: Decimal
    inputs_json: dict[str, Any] = Field(default_factory=dict)
    weights_json: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime


# ── PEPPOL ingest ────────────────────────────────────────────────────────────


class PeppolIngestResult(BaseModel):
    """Result of parsing + ingesting a UBL 2.1 PEPPOL invoice."""

    invoice_id: UUID
    invoice_number: str
    vendor_id: UUID
    matched_status: str  # auto_matched | exception | unmatched (no PO link)
    line_count: int
    total: Decimal
    currency: str
    exception_reason: str | None = None
    peppol_message_id: str | None = None
