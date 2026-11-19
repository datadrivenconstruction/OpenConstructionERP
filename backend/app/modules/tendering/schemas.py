# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tendering Pydantic schemas - request/response models.

Defines create, update, and response schemas for tender packages and bids.
v3 §10 - money fields are Decimal-as-string in JSON.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.decimal_types import FiniteDecimal

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


def _finite_total(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return "0"
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("total_amount must be a number") from exc
    if not d.is_finite() or d < 0 or d.adjusted() > 24:
        raise ValueError("total_amount must be a finite non-negative number")
    return v


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
    # A budget entered by hand; null clears it and the computed sum applies.
    budget_override: FiniteDecimal | None = None
    resource_scope: "ResourceScopeIn | None" = None

    @field_validator("budget_override")
    @classmethod
    def _check_override(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("budget_override must not be negative")
        return v


class ResourceScopeIn(BaseModel):
    """Which cost components of its lines a package covers.

    ``kinds`` are the cost kinds in the package (labor, material, machinery,
    equipment, subcontractor, other); ``excluded`` takes single components out
    line by line (position id to component keys), for rows the owner supplies.
    All kinds and no exclusions is the whole line, the default.
    """

    kinds: list[Literal["labor", "material", "machinery", "equipment", "subcontractor", "other"]] = Field(
        ..., min_length=1, max_length=6
    )
    excluded: dict[str, list[str]] = Field(default_factory=dict, max_length=50000)

    @field_validator("excluded")
    @classmethod
    def _check_excluded(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for keys in v.values():
            if len(keys) > 500 or any(len(k) > 64 for k in keys):
                raise ValueError("too many or too long component keys on one line")
        return v


PackageUpdate.model_rebuild()


class PackageCancel(BaseModel):
    """Cancel a tender that already went out: it is closed and kept, not deleted."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(default="", max_length=2000)


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
    # "informal" | "sealed"; ``sealed`` carries the opening state of a sealed package.
    submission_mode: str = "informal"
    sealed: "SealedInfo | None" = None
    #: The company the package is bought for; ``None`` means the project's company.
    legal_entity_id: UUID | None = None
    trade: str | None = None


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
    quantity: float = Field(default=0.0, allow_inf_nan=False)
    unit_rate: Decimal = Field(default=Decimal("0"), allow_inf_nan=False, max_digits=24)
    total: float = Field(default=0.0, allow_inf_nan=False)

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
    notes: str = Field(default="", max_length=10000)
    line_items: list[BidLineItem] = Field(default_factory=list, max_length=50000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("total_amount")
    @classmethod
    def _check_total(cls, v: str) -> str:
        return _finite_total(v) or "0"

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
    total_amount: str | None = Field(default=None, max_length=50)
    currency: str | None = None
    submitted_at: str | None = None
    status: str | None = Field(default=None, pattern=r"^(pending|submitted|accepted|rejected)$")
    notes: str | None = Field(default=None, max_length=10000)
    line_items: list[BidLineItem] | None = Field(default=None, max_length=50000)
    metadata: dict[str, Any] | None = None

    @field_validator("total_amount")
    @classmethod
    def _check_total(cls, v: str | None) -> str | None:
        return _finite_total(v)

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
    # True while the package is sealed and unopened: content fields are empty.
    sealed: bool = False
    # Directory party this bid belongs to (see PartyLink).
    contact_id: UUID | None = None
    contact_match_method: str | None = None
    contact_match_confidence: float | None = None


# ── Sealed mode ─────────────────────────────────────────────────────────────


class SealedInfo(BaseModel):
    """Opening state of a sealed package as listed with the package."""

    state: str  # sealed | awaiting_second | opened
    dual_opening: bool = False
    deadline_utc: datetime | None = None
    first_approver_id: str | None = None
    first_approved_at: datetime | None = None
    opened_at: datetime | None = None
    opened_by: str | None = None


class SubmissionModeUpdate(BaseModel):
    """Switch a package between informal and sealed submissions."""

    mode: Literal["informal", "sealed"]
    dual_opening: bool = False


class SealedSubmission(BaseModel):
    """A received sealed submission: who and when, never what."""

    bid_id: UUID
    company_name: str
    received_at: datetime
    sha256: str


class SealedStatusResponse(BaseModel):
    """Sealed state of a package on the server clock."""

    package_id: UUID
    mode: str
    state: str | None = None
    dual_opening: bool = False
    deadline_utc: datetime | None = None
    server_now: datetime
    deadline_passed: bool = False
    first_approver_id: str | None = None
    first_approved_at: datetime | None = None
    opened_at: datetime | None = None
    opened_by: str | None = None
    submissions: list[SealedSubmission] = Field(default_factory=list)


class BidIntegrityResponse(BaseModel):
    """Recomputed digest of a bid against the digest on its receipt."""

    bid_id: UUID
    receipt_sha256: str | None = None
    current_sha256: str
    received_at: datetime | None = None
    intact: bool


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
    # The bill's position number (OZ / item number), so a printed comparison
    # can be read against the bill the bidders priced.
    ordinal: str = ""
    description: str = ""
    unit: str = ""
    budget_quantity: float = 0.0
    budget_rate: FiniteDecimal = Decimal("0")
    budget_total: FiniteDecimal = Decimal("0")
    # One entry per bid. ``priced`` is False when the bid has no rate for this
    # line, so a reader can tell a missing price from one quoted at zero (an
    # unpriced entry carries ``unit_rate`` and ``total`` null, not 0).
    bids: list[dict[str, Any]] = Field(default_factory=list)
    # GAEB ``Provis`` flag of the bill line (``WithoutTotal`` / ``WithTotal``),
    # empty for a normal item. A ``WithoutTotal`` line is not in any total.
    provis: str = ""

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
    # ``budget_total`` is the budget in force: the buyer's override when one is
    # set. The sum of the package's lines stays readable beside it.
    budget_computed: Decimal = Decimal("0")
    budget_override: Decimal | None = None
    # Budget of the Bedarfspositionen ohne Gesamtbetrag, shown apart from
    # ``budget_total`` which never includes them.
    budget_provis_total: Decimal = Decimal("0")
    rows: list[BidComparisonRow] = Field(default_factory=list)
    bid_totals: list[dict[str, Any]] = Field(default_factory=list)
    # Tender BOQ revision bidders must price and the number of published addenda;
    # each bid total carries ``boq_revision_no``, ``missing_addenda`` and ``compliant``.
    current_boq_revision: int = 0
    published_addenda: int = 0

    @field_serializer("budget_total", "budget_computed", "budget_override", "budget_provis_total", when_used="json")
    def _ser_budget_total(self, v: Decimal | None) -> str | None:
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


# ── Package preview (what goes out, before it does) ─────────────────────────


class PackagePreviewComponent(BaseModel):
    """One cost component of a line: per line unit, in or out of the package."""

    key: str
    name: str
    code: str | None = None
    kind: str
    unit: str = ""
    quantity: FiniteDecimal = Decimal("0")
    unit_cost: FiniteDecimal = Decimal("0")
    included: bool = True

    @field_serializer("quantity", "unit_cost", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class PackagePreviewLine(BaseModel):
    """A row as the bidder sees it, with the buyer's budget beside it."""

    id: str
    kind: str  # "section" | "item"
    ordinal: str = ""
    short_text: str = ""
    long_text: str = ""
    unit: str = ""
    quantity: str = ""
    depth: int = 0
    supplied_by_others: list[str] = Field(default_factory=list)
    budget_rate: FiniteDecimal | None = None
    budget_total: FiniteDecimal | None = None
    # The scope left part of this line's components with the owner.
    split: bool = False
    # The scope names cost kinds but this line has no priced components.
    unsplittable: bool = False
    components: list[PackagePreviewComponent] = Field(default_factory=list)

    @field_serializer("budget_rate", "budget_total", when_used="json")
    def _ser(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class PackagePreviewRecipient(BaseModel):
    """A firm on the distribution list."""

    company_name: str
    email: str
    status: str
    # State of its newest bidder link, None when it has none.
    link_status: str | None = None


class PackagePreviewDocument(BaseModel):
    """A document an addendum issues or replaces."""

    addendum_revision: int
    addendum_title: str
    published: bool = False
    title: str = ""
    drawing_number: str = ""
    revision: str = ""
    document_id: str | None = None


class PackagePreviewResponse(BaseModel):
    """The whole content of a package as it goes out."""

    package_id: UUID
    name: str
    description: str = ""
    status: str
    deadline: str | None = None
    currency: str = ""
    lines: list[PackagePreviewLine] = Field(default_factory=list)
    item_count: int = 0
    budget_computed: Decimal = Decimal("0")
    budget_override: Decimal | None = None
    budget_total: Decimal = Decimal("0")
    scope_kinds: list[str] = Field(default_factory=list)
    scope_active: bool = False
    recipients: list[PackagePreviewRecipient] = Field(default_factory=list)
    documents: list[PackagePreviewDocument] = Field(default_factory=list)
    bid_count: int = 0
    # Results of the ``tendering_contents`` rule set.
    validation: list[dict[str, Any]] = Field(default_factory=list)

    @field_serializer("budget_computed", "budget_override", "budget_total", when_used="json")
    def _ser(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


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
    # Optional directory contact the recipient is. It must belong to the caller's
    # tenant; without it the contact is resolved from the email.
    contact_id: UUID | None = None

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
    contact_id: str | None = None
    # "pending" before the first send, then "sent" or "failed".
    status: str = "pending"
    sent_at: str | None = None
    last_error: str | None = None
    created_at: str = ""


class RecipientImportRow(BaseModel):
    """One file row with its findings; ``issues`` are stable codes the UI translates."""

    line: int
    company: str = ""
    contact_name: str = ""
    email: str = ""
    trade: str = ""
    vat_id: str = ""
    issues: list[str] = Field(default_factory=list)
    valid: bool = True


class RecipientImportPreview(BaseModel):
    """Dry run of a recipient file: nothing is stored."""

    total: int
    valid: int
    rows: list[RecipientImportRow]


class RecipientImportResult(BaseModel):
    """Outcome of a confirmed import."""

    added: list[RecipientResponse]
    skipped: list[RecipientImportRow]
    contacts_created: int = 0
    contacts_linked: int = 0
    # Firms the subcontractor directory blocks; left off the list (award.bidder_blocked).
    blocked: list[str] = Field(default_factory=list)


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


class AddendumDocumentChange(BaseModel):
    """A tender document the addendum issues or replaces, at the revision issued."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: UUID | None = None
    drawing_number: str | None = Field(default=None, max_length=120)
    title: str = Field(default="", max_length=255)
    revision: str | None = Field(default=None, max_length=40)
    note: str = Field(default="", max_length=1000)


class AddendumBOQChange(BaseModel):
    """One bill line the addendum adds, changes or deletes, with before and after."""

    model_config = ConfigDict(str_strip_whitespace=True)

    op: Literal["add", "change", "delete"]
    position_id: str | None = Field(default=None, max_length=64)
    ordinal: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=2000)
    unit: str = Field(default="", max_length=30)
    quantity_before: str | None = Field(default=None, max_length=40)
    quantity_after: str | None = Field(default=None, max_length=40)
    description_before: str | None = Field(default=None, max_length=2000)


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
    # What the addendum changes. Each part is optional; an addendum may only clarify.
    document_changes: list[AddendumDocumentChange] = Field(default_factory=list, max_length=200)
    boq_changes: list[AddendumBOQChange] = Field(default_factory=list, max_length=2000)
    new_deadline: str | None = Field(default=None, max_length=100)
    source_clarification_id: UUID | None = None


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
    document_changes: list[dict[str, Any]] = Field(default_factory=list)
    boq_changes: list[dict[str, Any]] = Field(default_factory=list)
    boq_revision_no: int | None = None
    previous_deadline: str | None = None
    new_deadline: str | None = None
    source_clarification_id: str | None = None
    notified: list[dict[str, Any]] = Field(default_factory=list)
    # Invited firms (recipient ids) that have not acknowledged a published addendum.
    pending_recipient_ids: list[str] = Field(default_factory=list)


class ClarificationCreate(BaseModel):
    """A bidder question, entered by the buyer or through the bidder link."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(..., min_length=3, max_length=5000)
    recipient_id: str | None = Field(default=None, max_length=64)
    asked_by_email: str = Field(default="", max_length=255)


class ClarificationAnswer(BaseModel):
    """The buyer's answer to one question."""

    model_config = ConfigDict(str_strip_whitespace=True)

    answer: str = Field(..., min_length=1, max_length=10000)


class ClarificationResponse(BaseModel):
    """A question and its answer as the buyer sees it (asker included)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    number: int
    question: str
    answer: str = ""
    status: str
    recipient_id: str | None = None
    asked_by_email: str = ""
    asked_at: datetime
    answered_at: datetime | None = None
    published_at: datetime | None = None
    addendum_id: str | None = None
    # Days left between the answer (or today) and closing; None without a deadline.
    days_before_closing: int | None = None


class PublicClarification(BaseModel):
    """A published question and answer as every bidder sees it: no asker."""

    number: int
    question: str
    answer: str
    published_at: datetime | None = None


class TimelineEvent(BaseModel):
    """One dated step of a tender: issued, questions closed, addenda, closing."""

    kind: str
    at: str | None = None
    label: str = ""
    ref_id: str | None = None
    past: bool = False


class TenderTimelineResponse(BaseModel):
    """The dated steps of a package plus the rules that set them."""

    package_id: UUID
    events: list[TimelineEvent] = Field(default_factory=list)
    rules: dict[str, Any] = Field(default_factory=dict)


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
    unit_rate: FiniteDecimal = Decimal("0")

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


# ── Bidder price-entry links (public bid portal) ─────────────────────────────
# A firm on the distribution list gets a personal link that opens the bill
# without an account. Staff schemas describe the links; the ``BidPortal*``
# schemas are the only shapes the public routes read or write, and they carry
# nothing of the buyer's own pricing: no rates, sums, markups, resources,
# budget or other bidders. Field names avoid words such as ``rate`` and
# ``total`` on purpose, so a test can assert on the keys of the payload.


class PartySuggestion(BaseModel):
    """A possible party for a bidder, waiting for a person to confirm it."""

    review_id: UUID
    contact_id: UUID
    contact_name: str = ""
    method: str
    confidence: float


class PartyLink(BaseModel):
    """Body of a link request."""

    contact_id: UUID


class PartyLinkResponse(BaseModel):
    """A bidder row's party after a link or unlink."""

    entity_id: UUID
    contact_id: UUID | None = None
    contact_name: str = ""
    contact_match_method: str | None = None
    contact_match_confidence: float | None = None


class BidInvitationResponse(BaseModel):
    """One bidder link as staff see it (never the token itself)."""

    id: UUID
    package_id: UUID
    recipient_id: str
    company_name: str
    email: str
    # not_opened | opened | submitted | declined | expired | revoked
    status: str
    expires_at: datetime
    opened_at: datetime | None = None
    draft_saved_at: datetime | None = None
    submitted_at: datetime | None = None
    revoked_at: datetime | None = None
    declined_at: datetime | None = None
    decline_reason: str | None = None
    # Files the firm uploaded through its link (X84, offer PDF, attachments).
    file_count: int = 0
    bid_id: UUID | None = None
    created_at: datetime
    # Directory party of this bidder; ``contact_name`` is its display name.
    contact_id: UUID | None = None
    contact_name: str = ""
    contact_match_method: str | None = None
    contact_match_confidence: float | None = None
    # Best pending suggestion waiting for a person, if there is no link yet.
    suggestion: PartySuggestion | None = None


class BidInvitationCreated(BidInvitationResponse):
    """A freshly made link. ``url`` holds the token and is returned only here."""

    url: str
    # How many older links of this recipient the new one replaced (revoked).
    replaced_count: int = 0


class BidInvitationListResponse(BaseModel):
    """Every bidder link of a package, newest first."""

    items: list[BidInvitationResponse] = Field(default_factory=list)
    total: int = 0


class BidPortalLine(BaseModel):
    """One row of the bill as the bidder sees it: text and quantity, no price."""

    id: str
    kind: str  # "section" | "item"
    ordinal: str = ""
    short_text: str = ""
    long_text: str = ""
    unit: str = ""
    # Decimal as a string; empty for a section heading.
    quantity: str = ""
    depth: int = 0
    # Components of the line another party supplies (owner-supplied materials).
    supplied_by_others: list[str] = Field(default_factory=list)


class BidPortalDraft(BaseModel):
    """The bidder's own entries: unit prices per line id, as decimal strings."""

    unit_prices: dict[str, str] = Field(default_factory=dict)
    notes: str = ""
    saved_at: datetime | None = None
    # unit_price: the bid is the priced lines; lump_sum: one figure for the package.
    pricing_mode: str = "unit_price"
    lump_sum: str | None = None


class BidPortalFile(BaseModel):
    """A file the bidder uploaded, as shown back to the bidder and to the buyer."""

    id: UUID
    # x84 | offer_pdf | attachment
    kind: str
    file_name: str
    file_size: int = 0
    sha256: str = ""
    uploaded_at: datetime


class BidPortalDocument(BaseModel):
    """A document the buyer sent out with the package; downloaded through the link."""

    id: UUID
    name: str
    file_size: int = 0
    mime_type: str = ""
    revision_code: str | None = None


class BidPortalView(BaseModel):
    """Everything the public bid page needs, and nothing else."""

    # open | submitted | declined | closed
    state: str
    package_name: str
    package_description: str = ""
    deadline: str | None = None
    currency: str = ""
    project_name: str = ""
    buyer_name: str = ""
    # The issuing company has a document logo; the page loads it from ``logo/``.
    buyer_logo: bool = False
    bidder_company: str = ""
    expires_at: datetime
    lines: list[BidPortalLine] = Field(default_factory=list)
    draft: BidPortalDraft = Field(default_factory=BidPortalDraft)
    submitted_at: datetime | None = None
    # The bidder's own submitted sum, as a decimal string; set once submitted.
    bid_amount: str | None = None
    # Sealed mode: the receipt of the submission (UTC time stamp, SHA-256).
    sealed: bool = False
    receipt_sha256: str | None = None
    received_at: datetime | None = None
    item_count: int = 0
    unpriced_count: int = 0
    declined_at: datetime | None = None
    decline_reason: str | None = None
    files: list[BidPortalFile] = Field(default_factory=list)
    documents: list[BidPortalDocument] = Field(default_factory=list)


class BidPortalDeclineRequest(BaseModel):
    """A firm that will not bid says so, with a reason the buyer reads."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(..., min_length=1, max_length=2000)


class BidFileResponse(BidPortalFile):
    """A bidder file as staff see it, with the firm and the Documents row it is filed as."""

    invitation_id: UUID | None = None
    recipient_id: str = ""
    company_name: str = ""
    bid_id: UUID | None = None
    mime_type: str = ""
    document_id: UUID | None = None


class PackageDocumentsAttach(BaseModel):
    """Project documents to send out with a package."""

    document_ids: list[UUID] = Field(..., min_length=1, max_length=200)


class PackageDocumentResponse(BaseModel):
    """A project document attached to a package."""

    id: UUID
    document_id: UUID
    name: str
    file_size: int = 0
    mime_type: str = ""
    category: str = ""
    revision_code: str | None = None
    added_at: datetime


class BillDifference(BaseModel):
    """One way the bill moved away from the file it was imported from."""

    ordinal: str = ""
    # ordinal | unit | quantity | text | removed | added
    field: str
    was: str = ""
    now: str = ""


class BillSourceState(BaseModel):
    """The imported file behind a package's bill and whether the bill still matches it."""

    source: dict[str, Any] | None = None
    changed: bool = False
    differences: list[BillDifference] = Field(default_factory=list)
    # The awarded bid an award export (X86) is written from by default.
    awarded_bid_id: UUID | None = None
    rule_results: list[dict[str, Any]] = Field(default_factory=list)


class BidPortalPricesRequest(BaseModel):
    """Unit prices a bidder saves as a draft or submits.

    Values are parsed on the server (decimal strings preferred, ``12.5`` and
    ``12`` accepted); ``null`` or an empty string leaves a line unpriced.
    ``currency``, when sent, must be the package currency.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # Values are parsed by the service, so a JSON ``true`` stays a boolean and
    # is refused rather than coerced to 1.
    unit_prices: dict[str, Any] = Field(default_factory=dict, max_length=50_000)
    notes: str = Field(default="", max_length=2000)
    currency: str | None = Field(default=None, max_length=10)
    # ``lump_sum`` offers one figure for the whole package; unit prices, when
    # given as well, are its breakdown and the contract keeps them on the lines.
    pricing_mode: Literal["unit_price", "lump_sum"] = "unit_price"
    lump_sum: Any = None


# -- GAEB X84 bid return --------------------------------------------------------


class BuyerPricesRequest(BaseModel):
    """Unit prices the buyer enters for a bid, per line id, as decimal strings."""

    unit_prices: dict[str, str] = Field(default_factory=dict, max_length=50000)
    notes: str | None = Field(default=None, max_length=10000)


class X84LineCheck(BaseModel):
    """One priced line of an X84 file, matched against the tender's bill."""

    ordinal: str
    position_id: str | None = None
    description: str = ""
    unit: str = ""
    quantity: str = ""
    unit_rate: str | None = None
    # Stable codes: unknown_position, unit_mismatch, quantity_changed, unpriced, duplicate_position.
    issues: list[str] = Field(default_factory=list)


class X84ImportPreview(BaseModel):
    """What importing an X84 file would put into the bid comparison."""

    filename: str = ""
    sha256: str = ""
    da_kind: str = ""
    currency: str = ""
    tender_currency: str = ""
    # File level codes: not_x84, currency_mismatch, no_bill, nothing_priced.
    file_issues: list[str] = Field(default_factory=list)
    lines: list[X84LineCheck] = Field(default_factory=list)
    matched: int = 0
    priced: int = 0
    missing_ordinals: list[str] = Field(default_factory=list)
    total_amount: str = "0.00"
    blocking: bool = False
    # GAEB phase rules run on the file itself (gaeb.phase_x84_structure_valid ...).
    rule_results: list[dict[str, Any]] = Field(default_factory=list)


class ClarificationListResponse(BaseModel):
    """Page of ClarificationResponse."""

    items: list[ClarificationResponse]
    total: int
    offset: int = 0
    limit: int = 50


# ── Package header, issuing company, rejections and filing ──────────────────


class PackageHeaderUpdate(BaseModel):
    """What a buyer sets on the package header. Only the fields sent are changed."""

    legal_entity_id: UUID | None = None
    trade: str | None = Field(default=None, max_length=120)
    cost_line_id: UUID | None = None
    issue_date: date | None = None
    questions_until: date | None = None
    bids_due: date | None = None
    award_planned: date | None = None
    buyer_id: str | None = Field(default=None, max_length=36)
    estimator_id: str | None = Field(default=None, max_length=36)
    site_manager_id: str | None = Field(default=None, max_length=36)
    approver_id: str | None = Field(default=None, max_length=36)

    @field_validator("trade", mode="after")
    @classmethod
    def _strip_trade(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class IssuingEntity(BaseModel):
    """The company letters and the contract are issued in, and why it is that one."""

    id: UUID
    code: str
    name: str
    #: ``package`` when the package names it, ``project`` when it comes from the project.
    source: Literal["package", "project"]


class HeaderCostLine(BaseModel):
    id: UUID
    code: str
    description: str = ""
    #: Budget on the cost line, Decimal as string in the project currency.
    budget: str = "0"


class PackageHeaderResponse(BaseModel):
    package_id: UUID
    legal_entity_id: UUID | None = None
    trade: str | None = None
    cost_line_id: UUID | None = None
    issue_date: date | None = None
    questions_until: date | None = None
    bids_due: date | None = None
    award_planned: date | None = None
    buyer_id: str | None = None
    estimator_id: str | None = None
    site_manager_id: str | None = None
    approver_id: str | None = None
    issuing_entity: IssuingEntity | None = None
    cost_line: HeaderCostLine | None = None
    #: Package budget (bill sum or the hand-entered override), Decimal as string.
    budget: str = "0"
    currency: str = ""
    #: How many active companies the group has; the company picker shows from two.
    active_entity_count: int = 0
    #: Date order problems, e.g. ``questions_after_bids_due``.
    warnings: list[str] = Field(default_factory=list)


class RejectionRow(BaseModel):
    bid_id: UUID
    company_name: str
    email: str = ""
    notified_at: str | None = None
    #: ``pending``, ``sent``, ``failed`` or ``no_email``.
    state: str = "pending"
    last_error: str | None = None


class RejectionsPreview(BaseModel):
    package_id: UUID
    awarded: bool
    issuing_entity: IssuingEntity | None = None
    rows: list[RejectionRow] = Field(default_factory=list)
    #: Rejected bidders not told yet who can be sent a letter.
    pending: int = 0


class RejectionsSendRequest(BaseModel):
    #: Bids to send to; empty means every pending rejected bid.
    bid_ids: list[UUID] = Field(default_factory=list, max_length=500)


class RejectionsSendResponse(RejectionsPreview):
    sent: int = 0
    failed: int = 0
    filed: int = 0
    backend: str = ""
    smtp_configured: bool = False


class FiledDocument(BaseModel):
    kind: Literal["contract", "award_record", "award_letter", "rejection_letter"]
    document_id: UUID | None = None
    name: str
    #: ``filed``, ``already_filed`` or ``skipped``.
    state: str
    reason: str | None = None


class AwardFilingResponse(BaseModel):
    package_id: UUID
    documents: list[FiledDocument] = Field(default_factory=list)
