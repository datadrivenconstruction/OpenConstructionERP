# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering Pydantic schemas - request/response models.

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
    """Create a new tender package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    boq_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    deadline: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PackageUpdate(BaseModel):
    """Partial update for a tender package."""

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


# ── Create-from-BOQ schema ────────────────────────────────────────────────────


class CreatePackageFromBOQData(BaseModel):
    """Request body for creating a tender package seeded from BOQ sections.

    When ``section_ids`` is empty every top-level row of the BOQ is included.
    A top-level row is a position whose ``parent_id`` is ``None``: a section,
    or a priced line that sits loose at the top of the bill. Ids that name no
    top-level row are refused rather than packaged as an empty scope.
    All descendant positions under the chosen rows are gathered
    recursively and stored as a compact line-item template in the package
    metadata so that incoming bids can be pre-seeded without an additional
    BOQ read.

    Money values inside the generated template follow the v3 contract:
    Decimal-as-string, never floats.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    boq_id: UUID
    section_ids: list[UUID] = Field(default_factory=list)
    package_name: str = Field(..., min_length=1, max_length=255)
    package_description: str = ""
    deadline: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PackageScopeSection(BaseModel):
    """One bill section a package was raised over."""

    id: UUID
    ordinal: str = ""
    description: str = ""
    position_count: int = 0


class PackageScopeResponse(BaseModel):
    """What part of the bill a package actually covers.

    ``create_from_boq`` has always recorded the chosen sections in the package
    metadata as ``source_section_ids``, and nothing has ever read them back, so
    a package over a quarter of a bill looked exactly like a package over all
    of it. Comparison and levelling already narrow to the scope; this is the
    same fact told to the reader rather than only used in the arithmetic.

    ``sections_recorded`` is false when the package predates that metadata or
    came from the demo installer, which records the scope as a flat position
    list. The sections are then derived by walking each in-scope position up to
    its top-level ancestor, which gives the same answer whenever the scope was
    built from whole sections and an honest approximation when it was not.
    """

    package_id: UUID
    boq_id: UUID | None = None
    boq_name: str = ""
    covers_whole_bill: bool = True
    sections_recorded: bool = False
    included_position_count: int = 0
    boq_position_count: int = 0
    sections: list[PackageScopeSection] = Field(default_factory=list)


# ── Distribution (issue the package to subcontractors) ───────────────────────
# Recipients live in the package ``metadata_`` JSON store under the
# ``recipients`` key - the same extensible-per-package pattern used for addenda
# and lifecycle stamps - so distribution needs no new table or migration. Each
# recipient carries who it went to and the per-recipient send state/timestamp
# so the UI can show a clear "sent / failed / pending" status. Distribution
# reuses the platform email sender (``app.core.email``); when SMTP is not
# configured the sender degrades to the console backend and never raises, so a
# fresh dev checkout still records a clean status instead of crashing.


class RecipientCreate(BaseModel):
    """Add a subcontractor to a package's distribution list."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=1, max_length=255)
    # Optional link back to the Subcontractor Directory entry the recipient
    # was picked from, so the UI can cross-reference prequalification status.
    subcontractor_id: str | None = Field(default=None, max_length=64)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("email must be a valid email address")
        return v


class RecipientResponse(BaseModel):
    """One recipient on a package's distribution list."""

    id: str
    company_name: str
    email: str
    subcontractor_id: str | None = None
    # "pending" before the first send, then "sent" or "failed".
    status: str = "pending"
    sent_at: str | None = None
    last_error: str | None = None
    created_at: str = ""


class DistributeRequest(BaseModel):
    """Request body for distributing a package to its recipients.

    ``recipient_ids`` optionally narrows the send to a subset of the stored
    recipients; an empty list (the default) sends to everyone on the list who
    has not already been successfully sent to. ``resend`` forces a re-send even
    to recipients already marked ``sent`` (e.g. after publishing an addendum).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    recipient_ids: list[str] = Field(default_factory=list)
    resend: bool = False
    message: str | None = Field(default=None, max_length=2000)


class DistributeResultEntry(BaseModel):
    """Per-recipient outcome of a distribution run."""

    recipient_id: str
    company_name: str
    email: str
    status: str  # "sent" | "failed" | "skipped"
    detail: str = ""


class DistributeResponse(BaseModel):
    """Summary of a distribution run."""

    package_id: UUID
    package_name: str
    backend: str = ""
    smtp_configured: bool = False
    sent_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    results: list[DistributeResultEntry] = Field(default_factory=list)


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


# ── Award record (Vergabevermerk) ────────────────────────────────────────────
# German public procurement asks the authority to keep a written record of the
# award procedure while it runs (VOB/A section 20, VgV section 8). Everything
# that record has to state about the procedure is assembled on read from the
# package, its bids, its scope and its levelling, so no fact is ever a copy that
# can drift. The statements only a person can make - which procedure type was
# chosen and why, and why the winning bid won - are stored inside the package
# ``metadata_`` JSON store under ``award_record``, the same extensible
# per-package store that already carries recipients, addenda and the lifecycle
# stamps. Nothing is stored until somebody writes a statement, so a package that
# has nothing to do with German public procurement is untouched by all of this.


class AwardRecordFact(BaseModel):
    """One fact the procedure itself already recorded.

    ``key`` is a stable code, never a sentence: the record is read in the
    reader's own language and the label belongs to the UI. Money rides as a
    Decimal-as-string (v3 section 10) and is formatted at the presentation
    boundary.
    """

    key: str
    text: str = ""
    amount: str | None = None
    currency: str = ""
    count: int | None = None
    at: str | None = None
    # A status code carried by the fact (a bid's own status, for instance).
    state: str = ""


class AwardRecordStatement(BaseModel):
    """A human statement that has since been superseded by a later one."""

    text: str = ""
    value: str = ""
    recorded_at: str | None = None
    recorded_by: str | None = None


class AwardRecordSection(BaseModel):
    """One section of the record, either assembled or written by a person.

    ``state`` is ``recorded`` when the section can be read, ``missing`` when the
    procedure has reached the point where it owes this section and it is not
    there, and ``not_due_yet`` when the procedure has not reached that point.
    Only ``missing`` counts as a gap: a draft package does not owe an award
    reason, and reporting one would be noise rather than a finding.
    """

    key: str
    # "procedure" (assembled from what the procedure recorded) or "reasoning"
    # (supplied by a person).
    source: str
    state: str
    facts: list[AwardRecordFact] = Field(default_factory=list)
    statement: str = ""
    value: str = ""
    recorded_at: str | None = None
    recorded_by: str | None = None
    superseded: list[AwardRecordStatement] = Field(default_factory=list)


class AwardRecordGap(BaseModel):
    """A section the procedure owes and that nothing has answered yet."""

    section: str
    source: str


class AwardRecordResponse(BaseModel):
    """The award record for one package, at whatever stage it stands.

    Readable from the first day of the procedure rather than only once an award
    exists: the law's point is contemporaneity, so a record that names its gaps
    early is the correct answer and one that appears only at the end is not.
    """

    package_id: UUID
    package_name: str
    project_name: str = ""
    # The package's lifecycle status, which is the stage the record stands at.
    stage: str = ""
    currency: str = ""
    # True once a person has written at least one statement into this record.
    # False means nothing has ever been stored on the package.
    started: bool = False
    started_at: str | None = None
    is_complete: bool = False
    sections: list[AwardRecordSection] = Field(default_factory=list)
    gaps: list[AwardRecordGap] = Field(default_factory=list)


class AwardRecordNoteCreate(BaseModel):
    """Write one statement into the record.

    Statements are append-only. An earlier statement for the same section is
    superseded and stays readable rather than being overwritten, because a
    record that can be quietly rewritten months later is not the document the
    law asks for.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # One of ``award_record.REASONING_SECTIONS``; validated in the service so
    # the allowed set lives in one place.
    section: str = Field(..., min_length=1, max_length=50)
    text: str = Field(default="", max_length=10000)
    # An optional machine-readable choice beside the prose, used by the
    # procedure-type section to carry the procedure that was chosen.
    value: str = Field(default="", max_length=100)


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
