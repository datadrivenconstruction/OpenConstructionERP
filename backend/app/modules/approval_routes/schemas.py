# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval Routes Pydantic schemas - request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Mirrors the model-level whitelists so the API surface and the DB stay
# in lockstep without two sources of truth for the literal lists.
TargetKindLiteral = Literal[
    "markup",
    "submittal",
    "change_order",
    "rfi",
    "contract",
    "variation",
    "invoice",
    "purchase_order",
    "qms_hold_point",
]
StepModeLiteral = Literal["all", "any", "majority"]
InstanceStatusLiteral = Literal["pending", "approved", "rejected", "cancelled"]
StepDecisionLiteral = Literal["pending", "approved", "rejected"]


# ── Step nested payloads ─────────────────────────────────────────────


class StepCreate(BaseModel):
    """One step inside a :class:`RouteCreate` payload."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ordinal: int = Field(ge=1, le=100)
    approver_role: str | None = Field(default=None, max_length=64)
    approver_user_id: UUID | None = None
    mode: StepModeLiteral = "all"
    # Eligible-approver population for a role-based all / majority step.
    # NULL means the author did not declare a quorum; see the advance logic
    # in service._maybe_advance for the fallback.
    required_approver_count: int | None = Field(default=None, ge=1, le=100)
    sla_hours: int | None = Field(default=None, ge=1, le=720)

    @model_validator(mode="after")
    def _exactly_one_approver(self) -> StepCreate:
        if (self.approver_role is None) == (self.approver_user_id is None):
            raise ValueError(
                "Step requires exactly one of approver_role or approver_user_id",
            )
        return self


class StepResponse(BaseModel):
    """Read-side projection of a :class:`Step` row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    route_id: UUID
    ordinal: int
    approver_role: str | None
    approver_user_id: UUID | None
    mode: str
    required_approver_count: int | None
    sla_hours: int | None


# ── Route payloads ───────────────────────────────────────────────────


class RouteCreate(BaseModel):
    """Create a new approval route template (with steps)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    target_kind: TargetKindLiteral
    is_active: bool = True
    steps: list[StepCreate] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _ordinals_are_unique_and_dense(self) -> RouteCreate:
        ordinals = sorted(s.ordinal for s in self.steps)
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise ValueError(
                "Route steps must use dense 1-based ordinals (1, 2, 3, …) without gaps or duplicates",
            )
        return self


class RouteUpdate(BaseModel):
    """Patch a route's mutable surface.

    ``name`` and ``is_active`` are simple field patches. When ``steps`` is
    supplied the whole step list is *replaced* (delete-and-reinsert with
    re-densified ordinals) so the editor can add / remove / reorder steps
    in one round trip. Omitting ``steps`` (``None``) leaves the existing
    steps untouched.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    steps: list[StepCreate] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _ordinals_are_unique_and_dense(self) -> RouteUpdate:
        if self.steps is None:
            return self
        if not self.steps:
            raise ValueError("A route must keep at least one step")
        ordinals = sorted(s.ordinal for s in self.steps)
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise ValueError(
                "Route steps must use dense 1-based ordinals (1, 2, 3, …) without gaps or duplicates",
            )
        return self


class RouteResponse(BaseModel):
    """Full read-side projection of a :class:`Route` + its steps."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    name: str
    target_kind: str
    is_active: bool
    created_by: UUID | None
    # Set only on platform-seeded presets (tenant-wide read-only review flows);
    # NULL for every user-created route. The UI flags a preset from this and the
    # API rejects edits / deletes of a route that carries it.
    system_key: str | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[StepResponse] = Field(default_factory=list)


# ── Instance payloads ────────────────────────────────────────────────


class StepStateResponse(BaseModel):
    """Read-side projection of a :class:`StepState` row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    instance_id: UUID
    step_id: UUID
    approver_user_id: UUID | None
    decision: str
    comment: str | None
    decided_at: datetime | None
    created_at: datetime


class InstanceCreate(BaseModel):
    """Start a new approval workflow against a specific target row."""

    model_config = ConfigDict(str_strip_whitespace=True)

    route_id: UUID
    target_kind: TargetKindLiteral
    target_id: UUID


class InstanceResponse(BaseModel):
    """Full read-side projection of an :class:`Instance` + its step states."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    route_id: UUID
    target_kind: str
    target_id: UUID
    current_step_ordinal: int
    status: str
    started_at: datetime
    completed_at: datetime | None
    started_by: UUID | None
    # Who must act on the current step right now (the "ball in court"). NULL
    # means the step's own approver / role (or its resolved out-of-office
    # delegate) is responsible; a value is a one-tap reassignment override.
    current_assignee_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    step_states: list[StepStateResponse] = Field(default_factory=list)


class DecisionSubmit(BaseModel):
    """Approve / reject the current step on an :class:`Instance`."""

    model_config = ConfigDict(str_strip_whitespace=True)

    step_id: UUID
    decision: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=2000)


class CancelInstance(BaseModel):
    """Cancel a pending instance with an optional reason."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str | None = Field(default=None, max_length=500)


class ReassignInstance(BaseModel):
    """One-tap reassignment of an instance's current step to another user."""

    model_config = ConfigDict(str_strip_whitespace=True)

    to_user_id: UUID
    reason: str | None = Field(default=None, max_length=500)


# ── Delegation (out-of-office) payloads ──────────────────────────────


class DelegationCreate(BaseModel):
    """Create an out-of-office hand-off of the caller's approvals.

    The delegator is always the authenticated caller - never taken from the
    request body - so a user can only delegate their own approvals. ``project_id``
    NULL means a blanket hand-off across every project.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    delegate_user_id: UUID
    project_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _window_is_ordered(self) -> DelegationCreate:
        if self.starts_at is not None and self.ends_at is not None and self.ends_at < self.starts_at:
            raise ValueError("ends_at must not be before starts_at")
        return self


class DelegationResponse(BaseModel):
    """Read-side projection of a :class:`Delegation` row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    delegator_user_id: UUID
    delegate_user_id: UUID
    project_id: UUID | None
    starts_at: datetime | None
    ends_at: datetime | None
    is_active: bool
    reason: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class EscalationOut(BaseModel):
    """Escalation standing of one pending instance's current step (#17).

    ``has_sla`` is ``False`` when the instance is not pending or its current
    step has no SLA clock; ``severity`` is one of on_time / late / breached /
    critical, ``next_target`` is the approver id to escalate to now (or null),
    and ``level`` is the 1-based escalation level (0 when none is due).
    """

    instance_id: str
    target_kind: str
    current_step_ordinal: int
    has_sla: bool
    severity: str
    hours_overdue: float
    should_escalate: bool
    next_target: str | None
    level: int
    reason: str
    chain_length: int
    current_holder: str | None


# ── Dry-run simulation payloads ──────────────────────────────────────


class SimulateDecision(BaseModel):
    """One step's hypothetical decision tally for a what-if dry run.

    ``distinct_approvers`` defaults to ``approvals`` (each approval treated as
    a different person), which is the common case; set it lower to model the
    same person approving twice against an all / majority gate.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    ordinal: int = Field(ge=1, le=100)
    approvals: int = Field(default=0, ge=0, le=100)
    rejections: int = Field(default=0, ge=0, le=100)
    distinct_approvers: int | None = Field(default=None, ge=0, le=100)


class SimulateRequest(BaseModel):
    """Optional body for ``POST /routes/{id}/simulate``.

    An empty body runs only the happy path (every step approved by the minimum
    number of approvers). Supplying ``decisions`` adds a second what-if walk;
    steps left out of the list keep their happy-path minimum.
    """

    decisions: list[SimulateDecision] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _ordinals_unique(self) -> SimulateRequest:
        ordinals = [d.ordinal for d in self.decisions]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("Each step ordinal may appear at most once in decisions")
        return self


class SimulatedStep(BaseModel):
    """Per-step analysis of a route template in a dry run."""

    ordinal: int
    mode: str
    approver_role: str | None
    approver_user_id: UUID | None
    quorum_required: int | None
    min_approvals_to_clear: int
    needs_multiple_approvers: bool
    note: str


class SimulationOutcome(BaseModel):
    """Where one dry-run walk (happy path or scenario) ends up.

    ``outcome`` is ``completed`` (reaches approved), ``rejected`` (a rejection
    short-circuits the workflow) or ``stuck`` (a step never gathers enough
    approvals). ``stopped_at_ordinal`` is the step it ended on (null when it
    completed), and ``trace`` is a step-by-step human-readable explanation.
    """

    outcome: Literal["completed", "rejected", "stuck"]
    stopped_at_ordinal: int | None
    trace: list[str]


class RouteSimulationResponse(BaseModel):
    """Result of dry-running a route template."""

    route_id: UUID
    target_kind: str
    step_count: int
    steps: list[SimulatedStep]
    happy_path: SimulationOutcome
    scenario: SimulationOutcome | None = None
    warnings: list[str] = Field(default_factory=list)
