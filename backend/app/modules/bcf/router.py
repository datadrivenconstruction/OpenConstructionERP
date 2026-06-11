"""‌⁠‍BCF API routes - mounted by the module loader at ``/api/v1/bcf``.

Endpoints
    GET    /projects/{project_id}/topics/
    POST   /projects/{project_id}/topics/
    GET    /projects/{project_id}/topics/{topic_id}
    PUT    /projects/{project_id}/topics/{topic_id}
    DELETE /projects/{project_id}/topics/{topic_id}
    POST   /projects/{project_id}/topics/{topic_id}/comments/
    PUT    /projects/{project_id}/topics/{topic_id}/comments/{comment_id}
    DELETE /projects/{project_id}/topics/{topic_id}/comments/{comment_id}
    POST   /projects/{project_id}/topics/{topic_id}/viewpoints/
    GET    /projects/{project_id}/topics/{topic_id}/viewpoints/{vp_guid}/snapshot
    GET    /projects/{project_id}/export?version=2.1|3.0   → .bcfzip
    POST   /projects/{project_id}/import                   → BCFImportReport

Auth mirrors the ``validation`` module exactly: a coarse
``RequirePermission`` gate on every route plus a per-project
owner/admin check (:func:`_require_project_access`) so a viewer of one
project can't read another project's issues (IDOR).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi import File as FileParam
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.bcf.bcf_xml import SUPPORTED_VERSIONS
from app.modules.bcf.messages import translate
from app.modules.bcf.schemas import (
    BCFImportReport,
    CommentCreate,
    CommentResponse,
    CommentUpdate,
    TopicCreate,
    TopicResponse,
    TopicUpdate,
    ViewpointCreate,
    ViewpointResponse,
)
from app.modules.bcf.service import (
    BCFExportFeatureUnavailable,
    BCFExportService,
    BCFService,
    BCFServiceError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["BCF"])

# 100 MiB hard cap on an uploaded .bcfzip - harmonised with the
# ``_BCF_IMPORT_MAX_BYTES`` cap on the clash-import endpoint below and
# the BCFReader's ``DEFAULT_MAX_TOTAL_BYTES``. A typical coordination
# round-trip is markup + small PNG snapshots, but federated models with
# hundreds of viewpoints can legitimately exceed 25 MiB.
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _get_service(session: SessionDep) -> BCFService:
    return BCFService(session)


# ── IDOR guard (mirrors validation.router._require_project_access) ─────────


async def _require_project_access(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
) -> str:
    """‌⁠‍Verify the caller owns (or is admin on) ``project_id``.

    Returns the project name (needed for the BCF project.bcfp on export).
    Raises 404 when the project is missing and 403 when access is denied.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.users.repository import UserRepository

    proj_repo = ProjectRepository(session)
    project = await proj_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    try:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(uuid.UUID(str(user_id)))
        if user is not None and getattr(user, "role", "") == "admin":
            return str(getattr(project, "name", ""))
    except Exception:  # noqa: BLE001 - best-effort admin check
        logger.exception("Admin-role lookup failed during BCF access check")

    if str(getattr(project, "owner_id", "")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you do not own this project",
        )
    return str(getattr(project, "name", ""))


def _locale_of(payload_user_id: str) -> str:
    """‌⁠‍Resolve the request locale for user-facing messages.

    The current i18n surface is context-scoped via middleware; we read the
    active locale rather than trusting a header here, falling back to
    ``en``.
    """
    try:
        from app.core.i18n import get_locale

        return get_locale() or "en"
    except Exception:  # noqa: BLE001
        return "en"


def _topic_response(topic: object) -> TopicResponse:
    """Map an ORM ``BCFTopic`` (with eager comments/viewpoints) → schema."""
    t = topic
    comments = [
        CommentResponse(
            guid=c.guid,
            comment=c.comment_text,
            author=c.author,
            date=c.date,
            modified_author=c.modified_author,
            modified_date=c.modified_date,
            viewpoint_guid=c.viewpoint_guid,
        )
        for c in t.comments  # type: ignore[attr-defined]
    ]
    viewpoints = [
        ViewpointResponse(
            guid=v.guid,
            index=v.vp_index,
            perspective_camera=None,
            orthogonal_camera=None,
            components=v.components or {},
            element_stable_ids=list(v.element_stable_ids or []),
            has_snapshot=bool(v.snapshot_key),
            snapshot_url=(
                f"/api/v1/bcf/projects/{t.project_id}/topics/{t.id}"  # type: ignore[attr-defined]
                f"/viewpoints/{v.guid}/snapshot"
                if v.snapshot_key
                else None
            ),
        )
        for v in t.viewpoints  # type: ignore[attr-defined]
    ]
    return TopicResponse(
        guid=t.guid,  # type: ignore[attr-defined]
        project_id=str(t.project_id),  # type: ignore[attr-defined]
        bim_model_id=t.bim_model_id,  # type: ignore[attr-defined]
        title=t.title,  # type: ignore[attr-defined]
        description=t.description,  # type: ignore[attr-defined]
        topic_type=t.topic_type,  # type: ignore[attr-defined]
        topic_status=t.topic_status,  # type: ignore[attr-defined]
        priority=t.priority,  # type: ignore[attr-defined]
        stage=t.stage,  # type: ignore[attr-defined]
        index=t.topic_index,  # type: ignore[attr-defined]
        assigned_to=t.assigned_to,  # type: ignore[attr-defined]
        due_date=t.due_date,  # type: ignore[attr-defined]
        labels=list(t.labels or []),  # type: ignore[attr-defined]
        reference_links=list(t.reference_links or []),  # type: ignore[attr-defined]
        creation_author=t.creation_author,  # type: ignore[attr-defined]
        creation_date=t.creation_date,  # type: ignore[attr-defined]
        modified_author=t.modified_author,  # type: ignore[attr-defined]
        modified_date=t.modified_date,  # type: ignore[attr-defined]
        comments=comments,
        viewpoints=viewpoints,
    )


# ── Topics ─────────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/topics/",
    response_model=list[TopicResponse],
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def list_topics(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> list[TopicResponse]:
    """List every BCF topic for a project, newest first."""
    await _require_project_access(session, project_id, user_id)
    topics = await service.list_topics(project_id)
    return [_topic_response(t) for t in topics]


@router.post(
    "/projects/{project_id}/topics/",
    response_model=TopicResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def create_topic(
    project_id: uuid.UUID,
    data: TopicCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> TopicResponse:
    """Create a new BCF topic."""
    await _require_project_access(session, project_id, user_id)
    topic = await service.create_topic(project_id, data, author=user_id, user_id=user_id)
    return _topic_response(topic)


@router.get(
    "/projects/{project_id}/topics/{topic_id}",
    response_model=TopicResponse,
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def get_topic(
    project_id: uuid.UUID,
    topic_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> TopicResponse:
    """Fetch one topic with its comments and viewpoints."""
    await _require_project_access(session, project_id, user_id)
    try:
        topic = await service.get_topic(project_id, topic_id)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("bcf.topic_not_found", _locale_of(user_id)),
        ) from exc
    return _topic_response(topic)


@router.put(
    "/projects/{project_id}/topics/{topic_id}",
    response_model=TopicResponse,
    dependencies=[Depends(RequirePermission("bcf.update"))],
)
async def update_topic(
    project_id: uuid.UUID,
    topic_id: uuid.UUID,
    data: TopicUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> TopicResponse:
    """Patch a topic - only fields present in the body change."""
    await _require_project_access(session, project_id, user_id)
    try:
        topic = await service.update_topic(project_id, topic_id, data, author=user_id)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("bcf.topic_not_found", _locale_of(user_id)),
        ) from exc
    return _topic_response(topic)


@router.delete(
    "/projects/{project_id}/topics/{topic_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("bcf.delete"))],
)
async def delete_topic(
    project_id: uuid.UUID,
    topic_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> None:
    """Delete a topic, its comments, viewpoints and snapshot blobs."""
    await _require_project_access(session, project_id, user_id)
    try:
        await service.delete_topic(project_id, topic_id)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("bcf.topic_not_found", _locale_of(user_id)),
        ) from exc


# ── Comments ───────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/topics/{topic_id}/comments/",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def add_comment(
    project_id: uuid.UUID,
    topic_id: uuid.UUID,
    data: CommentCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> CommentResponse:
    """Append a comment to a topic (optionally bound to a viewpoint)."""
    await _require_project_access(session, project_id, user_id)
    try:
        comment = await service.add_comment(project_id, topic_id, data, author=user_id, user_id=user_id)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return CommentResponse(
        guid=comment.guid,
        comment=comment.comment_text,
        author=comment.author,
        date=comment.date,
        modified_author=comment.modified_author,
        modified_date=comment.modified_date,
        viewpoint_guid=comment.viewpoint_guid,
    )


@router.put(
    "/projects/{project_id}/topics/{topic_id}/comments/{comment_id}",
    response_model=CommentResponse,
    dependencies=[Depends(RequirePermission("bcf.update"))],
)
async def update_comment(
    project_id: uuid.UUID,
    topic_id: uuid.UUID,
    comment_id: uuid.UUID,
    data: CommentUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> CommentResponse:
    """Edit a comment's text."""
    await _require_project_access(session, project_id, user_id)
    try:
        comment = await service.update_comment(project_id, topic_id, comment_id, data.comment, author=user_id)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return CommentResponse(
        guid=comment.guid,
        comment=comment.comment_text,
        author=comment.author,
        date=comment.date,
        modified_author=comment.modified_author,
        modified_date=comment.modified_date,
        viewpoint_guid=comment.viewpoint_guid,
    )


@router.delete(
    "/projects/{project_id}/topics/{topic_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("bcf.delete"))],
)
async def delete_comment(
    project_id: uuid.UUID,
    topic_id: uuid.UUID,
    comment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> None:
    """Delete a single comment."""
    await _require_project_access(session, project_id, user_id)
    try:
        await service.delete_comment(project_id, topic_id, comment_id)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


# ── Viewpoints ─────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/topics/{topic_id}/viewpoints/",
    response_model=ViewpointResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("bcf.create"))],
)
async def add_viewpoint(
    project_id: uuid.UUID,
    topic_id: uuid.UUID,
    data: ViewpointCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> ViewpointResponse:
    """Attach a viewpoint (camera + component selection + optional PNG)."""
    await _require_project_access(session, project_id, user_id)
    try:
        vp = await service.add_viewpoint(project_id, topic_id, data, user_id)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return ViewpointResponse(
        guid=vp.guid,
        index=vp.vp_index,
        perspective_camera=data.perspective_camera,
        orthogonal_camera=data.orthogonal_camera,
        components=data.components,
        element_stable_ids=list(vp.element_stable_ids or []),
        has_snapshot=bool(vp.snapshot_key),
        snapshot_url=(
            f"/api/v1/bcf/projects/{project_id}/topics/{topic_id}/viewpoints/{vp.guid}/snapshot"
            if vp.snapshot_key
            else None
        ),
    )


@router.get(
    "/projects/{project_id}/topics/{topic_id}/viewpoints/{vp_guid}/snapshot",
    dependencies=[Depends(RequirePermission("bcf.read"))],
)
async def get_viewpoint_snapshot(
    project_id: uuid.UUID,
    topic_id: uuid.UUID,
    vp_guid: str,
    user_id: CurrentUserId,
    session: SessionDep,
    service: BCFService = Depends(_get_service),
) -> Response:
    """Stream a viewpoint's snapshot PNG."""
    await _require_project_access(session, project_id, user_id)
    try:
        png = await service.get_snapshot(project_id, topic_id, vp_guid)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return Response(content=png, media_type="image/png")


# ── Export / Import ────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/export",
    dependencies=[Depends(RequirePermission("bcf.export"))],
)
async def export_project_bcf(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    version: str = Query(
        default="2.1",
        description="BCF schema version to emit: '2.1' or '3.0'.",
    ),
    service: BCFService = Depends(_get_service),
) -> Response:
    """Export every topic of a project as a downloadable ``.bcfzip``."""
    project_name = await _require_project_access(session, project_id, user_id)
    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=translate(
                "bcf.version_unsupported",
                _locale_of(user_id),
                version=version,
                supported=", ".join(SUPPORTED_VERSIONS),
            ),
        )
    try:
        archive, _count = await service.export_bcfzip(project_id, project_name or str(project_id), version)
    except BCFServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    filename = f"project-{project_id}-bcf{version}.bcfzip"
    return Response(
        content=archive,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/projects/{project_id}/import",
    response_model=BCFImportReport,
    dependencies=[Depends(RequirePermission("bcf.import"))],
)
async def import_project_bcf(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = FileParam(..., description="A .bcfzip archive (BCF 2.1 or 3.0)"),
    version: str | None = Query(
        default=None,
        description="Force a schema version instead of autodetecting.",
    ),
    service: BCFService = Depends(_get_service),
) -> BCFImportReport:
    """Import a ``.bcfzip``; topics/comments/viewpoints upsert by GUID.

    A malformed or non-BCF archive returns a structured report with
    ``status='errors'`` - never a 500.
    """
    await _require_project_access(session, project_id, user_id)
    if version is not None and version not in SUPPORTED_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=translate(
                "bcf.version_unsupported",
                _locale_of(user_id),
                version=version,
                supported=", ".join(SUPPORTED_VERSIONS),
            ),
        )
    try:
        payload = await file.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translate("bcf.upload_read_failed", _locale_of(user_id)),
        ) from exc

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translate("bcf.upload_empty", _locale_of(user_id)),
        )
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=translate("bcf.upload_too_large", _locale_of(user_id)),
        )

    return await service.import_bcfzip(project_id, payload, user_id, forced_version=version)


# ── Clash → BCF 3.0 zip (file-based, no persistence) ──────────────────────


@router.get(
    "/export/clashes",
    dependencies=[Depends(RequirePermission("bcf.export"))],
)
async def export_clashes_bcfzip(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description=(
            "Filter by clash status. Use the literal 'open' to include all "
            "unresolved states (new|active|persisted|reviewed)."
        ),
    ),
    severity: str | None = Query(default=None),
) -> Response:
    """Download all clashes for ``project_id`` as a BCF 3.0 ``.bcfzip``.

    File-based - does not persist anything in the BCF tables. The
    ``status`` and ``severity`` query parameters narrow the export.

    Returns 503 when the clash schema (v41) has not been migrated yet.
    """
    project_name = await _require_project_access(session, project_id, user_id)
    filter_dict: dict[str, str] = {}
    if status_filter:
        filter_dict["status"] = status_filter
    if severity:
        filter_dict["severity"] = severity

    export = BCFExportService(session)
    try:
        archive = await export.export_clashes_to_bcf(
            project_id,
            filter_dict,
            author=str(user_id),
            project_name=project_name or str(project_id),
        )
    except BCFExportFeatureUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    today = datetime.now(UTC).strftime("%Y%m%d")
    filename = f"clashes-{project_id}-{today}.bcfzip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── BCF 3.0 → Clash import (file-based, mirror of /export/clashes) ────────
#
# The endpoint below is the inbound half of the BCF round-trip introduced
# by the sibling export agent. It accepts a multipart-uploaded ``.bcfzip``,
# parses every Topic with :class:`BCFReader`, and upserts a
# :class:`ClashIssue` row per Topic via :class:`BCFImportService`. The
# auth pattern is the same as ``/export/clashes`` (RequirePermission +
# ``_require_project_access``) so an EDITOR on the target project can
# round-trip a Revit Coordination BCF without paperwork.
#
# Deliberate properties:
#   * 100 MiB hard cap on the multipart payload (matches the BCFReader's
#     default zip-bomb defence - we never read more than that into RAM)
#   * 413 on too-large uploads
#   * 422 on a non-zip / malformed archive
#   * 503 when the ClashIssue table hasn't been migrated yet (mirrors the
#     503 emitted by /export/clashes for the same condition)


_BCF_IMPORT_MAX_BYTES = 500 * 1024 * 1024  # 500 MiB - matches reader default


@router.post(
    "/import/clashes",
    dependencies=[Depends(RequirePermission("bcf.import"))],
)
async def import_clashes_bcfzip(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = FileParam(..., description="A BCF 3.0 .bcfzip archive (Revit/ArchiCAD/etc.)"),
) -> dict:
    """Ingest a ``.bcfzip`` and upsert each Topic as a :class:`ClashIssue`.

    Permission: ``bcf.import`` (EDITOR or higher).

    Returns a JSON :class:`ImportReport`:

        {
          "created": int, "updated": int, "skipped": int,
          "errors": [{"topic_guid": "...", "message": "..."}]
        }

    HTTP codes:
        * 200 - import completed (the report may still carry per-topic
          errors; ``created+updated+skipped+len(errors) == topic_count``)
        * 413 - uploaded archive exceeds the 100 MiB cap
        * 422 - payload is not a BCF .bcfzip / zip-bomb / path traversal
        * 503 - clash schema (v41) hasn't been migrated yet
    """
    await _require_project_access(session, project_id, user_id)

    # Stream-read with a 100 MiB cap. We trust starlette's spool boundary
    # (1 MiB default) - anything larger is rejected outright.
    try:
        payload = await file.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translate("bcf.upload_read_failed", _locale_of(user_id)),
        ) from exc

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=translate("bcf.upload_empty", _locale_of(user_id)),
        )
    if len(payload) > _BCF_IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=translate("bcf.upload_too_large", _locale_of(user_id)),
        )

    # Deferred import keeps the BCF module's import graph cheap when the
    # endpoint is never hit (most projects don't ingest BCF on every
    # request) and avoids circular imports with the clash module.
    from app.modules.bcf.import_service import (
        BCFFormatError,
        BCFImportFeatureUnavailable,
        BCFImportService,
        BCFReaderError,
        BCFSecurityError,
    )

    importer = BCFImportService(session)
    try:
        report = await importer.import_clashes_from_bcf(project_id, payload, current_user_id=user_id)
    except BCFImportFeatureUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BCFSecurityError as exc:
        # Zip-bomb / path-traversal - refuse to ingest.
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except BCFFormatError as exc:
        # Not a BCF zip / missing bcf.version → 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except BCFReaderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return report.to_dict()
