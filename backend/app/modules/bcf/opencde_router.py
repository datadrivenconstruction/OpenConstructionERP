"""OpenCDE BCF-API 3.0 — minimum compliant profile (14 endpoints).

Reference: https://github.com/buildingSMART/BCF-API/tree/release_3_0

Mount point: this router is attached as a sub-router of the BCF module's
main ``router`` (see :mod:`manifest`) so the final URL prefix is
``/api/v1/bcf/3.0``. All endpoints accept Bearer-token auth via the
existing :class:`RequirePermission` dependency.

Notes (security / protocol)
    * HTTPS enforcement is a deployment concern (reverse proxy / Nginx
      / Traefik) — this module does not check the scheme of the request.
    * The 14 endpoints below cover the conformance subset BCF Manager
      plugins (Revit / Archicad / Navisworks) probe; richer OpenCDE
      surfaces (related-topics, document-references, file-info,
      authentication discovery) are deliberately out of scope.
    * On mutation we set ``Cache-Control: no-store``; on single-resource
      reads we return an ``ETag`` derived from ``modified_date`` —
      stale-write detection on PUT/DELETE returns 412.
    * The minimum profile uses JSON for viewpoint create payloads, NOT
      XML — XML is reserved for the file-based ``.bcfzip`` codec.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.dependencies import (
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
)
from app.modules.bcf.opencde_schemas import (
    BCFCommentResponse,
    BCFProject,
    BCFTopicResponse,
    CommentCreatePayload,
    CommentListResponse,
    CurrentUser,
    OpenCDEError,
    TopicCreatePayload,
    TopicListResponse,
    TopicUpdatePayload,
    ViewpointCreatePayload,
    ViewpointListResponse,
    ViewpointResponse,
)
from app.modules.bcf.opencde_service import (
    OpenCDEService,
    OpenCDEServiceError,
    compute_topic_etag,
    parse_odata_filter,  # noqa: F401  — re-exported for tests
)

logger = logging.getLogger(__name__)

opencde_router = APIRouter(tags=["BCF OpenCDE 3.0"])

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _validate_guid(guid: str) -> str:
    """422 if ``guid`` is not a canonical UUID."""
    norm = guid.strip().lower().strip("{}")
    if not _UUID_RE.match(norm):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid GUID: {guid}",
        )
    return norm


def _email_of(payload: dict) -> str | None:
    """Best-effort email lookup for ``creation_author`` / ``modified_author``."""
    return payload.get("email") or payload.get("preferred_username")


def _service(session: SessionDep) -> OpenCDEService:
    return OpenCDEService(session)


_NO_STORE = {"Cache-Control": "no-store"}


async def _project_owned_by_caller(
    session,
    project_id: uuid.UUID,
    user_id: str,
    role: str,
) -> None:
    """403 if caller does not own / cannot admin ``project_id`` (404 if absent)."""
    from app.modules.projects.repository import ProjectRepository

    project = await ProjectRepository(session).get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    if role == "admin":
        return
    if str(getattr(project, "owner_id", "")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this project",
        )


def _service_error_to_http(exc: OpenCDEServiceError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail=exc.message,
    )


# ── 1. List projects ────────────────────────────────────────────────────


@opencde_router.get(
    "/3.0/projects",
    response_model=list[BCFProject],
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def list_projects(
    payload: CurrentUserPayload,
    session: SessionDep,
) -> list[BCFProject]:
    """List projects the caller can access (OpenCDE Project[])."""
    service = OpenCDEService(session)
    try:
        return await service.list_projects(user_id=payload["sub"], role=payload.get("role", "viewer"))
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc


# ── 2. Single project ──────────────────────────────────────────────────


@opencde_router.get(
    "/3.0/projects/{project_id}",
    response_model=BCFProject,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def get_project(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> BCFProject:
    """Single OpenCDE Project record."""
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        return await OpenCDEService(session).get_project(project_id, role=payload.get("role", "viewer"))
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc


# ── 3. Project extensions (extensions.xml twin) ────────────────────────


@opencde_router.get(
    "/3.0/projects/{project_id}/extensions",
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def get_project_extensions(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict:
    """OpenCDE ``extensions.xml`` data, served as JSON.

    Topic types / statuses / priorities / stages mirror the values
    the file-based exporter emits — keeps the REST surface and the
    .bcfzip codec consistent for round-trips through Revit / Archicad.
    """
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    return {
        "topic_type": ["Clash", "Issue", "Comment", "Request for Information", "Remark"],
        "topic_status": ["Open", "In Progress", "Closed"],
        "topic_label": [],
        "snippet_type": [],
        "priority": ["Minor", "Normal", "Major", "Critical"],
        "user_id_type": ["mailto"],
        "stage": ["Design", "Construction", "Handover"],
        "project_actions": ["update", "createTopic"],
        "topic_actions": [
            "update",
            "updateBimSnippet",
            "updateRelatedTopics",
            "updateDocumentReferences",
            "updateFiles",
            "createComment",
            "createViewpoint",
        ],
        "comment_actions": ["update"],
    }


# ── 4. List topics ─────────────────────────────────────────────────────


@opencde_router.get(
    "/3.0/projects/{project_id}/topics",
    response_model=TopicListResponse,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def list_topics(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    response: Response,
    filter_: Annotated[str | None, Query(alias="$filter")] = None,
    orderby: Annotated[str | None, Query(alias="$orderby")] = None,
    top: Annotated[int, Query(alias="$top", ge=1, le=500)] = 50,
    skip: Annotated[int, Query(alias="$skip", ge=0)] = 0,
) -> TopicListResponse:
    """List topics, with OData $filter / $orderby / $top / $skip."""
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    service = OpenCDEService(session)
    try:
        items, total = await service.list_topics(
            project_id,
            odata_filter=filter_,
            order_by=orderby,
            top=top,
            skip=skip,
            role=payload.get("role", "viewer"),
        )
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    response.headers["X-Total-Count"] = str(total)
    return TopicListResponse(items=items)


# ── 5. Create topic ────────────────────────────────────────────────────


@opencde_router.post(
    "/3.0/projects/{project_id}/topics",
    response_model=BCFTopicResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def create_topic(
    project_id: uuid.UUID,
    body: TopicCreatePayload,
    payload: CurrentUserPayload,
    session: SessionDep,
    response: Response,
) -> BCFTopicResponse:
    """Create a topic; ``creation_author`` is filled from the caller."""
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        topic_dto, topic = await OpenCDEService(session).create_topic(
            project_id,
            body,
            user_id=payload["sub"],
            user_email=_email_of(payload),
            role=payload.get("role", "viewer"),
        )
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    response.headers.update(_NO_STORE)
    response.headers["ETag"] = compute_topic_etag(topic)
    return topic_dto


# ── 6. Get single topic ────────────────────────────────────────────────


@opencde_router.get(
    "/3.0/projects/{project_id}/topics/{topic_guid}",
    response_model=BCFTopicResponse,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def get_topic(
    project_id: uuid.UUID,
    topic_guid: str,
    payload: CurrentUserPayload,
    session: SessionDep,
    response: Response,
) -> BCFTopicResponse:
    """Single topic — sets ``ETag`` for use with subsequent PUT/DELETE."""
    topic_guid = _validate_guid(topic_guid)
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        topic_dto, topic = await OpenCDEService(session).get_topic(
            project_id, topic_guid, role=payload.get("role", "viewer")
        )
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    response.headers["ETag"] = compute_topic_etag(topic)
    return topic_dto


# ── 7. Update topic ────────────────────────────────────────────────────


@opencde_router.put(
    "/3.0/projects/{project_id}/topics/{topic_guid}",
    response_model=BCFTopicResponse,
    dependencies=[Depends(RequirePermission("bcf.update"))],
)
async def update_topic(
    project_id: uuid.UUID,
    topic_guid: str,
    body: TopicUpdatePayload,
    payload: CurrentUserPayload,
    session: SessionDep,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> BCFTopicResponse:
    """PUT — full or partial update; supports If-Match for stale-write check."""
    topic_guid = _validate_guid(topic_guid)
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        topic_dto, topic = await OpenCDEService(session).update_topic(
            project_id,
            topic_guid,
            body,
            user_id=payload["sub"],
            user_email=_email_of(payload),
            role=payload.get("role", "viewer"),
            if_match=if_match,
        )
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    response.headers.update(_NO_STORE)
    response.headers["ETag"] = compute_topic_etag(topic)
    return topic_dto


# ── 8. Delete topic ────────────────────────────────────────────────────


@opencde_router.delete(
    "/3.0/projects/{project_id}/topics/{topic_guid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("bcf.delete"))],
)
async def delete_topic(
    project_id: uuid.UUID,
    topic_guid: str,
    payload: CurrentUserPayload,
    session: SessionDep,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> None:
    """DELETE — If-Match supported."""
    topic_guid = _validate_guid(topic_guid)
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        await OpenCDEService(session).delete_topic(project_id, topic_guid, if_match=if_match)
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    response.headers.update(_NO_STORE)


# ── 9. List comments ───────────────────────────────────────────────────


@opencde_router.get(
    "/3.0/projects/{project_id}/topics/{topic_guid}/comments",
    response_model=CommentListResponse,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def list_comments(
    project_id: uuid.UUID,
    topic_guid: str,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> CommentListResponse:
    """List comments on a topic, oldest first."""
    topic_guid = _validate_guid(topic_guid)
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        items = await OpenCDEService(session).list_comments(project_id, topic_guid, role=payload.get("role", "viewer"))
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    return CommentListResponse(items=items)


# ── 10. Create comment ─────────────────────────────────────────────────


@opencde_router.post(
    "/3.0/projects/{project_id}/topics/{topic_guid}/comments",
    response_model=BCFCommentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def create_comment(
    project_id: uuid.UUID,
    topic_guid: str,
    body: CommentCreatePayload,
    payload: CurrentUserPayload,
    session: SessionDep,
    response: Response,
) -> BCFCommentResponse:
    """Append a comment; reply chain captured via ``reply_to_comment_guid``."""
    topic_guid = _validate_guid(topic_guid)
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        result = await OpenCDEService(session).create_comment(
            project_id,
            topic_guid,
            body,
            user_id=payload["sub"],
            user_email=_email_of(payload),
            role=payload.get("role", "viewer"),
        )
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    response.headers.update(_NO_STORE)
    return result


# ── 11. List viewpoints ────────────────────────────────────────────────


@opencde_router.get(
    "/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints",
    response_model=ViewpointListResponse,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def list_viewpoints(
    project_id: uuid.UUID,
    topic_guid: str,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> ViewpointListResponse:
    """List viewpoints on a topic."""
    topic_guid = _validate_guid(topic_guid)
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        items = await OpenCDEService(session).list_viewpoints(project_id, topic_guid)
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    return ViewpointListResponse(items=items)


# ── 12. Create viewpoint ──────────────────────────────────────────────


@opencde_router.post(
    "/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints",
    response_model=ViewpointResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def create_viewpoint(
    project_id: uuid.UUID,
    topic_guid: str,
    body: ViewpointCreatePayload,
    payload: CurrentUserPayload,
    session: SessionDep,
    response: Response,
) -> ViewpointResponse:
    """Create a viewpoint; body is JSON, NOT XML."""
    topic_guid = _validate_guid(topic_guid)
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        result = await OpenCDEService(session).create_viewpoint(project_id, topic_guid, body, user_id=payload["sub"])
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    response.headers.update(_NO_STORE)
    return result


# ── 13. Viewpoint snapshot PNG ────────────────────────────────────────


@opencde_router.get(
    "/3.0/projects/{project_id}/topics/{topic_guid}/viewpoints/{viewpoint_guid}/snapshot",
    dependencies=[Depends(RequirePermission("bcf.read"))],
    responses={
        200: {"content": {"image/png": {}}},
        404: {"model": OpenCDEError},
    },
)
async def get_viewpoint_snapshot(
    project_id: uuid.UUID,
    topic_guid: str,
    viewpoint_guid: str,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> Response:
    """Stream the viewpoint's snapshot PNG."""
    topic_guid = _validate_guid(topic_guid)
    viewpoint_guid = _validate_guid(viewpoint_guid)
    await _project_owned_by_caller(session, project_id, payload["sub"], payload.get("role", "viewer"))
    try:
        png = await OpenCDEService(session).get_snapshot_png(project_id, topic_guid, viewpoint_guid)
    except OpenCDEServiceError as exc:
        raise _service_error_to_http(exc) from exc
    return Response(content=png, media_type="image/png")


# ── 14. Current user ──────────────────────────────────────────────────


@opencde_router.get(
    "/3.0/current-user",
    response_model=CurrentUser,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def get_current_user(
    payload: CurrentUserPayload,
    session: SessionDep,
) -> CurrentUser:
    """Tell the BCF Manager client who the bearer-token identifies."""
    from app.modules.users.models import User

    user = await session.get(User, uuid.UUID(str(payload["sub"])))
    name = getattr(user, "full_name", None) or getattr(user, "email", None) or str(payload["sub"])
    return CurrentUser(id=str(payload["sub"]), name=name)
