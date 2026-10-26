# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes for scheduling profiles and profile recalculation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_PROGRESS_MODE = r"^(retained_logic|progress_override|actual_dates)$"
_LAG_CALENDAR = r"^(elapsed|predecessor|successor|project)$"
_OPEN_ENDS = r"^(project_finish|own_finish)$"
_CRITICAL_RULE = r"^(total_float|longest_path)$"


class SchedulingProfileCreate(BaseModel):
    """Create a scheduling profile for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    is_default: bool = False
    progress_mode: str = Field(default="retained_logic", pattern=_PROGRESS_MODE)
    lag_calendar: str = Field(default="elapsed", pattern=_LAG_CALENDAR)
    open_ends: str = Field(default="project_finish", pattern=_OPEN_ENDS)
    critical_rule: str = Field(default="total_float", pattern=_CRITICAL_RULE)
    critical_float_threshold: int = Field(default=0, ge=0, le=365)


class SchedulingProfileUpdate(BaseModel):
    """Partial update of a scheduling profile."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    is_default: bool | None = None
    progress_mode: str | None = Field(default=None, pattern=_PROGRESS_MODE)
    lag_calendar: str | None = Field(default=None, pattern=_LAG_CALENDAR)
    open_ends: str | None = Field(default=None, pattern=_OPEN_ENDS)
    critical_rule: str | None = Field(default=None, pattern=_CRITICAL_RULE)
    critical_float_threshold: int | None = Field(default=None, ge=0, le=365)


class SchedulingProfileResponse(BaseModel):
    """A stored scheduling profile."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    description: str = ""
    is_default: bool = False
    progress_mode: str
    lag_calendar: str
    open_ends: str
    critical_rule: str
    critical_float_threshold: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileAssignRequest(BaseModel):
    """Choose the profile a schedule recalculates with; ``None`` = project default."""

    profile_id: UUID | None = None


class RecalculateRequest(BaseModel):
    """Recalculate with a profile; ``None`` uses the schedule's own profile."""

    profile_id: UUID | None = None


class ProfileSettings(BaseModel):
    """The effective settings of a recalculation."""

    progress_mode: str
    lag_calendar: str
    open_ends: str
    critical_rule: str
    critical_float_threshold: int


class EffectiveProfileResponse(BaseModel):
    """Which profile a schedule uses and where that choice comes from."""

    schedule_id: UUID
    profile_id: UUID | None = None
    profile_name: str | None = None
    source: str = Field(description="schedule | project_default | builtin")
    settings: ProfileSettings


class RecalculatedActivity(BaseModel):
    """One activity's dates before and after a profile recalculation."""

    activity_id: UUID
    activity_code: str | None = None
    name: str
    current_start: str | None = None
    current_end: str | None = None
    new_start: str
    new_end: str
    start_shift_days: int = 0
    finish_shift_days: int = 0
    total_float: int = 0
    was_critical: bool = False
    is_critical: bool = False
    completed: bool = False
    started: bool = False
    out_of_sequence: bool = False
    on_longest_path: bool = False
    open_start: bool = False
    open_finish: bool = False
    changed_by: list[str] = Field(
        default_factory=list,
        description="Settings whose value moved this activity: progress_mode, lag_calendar, status, "
        "open_ends, critical_rule, critical_float_threshold",
    )


class RecalculateResponse(BaseModel):
    """Result of a preview or an applied recalculation."""

    schedule_id: UUID
    applied: bool = False
    profile_id: UUID | None = None
    profile_name: str | None = None
    source: str
    settings: ProfileSettings
    data_date: str | None = None
    current_finish: str | None = None
    new_finish: str | None = None
    changed_count: int = 0
    critical_count: int = 0
    out_of_sequence_count: int = 0
    open_end_count: int = 0
    setting_effects: dict[str, int] = Field(
        default_factory=dict, description="How many activities each setting changed"
    )
    activities: list[RecalculatedActivity] = Field(default_factory=list)
