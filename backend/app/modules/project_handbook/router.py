# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project handbook API, mounted at ``/api/v1/project_handbook``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and awaits ``verify_project_access``
in its own body before it reads anything, so a project the caller cannot see answers 404 exactly like a
missing one. Chapters are looked up by ``(project_id, code)``; a chapter or folder of another project is 404.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in ``detail``;
``message_key`` is ``project_handbook.errors.<code>``. 404 = not found or not visible, 403 = permission or
the approver is the submitter (four eyes), 409 = state conflict, 422 = invalid input or a refusing rule.
Authorisation is decided here and handed down as booleans (:func:`_actor`); views carry ``can`` objects
``{"allowed", "reason", "applies"}`` computed by the function that enforces the action.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.project_handbook import data_room
from app.modules.project_handbook.catalogue import HANDBOOK_KIND
from app.modules.project_handbook.errors import HandbookError
from app.modules.project_handbook.messages import translate
from app.modules.project_handbook.permissions import EDIT as EDIT_PERMISSION
from app.modules.project_handbook.permissions import MANAGE, has_permission
from app.modules.project_handbook.schemas import ChapterPatch, HandbookPatch, HandbookSet, PlaceDocument
from app.modules.project_handbook.service import Actor, ProjectHandbookService

router = APIRouter(tags=["project_handbook"])

READ = Depends(RequirePermission("project_handbook.read"))
EDIT = Depends(RequirePermission(EDIT_PERMISSION))
MANAGE_DEP = Depends(RequirePermission(MANAGE))


async def _run[T](awaitable: Any) -> T:
    """Turn a :class:`HandbookError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except HandbookError as exc:
        message = translate(f"project_handbook.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = HandbookError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"project_handbook.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _actor(user_id: str, payload: dict[str, Any]) -> Actor:
    """The caller as the service sees them: an id and what the permission checks allow."""
    token = dict(payload or {})
    return Actor(
        _uid(user_id),
        manage=has_permission(token, MANAGE),
        edit=has_permission(token, EDIT_PERMISSION),
    )


def _page(items: list[Any], **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": len(items), "offset": 0, "limit": len(items), **extra}


def _file(content: bytes, name: str, locale: str) -> Response:
    """A rendered export. ``locale`` is the language its labels were written in, declared to the reader."""
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"', "Content-Language": locale},
    )


def _head(handbook: Any, chapters: list[dict[str, Any]]) -> dict[str, Any]:
    required = [c for c in chapters if c["required"]]
    return {
        "id": str(handbook.id),
        "project_id": str(handbook.project_id),
        "title": handbook.title,
        "edition": handbook.edition,
        "catalogue_source": handbook.catalogue_source,
        "catalogue_id": handbook.catalogue_id,
        "catalogue_version": handbook.catalogue_version,
        "chapters": chapters,
        "counts": {
            "chapters": len(chapters),
            "approved": sum(1 for c in chapters if c["approved_version"] is not None),
            "in_review": sum(1 for c in chapters if c["status"] == "in_review"),
            "required": len(required),
            "required_approved": sum(1 for c in required if c["approved_version"] is not None),
        },
    }


# ── catalogues ─────────────────────────────────────────────────────────────


@router.get("/catalogues", dependencies=[READ])
async def list_catalogues(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Shipped handbook catalogues and the caller's tenant ones, through the one governance resolver."""
    from app.modules.project_governance.catalogue_store import CatalogueStore

    ProjectHandbookService(session)  # registers the kind
    items = await _run(CatalogueStore(session).list_available(resolve_tenant_id(payload), kind=HANDBOOK_KIND))
    return _page(items)


# ── handbook ───────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/handbook", dependencies=[READ])
async def get_handbook(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """The handbook head with every chapter. 404 ``handbook_missing`` before one was created."""
    await verify_project_access(project_id, user_id, session)
    svc = ProjectHandbookService(session)
    handbook = await _run(svc.require_handbook(project_id))
    chapters = await _run(svc.list_chapters(project_id, locale=get_locale() or "en", actor=_actor(user_id, payload)))
    return _head(handbook, chapters)


@router.put("/projects/{project_id}/handbook", status_code=201, dependencies=[MANAGE_DEP])
async def create_handbook(
    project_id: uuid.UUID, body: HandbookSet, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = ProjectHandbookService(session)
    handbook = await _run(
        svc.create_handbook(
            project_id,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
            catalogue_source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            catalogue_version=body.catalogue_version,
            title=body.title,
            edition=body.edition,
            default_owner_id=_uid(user_id),
        )
    )
    chapters = await _run(svc.list_chapters(project_id, locale=get_locale() or "en", actor=_actor(user_id, payload)))
    return _head(handbook, chapters)


@router.patch("/projects/{project_id}/handbook", dependencies=[EDIT])
async def patch_handbook(
    project_id: uuid.UUID, body: HandbookPatch, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = ProjectHandbookService(session)
    handbook = await _run(svc.patch_handbook(project_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    chapters = await _run(svc.list_chapters(project_id, locale=get_locale() or "en", actor=_actor(user_id, payload)))
    return _head(handbook, chapters)


@router.post("/projects/{project_id}/handbook/sync", dependencies=[MANAGE_DEP])
async def sync_chapters(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, int]:
    """Lay out the chapters the catalogue asks for; nothing existing is rewritten."""
    await verify_project_access(project_id, user_id, session)
    return await _run(ProjectHandbookService(session).sync_chapters(project_id, actor_id=_uid(user_id)))


# ── chapters ───────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/chapters/{code}", dependencies=[READ])
async def get_chapter(
    project_id: uuid.UUID, code: str, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """One chapter with the live rows of its sources and its approved versions."""
    await verify_project_access(project_id, user_id, session)
    return await _run(
        ProjectHandbookService(session).get_chapter(
            project_id, code, locale=get_locale() or "en", actor=_actor(user_id, payload)
        )
    )


@router.patch("/projects/{project_id}/chapters/{code}", dependencies=[EDIT])
async def patch_chapter(
    project_id: uuid.UUID,
    code: str,
    body: ChapterPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = ProjectHandbookService(session)
    actor = _actor(user_id, payload)
    await _run(svc.patch_chapter(project_id, code, body.model_dump(exclude_unset=True), actor))
    return await _run(svc.get_chapter(project_id, code, locale=get_locale() or "en", actor=actor))


async def _transition(
    name: str, project_id: uuid.UUID, code: str, session: Any, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    svc = ProjectHandbookService(session)
    actor = _actor(user_id, payload)
    await _run(getattr(svc, name)(project_id, code, actor))
    return await _run(svc.get_chapter(project_id, code, locale=get_locale() or "en", actor=actor))


@router.post("/projects/{project_id}/chapters/{code}/submit", dependencies=[EDIT])
async def submit_chapter(
    project_id: uuid.UUID, code: str, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _transition("submit", project_id, code, session, user_id, payload)


@router.post("/projects/{project_id}/chapters/{code}/approve", dependencies=[MANAGE_DEP])
async def approve_chapter(
    project_id: uuid.UUID, code: str, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _transition("approve", project_id, code, session, user_id, payload)


@router.post("/projects/{project_id}/chapters/{code}/return", dependencies=[MANAGE_DEP])
async def return_chapter(
    project_id: uuid.UUID, code: str, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _transition("return_chapter", project_id, code, session, user_id, payload)


@router.get("/projects/{project_id}/chapters/{code}/versions", dependencies=[READ])
async def chapter_versions(
    project_id: uuid.UUID, code: str, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(ProjectHandbookService(session).versions(project_id, code)))


# ── findings, export ───────────────────────────────────────────────────────


@router.get("/projects/{project_id}/findings", dependencies=[READ])
async def handbook_findings(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Findings of the handbook rules (read only)."""
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(ProjectHandbookService(session).findings(project_id)))


@router.get("/projects/{project_id}/validation", dependencies=[READ])
async def validation(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The handbook run through the registered rule set."""
    from app.core.validation.engine import ValidationContext
    from app.modules.project_handbook.validators import HANDBOOK_RULES

    await verify_project_access(project_id, user_id, session)
    data = await _run(ProjectHandbookService(session).validation_payload(project_id))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    results: list[dict[str, Any]] = []
    for rule_cls in HANDBOOK_RULES:
        for r in await rule_cls().validate(context):
            results.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(r.severity),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
            )
    return _page(results)


@router.get("/projects/{project_id}/export", dependencies=[READ])
async def export(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    """The whole handbook as one PDF, with the live records of every source as they are now."""
    from app.modules.project_handbook import export as ex

    await verify_project_access(project_id, user_id, session)
    locale = get_locale() or "en"
    data = await _run(ProjectHandbookService(session).export_data(project_id, locale))
    return _file(ex.render(data, locale=locale), "project_handbook", locale)


# ── data room ──────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/data-room", dependencies=[READ])
async def get_data_room(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The materialised folder tree with the number of documents the caller may read per folder."""
    await verify_project_access(project_id, user_id, session)
    return await _run(ProjectHandbookService(session).data_room(project_id, _uid(user_id)))


@router.post("/projects/{project_id}/data-room/materialise", dependencies=[MANAGE_DEP])
async def materialise_data_room(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Create or update the folders of the project's phase model in the document tree; idempotent."""
    await verify_project_access(project_id, user_id, session)
    return await _run(data_room.materialise(session, project_id))


@router.post("/projects/{project_id}/data-room/place", dependencies=[EDIT])
async def place_document(
    project_id: uuid.UUID, body: PlaceDocument, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """File one document of the project into a folder named by code, or into the folder of an area or subject."""
    await verify_project_access(project_id, user_id, session)
    folder = await _run(
        data_room.place_document(
            session,
            project_id,
            body.document_id,
            folder_code=body.folder_code,
            subject=body.subject,
            area_code=body.area_code,
        )
    )
    return {"document_id": str(body.document_id), "folder_id": str(folder.id), "folder_code": folder.code}
