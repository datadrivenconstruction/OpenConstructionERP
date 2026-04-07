"""OpenCDE / BCF 3.0 Pydantic schemas.

These schemas match the BuildingSMART BCF API 3.0 specification.
They are intentionally separate from our internal schemas — the service
layer handles mapping between internal and BCF-standard formats.

References:
    - https://github.com/buildingSMART/BCF-API/tree/release/bcf/3.0
    - https://technical.buildingsmart.org/standards/bcf/
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Foundation API 1.1 ──────────────────────────────────────────────────


class FoundationAPIVersion(BaseModel):
    """A single supported API version."""

    api_id: str
    version_id: str
    detailed_version: str | None = None


class FoundationVersions(BaseModel):
    """Response for GET /foundation/versions."""

    versions: list[FoundationAPIVersion]


class FoundationAuth(BaseModel):
    """Response for GET /foundation/1.1/auth — authentication endpoints."""

    oauth2_auth_url: str = ""
    oauth2_token_url: str = ""
    http_basic_supported: bool = False
    supported_oauth2_flows: list[str] = Field(default_factory=list)


class BCFUser(BaseModel):
    """Current user info in BCF format."""

    id: str
    name: str
    email: str | None = None


# ── BCF 3.0 Projects ───────────────────────────────────────────────────


class BCFProject(BaseModel):
    """BCF-format project representation."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(..., alias="project_id")
    name: str


class BCFProjectList(BaseModel):
    """List of BCF projects."""

    projects: list[BCFProject] = Field(default_factory=list)


# ── BCF 3.0 Topics ─────────────────────────────────────────────────────


class BCFTopic(BaseModel):
    """BCF-format topic (maps to our collaboration comments with entity_type='bcf_topic')."""

    model_config = ConfigDict(populate_by_name=True)

    guid: str
    topic_type: str = ""
    topic_status: str = ""
    title: str
    description: str = ""
    priority: str = ""
    creation_date: datetime | None = None
    creation_author: str = ""
    modified_date: datetime | None = None
    modified_author: str = ""
    assigned_to: str = ""
    labels: list[str] = Field(default_factory=list)
    reference_links: list[str] = Field(default_factory=list)


class BCFTopicCreate(BaseModel):
    """Create a new BCF topic."""

    title: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    topic_type: str = ""
    topic_status: str = "Open"
    priority: str = ""
    assigned_to: str = ""
    labels: list[str] = Field(default_factory=list)


class BCFTopicUpdate(BaseModel):
    """Update a BCF topic."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    topic_type: str | None = None
    topic_status: str | None = None
    priority: str | None = None
    assigned_to: str | None = None
    labels: list[str] | None = None


# ── BCF 3.0 Comments ───────────────────────────────────────────────────


class BCFComment(BaseModel):
    """BCF-format comment (maps to our threaded comment replies)."""

    guid: str
    date: datetime | None = None
    author: str = ""
    comment: str = ""
    topic_guid: str = ""
    modified_date: datetime | None = None
    modified_author: str = ""
    viewpoint_guid: str | None = None


class BCFCommentCreate(BaseModel):
    """Create a new BCF comment."""

    comment: str = Field(..., min_length=1, max_length=10000)
    viewpoint_guid: str | None = None


# ── BCF 3.0 Viewpoints ─────────────────────────────────────────────────


class BCFVector(BaseModel):
    """3D vector for camera directions."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class BCFPoint(BaseModel):
    """3D point for camera position."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class BCFOrthogonalCamera(BaseModel):
    """Orthogonal camera in BCF format."""

    camera_view_point: BCFPoint = Field(default_factory=BCFPoint)
    camera_direction: BCFVector = Field(default_factory=BCFVector)
    camera_up_vector: BCFVector = Field(default_factory=BCFVector)
    view_to_world_scale: float = 1.0


class BCFPerspectiveCamera(BaseModel):
    """Perspective camera in BCF format."""

    camera_view_point: BCFPoint = Field(default_factory=BCFPoint)
    camera_direction: BCFVector = Field(default_factory=BCFVector)
    camera_up_vector: BCFVector = Field(default_factory=BCFVector)
    field_of_view: float = 60.0


class BCFViewpoint(BaseModel):
    """BCF-format viewpoint (maps to our collaboration viewpoints)."""

    guid: str
    index: int = 0
    orthogonal_camera: BCFOrthogonalCamera | None = None
    perspective_camera: BCFPerspectiveCamera | None = None
    snapshot: dict[str, Any] | None = None


class BCFViewpointCreate(BaseModel):
    """Create a new BCF viewpoint."""

    orthogonal_camera: BCFOrthogonalCamera | None = None
    perspective_camera: BCFPerspectiveCamera | None = None
