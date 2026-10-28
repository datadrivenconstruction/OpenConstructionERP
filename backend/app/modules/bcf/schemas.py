# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠BCF module Pydantic schemas (request / response).

These are the *API* shapes. They are deliberately decoupled from the
on-the-wire BCF-XML element names (which live in :mod:`app.modules.bcf.
bcf_xml`) so the REST surface stays ergonomic while the import/export
codec stays spec-faithful.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Camera primitives ──────────────────────────────────────────────────────


class Vec3(BaseModel):
    """A 3-component vector / point (BCF XYZ triplet)."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class PerspectiveCamera(BaseModel):
    """BCF ``PerspectiveCamera``."""

    camera_view_point: Vec3 = Field(default_factory=Vec3)
    camera_direction: Vec3 = Field(default_factory=Vec3)
    camera_up_vector: Vec3 = Field(default_factory=Vec3)
    field_of_view: float = 60.0


class OrthogonalCamera(BaseModel):
    """BCF ``OrthogonalCamera``."""

    camera_view_point: Vec3 = Field(default_factory=Vec3)
    camera_direction: Vec3 = Field(default_factory=Vec3)
    camera_up_vector: Vec3 = Field(default_factory=Vec3)
    view_to_world_scale: float = 1.0


# ── Viewpoint ──────────────────────────────────────────────────────────────


class ViewpointComponents(BaseModel):
    """Component selection / visibility of a viewpoint.

    ``selection`` / ``visible`` / ``hidden`` are lists of IFC GUIDs;
    ``default_visibility`` toggles the meaning of the visibility lists per
    the BCF ``ViewSetupHints``/``Visibility`` model.
    """

    selection: list[str] = Field(default_factory=list)
    visible: list[str] = Field(default_factory=list)
    hidden: list[str] = Field(default_factory=list)
    default_visibility: bool = True


class ViewpointBase(BaseModel):
    """Shared viewpoint fields."""

    perspective_camera: PerspectiveCamera | None = None
    orthogonal_camera: OrthogonalCamera | None = None
    components: ViewpointComponents = Field(default_factory=ViewpointComponents)
    element_stable_ids: list[str] = Field(default_factory=list)


class ViewpointCreate(ViewpointBase):
    """Create a viewpoint. ``snapshot_png_b64`` is optional base64 PNG."""

    snapshot_png_b64: str | None = None


class ViewpointResponse(ViewpointBase):
    """A persisted viewpoint."""

    model_config = ConfigDict(from_attributes=True)

    guid: str
    index: int = 0
    has_snapshot: bool = False
    snapshot_url: str | None = None


# ── Comment ────────────────────────────────────────────────────────────────


class CommentCreate(BaseModel):
    """Create a comment on a topic."""

    comment: str = Field(..., min_length=1, max_length=20000)
    viewpoint_guid: str | None = None


class CommentUpdate(BaseModel):
    """Update an existing comment's text."""

    comment: str = Field(..., min_length=1, max_length=20000)


class CommentResponse(BaseModel):
    """A persisted comment."""

    model_config = ConfigDict(from_attributes=True)

    guid: str
    comment: str
    author: str | None = None
    date: datetime | None = None
    modified_author: str | None = None
    modified_date: datetime | None = None
    viewpoint_guid: str | None = None


# ── Topic ──────────────────────────────────────────────────────────────────


class TopicCreate(BaseModel):
    """Create a BCF topic."""

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    topic_type: str | None = None
    topic_status: str = "Open"
    priority: str | None = None
    stage: str | None = None
    assigned_to: str | None = None
    labels: list[str] = Field(default_factory=list)
    reference_links: list[str] = Field(default_factory=list)
    bim_model_id: str | None = None
    due_date: datetime | None = None


class TopicUpdate(BaseModel):
    """Patch a BCF topic. Every field optional - only set fields apply."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    topic_type: str | None = None
    topic_status: str | None = None
    priority: str | None = None
    stage: str | None = None
    assigned_to: str | None = None
    labels: list[str] | None = None
    reference_links: list[str] | None = None
    due_date: datetime | None = None


class TopicResponse(BaseModel):
    """A persisted BCF topic with nested comments + viewpoints."""

    model_config = ConfigDict(from_attributes=True)

    guid: str
    project_id: str
    bim_model_id: str | None = None
    title: str
    description: str | None = None
    topic_type: str | None = None
    topic_status: str = "Open"
    priority: str | None = None
    stage: str | None = None
    index: int | None = None
    assigned_to: str | None = None
    due_date: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    reference_links: list[str] = Field(default_factory=list)
    creation_author: str | None = None
    creation_date: datetime | None = None
    modified_author: str | None = None
    modified_date: datetime | None = None
    comments: list[CommentResponse] = Field(default_factory=list)
    viewpoints: list[ViewpointResponse] = Field(default_factory=list)


# ── Import report (validation is first-class) ──────────────────────────────


class BCFImportIssue(BaseModel):
    """A single structural / schema problem found while importing a bcfzip."""

    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    location: str | None = None


class BCFImportReport(BaseModel):
    """Structured result of a ``.bcfzip`` import.

    A malformed archive never raises a 500 - it returns this report with
    ``status='errors'`` and an empty ``imported_*`` set.
    """

    status: Literal["passed", "warnings", "errors"]
    detected_version: str | None = None
    topics_imported: int = 0
    topics_updated: int = 0
    comments_imported: int = 0
    viewpoints_imported: int = 0
    issues: list[BCFImportIssue] = Field(default_factory=list)


class BCFExportInfo(BaseModel):
    """Lightweight metadata echoed alongside a generated ``.bcfzip``."""

    version: str
    topic_count: int
    filename: str


class BCFExportRequest(BaseModel):
    """Body of a selective ``.bcfzip`` export.

    A model-review session ends with a hand-over of exactly the issues it
    walked, which can be a small subset of a large register. The selection
    travels in a request body rather than the query string because a GUID list
    long enough for a real review (hundreds of 36-character GUIDs) overruns the
    URL length limits of common reverse proxies.

    ``topic_guids`` omitted (or null) means "every topic", i.e. the same
    archive the ``GET`` export returns.
    """

    version: str = Field(default="2.1", description="BCF schema version to emit: '2.1' or '3.0'.")
    topic_guids: list[str] | None = Field(
        default=None,
        max_length=1000,
        description="BCF topic GUIDs to include. Omit for the whole project.",
    )


# Anything the codec wants to stash that has no first-class field.
ExtensionBag = dict[str, Any]
