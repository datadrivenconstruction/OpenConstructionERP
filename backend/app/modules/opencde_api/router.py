# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠OpenCDE API routes.

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

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
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

router = APIRouter(tags=["opencde_api"])


def _get_service(session: SessionDep) -> OpenCDEService:
    return OpenCDEService(session)


async def _accessible_project_ids(session: SessionDep, payload: dict) -> set[str]:
    """Return the set of project IDs the caller may see (as strings).

    Mirrors the platform-wide scoping used by ``verify_project_access`` /
    ``ProjectRepository.list_for_user``: admins see every project, everyone
    else sees only projects they own or are a team member of. Used to scope
    the BCF project list - the underlying service intentionally returns every
    project, so the router filters it down to the caller's tenant.
    """
    from app.modules.projects.repository import ProjectRepository

    is_admin = payload.get("role", "") == "admin"
    owner_id = uuid.UUID(str(payload["sub"]))
    # Use a high limit so the caller's full project set is considered (the
    # BCF list is not paginated); include archived so the membership view
    # matches the unscoped service output it filters.
    projects, _ = await ProjectRepository(session).list_for_user(
        owner_id,
        offset=0,
        limit=100_000,
        exclude_archived=False,
        is_admin=is_admin,
    )
    return {str(p.id) for p in projects}


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
# BCF API 3.0 - Projects
# ══════════════════════════════════════════════════════════════════════════


@router.get(
    "/bcf/3.0/projects/",
    response_model=list[BCFProject],
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def bcf_list_projects(
    user_payload: CurrentUserPayload,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> list[BCFProject]:
    """List BCF projects the caller can access (own / member / admin)."""
    allowed = await _accessible_project_ids(session, user_payload)
    projects = await service.list_projects()
    return [p for p in projects if p.project_id in allowed]


@router.get(
    "/bcf/3.0/projects/{project_id}",
    response_model=BCFProject,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def bcf_get_project(
    project_id: uuid.UUID,
    user_payload: CurrentUserPayload,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> BCFProject:
    """Get a single project in BCF format (caller must be able to access it)."""
    await verify_project_access(project_id, user_payload["sub"], session)
    return await service.get_project(project_id)


# ══════════════════════════════════════════════════════════════════════════
# BCF API 3.0 - Topics
# ══════════════════════════════════════════════════════════════════════════


@router.get(
    "/bcf/3.0/projects/{project_id}/topics/",
    response_model=list[BCFTopic],
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def bcf_list_topics(
    project_id: uuid.UUID,
    user_payload: CurrentUserPayload,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> list[BCFTopic]:
    """List BCF topics for a project (caller must be able to access it)."""
    await verify_project_access(project_id, user_payload["sub"], session)
    return await service.list_topics(project_id)


@router.post(
    "/bcf/3.0/projects/{project_id}/topics/",
    response_model=BCFTopic,
    status_code=201,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def bcf_create_topic(
    project_id: uuid.UUID,
    data: BCFTopicCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> BCFTopic:
    """Create a new BCF topic (caller must be able to access the project)."""
    await verify_project_access(project_id, user_id, session)
    return await service.create_topic(project_id, data, uuid.UUID(user_id))


@router.get(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}",
    response_model=BCFTopic,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def bcf_get_topic(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    user_payload: CurrentUserPayload,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> BCFTopic:
    """Get a single BCF topic (caller must be able to access the project)."""
    await verify_project_access(project_id, user_payload["sub"], session)
    return await service.get_topic(project_id, topic_guid)


@router.put(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}",
    response_model=BCFTopic,
    dependencies=[Depends(RequirePermission("bcf.update"))],
)
async def bcf_update_topic(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    data: BCFTopicUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> BCFTopic:
    """Update a BCF topic (caller must be able to access the project)."""
    await verify_project_access(project_id, user_id, session)
    return await service.update_topic(project_id, topic_guid, data, uuid.UUID(user_id))


# ══════════════════════════════════════════════════════════════════════════
# BCF API 3.0 - Comments
# ══════════════════════════════════════════════════════════════════════════


@router.get(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}/comments/",
    response_model=list[BCFComment],
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def bcf_list_comments(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    user_payload: CurrentUserPayload,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> list[BCFComment]:
    """List BCF comments for a topic (caller must be able to access the project)."""
    await verify_project_access(project_id, user_payload["sub"], session)
    return await service.list_comments(project_id, topic_guid)


@router.post(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}/comments/",
    response_model=BCFComment,
    status_code=201,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def bcf_create_comment(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    data: BCFCommentCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> BCFComment:
    """Create a new BCF comment on a topic (caller must be able to access the project)."""
    await verify_project_access(project_id, user_id, session)
    return await service.create_comment(project_id, topic_guid, data, uuid.UUID(user_id))


# ══════════════════════════════════════════════════════════════════════════
# BCF API 3.0 - Viewpoints
# ══════════════════════════════════════════════════════════════════════════


@router.get(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints/",
    response_model=list[BCFViewpoint],
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def bcf_list_viewpoints(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    user_payload: CurrentUserPayload,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> list[BCFViewpoint]:
    """List BCF viewpoints for a topic (caller must be able to access the project)."""
    await verify_project_access(project_id, user_payload["sub"], session)
    return await service.list_viewpoints(project_id, topic_guid)


@router.post(
    "/bcf/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints/",
    response_model=BCFViewpoint,
    status_code=201,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def bcf_create_viewpoint(
    project_id: uuid.UUID,
    topic_guid: uuid.UUID,
    data: BCFViewpointCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: OpenCDEService = Depends(_get_service),
) -> BCFViewpoint:
    """Create a new BCF viewpoint for a topic (caller must be able to access the project)."""
    await verify_project_access(project_id, user_id, session)
    return await service.create_viewpoint(project_id, topic_guid, data, uuid.UUID(user_id))
