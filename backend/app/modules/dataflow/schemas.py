# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataflow response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ObjectCount(BaseModel):
    """Row count of one object type inside a project."""

    object: str
    count: int = Field(ge=0)


class ModuleCounts(BaseModel):
    """Counters contributed by one module."""

    module: str
    installed: bool
    objects: list[ObjectCount] = Field(default_factory=list)
    reason: str | None = None


class ProjectCounts(BaseModel):
    """Counts per module for one project."""

    project_id: uuid.UUID
    generated_at: datetime
    modules: list[ModuleCounts]


class Live(BaseModel):
    """Live numbers of one path or entity for the active project."""

    count: int | None = None
    value: str | None = Field(default=None, description="Sum or latest value, decimal string")
    latest_at: str | None = None
    state: str = Field(default="ok", description="ok|stale|broken|no_access|not_installed|unknown|hidden")
    stale_count: int | None = None
    active: bool = Field(default=False, description="Records changed in the last 7 days")
    reason: str | None = None


class EntityOut(BaseModel):
    id: str
    model: str
    label: str
    route: str
    measure: str
    live: Live


class PathOut(BaseModel):
    id: str
    direction: str
    module: str
    entity: str
    via: str
    label: str
    measure: str
    measure_field: str | None = None
    route: str
    importance: str
    breaks: str
    live: Live


class ParamOut(BaseModel):
    field: str
    label: str
    drives: list[str]
    drives_paths: list[str] = Field(default_factory=list)


class StaleOut(BaseModel):
    source: str
    copy_field: str
    label: str
    path_id: str | None = None
    count: int | None = None


class EdgeOut(BaseModel):
    source: str
    target: str
    kind: str
    details: list[str] = Field(default_factory=list)
    importance: str = "supporting"
    label: str = ""
    count: int | None = None
    active: bool = False
    state: str = "ok"


class ModulePaths(BaseModel):
    """Everything the drawer draws for one module."""

    module: str
    declared: bool
    installed: bool
    why: str = ""
    roles: list[str] = Field(default_factory=list)
    project_id: uuid.UUID | None = None
    currency: str = ""
    entities: list[EntityOut] = Field(default_factory=list)
    paths: list[PathOut] = Field(default_factory=list)
    parameters: list[ParamOut] = Field(default_factory=list)
    stale: list[StaleOut] = Field(default_factory=list)
    technical: list[EdgeOut] = Field(default_factory=list)
    neighbours: list[str] = Field(default_factory=list)
    generated_at: datetime


class MapModule(BaseModel):
    name: str
    display_name: str
    category: str
    declared: bool
    installed: bool
    why: str = ""
    roles: list[str] = Field(default_factory=list)
    count: int | None = Field(default=None, description="Records of the declared entities in the project")
    counts: dict[str, int] = Field(default_factory=dict)


class HealthItem(BaseModel):
    module: str
    path_id: str
    source: str
    label: str
    importance: str
    breaks: str
    missing: str = Field(default="", description="i18n key of the plain sentence for this gap")
    upstream: str = Field(default="", description="Module the data comes from")
    downstream: str = Field(default="", description="Module that has to act; the Fix link opens it")


class PlatformMap(BaseModel):
    """All visible modules and their data flows, with live counts on declared edges."""

    project_id: uuid.UUID | None = None
    currency: str = ""
    modules: list[MapModule]
    edges: list[EdgeOut]
    health: list[HealthItem] = Field(default_factory=list)
    generated_at: datetime


class PartyOut(BaseModel):
    id: str
    kind: str
    name: str
    initials: str
    zone: str
    roles: list[str]
    modules: list[str]
    placeholder: bool = False
    primary_role: str = ""
    touches: dict[str, int] = Field(default_factory=dict, description="Records per module that name this party")
    org: str | None = Field(default=None, description="Party id of the organisation a person works for")


class ProjectParties(BaseModel):
    project_id: uuid.UUID
    parties: list[PartyOut]
