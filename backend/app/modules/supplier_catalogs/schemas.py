"""‌⁠‍Supplier Catalogs Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    """‌⁠‍A vendor contact person (stored inside Vendor.contacts_json)."""

    name: str
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    primary: bool = False


class VendorCreate(BaseModel):
    """‌⁠‍Create a vendor."""

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


# ── Purchase requisition ─────────────────────────────────────────────────────


class PRLineCreate(BaseModel):
    catalog_item_id: UUID | None = None
    description: str = Field(..., min_length=1, max_length=500)
    quantity: Decimal = Field(..., gt=0)
    unit_of_measure: str = Field(default="pcs", max_length=20)
    estimated_unit_price: Decimal = Field(default=Decimal("0"), ge=0)


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
    unit_price: Decimal = Field(..., ge=0)


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
    """

    invoice_id: UUID
    status: str  # auto_matched / exception
    price_variance: Decimal
    qty_variance: Decimal
    tolerance_used_pct: Decimal
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
    unit_cost_avg: Decimal
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
    unit_cost: Decimal
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


class TolerianceProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    price_tolerance_pct: Decimal = Field(default=Decimal("2.0"), ge=0, le=100)
    price_tolerance_abs: Decimal = Field(default=Decimal("0"), ge=0)
    qty_tolerance_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    period_tolerance_days: int = Field(default=7, ge=0, le=365)
    require_gr: bool = True
    is_default: bool = False


class TolerianceProfileUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    price_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100)
    price_tolerance_abs: Decimal | None = Field(default=None, ge=0)
    qty_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100)
    period_tolerance_days: int | None = Field(default=None, ge=0, le=365)
    require_gr: bool | None = None
    is_default: bool | None = None


class TolerianceProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    price_tolerance_pct: Decimal
    price_tolerance_abs: Decimal
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
