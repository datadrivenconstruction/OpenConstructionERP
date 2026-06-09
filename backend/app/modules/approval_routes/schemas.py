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
