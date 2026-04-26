# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request/response schemas for the EAC v2 CRUD API.

Kept separate from :mod:`app.modules.eac.schemas` (which mirrors the
canonical ``EacRuleDefinition`` JSON Schema) so transport concerns —
pagination, soft-delete, version-history rendering — don't pollute
the canonical types that ship to the frontend type generator.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.eac.schemas import EacRuleDefinition

# ── Common ───────────────────────────────────────────────────────────────


class _ApiBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Rule ────────────────────────────────────────────────────────────────


class EacRuleCreate(BaseModel):
    """Payload for ``POST /rules``."""

    model_config = ConfigDict(extra="forbid")

    ruleset_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    output_mode: str = Field(description="aggregate | boolean | clash | issue")
    definition_json: dict[str, Any] = Field(default_factory=dict)
    formula: str | None = None
    result_unit: str | None = None
    tags: list[str] = Field(default_factory=list)
    project_id: UUID | None = None


class EacRuleUpdate(BaseModel):
    """Payload for ``PUT /rules/{id}``. All fields optional."""

    model_config = ConfigDict(extra="forbid")

    ruleset_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    output_mode: str | None = None
    definition_json: dict[str, Any] | None = None
    formula: str | None = None
    result_unit: str | None = None
    tags: list[str] | None = None
    is_active: bool | None = None
    change_reason: str | None = Field(
        default=None,
        description="Optional human-readable reason saved on the rule version row",
    )


class EacRuleRead(_ApiBase):
    """Response shape for a rule."""

    id: UUID
    ruleset_id: UUID | None = None
    name: str
    description: str | None = None
    output_mode: str
    definition_json: dict[str, Any] = Field(default_factory=dict)
    formula: str | None = None
    result_unit: str | None = None
    tags: list[str] = Field(default_factory=list)
    version: int
    is_active: bool
    tenant_id: UUID
    project_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by_user_id: UUID | None = None
    updated_by_user_id: UUID | None = None


# ── Ruleset ─────────────────────────────────────────────────────────────


class EacRulesetCreate(BaseModel):
    """Payload for ``POST /rulesets``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    kind: str = Field(default="mixed", description="boq | validation | clash_matrix | schedule_link | mixed")
    classifier_id: UUID | None = None
    parent_ruleset_id: UUID | None = None
    project_id: UUID | None = None
    is_template: bool = False
    is_public_in_marketplace: bool = False
    tags: list[str] = Field(default_factory=list)


class EacRulesetUpdate(BaseModel):
    """Payload for ``PUT /rulesets/{id}``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    kind: str | None = None
    classifier_id: UUID | None = None
    parent_ruleset_id: UUID | None = None
    is_template: bool | None = None
    is_public_in_marketplace: bool | None = None
    tags: list[str] | None = None


class EacRulesetRead(_ApiBase):
    """Response shape for a ruleset."""

    id: UUID
    name: str
    description: str | None = None
    kind: str
    classifier_id: UUID | None = None
    parent_ruleset_id: UUID | None = None
    tenant_id: UUID
    project_id: UUID | None = None
    is_template: bool
    is_public_in_marketplace: bool
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── Validate-rule endpoint ──────────────────────────────────────────────


class EacRuleValidateRequest(BaseModel):
    """Payload for ``POST /rules:validate``.

    Accepts either a fully-formed ``EacRuleDefinition`` or a raw JSON dict
    (the latter is what the frontend sends before the user clicks save).
    """

    model_config = ConfigDict(extra="forbid")

    definition_json: dict[str, Any]


class EacRuleValidationError(BaseModel):
    """Single validation error returned by the validator."""

    code: str
    path: str
    message: str
    message_i18n_key: str | None = None


class EacRuleValidateResponse(BaseModel):
    """Response from ``POST /rules:validate``."""

    valid: bool
    errors: list[EacRuleValidationError] = Field(default_factory=list)


# ── List filters ────────────────────────────────────────────────────────


class EacRuleListFilters(BaseModel):
    """Optional filter parameters for ``GET /rules``."""

    model_config = ConfigDict(extra="forbid")

    ruleset_id: UUID | None = None
    project_id: UUID | None = None
    output_mode: str | None = None
    is_active: bool | None = None
    tag: str | None = None
    search: str | None = Field(
        default=None,
        description="Substring match against rule name/description",
    )
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# ── Runs (EAC-1.4 / RFC 35 §1.7) ────────────────────────────────────────


class EacDryRunRequest(BaseModel):
    """Payload for ``POST /rules:dry-run``.

    Carries the rule body the user is editing plus a small list of
    ad-hoc elements to evaluate against. No DB lookups, no persistence.
    """

    model_config = ConfigDict(extra="forbid")

    definition_json: dict[str, Any]
    elements: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=5000,
        description="Canonical element rows to evaluate against (≤5000)",
    )


class EacRunElementResult(BaseModel):
    """One per-element verdict in a dry-run response."""

    element_id: str
    passed: bool | None = Field(
        default=None,
        description="True/false for boolean+issue modes; None for aggregate",
    )
    attribute_snapshot: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class EacRunIssueResult(BaseModel):
    """One issue rendered by ``output_mode='issue'``."""

    element_id: str
    title: str
    description: str | None = None
    topic_type: str
    priority: str
    stage: str | None = None
    labels: list[str] = Field(default_factory=list)
    attribute_snapshot: dict[str, Any] = Field(default_factory=dict)


class EacRunAggregateResult(BaseModel):
    """Single scalar produced by ``output_mode='aggregate'``."""

    value: Any
    result_unit: str | None = None
    elements_evaluated: int


class EacDryRunResponse(BaseModel):
    """Response from ``POST /rules:dry-run``."""

    output_mode: str
    elements_evaluated: int
    elements_matched: int
    elements_passed: int
    boolean_results: list[EacRunElementResult] = Field(default_factory=list)
    issue_results: list[EacRunIssueResult] = Field(default_factory=list)
    aggregate_result: EacRunAggregateResult | None = None
    errors: list[str] = Field(default_factory=list)


class EacRunRulesetRequest(BaseModel):
    """Payload for ``POST /rulesets/{id}:run``.

    Either ``elements`` is supplied directly (small models / tests) or
    ``model_id`` is set, in which case the runner loads BIMElement rows
    from the BIM hub. ``triggered_by`` defaults to ``manual`` for the
    interactive UI path.
    """

    model_config = ConfigDict(extra="forbid")

    model_id: UUID | None = None
    model_version_id: UUID | None = None
    elements: list[dict[str, Any]] | None = Field(
        default=None,
        max_length=100_000,
        description="Inline canonical elements (overrides model_id when set)",
    )
    triggered_by: Literal[
        "manual", "scheduled", "webhook", "auto_on_upload"
    ] = "manual"


class EacRunRead(_ApiBase):
    """Top-level run record."""

    id: UUID
    ruleset_id: UUID
    model_version_id: UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str
    summary_json: dict[str, Any] | None = None
    elements_evaluated: int
    elements_matched: int
    error_count: int
    triggered_by: str


class EacRunResultItemRead(_ApiBase):
    """One element-level result row."""

    id: UUID
    run_id: UUID
    rule_id: UUID
    element_id: str
    pass_: bool | None = Field(default=None, alias="pass_")
    attribute_snapshot: dict[str, Any] | None = None
    result_value: dict[str, Any] | None = None
    error: str | None = None


# ── Engine API completeness (RFC 35 §1.7 / task #221) ───────────────────


class EacCompileRequest(BaseModel):
    """Payload for ``POST /rules:compile``.

    Validates and compiles a draft rule body into an executable plan
    without persistence. Used by the rule editor's "Show plan" panel.
    """

    model_config = ConfigDict(extra="forbid")

    definition_json: dict[str, Any]


class EacCompileResponse(BaseModel):
    """Output of ``POST /rules:compile`` and ``POST /plans/describe``.

    Mirrors :class:`engine.api.CompiledPlan` but in JSON-serialisable
    form so the frontend type generator emits a stable shape.
    """

    valid: bool
    duckdb_sql: str
    projection_columns: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    post_python_step: str | None = None
    estimated_cost: int = 0
    issues: list[dict[str, Any]] = Field(default_factory=list)


class EacRunStatusResponse(BaseModel):
    """Output of ``GET /runs/{run_id}/status``.

    ``progress`` is in ``[0.0, 1.0]`` — the frontend renders it as a
    percentage with one decimal. ``errors`` is a flat list of human
    readable strings sourced from each rule outcome so the run-detail
    header can show "Rule 'F90' — formula crashed at row 42" without
    drilling.
    """

    run_id: UUID
    status: str
    progress: float
    elements_evaluated: int
    elements_matched: int
    error_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    errors: list[str] = Field(default_factory=list)


class EacRunCancelResponse(BaseModel):
    """Output of ``POST /runs/{run_id}:cancel``."""

    run_id: UUID
    cancelled: bool
    status: str


class EacRunRerunRequest(BaseModel):
    """Payload for ``POST /runs/{run_id}:rerun``.

    The caller supplies the elements explicitly — the engine doesn't
    persist the original input set, and rebuilding it from the BIM
    model is the responsibility of the caller (router resolves
    ``model_id`` → elements; tests pass them inline).
    """

    model_config = ConfigDict(extra="forbid")

    elements: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=100_000,
        description="Inline canonical elements to evaluate against",
    )
    triggered_by: Literal[
        "manual", "scheduled", "webhook", "auto_on_upload"
    ] = "manual"


class EacRunDiffResponse(BaseModel):
    """Output of ``GET /runs/{run_a}:diff/{run_b}``."""

    run_id_a: UUID
    run_id_b: UUID
    elements_only_in_a: list[str] = Field(default_factory=list)
    elements_only_in_b: list[str] = Field(default_factory=list)
    flipped_pass_to_fail: list[str] = Field(default_factory=list)
    flipped_fail_to_pass: list[str] = Field(default_factory=list)
    unchanged_count: int = 0


__all__ = [
    "EacCompileRequest",
    "EacCompileResponse",
    "EacDryRunRequest",
    "EacDryRunResponse",
    "EacRuleCreate",
    "EacRuleDefinition",  # re-export for convenience
    "EacRuleListFilters",
    "EacRuleRead",
    "EacRuleUpdate",
    "EacRuleValidateRequest",
    "EacRuleValidateResponse",
    "EacRuleValidationError",
    "EacRunAggregateResult",
    "EacRunCancelResponse",
    "EacRunDiffResponse",
    "EacRunElementResult",
    "EacRunIssueResult",
    "EacRunRead",
    "EacRunRerunRequest",
    "EacRunResultItemRead",
    "EacRunRulesetRequest",
    "EacRunStatusResponse",
    "EacRulesetCreate",
    "EacRulesetRead",
    "EacRulesetUpdate",
]
