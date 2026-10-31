# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board request and response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CARD_KIND = "^(crew|worker|equipment|rental)$"
LOCATION_KIND = "^(project|yard|shop|rental_return)$"
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LocationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="project", pattern=LOCATION_KIND)
    project_id: uuid.UUID | None = None
    sort_order: int = Field(default=0, ge=0, le=100000)


class LocationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class LocationResponse(_Out):
    id: uuid.UUID
    name: str
    kind: str
    project_id: uuid.UUID | None
    sort_order: int
    is_active: bool


class CrewCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str = Field(min_length=1, max_length=255)
    foreman_resource_id: uuid.UUID | None = None
    foreman_user_id: uuid.UUID | None = None
    member_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    min_size: int = Field(default=0, ge=0, le=200)
    trade: str = Field(default="", max_length=120)
    labor_crew_id: uuid.UUID | None = None


class CrewUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    foreman_resource_id: uuid.UUID | None = None
    foreman_user_id: uuid.UUID | None = None
    member_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    min_size: int | None = Field(default=None, ge=0, le=200)
    trade: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class CrewResponse(_Out):
    id: uuid.UUID
    name: str
    foreman_resource_id: str | None
    foreman_user_id: uuid.UUID | None
    member_ids: list[str]
    min_size: int
    trade: str
    labor_crew_id: uuid.UUID | None
    is_active: bool


class CardRef(BaseModel):
    card_kind: str = Field(pattern=CARD_KIND)
    card_ref: str = Field(min_length=1, max_length=36)


class PlaceRequest(BaseModel):
    """Put one or more cards on a column for a day (multi-select drop)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    day: date
    location_id: uuid.UUID
    cards: list[CardRef] = Field(min_length=1, max_length=200)
    start_time: str = Field(default="07:00", pattern=HHMM)
    notes: str = Field(default="", max_length=2000)
    operator_ref: str | None = Field(default=None, max_length=36)


class MoveRequest(BaseModel):
    placement_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    to_location_id: uuid.UUID


class PlacementUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    start_time: str | None = Field(default=None, pattern=HHMM)
    notes: str | None = Field(default=None, max_length=2000)
    operator_ref: str | None = Field(default=None, max_length=36)


class RemoveRequest(BaseModel):
    placement_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class CopyDayRequest(BaseModel):
    from_day: date
    to_day: date
    replace: bool = False


class ScheduleMoveRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    card_kind: str = Field(pattern=CARD_KIND)
    card_ref: str = Field(min_length=1, max_length=36)
    to_location_id: uuid.UUID
    effective_date: date
    start_time: str = Field(default="07:00", pattern=HHMM)
    notes: str = Field(default="", max_length=2000)


class ScheduledMoveResponse(_Out):
    id: uuid.UUID
    card_kind: str
    card_ref: str
    to_location_id: uuid.UUID
    effective_date: date
    start_time: str
    notes: str
    status: str
    applied_at: datetime | None


class PlacementResponse(BaseModel):
    id: uuid.UUID
    day: date
    card_kind: str
    card_ref: str
    location_id: uuid.UUID
    operator_ref: str | None
    start_time: str
    notes: str
    source: str
    label: str
    subtitle: str = ""
    status: str = ""
    members: list[dict[str, str]] = Field(default_factory=list)
    conflict_kinds: list[str] = Field(default_factory=list)


class ConflictResponse(BaseModel):
    kind: str
    card_kind: str
    card_ref: str
    message: str
    severity: str
    placement_ids: list[str]
    details: dict[str, Any] = Field(default_factory=dict)


class BoardResponse(BaseModel):
    day: date
    locations: list[LocationResponse]
    placements: list[PlacementResponse]
    conflicts: list[ConflictResponse]
    pending_moves: list[ScheduledMoveResponse]
    applied_moves: int = 0


class WeekDay(BaseModel):
    day: date
    placements: list[PlacementResponse]
    conflict_count: int


class WeekResponse(BaseModel):
    start: date
    locations: list[LocationResponse]
    days: list[WeekDay]


class Card(BaseModel):
    card_kind: str
    card_ref: str
    label: str
    subtitle: str = ""
    status: str = ""


class CardListResponse(BaseModel):
    items: list[Card]
    total: int
    limit: int
    offset: int


class PlanLine(BaseModel):
    location: str
    location_id: uuid.UUID
    card_kind: str
    who_or_what: str
    operator: str = ""
    start_time: str
    notes: str


class ForemanPlan(BaseModel):
    foreman: str
    foreman_user_id: uuid.UUID | None
    lines: list[PlanLine]


class DailyPlanResponse(BaseModel):
    day: date
    plans: list[ForemanPlan]


class ShareResponse(BaseModel):
    day: date
    notified: int
    without_user: list[str]


class PrefillRequest(BaseModel):
    location_id: uuid.UUID
    day: date
    hours: Decimal = Field(default=Decimal("8"), ge=0, le=24)


class PrefillResponse(BaseModel):
    timesheet_id: uuid.UUID
    reference: str
    created: bool
    lines_added: int


class UtilisationRow(BaseModel):
    unit_ref: str
    card_kind: str
    label: str
    days_assigned: int
    days_idle: int
    working_days: int
    percent: int
    assigned_days: list[str]


class UtilisationResponse(BaseModel):
    start: date
    end: date
    items: list[UtilisationRow]


class ViewPref(BaseModel):
    card_density: str = Field(default="detailed", pattern="^(compact|detailed)$")
    settings: dict[str, Any] = Field(default_factory=dict)


class ValidationResponse(BaseModel):
    day: date
    status: str
    checked: int
    results: list[dict[str, Any]]
