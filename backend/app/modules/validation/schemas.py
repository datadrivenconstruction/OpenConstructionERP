# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation Pydantic schemas - request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

# ── Result item (single rule check) ────────────────────────────────


class ValidationResultItem(BaseModel):
    """A single validation rule result within a report."""

    rule_id: str
    status: str = Field(description="pass, warning, error")
    message: str
    element_ref: str | None = None
    details: dict[str, Any] | None = None
    suggestion: str | None = None


# ── Report ────────────────────────────────────────────────────────────────


class ValidationReportCreate(BaseModel):
    """Schema for creating a validation report manually (rare - prefer /run)."""

    project_id: UUID
    target_type: str = Field(description="boq, document, cad_import, tender")
    target_id: str
    rule_set: str = Field(description="e.g. 'din276+gaeb+boq_quality'")


class ValidationReportResponse(BaseModel):
    """Full validation report returned by the API."""

    id: UUID
    project_id: UUID
    target_type: str
    target_id: str
    rule_set: str
    status: str
    score: str | None = None
    total_rules: int = 0
    passed_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime | None = None
    # NB: SQLAlchemy declarative reserves `metadata` for the class-level
    # MetaData() registry, so reading `report.metadata` returns the
    # SQLAlchemy registry object - not our column.  We use AliasChoices
    # to make Pydantic try `metadata_` (the python attribute name) FIRST
    # when `from_attributes=True` is on, falling back to `metadata` for
    # the JSON-input case.
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
        serialization_alias="metadata",
    )

    model_config = {"from_attributes": True, "populate_by_name": True}


# ── Run validation ────────────────────────────────────────────────────────


class RunValidationRequest(BaseModel):
    """Request body for POST /validation/run."""

    project_id: UUID
    boq_id: UUID
    rule_sets: list[str] = Field(
        default=["boq_quality"],
        description="Rule set names to apply, e.g. ['boq_quality', 'din276']",
    )


class RunValidationResponse(BaseModel):
    """Response from POST /validation/run - report summary + full results."""

    report_id: UUID
    status: str
    score: float | None = None
    total_rules: int
    passed_count: int
    warning_count: int
    error_count: int
    info_count: int
    rule_sets: list[str]
    # Which of the requested rule sets actually executed vs were not
    # implemented/unknown. Surfacing these lets the dashboard distinguish
    # "ran and passed" from "never ran" instead of silently treating an
    # unsupported set as a clean pass.
    supported_rule_sets: list[str] = Field(default_factory=list)
    unsupported_rule_sets: list[str] = Field(default_factory=list)
    duration_ms: float
    results: list[ValidationResultItem]


# ── BIM per-element validation ────────────────────────────────────────────


class CheckBIMModelRequest(BaseModel):
    """Request body for POST /validation/check-bim-model.

    ``rule_ids`` is optional; if omitted the full enabled set of universal
    BIM element rules runs.
    """

    model_id: UUID
    rule_ids: list[str] | None = Field(
        default=None,
        description=(
            "Optional subset of BIMElementRule ids to run "
            "(e.g. ['bim.wall.has_thickness']). None runs all enabled rules."
        ),
    )


# ── Rule sets ─────────────────────────────────────────────────────────────


class RuleSetInfo(BaseModel):
    """Information about an available rule set."""

    name: str
    description: str
    rule_count: int
    rules: list[dict[str, Any]] = Field(default_factory=list)


# ── Cross-project validation status (portfolio view) ─────────────────────


class PortfolioEstimateStatus(BaseModel):
    """The current validation verdict of one estimate (BOQ) in a project.

    The verdict rests on every report that is still the newest one for at
    least one rule set it ran, so a narrow run (the one-click audit) does not
    clear findings of a broader run it did not repeat. ``state`` is the worst
    of those reports. It is ``not_validated`` whenever there is no report, or
    the reports did not actually check anything (pending, skipped, unsupported
    rule sets, no rules run), so an estimate nobody validated can never read
    as passed.

    ``report_id``, ``report_status``, ``score`` and ``validated_at`` describe
    the report that drives the verdict, the one a link should open. The counts
    add up the reports behind the verdict; where two of them ran the same rule
    set, that overlap is counted from both.
    """

    boq_id: UUID
    boq_name: str
    state: str = Field(description="errors, warnings, not_validated, info or passed")
    report_id: UUID | None = None
    report_status: str | None = Field(
        default=None, description="Raw status of the report that drives the verdict, if any"
    )
    rule_sets: list[str] = Field(default_factory=list)
    unsupported_rule_sets: list[str] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    passed_count: int = 0
    total_rules: int = 0
    score: float | None = None
    validated_at: datetime | None = None


class PortfolioProjectStatus(BaseModel):
    """One project's validation standing, taken from its estimates' verdicts.

    ``state`` is the worst state among the estimates, and ``not_validated``
    for a project that has no estimates at all. The counts add up the reports
    behind each estimate's verdict, never the superseded report history.
    """

    project_id: UUID
    project_name: str
    state: str
    estimate_count: int = 0
    validated_count: int = 0
    not_validated_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    passed_count: int = 0
    rule_sets: list[str] = Field(default_factory=list)
    last_validated_at: datetime | None = None
    estimates: list[PortfolioEstimateStatus] = Field(default_factory=list)


class PortfolioStateSummary(BaseModel):
    """How many projects sit in each state."""

    errors: int = 0
    warnings: int = 0
    not_validated: int = 0
    info: int = 0
    passed: int = 0


class ValidationPortfolioResponse(BaseModel):
    """Response of GET /validation/portfolio-status/, projects sorted worst first."""

    project_count: int = 0
    summary: PortfolioStateSummary = Field(default_factory=PortfolioStateSummary)
    projects: list[PortfolioProjectStatus] = Field(default_factory=list)
