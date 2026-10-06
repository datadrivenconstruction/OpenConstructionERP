# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document Management Pydantic schemas - request/response models.

Defines create, update, and response schemas for documents.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.validation.schemas import ValidationResultItem

# The categories a project photo may hold. Uploading validated against this set
# in the service while editing validated against a pattern written out by hand,
# and the two had drifted: a photo could be uploaded as "aerial" and shown with
# its own badge and filter, but changing any photo to that category came back
# 422. Both sides read this now, so the next value added reaches both.
PHOTO_CATEGORIES: tuple[str, ...] = (
    "site",
    "progress",
    "defect",
    "delivery",
    "safety",
    "aerial",
    "other",
)
_PHOTO_CATEGORY_PATTERN = f"^({'|'.join(PHOTO_CATEGORIES)})$"

# ── Document schemas ─────────────────────────────────────────────────────


class DocumentUpdate(BaseModel):
    """Partial update for a document."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(drawing|contract|specification|photo|correspondence|reality_capture|other)$",
    )
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None

    # Phase 17: CDE / revision-chain fields
    cde_state: str | None = Field(
        default=None,
        pattern=r"^(wip|shared|published|archived)$",
    )
    suitability_code: str | None = Field(default=None, max_length=10)
    revision_code: str | None = Field(default=None, max_length=20)
    drawing_number: str | None = Field(default=None, max_length=100)
    is_current_revision: bool | None = None
    parent_document_id: UUID | None = None
    security_classification: str | None = Field(default=None, max_length=50)
    discipline: str | None = Field(
        default=None,
        pattern=r"^(architectural|structural|mechanical|electrical|plumbing|civil)$",
    )
    # ISO 19650 Gate-B precondition (SHARED → PUBLISHED). Not a stored column
    # - captured into the document's metadata compliance block by the
    # service. MVP accepts any non-empty string as a signature.
    approver_signature: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _validate_suitability_for_state(self) -> DocumentUpdate:
        """Reject a suitability code that is illegal for the target state.

        ISO 19650 suitability codes are state-scoped (S0 only in wip,
        S1-S7 in shared, A1-A5 in published, AR in archived). When a
        single PATCH carries BOTH ``cde_state`` and ``suitability_code``
        we can validate the combination here and fail fast with a 422.

        A suitability-only PATCH (no ``cde_state`` in the body) cannot be
        validated at the schema level because the document's current state
        is unknown here - the service performs that authoritative check
        against the live row. A blank code is always allowed (suitability
        is optional).
        """
        if self.cde_state and self.suitability_code:
            from app.modules.cde.suitability import validate_suitability_for_state

            ok, reason = validate_suitability_for_state(self.suitability_code, self.cde_state)
            if not ok:
                raise ValueError(reason)
        return self


class DocumentResponse(BaseModel):
    """Document returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str
    category: str
    file_size: int = 0
    mime_type: str = ""
    version: int = 1
    uploaded_by: str = ""
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # Phase 17: CDE / revision-chain fields
    cde_state: str | None = None
    suitability_code: str | None = None
    revision_code: str | None = None
    drawing_number: str | None = None
    is_current_revision: bool | None = True
    parent_document_id: UUID | None = None
    security_classification: str | None = None
    discipline: str | None = None


class DocumentListResponse(BaseModel):
    """One page of the document register plus the size of the whole set.

    ``total`` is the number of documents the filters matched and the caller is
    allowed to see, not the length of ``items``. The register is where a
    project's drawings, contracts and specifications are looked up, so a client
    that renders ``items`` without reading ``total`` shows a slice of the
    register and cannot tell the reader that it did.
    """

    items: list[DocumentResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── Summary schema ───────────────────────────────────────────────────────


class RecentUpload(BaseModel):
    """A recently uploaded document summary."""

    name: str
    uploaded_at: str
    size: int = 0


class DocumentSummary(BaseModel):
    """Aggregated document stats for a project."""

    total: int = 0
    total_documents: int = 0
    total_size_bytes: int = 0
    total_size_mb: float = 0.0
    by_category: dict[str, int] = Field(default_factory=dict)
    recent_uploads: list[RecentUpload] = Field(default_factory=list)


# ── Photo schemas ───────────────────────────────────────────────────────


class PhotoUpdate(BaseModel):
    """Partial update for a project photo."""

    model_config = ConfigDict(str_strip_whitespace=True)

    caption: str | None = None
    tags: list[str] | None = None
    category: str | None = Field(default=None, pattern=_PHOTO_CATEGORY_PATTERN)


class PhotoResponse(BaseModel):
    """Photo returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_id: str | None = None
    filename: str
    file_path: str = ""
    caption: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    tags: list[str] = Field(default_factory=list)
    taken_at: datetime | None = None
    category: str = "site"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime
    # True when a server-side thumbnail exists for this photo. Clients should
    # prefer the thumb endpoint for grid/timeline renders and only fall back
    # to the full file when this is false or the client needs the original.
    has_thumbnail: bool = False


class PhotoListResponse(BaseModel):
    """One page of site photos plus the size of the whole set.

    ``total`` counts the photos matching the query's SQL filters. The ``tag``
    filter is applied in Python after the page is read, because ``tags`` is a
    JSON column with no portable containment operator, so a tagged query
    returns a page the tag narrowed and a total it did not. That combination
    is documented on the route rather than hidden here.
    """

    items: list[PhotoResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 100


class RecentPhotoResponse(BaseModel):
    """A recent photo across the projects the caller can access.

    Powers the dashboard "Latest site photos" widget. Carries just
    enough to render a labelled thumbnail and deep-link to the owning
    project's photo gallery: the project name (joined from the projects
    table), a capture / upload date for the relative-time label, and a
    relative file URL the frontend loads through ``AuthImage``.
    """

    id: UUID
    project_id: UUID
    project_name: str
    caption: str | None = None
    category: str = "site"
    taken_at: datetime | None = None
    created_at: datetime
    # Relative API path the frontend already uses for photo thumbnails
    # (served via the authenticated thumb route, full-file fallback on a
    # missing thumbnail). Mirrors ``getPhotoThumbUrl`` in the documents
    # feature so the widget reuses the exact same URL shape.
    file_url: str


# ── Sheet schemas ──────────────────────────────────────────────────────


class SheetUpdate(BaseModel):
    """Partial update for a drawing sheet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sheet_number: str | None = Field(default=None, max_length=100)
    sheet_title: str | None = Field(default=None, max_length=500)
    discipline: str | None = Field(default=None, max_length=100)
    revision: str | None = Field(default=None, max_length=50)
    revision_date: datetime | None = None
    scale: str | None = Field(default=None, max_length=50)
    is_current: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("sheet_number", "sheet_title", "discipline", "revision", "scale", mode="after")
    @classmethod
    def _blank_is_unset(cls, value: str | None) -> str | None:
        """A field cleared in the edit form is stored as unset, not as "".

        An empty sheet number would otherwise be a value two sheets could stack
        on, and an empty revision one the order comparison would have to rank.
        """
        return value or None

    @field_validator("revision_date", mode="after")
    @classmethod
    def _date_is_utc(cls, value: datetime | None) -> datetime | None:
        """A bare date from the edit form ("2025-03-12") is that day at midnight UTC."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class SheetRereadSummary(BaseModel):
    """What re-reading a project's title blocks from the stored drawings changed."""

    sheets_checked: int = Field(description="Sheets of the project that were considered.")
    sheets_updated: int = Field(description="Sheets with at least one field changed by the re-read.")
    fields_updated: int = Field(description="Fields changed across all sheets, discipline included.")
    files_missing: int = Field(description="Sheets left as they were because their PDF could not be read.")
    current_conflicts: list[str] = Field(
        default_factory=list,
        description=(
            "Ids of sheets made current or superseded by hand whose corrected revisions say otherwise. "
            "The hand setting was kept; the sheet needs a look."
        ),
    )


class SheetResponse(BaseModel):
    """Sheet returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_id: str = ""
    page_number: int
    sheet_number: str | None = None
    sheet_title: str | None = None
    discipline: str | None = None
    revision: str | None = None
    revision_date: datetime | None = None
    scale: str | None = None
    is_current: bool = True
    previous_version_id: UUID | None = None
    thumbnail_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class SheetListResponse(BaseModel):
    """One page of the sheet index plus the size of the whole set.

    The route used to answer with a bare array and an ``X-Total-Count`` header.
    A header is invisible to a caller that reads the body, and the drawing
    index asks for the maximum page the route allows, so the response that
    holds every sheet and the response that holds the first 500 of them looked
    identical. ``total`` moves that count into the body where the register
    reads it.
    """

    items: list[SheetResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 100


class SheetVersionHistory(BaseModel):
    """Version history for a sheet - list of all revisions."""

    current: SheetResponse
    history: list[SheetResponse] = Field(default_factory=list)


# ── Sheet completeness (drawing index reconciliation) schemas ────────────


class ExpectedSheetIn(BaseModel):
    """One expected sheet supplied directly by the caller (skips parsing)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sheet_number: str = Field(min_length=1, max_length=100)
    sheet_title: str | None = Field(default=None, max_length=500)
    revision: str | None = Field(default=None, max_length=50)


class SheetCompletenessRequest(BaseModel):
    """Reconcile the project sheet set against a drawing index / issue register.

    Exactly one index source must be provided: an already-uploaded index PDF
    (``index_document_id``), a pasted sheet list (``pasted_index``), or a
    structured override (``expected_sheets``). ``index_page`` is 1-based and
    only valid together with ``index_document_id``.
    """

    project_id: UUID
    index_document_id: UUID | None = None
    index_page: int | None = Field(default=None, ge=1)
    pasted_index: str | None = None
    expected_sheets: list[ExpectedSheetIn] | None = None
    current_only: bool = True

    @model_validator(mode="after")
    def _check_single_source(self) -> SheetCompletenessRequest:
        sources = [
            self.index_document_id is not None,
            bool(self.pasted_index and self.pasted_index.strip()),
            bool(self.expected_sheets),
        ]
        if sum(sources) == 0:
            raise ValueError("Provide an index source: index_document_id, pasted_index or expected_sheets")
        if sum(sources) > 1:
            raise ValueError("Provide exactly one index source")
        if self.index_page is not None and self.index_document_id is None:
            raise ValueError("index_page requires index_document_id")
        return self


class SheetRevisionMismatchItem(BaseModel):
    """A matched sheet whose revision differs from what the index expects."""

    sheet_number: str
    expected_rev: str
    actual_rev: str


class SheetCompletenessSummary(BaseModel):
    """The reconciliation snapshot (missing / extra / matched / rev mismatch)."""

    index_source: str
    index_document_id: str | None = None
    index_page: int | None = None
    expected_count: int
    actual_count: int
    missing: list[str] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)
    matched: list[str] = Field(default_factory=list)
    rev_mismatch: list[SheetRevisionMismatchItem] = Field(default_factory=list)


class SheetCompletenessResponse(BaseModel):
    """Result of a sheet-completeness run - report summary + reconciliation."""

    report_id: UUID
    status: str
    score: float | None = None
    total_rules: int
    passed_count: int
    warning_count: int
    error_count: int
    info_count: int
    rule_sets: list[str] = Field(default_factory=list)
    duration_ms: float
    results: list[ValidationResultItem] = Field(default_factory=list)
    completeness: SheetCompletenessSummary


# ── DocumentBIMLink schemas ─────────────────────────────────────────────


class DocumentBIMLinkCreate(BaseModel):
    """Create a link between a Document and a BIM element."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: UUID
    bim_element_id: UUID
    link_type: str = Field(default="manual", max_length=50)
    confidence: str | None = Field(default=None, max_length=10)
    region_bbox: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentBIMLinkResponse(BaseModel):
    """Full DocumentBIMLink row returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    document_id: UUID
    bim_element_id: UUID
    link_type: str
    confidence: str | None = None
    region_bbox: dict[str, Any] | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class DocumentBIMLinkBrief(BaseModel):
    """Compact DocumentBIMLink for embedding inside BIMElementResponse.

    Contains just enough data for the viewer to render a link badge and
    navigate to the linked document without a second round trip.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    document_id: UUID
    document_name: str | None = None
    document_category: str | None = None
    link_type: str
    confidence: str | None = None


class DocumentBIMLinkListResponse(BaseModel):
    """List of DocumentBIMLink rows."""

    items: list[DocumentBIMLinkResponse] = Field(default_factory=list)
    total: int = 0


# ── BIMElementBrief ─────────────────────────────────────────────────────
#
# A compact BIM element shape that lives in the documents schemas module so
# DocumentResponse (and any future document-centric aggregate responses) can
# embed linked BIM elements without importing from bim_hub.schemas, which
# would introduce a circular dependency.


class BIMElementBrief(BaseModel):
    """Lightweight BIM element summary for embedding inside document responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    model_id: UUID
    element_type: str | None = None
    name: str | None = None
    storey: str | None = None
    discipline: str | None = None


# ── Activity log ─────────────────────────────────────────────────────────


class DocumentActivityResponse(BaseModel):
    """Single audit event from the per-document activity timeline."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    document_id: UUID
    user_id: str | None = None
    action: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DocumentActivityListResponse(BaseModel):
    """One page of a document's timeline plus the number of events behind it.

    The timeline is newest-first and the route caps ``limit`` at 100, so a
    document that has been through many revisions shows its recent history and
    silently drops the rest. ``total`` is what lets the drawer say so.
    """

    items: list[DocumentActivityResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 20


# ── Share links ──────────────────────────────────────────────────────────


class ShareLinkCreate(BaseModel):
    """Create a password-protected share link for a document.

    Both fields are optional:
        * ``password`` - when omitted (or empty), the link is open
          and any recipient who knows the URL can download.
        * ``expires_in_days`` - when omitted, the service defaults to
          30 days (R7 audit: previously ``None`` meant *never*, which
          is too permissive for a downloadable file URL - even with
          password protection, a leaked URL would remain valid until
          manually revoked). ``0`` is rejected as a likely typo;
          callers wanting "immediately expire" should DELETE instead.
          Maximum capped at 365 days (was 3650 / 10 years) so the
          worst-case lifetime of a leaked token is one calendar year.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    password: str | None = Field(default=None, min_length=1, max_length=128)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ShareLinkResponse(BaseModel):
    """Newly minted share link, returned to the owner."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    token: str
    url: str
    document_id: UUID
    requires_password: bool = False
    expires_at: datetime | None = None
    created_at: datetime
    download_count: int = 0
    revoked: bool = False


class ShareLinkListItem(BaseModel):
    """Compact row in the owner-only "existing links" list."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    token: str
    url: str
    requires_password: bool = False
    expires_at: datetime | None = None
    created_at: datetime
    download_count: int = 0
    revoked: bool = False


class ShareLinkPublicInfo(BaseModel):
    """Public probe response - what the recipient sees before unlocking.

    Intentionally omits ``download_count`` and ``id``/``created_by`` so
    nothing about the owner or usage history leaks to recipients.
    """

    filename: str
    requires_password: bool = False
    expired: bool = False


class ShareLinkAccessRequest(BaseModel):
    """Recipient submits this with the optional password."""

    model_config = ConfigDict(str_strip_whitespace=True)

    password: str | None = Field(default=None, max_length=128)


class ShareLinkAccessResponse(BaseModel):
    """Successful unlock - recipient receives the authenticated download URL."""

    download_url: str
    filename: str


# ── Folder permissions ───────────────────────────────────────────────────


class FolderPermissionCreate(BaseModel):
    """Owner-supplied grant payload.

    ``scope_path`` is optional - when omitted the grant applies to
    every file of ``scope_kind`` in the project (a "kind-wide"
    grant).  Empty-string and explicit ``null`` are treated the same.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: UUID
    scope_kind: str = Field(min_length=1, max_length=50)
    scope_path: str | None = Field(default=None, max_length=500)
    role: str = Field(
        default="viewer",
        pattern=r"^(viewer|editor|owner)$",
    )


class FolderPermissionResponse(BaseModel):
    """Single grant row returned by the management endpoints."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    user_id: UUID
    scope_kind: str
    scope_path: str | None = None
    role: str
    granted_by: UUID
    granted_at: datetime | None = None
    revoked: bool = False
    created_at: datetime
    updated_at: datetime
    # Pre-joined for the modal so it doesn't have to make N member lookups.
    user_email: str | None = None
    user_full_name: str | None = None


class DocumentReferenceItem(BaseModel):
    """One module's remaining hold on a document, with how many rows hold it."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    module: str
    model: str
    #: ``strands`` (NOT NULL, the row cannot record the loss), ``unlinks``
    #: (nullable or a JSON array element, the row survives without it) or
    #: ``retains`` (audit and preserved copies, meant to outlive the document).
    impact: str
    count: int


class DocumentReferencesResponse(BaseModel):
    """What still points at a document, for the delete confirmation.

    Purely informational. The delete endpoint does not consult this and is
    not blocked by it: several of these links are documented as deliberately
    severable, so the decision belongs to the person confirming.
    """

    document_id: UUID
    total: int = 0
    strands: int = 0
    unlinks: int = 0
    retains: int = 0
    references: list[DocumentReferenceItem] = Field(default_factory=list)


#: Same ceiling as :class:`app.core.bulk_ops.BulkDeleteRequest`, so anything
#: the batch delete accepts can be checked first in one call.
_BATCH_MAX_IDS = 2000


class DocumentBatchReferencesRequest(BaseModel):
    """Documents a bulk delete is about to remove."""

    ids: list[UUID] = Field(..., min_length=1, max_length=_BATCH_MAX_IDS)


class DocumentBatchReferencesResponse(BaseModel):
    """What still points at any document in a batch, for the bulk delete prompt.

    The totals and ``references`` cover the whole batch so the prompt can say
    what the whole delete costs in one panel. They count rows, each once: a
    meeting holding two of the selected documents is one record, counted under
    one reference key (the heaviest impact that reaches it), so ``references``
    adds up to ``total``. ``documents`` keeps the per-document answer (only
    documents something points at), which counts links exactly as the single
    endpoint does, so a caller can name the files responsible. ``checked`` is how many of the requested ids
    the caller may read and were looked at; ids outside it are neither counted
    nor named, so the answer never says more than reading those documents
    would.
    """

    checked: int = 0
    referenced_documents: int = 0
    total: int = 0
    strands: int = 0
    unlinks: int = 0
    retains: int = 0
    references: list[DocumentReferenceItem] = Field(default_factory=list)
    documents: list[DocumentReferencesResponse] = Field(default_factory=list)

    @property
    def severs(self) -> int:
        """Rows the delete would strand or unlink, the ones that lose something."""
        return self.strands + self.unlinks


class DocumentBatchDeleteRequest(BaseModel):
    """IDs to delete, plus the caller's word that the references were seen.

    ``acknowledge_references`` defaults to false. A batch where any document is
    still pointed at by a row that would be stranded or unlinked is refused
    with 409 and the references report until the caller sends it as true,
    the server-side form of the confirmation the single-document prompt asks
    of the person.
    """

    ids: list[UUID] = Field(..., min_length=1, max_length=_BATCH_MAX_IDS)
    acknowledge_references: bool = False
