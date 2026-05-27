"""OpenCDE BCF-API 3.0 — Pydantic request/response schemas.

These shapes mirror the buildingSMART OpenCDE BCF-API 3.0 JSON schemas
(``release_3_0/Schemas_draft-03``). Field NAMES use snake_case in Python
but every model is configured with ``populate_by_name=True`` and accepts
either snake_case or the spec's canonical names — so a BCF Manager
plugin (Revit / Archicad / Navisworks) that sends the wire form ``topic_status``
and ``"creation_author"`` works without translation.

Distinct from :mod:`app.modules.bcf.schemas` (the legacy native CRUD
shapes) — the OpenCDE wire format has its own field set (authorization
sub-object, server_assigned_id, project_actions, current_user) and we
keep the two surfaces decoupled so the BCF Manager protocol can evolve
independently of our internal native API.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Authorization ────────────────────────────────────────────────────────


TopicAction = Literal[
    "update",
    "updateBimSnippet",
    "updateRelatedTopics",
    "updateDocumentReferences",
    "updateFiles",
    "createComment",
    "createViewpoint",
]


class TopicAuthorization(BaseModel):
    """``authorization`` sub-object on a topic.

    Tells the BCF Manager client which verbs the current caller may use
    against THIS topic. Computed dynamically per request from the caller's
    RBAC permissions — never persisted.
    """

    topic_actions: list[TopicAction] = Field(default_factory=list)
    topic_status: list[str] = Field(default_factory=list)


class CommentAuthorization(BaseModel):
    """``authorization`` sub-object on a comment."""

    comment_actions: list[Literal["update"]] = Field(default_factory=list)


class ProjectAuthorization(BaseModel):
    """``authorization`` sub-object on a project."""

    project_actions: list[Literal["update", "createTopic"]] = Field(default_factory=list)


# ── Project / extensions / current-user ─────────────────────────────────


class BCFProject(BaseModel):
    """OpenCDE ``Project`` representation."""

    project_id: str
    name: str
    authorization: ProjectAuthorization = Field(default_factory=ProjectAuthorization)


class BCFExtensions(BaseModel):
    """OpenCDE ``Extensions`` document — the JSON twin of ``extensions.xml``.

    Lists of allowed values that the server expects on incoming topics +
    the user directory the caller can browse for ``assigned_to`` /
    ``modified_author`` autocomplete.
    """

    topic_type: list[str] = Field(default_factory=list)
    topic_status: list[str] = Field(default_factory=list)
    topic_label: list[str] = Field(default_factory=list)
    snippet_type: list[str] = Field(default_factory=list)
    priority: list[str] = Field(default_factory=list)
    user_id_type: list[str] = Field(default_factory=list)
    stage: list[str] = Field(default_factory=list)
    project_actions: list[str] = Field(default_factory=list)
    topic_actions: list[str] = Field(default_factory=list)
    comment_actions: list[str] = Field(default_factory=list)


class CurrentUser(BaseModel):
    """OpenCDE ``/current-user`` response."""

    id: str
    name: str


# ── BimSnippet ──────────────────────────────────────────────────────────


class BimSnippet(BaseModel):
    """OpenCDE ``BimSnippet``."""

    snippet_type: str
    is_external: bool = False
    reference: str
    reference_schema: str


# ── Topic ───────────────────────────────────────────────────────────────


class TopicBase(BaseModel):
    """Fields shared by topic create / update / response."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    topic_type: str | None = None
    topic_status: str | None = None
    priority: str | None = None
    stage: str | None = None
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    assigned_to: str | None = None
    due_date: date | None = None
    labels: list[str] = Field(default_factory=list)
    reference_links: list[str] = Field(default_factory=list)
    bim_snippet: BimSnippet | None = None


class TopicCreatePayload(TopicBase):
    """Payload of ``POST /projects/{id}/topics``."""


class TopicUpdatePayload(BaseModel):
    """Payload of ``PUT /projects/{id}/topics/{guid}`` — every field optional."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    topic_type: str | None = None
    topic_status: str | None = None
    priority: str | None = None
    stage: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    assigned_to: str | None = None
    due_date: date | None = None
    labels: list[str] | None = None
    reference_links: list[str] | None = None
    bim_snippet: BimSnippet | None = None


class BCFTopicResponse(TopicBase):
    """``GET /projects/{id}/topics`` element + single-topic response."""

    guid: str
    server_assigned_id: str | None = None
    creation_author: str | None = None
    creation_date: datetime | None = None
    modified_author: str | None = None
    modified_date: datetime | None = None
    authorization: TopicAuthorization = Field(default_factory=TopicAuthorization)


# ── Comment ─────────────────────────────────────────────────────────────


class CommentCreatePayload(BaseModel):
    """Payload of ``POST .../topics/{guid}/comments``."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    comment: str = Field(..., min_length=1, max_length=20000)
    viewpoint_guid: str | None = None
    reply_to_comment_guid: str | None = None


class CommentUpdatePayload(BaseModel):
    """Payload of ``PUT .../comments/{guid}``."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    comment: str = Field(..., min_length=1, max_length=20000)


class BCFCommentResponse(BaseModel):
    """OpenCDE Comment response."""

    model_config = ConfigDict(populate_by_name=True)

    guid: str
    date: datetime | None = None
    author: str | None = None
    modified_date: datetime | None = None
    modified_author: str | None = None
    comment: str
    topic_guid: str
    viewpoint_guid: str | None = None
    reply_to_comment_guid: str | None = None
    authorization: CommentAuthorization = Field(default_factory=CommentAuthorization)


# ── Viewpoint ───────────────────────────────────────────────────────────


class Point(BaseModel):
    """A 3-component point — OpenCDE Point shape."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Direction(BaseModel):
    """A 3-component direction — OpenCDE Direction shape."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class PerspectiveCamera(BaseModel):
    """OpenCDE PerspectiveCamera."""

    model_config = ConfigDict(populate_by_name=True)

    camera_view_point: Point = Field(default_factory=Point)
    camera_direction: Direction = Field(default_factory=Direction)
    camera_up_vector: Direction = Field(default_factory=Direction)
    field_of_view: float = 60.0
    aspect_ratio: float = 1.0


class OrthogonalCamera(BaseModel):
    """OpenCDE OrthogonalCamera."""

    model_config = ConfigDict(populate_by_name=True)

    camera_view_point: Point = Field(default_factory=Point)
    camera_direction: Direction = Field(default_factory=Direction)
    camera_up_vector: Direction = Field(default_factory=Direction)
    view_to_world_scale: float = 1.0
    aspect_ratio: float = 1.0


class ClippingPlane(BaseModel):
    """OpenCDE ClippingPlane."""

    location: Point = Field(default_factory=Point)
    direction: Direction = Field(default_factory=Direction)


class Line(BaseModel):
    """OpenCDE Line — annotation geometry."""

    start_point: Point = Field(default_factory=Point)
    end_point: Point = Field(default_factory=Point)


class BitmapPayload(BaseModel):
    """OpenCDE Bitmap reference."""

    bitmap_type: Literal["jpg", "png"] = "png"
    bitmap_data: str = ""
    location: Point = Field(default_factory=Point)
    normal: Direction = Field(default_factory=Direction)
    up: Direction = Field(default_factory=Direction)
    height: float = 1.0


class VisibilityExceptions(BaseModel):
    """``Components/Visibility/Exceptions`` — list of component refs."""

    component: list[dict[str, Any]] = Field(default_factory=list)


class Visibility(BaseModel):
    """``Components/Visibility`` setting."""

    default_visibility: bool = True
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
    view_setup_hints: dict[str, Any] | None = None


class Components(BaseModel):
    """OpenCDE Components — selection + visibility + colouring."""

    model_config = ConfigDict(populate_by_name=True)

    selection: list[dict[str, Any]] = Field(default_factory=list)
    visibility: Visibility = Field(default_factory=Visibility)
    coloring: list[dict[str, Any]] = Field(default_factory=list)


class SnapshotInfo(BaseModel):
    """``snapshot`` block on a viewpoint — metadata only.

    The image bytes are NOT returned inline: the dedicated
    ``GET .../snapshot`` endpoint streams the raw ``image/png``.
    """

    snapshot_type: Literal["png", "jpg"] = "png"
    snapshot_data: str | None = None  # base64 on POST; null on GET-list


class ViewpointCreatePayload(BaseModel):
    """Payload of ``POST .../viewpoints``."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    guid: str | None = None
    perspective_camera: PerspectiveCamera | None = None
    orthogonal_camera: OrthogonalCamera | None = None
    lines: list[Line] = Field(default_factory=list)
    clipping_planes: list[ClippingPlane] = Field(default_factory=list)
    bitmaps: list[BitmapPayload] = Field(default_factory=list)
    components: Components | None = None
    snapshot: SnapshotInfo | None = None


class ViewpointResponse(BaseModel):
    """OpenCDE Viewpoint response."""

    model_config = ConfigDict(populate_by_name=True)

    guid: str
    index: int = 0
    perspective_camera: PerspectiveCamera | None = None
    orthogonal_camera: OrthogonalCamera | None = None
    lines: list[Line] = Field(default_factory=list)
    clipping_planes: list[ClippingPlane] = Field(default_factory=list)
    bitmaps: list[BitmapPayload] = Field(default_factory=list)
    components: Components | None = None
    snapshot: SnapshotInfo | None = None


# ── List / collection envelope ──────────────────────────────────────────


class TopicListResponse(BaseModel):
    """Envelope for paged topic lists."""

    items: list[BCFTopicResponse] = Field(default_factory=list)


class CommentListResponse(BaseModel):
    """Envelope for paged comment lists."""

    items: list[BCFCommentResponse] = Field(default_factory=list)


class ViewpointListResponse(BaseModel):
    """Envelope for viewpoint lists."""

    items: list[ViewpointResponse] = Field(default_factory=list)


class ProjectListResponse(BaseModel):
    """Envelope for project lists."""

    items: list[BCFProject] = Field(default_factory=list)


# ── Errors ──────────────────────────────────────────────────────────────


class OpenCDEError(BaseModel):
    """OpenCDE ``Error`` response."""

    code: str
    message: str
    detail: str | None = None
