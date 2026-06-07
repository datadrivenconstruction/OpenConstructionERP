"""‌⁠‍Tendering Pydantic schemas - request/response models.

Defines create, update, and response schemas for tender packages and bids.
v3 §10 - money fields are Decimal-as-string in JSON.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

# Pragmatic email regex - RFC 5322 is impractical to validate at the
# schema layer, so we apply the same shape check the frontend ``type=email``
# input uses (HTML5 living standard). Empty string stays valid because the
# field is optional on a bid (Wave 12 audit added validation).
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py - money fields are stored /
# accepted as Decimal but emitted as plain decimal strings in JSON.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# ── Package schemas ──────────────────────────────────────────────────────────


class PackageCreate(BaseModel):
    """‌⁠‍Create a new tender package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    boq_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    deadline: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PackageUpdate(BaseModel):
    """‌⁠‍Partial update for a tender package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|issued|collecting|evaluating|awarded|closed)$",
    )
    deadline: str | None = None
    metadata: dict[str, Any] | None = None


class PackageResponse(BaseModel):
    """Tender package returned from the API.

    ``validation_alias='metadata_'`` lets the model read the ORM column
    named ``metadata_`` while emitting the canonical ``metadata`` key on
    the wire. FastAPI defaults ``response_model_by_alias=True``, which
    used to leak ``metadata_`` to the frontend - the frontend reads
    ``metadata`` and was getting ``undefined`` (Wave 12 audit).
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    boq_id: UUID | None = None
    name: str
    description: str
    status: str
    deadline: str | None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    bid_count: int = 0


class PackageWithBidsResponse(PackageResponse):
    """Package response including all bids."""

    bids: list["BidResponse"] = []


# ── Bid schemas ──────────────────────────────────────────────────────────────


class BidLineItem(BaseModel):
    """A single line item within a bid.

    v3 §10 - ``unit_rate`` is money; Decimal-as-string in JSON.
    ``total`` stays float (not in the deferred audit list - kept as the
    UI-side preview value the FE rolls up).
    """

    position_id: str | None = None
    description: str = ""
    unit: str = ""
    quantity: float = 0.0
    unit_rate: Decimal = Decimal("0")
    total: float = 0.0

    @field_serializer("unit_rate", when_used="json")
    def _ser_unit_rate(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class BidCreate(BaseModel):
    """Create a new bid for a tender package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str = Field(..., min_length=1, max_length=255)
    contact_email: str = Field(default="", max_length=255)
    total_amount: str = Field(default="0", max_length=50)
    currency: str = Field(default="EUR", max_length=10)
    submitted_at: str | None = Field(default=None, max_length=20)
    status: str = Field(default="pending", pattern=r"^(pending|submitted|accepted|rejected)$")
    notes: str = ""
    line_items: list[BidLineItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("contact_email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        # Optional field - empty stays empty. Anything non-empty must look
        # like an email so we don't accept garbage strings the buyer can
        # later try to send notifications to (Wave 12 audit).
        if v and not _EMAIL_RE.match(v):
            raise ValueError("contact_email must be a valid email address")
        return v


class BidUpdate(BaseModel):
    """Partial update for a bid."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_email: str | None = None
    total_amount: str | None = None
    currency: str | None = None
    submitted_at: str | None = None
    status: str | None = Field(default=None, pattern=r"^(pending|submitted|accepted|rejected)$")
    notes: str | None = None
    line_items: list[BidLineItem] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("contact_email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        if v and not _EMAIL_RE.match(v):
            raise ValueError("contact_email must be a valid email address")
        return v


class BidResponse(BaseModel):
    """Bid returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    package_id: UUID
    company_name: str
    contact_email: str
    total_amount: str
    currency: str
    submitted_at: str | None
    status: str
    notes: str
    line_items: list[dict[str, Any]]
    # See PackageResponse.metadata for why this uses ``validation_alias``
    # rather than ``alias`` (Wave 12 audit fix).
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Comparison schema ────────────────────────────────────────────────────────


class BidComparisonRow(BaseModel):
    """A single row in the bid comparison matrix.

    v3 §10 - ``budget_rate`` and ``budget_total`` are money;
    Decimal-as-string in JSON. ``budget_quantity`` listed in the audit as
    "measurement, but priced - verify per project"; it is genuinely a
    measured quantity in the bid context (not a unit price) so we keep
    it as float for symmetry with ``BidLineItem.quantity`` and the
    upstream BOQ position's ``quantity``.
    """

    position_id: str | None = None
    description: str = ""
    unit: str = ""
    budget_quantity: float = 0.0
    budget_rate: Decimal = Decimal("0")
    budget_total: Decimal = Decimal("0")
    bids: list[dict[str, Any]] = Field(default_factory=list)

    @field_serializer("budget_rate", "budget_total", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class BidComparisonResponse(BaseModel):
    """Full bid comparison for a package.

    v3 §10 - ``budget_total`` is money; Decimal-as-string in JSON.
    """

    package_id: UUID
    package_name: str
    bid_count: int = 0
    bid_companies: list[str] = Field(default_factory=list)
    budget_total: Decimal = Decimal("0")
    rows: list[BidComparisonRow] = Field(default_factory=list)
    bid_totals: list[dict[str, Any]] = Field(default_factory=list)

    @field_serializer("budget_total", when_used="json")
    def _ser_budget_total(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Project Intelligence (RFC 25) ───────────────────────────────────────────


class BidVendorEntry(BaseModel):
    """Aggregated summary for a single bidder across all packages."""

    company_name: str
    total: float = 0.0
    currency: str = "EUR"
    bid_count: int = 0


class BidOutlierEntry(BaseModel):
    """One bid identified as an outlier vs the spread (IQR-based)."""

    bid_id: UUID
    company_name: str
    total: float = 0.0
    reason: str = Field("", description="Why the bid is flagged (too_high | too_low)")


class BidSpread(BaseModel):
    """Statistical spread across all bid totals for a project."""

    min: float = 0.0
    max: float = 0.0
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    mean: float = 0.0
    std: float = 0.0
    sample_size: int = 0


class BidAnalysisResponse(BaseModel):
    """Vendor concentration + outlier + spread summary for the project."""

    vendors: list[BidVendorEntry] = Field(default_factory=list)
    outliers: list[BidOutlierEntry] = Field(default_factory=list)
    spread: BidSpread = Field(default_factory=BidSpread)


# ── Addenda (mid-tender clarifications) ──────────────────────────────────────
# Addenda are stored inside the package ``metadata_`` JSON store (under the
# ``addenda`` key) rather than a dedicated table - they are a lightweight,
# append-only revision log scoped to one package, and the data model already
# uses ``metadata_`` as the extensible per-package store (see service
# ``update_package`` lifecycle stamps). This keeps the feature schema-free
# (no migration) while remaining fully persisted and FX-irrelevant.


class AddendumAckEntry(BaseModel):
    """One bidder acknowledgement of a published addendum."""

    bidder_id: str
    acknowledged_at: str
    user_id: str | None = None


class AddendumCreate(BaseModel):
    """Create a new (draft) addendum on a package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(..., min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=10000)


class AddendumAcknowledgeRequest(BaseModel):
    """Record a bidder's acknowledgement of an addendum."""

    model_config = ConfigDict(str_strip_whitespace=True)

    bidder_id: str = Field(..., min_length=1, max_length=100)


class AddendumResponse(BaseModel):
    """An addendum revision returned from the API."""

    id: str
    package_id: UUID
    revision_no: int
    title: str
    body: str | None = None
    published_at: str | None = None
    published_by_user_id: str | None = None
    acknowledged_by: list[AddendumAckEntry] = Field(default_factory=list)
    created_at: str
    updated_at: str


# ── Bid leveling ─────────────────────────────────────────────────────────────
# Bid leveling normalizes every bid onto the package's reference BOQ lines.
# It is a pure computation over data that already exists (BOQ positions + each
# bid's ``line_items``) - no persistence, no migration. Lines a bidder omitted
# are "imputed" at the bidder's own mean rate so a short quote cannot win on a
# misleadingly low total.


class BidLevelingSummary(BaseModel):
    """Per-bid leveling rollup (raw vs leveled, line classification counts).

    v3 §10 - the rolled-up amounts are money, so they ride as
    Decimal-as-string in JSON like every other money field.
    """

    bid_id: str
    company_name: str
    raw_amount: Decimal = Decimal("0")
    leveled_amount: Decimal = Decimal("0")
    matched_lines: int = 0
    scaled_lines: int = 0
    imputed_lines: int = 0
    currency: str = ""

    @field_serializer("raw_amount", "leveled_amount", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class LevelingMatrixCell(BaseModel):
    """One (reference line × bid) cell of the leveling matrix."""

    bid_id: str
    company_name: str
    raw_total: float = 0.0
    leveled_total: float = 0.0
    status: str = ""  # "" | "matched" | "scaled" | "imputed"
    # v3 §10 - the bidder's unit price is money (Decimal-as-string in JSON).
    unit_rate: Decimal = Decimal("0")

    @field_serializer("unit_rate", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class LevelingMatrixRow(BaseModel):
    """One reference BOQ line with a cell per bid."""

    position_id: str | None = None
    line_code: str = ""
    description: str = ""
    unit: str = ""
    reference_quantity: float = 0.0
    reference_rate: float = 0.0
    reference_total: float = 0.0
    cells: list[LevelingMatrixCell] = Field(default_factory=list)


class LevelingMatrixResponse(BaseModel):
    """Full bid-leveling matrix for a package."""

    package_id: UUID
    package_name: str
    # ISO currency the matrix is computed in (the package currency). Leveling
    # only includes bids quoted in this currency - never blend currencies.
    currency: str = ""
    # Count of bids excluded because they were quoted in a different currency.
    excluded_off_currency: int = 0
    bid_summaries: list[BidLevelingSummary] = Field(default_factory=list)
    rows: list[LevelingMatrixRow] = Field(default_factory=list)


class LevelBidsResponse(BaseModel):
    """Result of running leveling across a package's bids."""

    package_id: UUID
    package_name: str
    # ISO currency the leveling was computed in (the package currency).
    currency: str = ""
    # Count of bids excluded because they were quoted in a different currency.
    excluded_off_currency: int = 0
    bid_count: int = 0
    reference_line_count: int = 0
    bid_summaries: list[BidLevelingSummary] = Field(default_factory=list)
