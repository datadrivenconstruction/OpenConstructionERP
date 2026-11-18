# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document layout API, mounted at ``/api/v1/doc-templates/layouts/``.

GET    /                                  - documents a firm can lay out
GET    /clauses                           - clause library
PUT    /clauses/{key}                     - create or replace a clause (manager)
DELETE /clauses/{key}                     - delete a clause (manager)
GET    /{key}?project_id=&variant=        - editor: spec, locks, template in force, draft, versions, variants
PUT    /{key}/draft                       - save the working template
DELETE /{key}/draft                       - discard it
POST   /{key}/publish                     - publish the draft (422 when a lock or a field is broken)
POST   /{key}/reset                       - publish "standard"
POST   /{key}/default                     - make this variant the default of its scope
DELETE /{key}/variant                     - delete this variant
GET    /{key}/versions/{id}               - the template a version printed
GET    /{key}/versions/{id}/diff?against= - block changes a version makes to another (or to standard)
POST   /{key}/versions/{id}/restore       - publish a copy of an old version
GET    /{key}/export                      - the template in force as a JSON file
POST   /{key}/import                      - load a JSON file into the draft
GET    /{key}/records                     - records "Preview with" can use
GET    /{key}/values?record_id=           - merge field values of a record (or the sample), for the picker
POST   /{key}/preview?locale=             - PDF of an unsaved template

Everyone with ``doc_templates.read`` may open a layout; editing needs the
Document manager role. A project override also needs access to the project.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.doc_templates import layout_service as ls
from app.modules.doc_templates.permissions import is_doc_manager
from app.modules.doc_templates.schemas import (
    ClauseIn,
    LayoutDraftIn,
    LayoutImportIn,
    LayoutListResponse,
    LayoutPreviewIn,
    LayoutPublishIn,
    LayoutSummary,
)
from app.modules.doc_templates.service import workspace_countries

layout_router = APIRouter()

_READ = [Depends(RequirePermission("doc_templates.read"))]
_KEY = Path(..., pattern=r"^[a-z][a-z0-9_]{0,40}\.[a-z][a-z0-9_]{0,60}$")
_CLAUSE_KEY = Path(..., pattern=r"^[a-z][a-z0-9_]{0,39}$")
_PROJECT = Query(None, description="Project override; the company default when absent")
_VARIANT = Query("standard", max_length=40)
_LOCALE = Query("en", max_length=10)


async def _can_edit(session: Any, user_id: str, payload: dict[str, Any]) -> bool:
    from app.modules.users.models import User

    user = await session.get(User, uuid.UUID(user_id))
    if user is None:
        return False
    return is_doc_manager(payload.get("role") or user.role, user.metadata_)


async def _scope(session: Any, user_id: str, project_id: uuid.UUID | None) -> str:
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    return ls.scope_for(project_id)


async def _editor(session: Any, user_id: str, payload: dict[str, Any], project_id: uuid.UUID | None) -> str:
    scope = await _scope(session, user_id, project_id)
    if not await _can_edit(session, user_id, payload):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: doc_templates.edit")
    return scope


async def _full_state(
    session: Any,
    key: str,
    *,
    project_id: uuid.UUID | None,
    variant: str,
    locale: str,
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    spec = ls.require_layout(key)
    scope = await _scope(session, user_id, project_id)
    countries = await workspace_countries(session, payload, user_id)
    return {
        "spec": ls.describe(spec, locale, countries),
        "state": await ls.state(session, spec, scope=scope, variant=ls.clean_variant(variant), countries=countries),
        "can_edit": await _can_edit(session, user_id, payload),
    }


@layout_router.get("/", response_model=LayoutListResponse, dependencies=_READ)
async def list_layouts(session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload) -> LayoutListResponse:
    """Every document whose module is enabled and whose layout a firm can change."""
    items = [LayoutSummary.model_validate(row) for row in await ls.list_summaries(session)]
    return LayoutListResponse(items=items, total=len(items), can_edit=await _can_edit(session, user_id, payload))


@layout_router.get("/clauses", dependencies=_READ)
async def list_clauses(session: SessionDep) -> dict[str, Any]:
    """The clause library a clause block can print."""
    items = await ls.list_clauses(session)
    return {"items": items, "total": len(items)}


@layout_router.put("/clauses/{clause_key}", dependencies=_READ)
async def save_clause(
    body: ClauseIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    clause_key: str = _CLAUSE_KEY,
) -> dict[str, Any]:
    """Create or replace one clause."""
    await _editor(session, user_id, payload, None)
    out = await ls.save_clause(session, clause_key, body.category, body.title, body.text, user_id)
    await session.commit()
    return out


@layout_router.delete("/clauses/{clause_key}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_READ)
async def delete_clause(
    session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload, clause_key: str = _CLAUSE_KEY
) -> Response:
    """Delete one clause."""
    await _editor(session, user_id, payload, None)
    await ls.delete_clause(session, clause_key)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@layout_router.get("/{key}", dependencies=_READ)
async def get_layout_state(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Everything the editor needs for one layout in one scope and variant."""
    return await _full_state(
        session, key, project_id=project_id, variant=variant, locale=locale, user_id=user_id, payload=payload
    )


@layout_router.put("/{key}/draft", dependencies=_READ)
async def save_draft(
    body: LayoutDraftIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Store the working template and return the new state with its issues."""
    spec = ls.require_layout(key)
    scope = await _editor(session, user_id, payload, project_id)
    await ls.save_draft(
        session,
        spec,
        scope=scope,
        variant=ls.clean_variant(variant),
        template=body.template,
        name=body.name,
        user_id=user_id,
    )
    await session.commit()
    return await _full_state(
        session, key, project_id=project_id, variant=variant, locale=locale, user_id=user_id, payload=payload
    )


@layout_router.delete("/{key}/draft", dependencies=_READ)
async def discard_draft(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Drop the working template."""
    spec = ls.require_layout(key)
    scope = await _editor(session, user_id, payload, project_id)
    await ls.discard_draft(session, spec, scope=scope, variant=ls.clean_variant(variant))
    await session.commit()
    return await _full_state(
        session, key, project_id=project_id, variant=variant, locale=locale, user_id=user_id, payload=payload
    )


@layout_router.post("/{key}/publish", dependencies=_READ)
async def publish(
    body: LayoutPublishIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Publish the draft as a new version."""
    spec = ls.require_layout(key)
    scope = await _editor(session, user_id, payload, project_id)
    countries = await workspace_countries(session, payload, user_id)
    await ls.publish(
        session,
        spec,
        scope=scope,
        variant=ls.clean_variant(variant),
        note=body.note,
        countries=countries,
        user_id=user_id,
    )
    await session.commit()
    return await _full_state(
        session, key, project_id=project_id, variant=variant, locale=locale, user_id=user_id, payload=payload
    )


@layout_router.post("/{key}/reset", dependencies=_READ)
async def reset(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Publish the standard template: the document prints as the platform ships it."""
    spec = ls.require_layout(key)
    scope = await _editor(session, user_id, payload, project_id)
    await ls.reset(session, spec, scope=scope, variant=ls.clean_variant(variant), user_id=user_id)
    await session.commit()
    return await _full_state(
        session, key, project_id=project_id, variant=variant, locale=locale, user_id=user_id, payload=payload
    )


@layout_router.post("/{key}/default", dependencies=_READ)
async def make_default(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Make this variant the one documents print when none is picked."""
    spec = ls.require_layout(key)
    scope = await _editor(session, user_id, payload, project_id)
    await ls.set_default(session, spec, scope=scope, variant=ls.clean_variant(variant), user_id=user_id)
    await session.commit()
    return await _full_state(
        session, key, project_id=project_id, variant=variant, locale=locale, user_id=user_id, payload=payload
    )


@layout_router.delete("/{key}/variant", dependencies=_READ)
async def delete_variant(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Delete one variant and its versions; the editor returns to the standard variant."""
    spec = ls.require_layout(key)
    scope = await _editor(session, user_id, payload, project_id)
    await ls.delete_variant(session, spec, scope=scope, variant=ls.clean_variant(variant), user_id=user_id)
    await session.commit()
    return await _full_state(
        session,
        key,
        project_id=project_id,
        variant=ls.STANDARD_VARIANT,
        locale=locale,
        user_id=user_id,
        payload=payload,
    )


@layout_router.get("/{key}/versions/{version_id}", dependencies=_READ)
async def get_version(version_id: uuid.UUID, session: SessionDep, key: str = _KEY) -> dict[str, Any]:
    """The template one version printed."""
    spec = ls.require_layout(key)
    return {"template": await ls.version_document(session, spec, version_id)}


@layout_router.get("/{key}/versions/{version_id}/diff", dependencies=_READ)
async def diff_version(
    version_id: uuid.UUID,
    session: SessionDep,
    key: str = _KEY,
    against: uuid.UUID | None = Query(None, description="Older version; the standard template when absent"),
) -> dict[str, Any]:
    """Block-level changes a version makes to *against* (the standard template by default)."""
    spec = ls.require_layout(key)
    new = await ls.version_document(session, spec, version_id)
    old = await ls.version_document(session, spec, against) if against else ls.normalise(ls.standard_template(spec))
    return {"changes": ls.diff_templates(old, new)}


@layout_router.post("/{key}/versions/{version_id}/restore", dependencies=_READ)
async def restore(
    version_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Publish a copy of an old version as the newest one."""
    spec = ls.require_layout(key)
    scope = await _editor(session, user_id, payload, project_id)
    countries = await workspace_countries(session, payload, user_id)
    await ls.restore(
        session,
        spec,
        scope=scope,
        variant=ls.clean_variant(variant),
        version_id=version_id,
        countries=countries,
        user_id=user_id,
    )
    await session.commit()
    return await _full_state(
        session, key, project_id=project_id, variant=variant, locale=locale, user_id=user_id, payload=payload
    )


@layout_router.get("/{key}/export", response_model=None, dependencies=_READ)
async def export_layout(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
) -> Response:
    """The template in force (the draft when there is one) as a portable JSON file."""
    spec = ls.require_layout(key)
    scope = await _scope(session, user_id, project_id)
    countries = await workspace_countries(session, payload, user_id)
    current = await ls.state(session, spec, scope=scope, variant=ls.clean_variant(variant), countries=countries)
    body = ls.export_payload(spec, current["template"], current["name"])
    filename = f"{spec.key.replace('.', '-')}-{current['variant']}.json"
    return Response(
        content=json.dumps(body, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@layout_router.post("/{key}/import", dependencies=_READ)
async def import_layout(
    body: LayoutImportIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    project_id: uuid.UUID | None = _PROJECT,
    variant: str = _VARIANT,
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Load an exported layout into the draft; it is checked again on publish."""
    spec = ls.require_layout(key)
    scope = await _editor(session, user_id, payload, project_id)
    await ls.import_template(
        session,
        spec,
        scope=scope,
        variant=ls.clean_variant(variant),
        payload=body.model_dump(by_alias=True),
        user_id=user_id,
    )
    await session.commit()
    return await _full_state(
        session, key, project_id=project_id, variant=variant, locale=locale, user_id=user_id, payload=payload
    )


@layout_router.get("/{key}/records", dependencies=_READ)
async def list_records(session: SessionDep, user_id: CurrentUserId, key: str = _KEY) -> dict[str, Any]:
    """Records of projects the caller can open that "Preview with" can use."""
    spec = ls.require_layout(key)
    items: list[dict[str, str]] = []
    if spec.records is not None:
        ids = await accessible_project_ids(session, user_id)
        items = [{"id": rid, "label": label} for rid, label in await spec.records(session, ids)]
    return {"items": items, "total": len(items)}


@layout_router.get("/{key}/values", dependencies=_READ)
async def record_values(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    record_id: str | None = Query(None, max_length=64),
    locale: str = _LOCALE,
) -> dict[str, Any]:
    """Merge field values of a record (or the sample) for the picker, and the data it lacks to be issued."""
    spec = ls.require_layout(key)
    ids = await accessible_project_ids(session, user_id)
    ctx = await ls.preview_context(session, spec, locale, record_id, ids)
    _notes, problems = ls.data_issues(spec, ctx, await workspace_countries(session, payload, user_id))
    return {
        "values": ctx.values,
        "status": ctx.status,
        "rows": {k: len(v) for k, v in ctx.collections.items()},
        "issues": [i.as_dict() for i in problems] if record_id else [],
    }


@layout_router.post("/{key}/preview", response_model=None, dependencies=_READ)
async def preview(
    body: LayoutPreviewIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    key: str = _KEY,
    locale: str = _LOCALE,
) -> Response:
    """PDF of an unsaved template on a real record the caller can open, or on sample data."""
    spec = ls.require_layout(key)
    ids = await accessible_project_ids(session, user_id)
    pdf = await ls.preview_pdf(
        session,
        spec,
        body.template,
        locale=locale,
        record_id=body.record_id,
        project_ids=ids,
        countries=await workspace_countries(session, payload, user_id),
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store", "Content-Language": locale, "Content-Disposition": "inline"},
    )
