# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic request/response schemas for progress rigor (T3.2).

Dependency-free (pydantic + stdlib only) so it imports and unit-tests on the
local runner. Money-named response fields (``planned_value`` / ``earned_value``
/ ``budget_at_completion``) are :class:`~decimal.Decimal` and serialise to JSON
as strings, per the platform's money discipline; weights and percents are plain
ratios and serialise as numbers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

#: The three percent-complete types (mirrors ``progress_math``); first = default.
PctType = Literal["physical", "duration", "units"]


class TypedProgressRequest(BaseModel):
    """Set progress on an activity, routed through the per-type engine.

    ``percent_complete_type`` defaults to the activity's current type when
    omitted. ``percent`` is the driver for ``duration`` and the fallback for
    ``physical`` (ignored when steps exist); ``installed_units`` /
    ``budgeted_units`` drive ``units``; ``remaining_duration`` is honoured only
    for ``physical`` (the one type where percent and remaining may diverge).
    """

    model_config = ConfigDict(extra="forbid")

    percent_complete_type: PctType | None = None
    percent: float | None = Field(default=None, ge=0.0, le=100.0)
    installed_units: Decimal | None = Field(default=None, ge=0)
    budgeted_units: Decimal | None = Field(default=None, ge=0)
    remaining_duration: int | None = Field(default=None, ge=0)
    data_date: str | None = Field(default=None, max_length=40)


class PercentTypeRequest(BaseModel):
    """Change an activity's percent-complete type (preview distortion first)."""

    model_config = ConfigDict(extra="forbid")

    percent_complete_type: PctType


class StepCreate(BaseModel):
    """Create a weighted progress step."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    weight: Decimal = Field(default=Decimal("1"), ge=0)
    percent_complete: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    sort_order: int = Field(default=0, ge=0)
    is_milestone: bool = False


class StepPatch(BaseModel):
    """Partial update of a progress step (only supplied fields change)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    weight: Decimal | None = Field(default=None, ge=0)
    percent_complete: Decimal | None = Field(default=None, ge=0, le=100)
    sort_order: int | None = Field(default=None, ge=0)
    is_milestone: bool | None = None


class StepResponse(BaseModel):
    """A progress step as returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_id: UUID
    name: str
    weight: float
    percent_complete: float
    sort_order: int
    is_milestone: bool


class SuspendRequest(BaseModel):
    """Suspend an in-progress / not-started activity, freezing remaining work."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(default="", max_length=2000)
    effective_date: str | None = Field(default=None, max_length=40)


class ResumeRequest(BaseModel):
    """Resume a suspended activity, rescheduling from the frozen remaining work."""

    model_config = ConfigDict(extra="forbid")

    effective_date: str | None = Field(default=None, max_length=40)


class CalendarSetRequest(BaseModel):
    """Attach (or clear, with ``null``) a per-activity working calendar."""

    model_config = ConfigDict(extra="forbid")

    calendar_id: UUID | None = None


class ProgressResultResponse(BaseModel):
    """The resolved progress state plus any deterministic EVM-distortion warnings."""

    activity_id: UUID
    percent_complete_type: str
    percent_complete: float
    remaining_duration: int
    forecast_finish: str
    status: str
    evm_warnings: list[str] = Field(default_factory=list)
    # The stored unit quantities and suspension state, so the progress panel can
    # prefill its inputs from this one response. Without the units a save that
    # only edits "installed" would send an empty "budgeted" back as zero.
    installed_units: Decimal | None = None
    budgeted_units: Decimal | None = None
    suspended_at: str | None = None
    suspend_reason: str | None = None

    @field_serializer("installed_units", "budgeted_units", when_used="json")
    def _serialize_units(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class PercentTypePreviewResponse(BaseModel):
    """Result of changing the percent-complete type (warnings previewed)."""

    activity_id: UUID
    percent_complete_type: str
    evm_warnings: list[str] = Field(default_factory=list)


class ActivityProgressStateResponse(BaseModel):
    """Compact progress-relevant view of an activity (suspend/resume/calendar)."""

    id: UUID
    schedule_id: UUID
    status: str
    progress_pct: float
    percent_complete_type: str
    remaining_duration: int | None
    start_date: str
    end_date: str
    calendar_id: UUID | None
    suspended_at: str | None
    resumed_at: str | None
    suspend_reason: str | None


class PlannedValueResponse(BaseModel):
    """Time-phased planned value preview at an arbitrary data date (read-only).

    ``planned_value`` is the time-phased PV / BCWS (not BAC); ``earned_value``
    is the method-aware EV from each activity's resolved percent; values lie in
    ``[0, budget_at_completion]`` inside the schedule window.
    """

    schedule_id: UUID
    as_of: str
    planned_value: Decimal
    earned_value: Decimal
    budget_at_completion: Decimal
    activity_count: int

    @field_serializer("planned_value", "earned_value", "budget_at_completion", when_used="json")
    def _serialize_money(self, value: Decimal) -> str:
        return str(value)
