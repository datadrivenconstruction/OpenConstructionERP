# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Forms & Checklists Pydantic schemas - request / response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.forms.conditional import CONDITION_OPERATORS
from app.modules.forms.validation import CATEGORIES, FIELD_TYPES

# Build the regex alternations from the single source of truth in validation.py /
# conditional.py so a new field type / category / operator only has to be added
# in one place.
_FIELD_TYPE_PATTERN = "^(" + "|".join(FIELD_TYPES) + ")$"
_CATEGORY_PATTERN = "^(" + "|".join(CATEGORIES) + ")$"
_OPERATOR_PATTERN = "^(" + "|".join(CONDITION_OPERATORS) + ")$"


class ConditionExpr(BaseModel):
    """A branching rule attached to a field via ``visible_if`` / ``required_if``.

    It is either a single comparison (``field`` + ``op`` [+ ``value``]) or a
    boolean group of nested expressions - ``all`` (every one holds) or ``any`` (at
    least one holds). Only operators in
    :data:`app.modules.forms.conditional.CONDITION_OPERATORS` are accepted; the
    pure evaluator in that module is the runtime source of truth.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    field: str | None = Field(default=None, max_length=60, description="Key of the field this rule reads.")
    op: str | None = Field(default=None, pattern=_OPERATOR_PATTERN, description="Comparison operator.")
    value: Any = Field(default=None, description="Value compared against (unused by empty / not_empty).")
    all: list["ConditionExpr"] | None = Field(default=None, description="Every sub-expression must hold.")
    any: list["ConditionExpr"] | None = Field(default=None, description="At least one sub-expression must hold.")


ConditionExpr.model_rebuild()


class FormField(BaseModel):
    """One field in a template. Mirrors the pure-layer field dict.

    ``key`` is optional on input - the service derives a stable unique key from
    the label when it is omitted (see :func:`validation.normalize_fields`).
    ``visible_if`` / ``required_if`` carry optional branching logic (see
    :class:`ConditionExpr`).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    key: str | None = Field(default=None, max_length=60)
    type: str = Field(..., pattern=_FIELD_TYPE_PATTERN)
    label: str = Field(default="", max_length=500)
    required: bool = False
    help_text: str | None = Field(default=None, max_length=1000)
    options: list[str] = Field(default_factory=list)
    unit: str | None = Field(default=None, max_length=40)
    max_rating: int | None = Field(default=None, ge=2, le=10)
    # Per-field capture config. All optional; the service keeps only the ones that
    # apply to the field's type (see validation.normalize_fields).
    placeholder: str | None = Field(default=None, max_length=200)
    default: Any = Field(default=None, description="Prefilled default answer.")
    min: float | None = Field(default=None, description="Minimum for a number field.")
    max: float | None = Field(default=None, description="Maximum for a number field.")
    min_length: int | None = Field(default=None, ge=0, description="Minimum length for a text field.")
    pattern: str | None = Field(default=None, max_length=300, description="Regex a text answer must match.")
    formula: str | None = Field(default=None, max_length=512, description="Expression for a computed field.")
    visible_if: ConditionExpr | None = Field(default=None, description="Show this field only while the rule holds.")
    required_if: ConditionExpr | None = Field(default=None, description="Require this field only while the rule holds.")


# ── Templates ────────────────────────────────────────────────────────────────


class TemplateCreate(BaseModel):
    """Create a reusable template. Omit ``project_id`` for a global library one."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    category: str = Field(default="custom", pattern=_CATEGORY_PATTERN)
    status: str = Field(default="published", pattern=r"^(draft|published|archived)$")
    fields: list[FormField] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TemplateUpdate(BaseModel):
    """Partial update for a template. Supplying ``fields`` bumps the version."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, pattern=_CATEGORY_PATTERN)
    status: str | None = Field(default=None, pattern=r"^(draft|published|archived)$")
    fields: list[FormField] | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class TemplateResponse(BaseModel):
    """A template returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None = None
    name: str
    description: str | None = None
    category: str
    status: str
    version: int
    fields: list[dict[str, Any]] = Field(default_factory=list, validation_alias="fields_data")
    tags: list[str] = Field(default_factory=list)
    is_seed: bool = False
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class TemplateSummary(BaseModel):
    """A lighter template row for the library list (no field payload)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    name: str
    description: str | None = None
    category: str
    status: str
    version: int
    field_count: int = 0
    tags: list[str] = Field(default_factory=list)
    is_seed: bool = False
    updated_at: datetime


# ── Submissions ──────────────────────────────────────────────────────────────


class SubmissionCreate(BaseModel):
    """Start a submission by filling a template into a project.

    Answers are optional at create time (a submission usually starts as a draft
    and is filled in progressively), keyed by field key.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    template_id: UUID
    title: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=500)
    answers: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmissionUpdate(BaseModel):
    """Save progress on a draft submission."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=500)
    answers: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class CompleteSubmissionRequest(BaseModel):
    """Optionally patch answers, then validate and complete."""

    model_config = ConfigDict(str_strip_whitespace=True)

    answers: dict[str, Any] | None = None


class SubmissionResponse(BaseModel):
    """A submission returned from the API, including its frozen template snapshot."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    template_id: UUID | None = None
    submission_number: str
    template_name: str
    template_category: str
    template_version: int
    template_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    title: str | None = None
    location: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict, validation_alias="answers_data")
    status: str
    result: str | None = None
    completed_at: str | None = None
    completed_by: str | None = None
    linked_inspection_id: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class SubmissionSummary(BaseModel):
    """A lighter submission row for the list view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    submission_number: str
    template_name: str
    template_category: str
    title: str | None = None
    location: str | None = None
    status: str
    result: str | None = None
    completed_at: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Shared error / meta payloads ─────────────────────────────────────────────


class FieldIssueOut(BaseModel):
    """A single validation issue, surfaced in a 422 detail payload."""

    field_index: int
    field_key: str | None = None
    code: str
    message: str


class CategoryInfo(BaseModel):
    """Metadata for one template category (for the library filter chips)."""

    key: str
    label: str
    template_count: int = 0
