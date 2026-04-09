"""OpenCDE API routes.

BuildingSMART-compliant API endpoints:

Foundation API 1.1:
    GET /foundation/versions
    GET /foundation/1.1/auth
    GET /foundation/1.1/current-user

BCF API 3.0:
    GET    /bcf/3.0/projects
    GET    /bcf/3.0/projects/{project_id}
    GET    /bcf/3.0/projects/{project_id}/topics
    POST   /bcf/3.0/projects/{project_id}/topics
    GET    /bcf/3.0/projects/{project_id}/topics/{topic_guid}
    PUT    /bcf/3.0/projects/{project_id}/topics/{topic_guid}
    GET    /bcf/3.0/projects/{project_id}/topics/{topic_guid}/comments
    POST   /bcf/3.0/projects/{project_id}/topics/{topic_guid}/comments
    GET    /bcf/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints
    POST   /bcf/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints
"""

import uuid

from fastapi import APIRouter, Depends

from app.dependencies import CurrentUserId, OptionalUserPayload, SessionDep
from app.modules.opencde_api.schemas import (
    BCFComment,
    BCFCommentCreate,
    BCFProject,
    BCFTopic,
    BCFTopicCreate,
    BCFTopicUpdate,
    BCFUser,
    BCFViewpoint,
    BCFViewpointCreate,
    FoundationAuth,
    FoundationVersions,
)
from app.modules.opencde_api.service import OpenCDEService

router = APIRouter()


def _get_service(session: SessionDep) -> OpenCDEService:
    return OpenCDEService(session)


# ══════════════════════════════════════════════════════════════════════════
# Foundation API 1.1
# ══════════════════════════════════════════════════════════════════════════


@router.get("/foundation/versions/", response_model=FoundationVersions)
async def foundation_versions() -> FoundationVersions:
    """Return supported API versions (OpenCDE Foundation API 1.1)."""
    return FoundationVersions(
        versions=[
            {
                "api_id": "opencde-foundation",
                "version_id": "1.1",
                "detailed_version": "1.1.0",
            },
            {
                "api_id": "bcf",
                "version_id": "3.0",
                "detailed_version": "3.0.0",
            },
        ]
    )


@router.get("/foundation/1.1/auth/", response_model=FoundationAuth)
async def foundation_auth() -> FoundationAuth:
    """Return authentication info (OpenCDE Foundation API 1.1)."""
    return FoundationAuth(
        oauth2_auth_url="",
        oauth2_token_url="",
        http_basic_supported=True,
        supported_oauth2_flows=[],
    )


@router.get("/foundation/1.1/current-user/", response_model=BCFUser)
async def foundation_current_user(
    user_id: CurrentUserId,
    session: SessionDep,
) -> BCFUser:
    """Return current authenticated user (OpenCDE Foundation API 1.1)."""
    from app.modules.users.models import User

    user = await session.get(User, uuid.UUID(user_id))
    if user is None:
        return BCFUser(id=user_id, name="Unknown")
    return BCFUser(
        id=str(user.id),
        name=user.full_name or user.email,
        email=user.email,
    )


# ══════════════════════════════════════════════════════════════════════════
# BCF API 3.0 — Projects
# ══════════════════════════════════════════════════════════════════════════


@router.get("/bcf/3.0/projects/", response_model=list[BCFProject])
async def bcf_list_projects(
    user_payload: OptionalUserPayload,
    service: OpenCDEService = Depends(_get_service),
) -> list[BCFProject]:
    """List all projects in BCF format."""
    return await service.list_projects()


@router.get("/bcf/3.0/projects/{project_id}", response_model=BCFProject)
async def bcf_get_project(
    project_id: uuid.UUID,
    user_payload: OptionalUserPayload,
    service: OpenCDEService = Depends(_get_service),
) -> BCFProject:
    """Get a single project in BCF format."""
    return await service.get_project(project_id)


# ══════════════════════════════════════════════════════════════════════════
# BCF API 3.0 — Topics
# ══════════════════════════════════════════════════════════════════════════


@router.get(
    "/bcf/3.0/projects/{project_id}/topics/",
    response_model=list[BCFTopic],
)
async def bcf_list_topics(
    project_id: uuid.UUID,
    user_payload: OptionalUserPayload,
    service: OpenCDEService = Depends(_get_service),
) -> list[BCFTopic]:
    """List BCF topics for a project."""
    return await service.list_topics(project_id)


@router.post(
    "/bcf/3.0/projects/{project_id}/topics/",
    response_model=BCFTopic,
    status_code=201,
)
async def bcf_create_topic(
    project_id: uuid.UUID,
    data: BCFTopicCreate,
    user_id: CurrentUserId,
    service: OpenCDEService = Depends(_get_service),
) -> BCFTopic:
    """Create a new BCF topic."""
    return await service.create_topic(project_id, data, uuid.UUID(user_id))


@router.get(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}",
    response_model=BCFTopic,
)
async def bcf_get_topic(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    user_payload: OptionalUserPayload,
    service: OpenCDEService = Depends(_get_service),
) -> BCFTopic:
    """Get a single BCF topic."""
    return await service.get_topic(project_id, topic_guid)


@router.put(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}",
    response_model=BCFTopic,
)
async def bcf_update_topic(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    data: BCFTopicUpdate,
    user_id: CurrentUserId,
    service: OpenCDEService = Depends(_get_service),
) -> BCFTopic:
    """Update a BCF topic."""
    return await service.update_topic(project_id, topic_guid, data)


# ══════════════════════════════════════════════════════════════════════════
# BCF API 3.0 — Comments
# ══════════════════════════════════════════════════════════════════════════


@router.get(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}/comments/",
    response_model=list[BCFComment],
)
async def bcf_list_comments(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    user_payload: OptionalUserPayload,
    service: OpenCDEService = Depends(_get_service),
) -> list[BCFComment]:
    """List BCF comments for a topic."""
    return await service.list_comments(project_id, topic_guid)


@router.post(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}/comments/",
    response_model=BCFComment,
    status_code=201,
)
async def bcf_create_comment(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    data: BCFCommentCreate,
    user_id: CurrentUserId,
    service: OpenCDEService = Depends(_get_service),
) -> BCFComment:
    """Create a new BCF comment on a topic."""
    return await service.create_comment(
        project_id, topic_guid, data, uuid.UUID(user_id)
    )


# ══════════════════════════════════════════════════════════════════════════
# BCF API 3.0 — Viewpoints
# ══════════════════════════════════════════════════════════════════════════


@router.get(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints/",
    response_model=list[BCFViewpoint],
)
async def bcf_list_viewpoints(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    user_payload: OptionalUserPayload,
    service: OpenCDEService = Depends(_get_service),
) -> list[BCFViewpoint]:
    """List BCF viewpoints for a topic."""
    return await service.list_viewpoints(project_id, topic_guid)


@router.post(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints/",
    response_model=BCFViewpoint,
    status_code=201,
)
async def bcf_create_viewpoint(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    data: BCFViewpointCreate,
    user_id: CurrentUserId,
    service: OpenCDEService = Depends(_get_service),
) -> BCFViewpoint:
    """Create a new BCF viewpoint for a topic."""
    return await service.create_viewpoint(
        project_id, topic_guid, data, uuid.UUID(user_id)
    )
