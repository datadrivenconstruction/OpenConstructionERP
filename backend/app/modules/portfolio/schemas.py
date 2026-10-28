# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the portfolio tree (T3.3).

Pure (pydantic + stdlib) so it imports and unit-tests on the local runner.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal["portfolio", "programme", "subprogramme"]


class NodeCreate(BaseModel):
    """Create a portfolio / programme node."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    node_type: NodeType = "programme"
    code: str = Field(default="", max_length=50)
    parent_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0)
    metadata: dict = Field(default_factory=dict)


class NodePatch(BaseModel):
    """Partial update of a node (rename / reparent / reorder).

    A supplied ``parent_id`` of ``null`` moves the node to the root; omitting
    ``parent_id`` leaves the parent unchanged (distinguished via
    ``model_fields_set`` in the service).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    node_type: NodeType | None = None
    code: str | None = Field(default=None, max_length=50)
    parent_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=0)


class NodeResponse(BaseModel):
    """A portfolio node as returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    parent_id: UUID | None
    node_type: str
    name: str
    code: str
    owner_id: UUID | None
    sort_order: int
    metadata: dict = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class AttachProjectRequest(BaseModel):
    """Attach a project to a node (the project must be accessible to the caller)."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID


class TreeNode(BaseModel):
    """A node in the access-pruned portfolio tree."""

    id: UUID
    parent_id: UUID | None = None
    node_type: str
    name: str
    code: str = ""
    sort_order: int = 0
    project_ids: list[UUID] = Field(default_factory=list)
    children: list[TreeNode] = Field(default_factory=list)


TreeNode.model_rebuild()


DepType = Literal["FS", "SS", "FF", "SF"]


class CrossLinkCreate(BaseModel):
    """Create a cross-schedule dependency between two activities."""

    model_config = ConfigDict(extra="forbid")

    predecessor_schedule_id: UUID
    predecessor_activity_id: UUID
    successor_schedule_id: UUID
    successor_activity_id: UUID
    dep_type: DepType = "FS"
    lag_days: int = 0


class CrossLinkResponse(BaseModel):
    """A cross-schedule dependency as returned from the API.

    The four ``*_name`` fields name what the four ids point at. They are
    resolved here rather than on the page because an endpoint can sit in a
    different schedule, and often a different project, from the one being
    listed: a client would need one request per row to name them, where the
    API needs two selects for the whole page. A name is ``None`` when the
    schedule or activity behind the id no longer exists, which a link can
    outlive - the id stays on the wire so the reader keeps a handle on a
    dependency that has lost its target.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    predecessor_schedule_id: UUID
    predecessor_activity_id: UUID
    predecessor_schedule_name: str | None = None
    predecessor_activity_name: str | None = None
    successor_schedule_id: UUID
    successor_activity_id: UUID
    successor_schedule_name: str | None = None
    successor_activity_name: str | None = None
    dep_type: str
    lag_days: int
    created_at: datetime
    updated_at: datetime


class PortfolioCpmActivity(BaseModel):
    """One activity's CPM result on the shared portfolio timeline (work-days)."""

    schedule_id: UUID
    activity_id: UUID
    schedule_name: str = ""
    activity_name: str = ""
    es: int
    ef: int
    ls: int
    lf: int
    total_float: int
    is_critical: bool


class PortfolioCpmResponse(BaseModel):
    """Portfolio (schedule-of-schedules) CPM result for a node's subtree."""

    node_id: UUID
    schedule_count: int
    activity_count: int
    project_finish_workday: int
    cross_links_applied: int
    cross_links_omitted: int
    critical_path: list[PortfolioCpmActivity] = Field(default_factory=list)
    activities: list[PortfolioCpmActivity] = Field(default_factory=list)
