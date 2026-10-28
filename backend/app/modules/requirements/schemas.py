# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Requirements & Quality Gates Pydantic schemas - request/response models.

Defines create, update, and response schemas for requirement sets,
individual requirements (EAC triplets), and quality gate results.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.requirements.intl import PRIORITY_ORDER
from app.modules.requirements.lifecycle import (
    DEFAULT_VOCABULARY,
    ORIGINATOR_ROLES,
    PHASE_SPINE,
    VERIFICATION_METHODS,
    VOCABULARIES,
)


def _one_of(values: tuple[str, ...] | list[str]) -> str:
    """Anchored alternation over a controlled vocabulary.

    Built from the vocabulary itself rather than typed out again. A pattern
    written by hand drifts from the list it is supposed to mirror, and this
    module has already paid for that once: the priority pattern accepted ``may``
    while the label catalog knew ``could`` and ``wont``, so one value rendered
    as a raw key in all forty languages and two were unreachable through the API.
    """
    return "^(?:" + "|".join(values) + ")$"


#: MoSCoW, from the label catalog, plus the legacy spelling. ``may`` was what
#: this API accepted before the catalog existed; it means ``could`` and is kept
#: so requests and rows written against the old pattern keep working.
LEGACY_PRIORITY = "may"
_PRIORITY_PATTERN = _one_of((*PRIORITY_ORDER, LEGACY_PRIORITY))
_PHASE_PATTERN = _one_of(("", *PHASE_SPINE))
_VERIFICATION_PATTERN = _one_of(("", *VERIFICATION_METHODS))
_ORIGINATOR_ROLE_PATTERN = _one_of(("", *ORIGINATOR_ROLES))
_VOCABULARY_PATTERN = _one_of(tuple(VOCABULARIES))
_LINK_SOURCE_PATTERN = _one_of(("manual", "import", "ai", "migrated"))

# ── Requirement schemas ─────────────────────────────────────────────────────


class RequirementCreate(BaseModel):
    """Create a new EAC requirement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity: str = Field(..., min_length=1, max_length=255)
    attribute: str = Field(..., min_length=1, max_length=255)
    constraint_type: str = Field(
        default="equals",
        pattern=r"^(equals|not_equals|min|max|range|contains|not_contains|regex|exists|not_exists)$",
    )
    constraint_value: str = Field(default="", max_length=500)
    unit: str = Field(default="", max_length=50)
    category: str = Field(default="general", max_length=100)
    priority: str = Field(default="must", pattern=_PRIORITY_PATTERN)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_ref: str = Field(default="", max_length=500)

    # ── The five questions the EAC triplet does not answer ──────────────────
    rationale: str = Field(default="", description="Why this is required at all")
    originator: str = Field(default="", max_length=255, description="Who raised it")
    originator_role: str = Field(default="", pattern=_ORIGINATOR_ROLE_PATTERN)
    phase: str = Field(default="", pattern=_PHASE_PATTERN, description="Project phase key, never a display word")
    verification_method: str = Field(default="", pattern=_VERIFICATION_PATTERN)
    parent_requirement_id: UUID | None = None

    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequirementUpdate(BaseModel):
    """Partial update for a requirement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    entity: str | None = Field(default=None, min_length=1, max_length=255)
    attribute: str | None = Field(default=None, min_length=1, max_length=255)
    constraint_type: str | None = Field(
        default=None,
        pattern=r"^(equals|not_equals|min|max|range|contains|not_contains|regex|exists|not_exists)$",
    )
    constraint_value: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    priority: str | None = Field(default=None, pattern=_PRIORITY_PATTERN)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_ref: str | None = Field(default=None, max_length=500)
    status: str | None = Field(
        default=None,
        pattern=r"^(open|verified|linked|conflict)$",
    )

    rationale: str | None = None
    originator: str | None = Field(default=None, max_length=255)
    originator_role: str | None = Field(default=None, pattern=_ORIGINATOR_ROLE_PATTERN)
    phase: str | None = Field(default=None, pattern=_PHASE_PATTERN)
    verification_method: str | None = Field(default=None, pattern=_VERIFICATION_PATTERN)
    #: Explicitly settable to null, so a decomposed requirement can be detached
    #: from its parent. ``None`` therefore cannot mean "leave alone" here, and
    #: the service reads ``model_fields_set`` to tell the two apart.
    parent_requirement_id: UUID | None = None

    notes: str | None = None
    metadata: dict[str, Any] | None = None


class RequirementResponse(BaseModel):
    """Requirement item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence_from_text(cls, value: Any) -> Any:
        """The column stores the text of a float; unreadable text is no answer.

        Returns ``None`` rather than raising. A malformed confidence is a
        property of one historic row, and refusing to serialise the requirement
        over it would hide the twenty fields that are fine.
        """
        if value is None or isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    id: UUID
    requirement_set_id: UUID
    entity: str
    attribute: str
    constraint_type: str
    constraint_value: str
    unit: str = ""
    category: str = "general"
    priority: str = "must"
    confidence: float | None = None
    source_ref: str = ""
    status: str = "open"
    linked_position_id: UUID | None = None

    rationale: str = ""
    originator: str = ""
    originator_role: str = ""
    phase: str = ""
    verification_method: str = ""
    parent_requirement_id: UUID | None = None
    #: Every position this requirement governs, the legacy single link folded
    #: in, so a client never has to read two fields to get one answer.
    linked_position_ids: list[UUID] = Field(default_factory=list)
    #: Which of the six questions are still unanswered, and how far along the
    #: requirement is. Computed, so a screen can show the gap without knowing
    #: the rule, and an export can be sorted by it.
    unanswered_questions: list[str] = Field(default_factory=list)
    cycle_completeness: float = 0.0

    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Position link schemas (Womit) ───────────────────────────────────────────


class PositionLinkCreate(BaseModel):
    """Attach one requirement to one priced BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    position_id: UUID
    link_source: str = Field(default="manual", pattern=_LINK_SOURCE_PATTERN)
    notes: str = ""


class PositionLinkResponse(BaseModel):
    """A requirement-to-position link returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    requirement_id: UUID
    position_id: UUID
    link_source: str = "manual"
    confirmed_by: str = ""
    notes: str = ""
    created_at: datetime
    updated_at: datetime


# ── Vocabulary schemas ──────────────────────────────────────────────────────


class VocabularyTerm(BaseModel):
    """One term, in the wording and language the caller asked for."""

    key: str
    label: str


class PhaseOption(BaseModel):
    """A phase on the neutral spine, named in each stage system that has it.

    ``systems`` omits a system that does not name this phase separately rather
    than carrying an empty string for it, so a caller can tell "RIBA has no
    permit stage" from "RIBA calls it nothing".
    """

    key: str
    label: str
    rank: int
    systems: dict[str, str] = Field(default_factory=dict)


class CycleVocabularyResponse(BaseModel):
    """Everything a screen needs to render the cycle in one language.

    Served instead of shipping these words in the frontend bundle: the phase
    spine, the verification methods and the party roles are domain data that
    changes with the platform, not with the design.
    """

    vocabulary: str
    language: str
    terms: list[VocabularyTerm] = Field(default_factory=list)
    phases: list[PhaseOption] = Field(default_factory=list)
    verification_methods: list[VocabularyTerm] = Field(default_factory=list)
    originator_roles: list[VocabularyTerm] = Field(default_factory=list)
    priorities: list[VocabularyTerm] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


# ── RequirementSet schemas ──────────────────────────────────────────────────


class RequirementSetCreate(BaseModel):
    """Create a new requirement set."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    source_type: str = Field(
        default="manual",
        pattern=r"^(manual|pdf|cad|bim|specification)$",
    )
    source_filename: str = Field(default="", max_length=500)
    #: Which wording this project reads its requirements in. Renames concepts
    #: and never changes which ones exist, so it is safe to flip at any time.
    vocabulary: str = Field(default=DEFAULT_VOCABULARY, pattern=_VOCABULARY_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequirementSetUpdate(BaseModel):
    """Partial update for a requirement set.

    All fields are optional - pass only what should change.  Project
    re-assignment is intentionally NOT supported here (sets are
    project-scoped at creation; moving them would silently break
    every BIM/BOQ link they own).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    source_type: str | None = Field(
        default=None,
        pattern=r"^(manual|pdf|cad|bim|specification)$",
    )
    source_filename: str | None = Field(default=None, max_length=500)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|active|locked|archived)$",
    )
    vocabulary: str | None = Field(default=None, pattern=_VOCABULARY_PATTERN)
    metadata: dict[str, Any] | None = None


class RequirementBulkDeleteRequest(BaseModel):
    """Body of the bulk-delete endpoint.

    A single transaction deletes every requirement whose id is in the
    list.  Ids that do not belong to the path's ``set_id`` are silently
    skipped - the endpoint reports the actual delete count so callers
    can detect that case.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    requirement_ids: list[UUID] = Field(..., min_length=1, max_length=500)


class RequirementBulkDeleteResult(BaseModel):
    """Response from the bulk-delete endpoint."""

    deleted_count: int = 0
    skipped_count: int = 0


class RequirementSetResponse(BaseModel):
    """Requirement set returned from the API (without nested requirements)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str = ""
    source_type: str = "manual"
    source_filename: str = ""
    status: str = "draft"
    vocabulary: str = DEFAULT_VOCABULARY
    gate_status: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class RequirementSetDetail(BaseModel):
    """Requirement set with nested requirements and gate results."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str = ""
    source_type: str = "manual"
    source_filename: str = ""
    status: str = "draft"
    vocabulary: str = DEFAULT_VOCABULARY
    gate_status: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    requirements: list[RequirementResponse] = Field(default_factory=list)
    gate_results: list["GateResultResponse"] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── GateResult schemas ──────────────────────────────────────────────────────


class GateResultResponse(BaseModel):
    """Quality gate result returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    requirement_set_id: UUID
    gate_number: int
    gate_name: str
    status: str = "skipped"
    score: float = 0.0
    findings: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


# ── Stats schemas ───────────────────────────────────────────────────────────


class RequirementStats(BaseModel):
    """Aggregated requirement stats for a project."""

    total_requirements: int = 0
    total_sets: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    linked_count: int = 0
    unlinked_count: int = 0


# ── Text import schema ─────────────────────────────────────────────────────


class TextImportRequest(BaseModel):
    """Request body for importing requirements from structured text."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(..., min_length=1)
    set_name: str = Field(default="Imported Requirements", max_length=255)
    default_category: str = Field(default="general", max_length=100)
    default_priority: str = Field(
        default="must",
        pattern=r"^(must|should|may)$",
    )


# ── EIR Deliverable schemas (T13) ──────────────────────────────────────────


# BIMForum LOD vocabulary + the ISO 19650 LOI vocabulary. Stored as
# free strings under the hood (label "LOD 350" vs raw "350" varies by
# template) but validated here so the matrix view doesn't need to
# render "LOD undefined" cells.
_LOD_PATTERN = r"^(100|200|300|350|400|500)$"
_LOI_PATTERN = r"^[1-5]$"
_DELIVERABLE_TYPE_PATTERN = r"^(model|drawing|schedule|report|cobie|pset|other)$"


class DeliverableCreate(BaseModel):
    """Create a new EIR deliverable row for a requirement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    deliverable_type: str = Field(..., pattern=_DELIVERABLE_TYPE_PATTERN, max_length=64)
    lod: str | None = Field(default=None, pattern=_LOD_PATTERN)
    loi: str | None = Field(default=None, pattern=_LOI_PATTERN)
    due_milestone_id: UUID | None = None
    submitted_at: datetime | None = None
    accepted_at: datetime | None = None
    notes: str = ""


class DeliverableUpdate(BaseModel):
    """Partial update for an EIR deliverable row."""

    model_config = ConfigDict(str_strip_whitespace=True)

    deliverable_type: str | None = Field(default=None, pattern=_DELIVERABLE_TYPE_PATTERN, max_length=64)
    lod: str | None = Field(default=None, pattern=_LOD_PATTERN)
    loi: str | None = Field(default=None, pattern=_LOI_PATTERN)
    due_milestone_id: UUID | None = None
    submitted_at: datetime | None = None
    accepted_at: datetime | None = None
    notes: str | None = None


class DeliverableResponse(BaseModel):
    """EIR deliverable row returned from the API.

    The ``status`` field is derived server-side from the timestamps
    (``accepted`` if ``accepted_at`` is set, else ``submitted`` if
    ``submitted_at`` is set, else ``missing``) - the matrix view's
    cell colouring reads it directly.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    requirement_id: UUID
    deliverable_type: str
    lod: str | None = None
    loi: str | None = None
    due_milestone_id: UUID | None = None
    submitted_at: datetime | None = None
    accepted_at: datetime | None = None
    notes: str = ""
    status: str = "missing"
    created_at: datetime
    updated_at: datetime


class DeliverableTypeCoverage(BaseModel):
    """Per-type coverage breakdown returned inside the coverage summary."""

    total: int = 0
    submitted: int = 0
    accepted: int = 0
    missing: int = 0


class DeliverableCoverage(BaseModel):
    """Coverage summary for one requirement's deliverables."""

    requirement_id: UUID
    total: int = 0
    submitted: int = 0
    accepted: int = 0
    missing: int = 0
    coverage_pct: float = 0.0
    by_type: dict[str, DeliverableTypeCoverage] = Field(default_factory=dict)


class MatrixCell(BaseModel):
    """A single (requirement × deliverable-type) cell in the EIR matrix."""

    deliverable_id: UUID | None = None
    lod: str | None = None
    loi: str | None = None
    status: str = "missing"
    due_milestone_id: UUID | None = None
    submitted_at: datetime | None = None
    accepted_at: datetime | None = None


class MatrixRow(BaseModel):
    """A single row of the EIR matrix - one requirement + its cells."""

    requirement_id: UUID
    requirement_set_id: UUID
    entity: str
    attribute: str
    priority: str = "must"
    # The BOQ position this requirement is linked to, if any. Surfaced so the
    # matrix can show a clickable "BOQ" chip deep-linking to /boq.
    linked_position_id: UUID | None = None
    cells: dict[str, MatrixCell] = Field(default_factory=dict)
    coverage_pct: float = 0.0


class MatrixResponse(BaseModel):
    """Full project EIR matrix returned from the API."""

    project_id: UUID
    deliverable_types: list[str] = Field(default_factory=list)
    rows: list[MatrixRow] = Field(default_factory=list)
    coverage_pct: float = 0.0
