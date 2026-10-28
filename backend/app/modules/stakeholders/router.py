# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Stakeholders API, mounted at ``/api/v1/stakeholders``.

The module loader mounts one prefix per module, so the SPEC's two roots are
realised as ``/api/v1/stakeholders/projects/{project_id}/...`` (register,
plan, events, commitments) and ``/api/v1/stakeholders/projects/{project_id}/organisation/...``
(roles, bodies, mandates). Every project route calls ``verify_project_access``
before it reads anything, so a project the caller cannot see answers 404
exactly like a missing one; child rows are read by ``(project_id, id)`` and
links into other modules are checked against the project or tenant (rule 22).

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``stakeholders.errors.<code>``. 404 = not found
or not visible, 403 = not the deciding role, 409 = state conflict, 422 =
invalid input or a refusing rule.

Names of private persons (``is_confidential``) are returned only to callers
holding ``stakeholders.read_personal``; others get ``name: null, masked: true``
in lists and ``(confidential)`` in exports (rule 17).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.stakeholders.catalogue import FRAMEWORK_KIND
from app.modules.stakeholders.errors import StakeholderError
from app.modules.stakeholders.messages import translate
from app.modules.stakeholders.schemas import (
    AssessmentIn,
    BodyIn,
    CommitmentIn,
    CommitmentTransition,
    EventIn,
    FileExportIn,
    FrameworkCreate,
    FrameworkUpdate,
    MandatesPut,
    MembersPut,
    PlanItemIn,
    RoleHoldersPut,
    SettingsPut,
    StakeholderIn,
)
from app.modules.stakeholders.service import StakeholderService

router = APIRouter(tags=["stakeholders"])

READ = Depends(RequirePermission("stakeholders.read"))
EDIT = Depends(RequirePermission("stakeholders.edit"))
ORG = Depends(RequirePermission("organisation.manage"))
CATALOGUE = Depends(RequirePermission("stakeholders.catalogue"))
_MEDIA = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


async def _run[T](awaitable: Awaitable[T]) -> T:
    """Turn a :class:`StakeholderError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except StakeholderError as exc:
        message = translate(f"stakeholders.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = StakeholderError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"stakeholders.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


async def _refuse(code: str, status_code: int = 422) -> None:
    """Raise a named, translated refusal through the same path as a service error."""
    raise StakeholderError(code, status_code)


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _today(value: date | None) -> date:
    return value or datetime.now(UTC).date()


def _page(items: list[Any], offset: int = 0, limit: int | None = None, **extra: Any) -> dict[str, Any]:
    total = len(items)
    window = items[offset : offset + limit] if limit is not None else items[offset:]
    return {"items": window, "total": total, "offset": offset, "limit": limit if limit is not None else total, **extra}


def _tenant(payload: dict[str, Any]) -> str:
    tenant = resolve_tenant_id(payload)
    if not tenant:
        raise HTTPException(status_code=404, detail="Not found")
    return tenant


def _has(payload: dict[str, Any], permission: str) -> bool:
    from app.core.permissions import permission_registry

    role = str(payload.get("role") or "")
    return (
        role == "admin"
        or permission in (payload.get("permissions") or [])
        or permission_registry.role_has_permission(role, permission)
    )


def _data(body: Any) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


# ── catalogue admin (tenant scoped) ────────────────────────────────────────


async def _framework_out(store: Any, row: Any) -> dict[str, Any]:
    versions = await store.repo.list_catalogue_versions(row.id)
    return {
        "id": str(row.id),
        "kind": row.kind,
        "code": row.code,
        "name": row.name,
        "based_on": row.based_on,
        "state": row.state,
        "draft_body": row.draft_body,
        "versions": [
            {
                "version": v.version,
                "content_hash": v.content_hash,
                "published_by": str(v.published_by) if v.published_by else None,
                "published_at": v.published_at.isoformat(),
            }
            for v in versions
        ],
        "validation_errors": store.validation_errors(row),
    }


async def _own_framework(store: Any, tenant: str, catalogue_id: uuid.UUID) -> Any:
    row = await _run(store.get(tenant, catalogue_id))
    if row.kind != FRAMEWORK_KIND:
        raise HTTPException(status_code=404, detail={"code": "unknown_catalogue"})
    return row


@router.get("/frameworks", dependencies=[READ])
async def list_frameworks(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Shipped stakeholder frameworks and the caller's tenant frameworks."""
    from app.modules.project_governance.catalogue_store import CatalogueStore

    StakeholderService(session)  # registers the kind
    items = await _run(CatalogueStore(session).list_available(resolve_tenant_id(payload), kind=FRAMEWORK_KIND))
    return _page(items)


@router.get("/frameworks/shipped/{framework_id}", dependencies=[READ])
async def get_shipped_framework(framework_id: str, session: SessionDep, version: int | None = None) -> dict[str, Any]:
    """The full body of a shipped framework (labels, scales, formats, template)."""
    svc = StakeholderService(session)
    fw = await _run(svc.framework("shipped", framework_id, version))
    return fw.model_dump(mode="json")


@router.post("/frameworks", status_code=201, dependencies=[CATALOGUE])
async def create_framework(
    body: FrameworkCreate, session: SessionDep, payload: CurrentUserPayload, user_id: CurrentUserId
) -> dict[str, Any]:
    """Clone a shipped or own framework into a tenant draft."""
    from app.modules.project_governance.catalogue_store import CatalogueStore

    StakeholderService(session)
    store = CatalogueStore(session)
    row = await _run(
        store.create(
            _tenant(payload),
            code=body.code,
            name=body.name,
            based_on_source=body.based_on_source,
            based_on_id=body.based_on_id,
            based_on_version=body.based_on_version,
            actor_id=_uid(user_id),
            kind=FRAMEWORK_KIND,
        )
    )
    return await _framework_out(store, row)


@router.get("/frameworks/{catalogue_id}", dependencies=[READ])
async def get_framework(catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    StakeholderService(session)
    store = CatalogueStore(session)
    return await _framework_out(store, await _own_framework(store, _tenant(payload), catalogue_id))


@router.patch("/frameworks/{catalogue_id}", dependencies=[CATALOGUE])
async def update_framework(
    catalogue_id: uuid.UUID, body: FrameworkUpdate, session: SessionDep, payload: CurrentUserPayload
) -> dict[str, Any]:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    StakeholderService(session)
    store = CatalogueStore(session)
    tenant = _tenant(payload)
    await _own_framework(store, tenant, catalogue_id)
    row = await _run(store.update_draft(tenant, catalogue_id, body=body.body, name=body.name))
    return await _framework_out(store, row)


@router.post("/frameworks/{catalogue_id}/publish", dependencies=[CATALOGUE])
async def publish_framework(
    catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload, user_id: CurrentUserId
) -> dict[str, Any]:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    StakeholderService(session)
    store = CatalogueStore(session)
    tenant = _tenant(payload)
    await _own_framework(store, tenant, catalogue_id)
    v = await _run(store.publish(tenant, catalogue_id, actor_id=_uid(user_id)))
    return {"version": v.version, "content_hash": v.content_hash, "published_at": v.published_at.isoformat()}


@router.get("/frameworks/{catalogue_id}/diff", dependencies=[READ])
async def diff_framework(
    catalogue_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    v_from: int = Query(..., alias="from", ge=1),
    v_to: int = Query(..., alias="to", ge=1),
) -> dict[str, Any]:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    StakeholderService(session)
    store = CatalogueStore(session)
    tenant = _tenant(payload)
    await _own_framework(store, tenant, catalogue_id)
    return await _run(store.diff(tenant, catalogue_id, v_from, v_to))


# ── settings ───────────────────────────────────────────────────────────────


def _can(payload: dict[str, Any]) -> dict[str, bool]:
    """What the caller's permissions allow in this module; the same block with and without a pinned framework."""
    return {
        "edit": _has(payload, "stakeholders.edit"),
        "read_personal": _has(payload, "stakeholders.read_personal"),
        "manage_organisation": _has(payload, "organisation.manage"),
    }


def _settings_out(s: Any, fw: Any, payload: dict[str, Any], can_file: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "project_id": str(s.project_id),
        "framework_source": s.framework_source,
        "framework_id": s.framework_id,
        "framework_version": s.framework_version,
        "analysis_method": s.analysis_method,
        "review_interval_days": s.review_interval_days,
        "owner_area_code": s.owner_area_code,
        "commitment_route_id": str(s.commitment_route_id) if s.commitment_route_id else None,
        "framework": fw.model_dump(mode="json"),
        "can": _can(payload),
        # Filing an export as a frame document, per export: absent on a project run without gates.
        "can_file": can_file,
    }


async def _can_file(svc: StakeholderService, project_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    return await _run(svc.filing_can(project_id, can_manage=_has(payload, "organisation.manage")))


@router.get("/projects/{project_id}/settings", dependencies=[READ])
async def get_settings(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Pinned framework (full body) and register options; 404 ``settings_missing`` before the first pin.

    The 404 carries ``detail.can`` too, so the screen knows whether to offer the first pin.
    """
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    try:
        settings, fw = await _run(svc.context(project_id))
    except HTTPException as exc:
        if exc.status_code == 404 and isinstance(exc.detail, dict) and exc.detail.get("code") == "settings_missing":
            raise HTTPException(status_code=404, detail={**exc.detail, "can": _can(payload)}) from exc
        raise
    return _settings_out(settings, fw, payload, await _can_file(svc, project_id, payload))


@router.put("/projects/{project_id}/settings", dependencies=[ORG])
async def put_settings(
    project_id: uuid.UUID, body: SettingsPut, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Pin a framework (default by country) and set options; the first pin copies the mandate template."""
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    await _run(svc.put_settings(project_id, _data(body), actor_id=_uid(user_id), tenant_id=resolve_tenant_id(payload)))
    settings, fw = await _run(svc.context(project_id))
    return _settings_out(settings, fw, payload, await _can_file(svc, project_id, payload))


# ── stakeholders and assessments ───────────────────────────────────────────


@router.get("/projects/{project_id}/stakeholders", dependencies=[READ])
async def list_stakeholders(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    category: str | None = None,
    classification: str | None = None,
    review_due: bool | None = None,
    include_archived: bool = False,
    today: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """The register with classification, engagement, review flag and open commitments."""
    await verify_project_access(project_id, user_id, session)
    rows = await _run(
        StakeholderService(session).stakeholder_views(
            project_id, can_read_personal=_has(payload, "stakeholders.read_personal"), today=_today(today)
        )
    )
    rows = [
        r
        for r in rows
        if (include_archived or r["status"] != "archived")
        and (category is None or r["category"] == category)
        and (classification is None or r["classification"] == classification)
        and (review_due is None or r["review_due"] == review_due)
    ]
    return _page(rows, offset, limit)


@router.post("/projects/{project_id}/stakeholders", status_code=201, dependencies=[EDIT])
async def create_stakeholder(
    project_id: uuid.UUID, body: StakeholderIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    row = await _run(svc.create_stakeholder(project_id, _data(body), actor_id=_uid(user_id)))
    return await _stakeholder_detail(svc, project_id, row.id, payload)


async def _stakeholder_detail(svc: StakeholderService, project_id: uuid.UUID, sid: uuid.UUID, payload: dict) -> dict:
    views = await _run(
        svc.stakeholder_views(
            project_id, can_read_personal=_has(payload, "stakeholders.read_personal"), today=_today(None)
        )
    )
    view = next((v for v in views if v["id"] == str(sid)), None)
    if view is None:
        raise HTTPException(status_code=404, detail={"code": "stakeholder_not_found"})
    return view


@router.get("/projects/{project_id}/stakeholders/{stakeholder_id}", dependencies=[READ])
async def get_stakeholder(
    project_id: uuid.UUID,
    stakeholder_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    await _run(svc.get_stakeholder(project_id, stakeholder_id))
    return await _stakeholder_detail(svc, project_id, stakeholder_id, payload)


@router.patch("/projects/{project_id}/stakeholders/{stakeholder_id}", dependencies=[EDIT])
async def update_stakeholder(
    project_id: uuid.UUID,
    stakeholder_id: uuid.UUID,
    body: StakeholderIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    await _run(svc.update_stakeholder(project_id, stakeholder_id, _data(body), actor_id=_uid(user_id)))
    return await _stakeholder_detail(svc, project_id, stakeholder_id, payload)


@router.delete("/projects/{project_id}/stakeholders/{stakeholder_id}", dependencies=[EDIT])
async def archive_stakeholder(
    project_id: uuid.UUID, stakeholder_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Archive (history stays): assessments and commitments keep pointing at it."""
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        StakeholderService(session).archive_stakeholder(project_id, stakeholder_id, actor_id=_uid(user_id))
    )
    return {"id": str(row.id), "status": row.status}


@router.get("/projects/{project_id}/stakeholders/{stakeholder_id}/assessments", dependencies=[READ])
async def list_assessments(
    project_id: uuid.UUID, stakeholder_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """History, newest first, every method (decision d)."""
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    rows = await _run(svc.list_assessments(project_id, stakeholder_id))
    return _page([svc.assessment_out(a) for a in rows])


@router.post("/projects/{project_id}/stakeholders/{stakeholder_id}/assessments", status_code=201, dependencies=[EDIT])
async def create_assessment(
    project_id: uuid.UUID, stakeholder_id: uuid.UUID, body: AssessmentIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    row = await _run(svc.assess(project_id, stakeholder_id, body.model_dump(), actor_id=_uid(user_id)))
    return svc.assessment_out(row)


@router.get("/projects/{project_id}/grid", dependencies=[READ])
async def grid(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    method: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Grid positions under one method; stakeholders without an assessment of it are ``not_assessed``."""
    await verify_project_access(project_id, user_id, session)
    return await _run(
        StakeholderService(session).grid(
            project_id,
            method=method,
            can_read_personal=_has(payload, "stakeholders.read_personal"),
            today=_today(today),
        )
    )


# ── communication plan and events ─────────────────────────────────────────


@router.get("/projects/{project_id}/plan-items", dependencies=[READ])
async def list_plan_items(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    await _run(svc.context(project_id))
    return _page([svc.plan_out(p, _today(today)) for p in await svc.repo.plan_items(project_id)])


@router.get("/projects/{project_id}/plan-items/due", dependencies=[READ])
async def due(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    start: date | None = None,
    end: date | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Communication calendar: computed occurrences in the window plus overdue ones (not stored)."""
    await verify_project_access(project_id, user_id, session)
    day = _today(today)
    lo = start or day - timedelta(days=30)
    hi = end or day + timedelta(days=90)
    if hi < lo or (hi - lo).days > 731:
        await _run(_refuse("invalid_window"))
    return _page(await _run(StakeholderService(session).due(project_id, start=lo, end=hi, today=day)))


@router.post("/projects/{project_id}/plan-items", status_code=201, dependencies=[EDIT])
async def create_plan_item(
    project_id: uuid.UUID, body: PlanItemIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    row = await _run(svc.create_plan_item(project_id, _data(body), actor_id=_uid(user_id)))
    return svc.plan_out(row, _today(None))


@router.patch("/projects/{project_id}/plan-items/{item_id}", dependencies=[EDIT])
async def update_plan_item(
    project_id: uuid.UUID, item_id: uuid.UUID, body: PlanItemIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    row = await _run(svc.update_plan_item(project_id, item_id, _data(body), actor_id=_uid(user_id)))
    return svc.plan_out(row, _today(None))


@router.delete("/projects/{project_id}/plan-items/{item_id}", status_code=204, dependencies=[EDIT])
async def delete_plan_item(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(StakeholderService(session).delete_plan_item(project_id, item_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


@router.post("/projects/{project_id}/plan-items/{item_id}/record", status_code=201, dependencies=[EDIT])
async def record_occurrence(
    project_id: uuid.UUID, item_id: uuid.UUID, body: EventIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Record a held occurrence of a plan item; advances its ``next_due`` (rule 7)."""
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    data = {**_data(body), "plan_item_id": str(item_id), "status": "held"}
    if not data.get("held_on"):
        data["held_on"] = _today(None)
    row = await _run(svc.create_event(project_id, data, actor_id=_uid(user_id)))
    _settings, fw = await _run(svc.context(project_id))
    return svc.event_out(row, fw, _today(None))


@router.get("/projects/{project_id}/events", dependencies=[READ])
async def list_events(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    stakeholder_id: uuid.UUID | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    _settings, fw = await _run(svc.context(project_id))
    rows = await svc.repo.events(project_id)
    if stakeholder_id is not None:
        rows = [e for e in rows if str(stakeholder_id) in (e.stakeholder_ids or [])]
    return _page([svc.event_out(e, fw, _today(today)) for e in rows])


@router.post("/projects/{project_id}/events", status_code=201, dependencies=[EDIT])
async def create_event(
    project_id: uuid.UUID, body: EventIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    row = await _run(svc.create_event(project_id, _data(body), actor_id=_uid(user_id)))
    _settings, fw = await _run(svc.context(project_id))
    return svc.event_out(row, fw, _today(None))


@router.patch("/projects/{project_id}/events/{event_id}", dependencies=[EDIT])
async def update_event(
    project_id: uuid.UUID, event_id: uuid.UUID, body: EventIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    data = _data(body)
    data.pop("plan_item_id", None)
    row = await _run(svc.update_event(project_id, event_id, data, actor_id=_uid(user_id)))
    _settings, fw = await _run(svc.context(project_id))
    return svc.event_out(row, fw, _today(None))


@router.delete("/projects/{project_id}/events/{event_id}", status_code=204, dependencies=[EDIT])
async def delete_event(
    project_id: uuid.UUID, event_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    """Soft delete: commitments made at the event keep their source (rule 9)."""
    await verify_project_access(project_id, user_id, session)
    await _run(StakeholderService(session).delete_event(project_id, event_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


# ── commitments ────────────────────────────────────────────────────────────


async def _commitments_out(
    svc: StakeholderService, project_id: uuid.UUID, rows: list[Any], payload: dict[str, Any], user_id: str, day: date
) -> list[dict[str, Any]]:
    """Commitment rows with the caller's ``can`` block."""
    can = await _run(
        svc.commitment_can(
            project_id, rows, actor_id=_uid(user_id), can_edit=_has(payload, "stakeholders.edit"), today=day
        )
    )
    return [{**svc.commitment_out(c, day), "can": can[str(c.id)]} for c in rows]


@router.get("/projects/{project_id}/commitments", dependencies=[READ])
async def list_commitments(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    status: str | None = None,
    stakeholder_id: uuid.UUID | None = None,
    overdue: bool | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    await _run(svc.context(project_id))
    day = _today(today)
    rows = await _commitments_out(svc, project_id, await svc.repo.commitments(project_id), payload, user_id, day)
    rows = [
        r
        for r in rows
        if (status is None or r["status"] == status)
        and (stakeholder_id is None or str(stakeholder_id) in r["stakeholder_ids"])
        and (overdue is None or r["overdue"] == overdue)
    ]
    return _page(rows)


@router.post("/projects/{project_id}/commitments", status_code=201, dependencies=[EDIT])
async def create_commitment(
    project_id: uuid.UUID, body: CommitmentIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    row = await _run(svc.create_commitment(project_id, _data(body), actor_id=_uid(user_id)))
    return (await _commitments_out(svc, project_id, [row], payload, user_id, _today(None)))[0]


@router.get("/projects/{project_id}/commitments/{commitment_id}", dependencies=[READ])
async def get_commitment(
    project_id: uuid.UUID,
    commitment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    row = await _run(svc.get_commitment(project_id, commitment_id))
    return (await _commitments_out(svc, project_id, [row], payload, user_id, _today(None)))[0]


@router.patch("/projects/{project_id}/commitments/{commitment_id}", dependencies=[EDIT])
async def update_commitment(
    project_id: uuid.UUID,
    commitment_id: uuid.UUID,
    body: CommitmentIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    data = _data(body)
    data.pop("source_kind", None)
    data.pop("source_ref", None)
    row = await _run(
        svc.update_commitment(
            project_id,
            commitment_id,
            data,
            actor_id=_uid(user_id),
            can_manage=_has(payload, "organisation.manage"),
        )
    )
    return (await _commitments_out(svc, project_id, [row], payload, user_id, _today(None)))[0]


@router.post("/projects/{project_id}/commitments/{commitment_id}/transition", dependencies=[EDIT])
async def transition_commitment(
    project_id: uuid.UUID,
    commitment_id: uuid.UUID,
    body: CommitmentTransition,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Move a commitment; ``agreed`` / ``withdrawn`` are mandate decisions (rule 10), possibly via approval.

    The date that decides who holds the mandate today is the server's, never the caller's.
    """
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    day = _today(None)
    row, warnings = await _run(
        svc.transition_commitment(
            project_id,
            commitment_id,
            body.target,
            actor_id=_uid(user_id),
            rationale=body.rationale,
            communicated_back_at=body.communicated_back_at,
            loop_not_required_rationale=body.loop_not_required_rationale,
            create_risk=body.create_risk,
            today=day,
        )
    )
    return {**(await _commitments_out(svc, project_id, [row], payload, user_id, day))[0], "warnings": warnings}


# ── sweep, readiness, validation, export ──────────────────────────────────


@router.post("/projects/{project_id}/sweep", dependencies=[EDIT])
async def sweep(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict:
    """The daily job for one project, on the server date: review, plan and commitment notices (each once)."""
    await verify_project_access(project_id, user_id, session)
    return await _run(StakeholderService(session).sweep(project_id, today=_today(None)))


@router.get("/projects/{project_id}/readiness", dependencies=[READ])
async def readiness(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict:
    """The five governance evidence checks (rule 20) as module 1 sees them."""
    await verify_project_access(project_id, user_id, session)
    return await _run(StakeholderService(session).readiness(project_id, today=_today(today)))


@router.get("/projects/{project_id}/validation", dependencies=[READ])
async def validation(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext
    from app.modules.stakeholders.validators import STAKEHOLDER_RULES

    await verify_project_access(project_id, user_id, session)
    data = await _run(StakeholderService(session).validation_payload(project_id, today=_today(today)))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    findings: list[dict[str, Any]] = []
    for rule_cls in STAKEHOLDER_RULES:
        for r in await rule_cls().validate(context):
            findings.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(r.severity),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
            )
    return _page(findings)


async def _render(
    svc: StakeholderService, project_id: uuid.UUID, which: str, fmt: str, can_read_personal: bool
) -> tuple[bytes, str, str]:
    """The document, its file name and the language it was written in."""
    from app.modules.projects.models import Project
    from app.modules.stakeholders import export

    _settings, fw = await _run(svc.context(project_id))
    day = _today(None)
    locale = export.written_locale(get_locale())
    project = await svc.session.get(Project, project_id)
    name = getattr(project, "name", "") or ""
    if which == "organisation":
        docs = export.organisation_documents(
            fw,
            roles=await _run(svc.roles_view(project_id, today=day)),
            bodies=await _run(svc.bodies_view(project_id, today=day)),
            matrix=await _run(svc.matrix(project_id, today=day)),
            project_name=name,
            locale=locale,
        )
        stem = "project_organisation_and_mandates"
    else:
        docs = export.register_documents(
            fw,
            stakeholders=await _run(svc.stakeholder_views(project_id, can_read_personal=can_read_personal, today=day)),
            plan_items=[svc.plan_out(p, day) for p in await svc.repo.plan_items(project_id)],
            commitments=[svc.commitment_out(c, day) for c in await svc.repo.commitments(project_id)],
            project_name=name,
            locale=locale,
        )
        stem = "stakeholder_and_communication_plan"
    return export.render(docs, fmt), f"{stem}.{fmt}", locale


@router.get("/projects/{project_id}/gates", dependencies=[READ])
async def list_gates(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The project's gates for the plan trigger picker.

    ``gates_in_use`` is false on a project run without gates: there is nothing
    to pick then, and a plan item takes neither the gate trigger nor one of
    ``gate_bound_event_triggers``, the listened events only a gate can cause.
    """
    from app.modules.stakeholders.service import GATE_BOUND_EVENT_TRIGGERS

    await verify_project_access(project_id, user_id, session)
    items = await _run(StakeholderService(session).gates(project_id))
    return {
        "items": items,
        "gates_in_use": bool(items),
        "gate_bound_event_triggers": list(GATE_BOUND_EVENT_TRIGGERS),
    }


@router.get("/projects/{project_id}/requirements", dependencies=[READ])
async def list_requirements(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Requirements of the project's sets, for the commitment link picker."""
    await verify_project_access(project_id, user_id, session)
    return {"items": await _run(StakeholderService(session).requirement_options(project_id))}


@router.get("/projects/{project_id}/release-items", dependencies=[READ])
async def list_release_items(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Release items for the commitment link picker; ``available: false`` while no module provides them."""
    await verify_project_access(project_id, user_id, session)
    return await _run(StakeholderService(session).release_item_options(project_id))


@router.get("/projects/{project_id}/export", dependencies=[READ])
async def export_register(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
) -> Response:
    """Stakeholder and communication plan as PDF or XLSX; private names masked without ``read_personal``."""
    await verify_project_access(project_id, user_id, session)
    content, file_name, locale = await _render(
        StakeholderService(session), project_id, "register", fmt, _has(payload, "stakeholders.read_personal")
    )
    return Response(
        content=content,
        media_type=_MEDIA[fmt],
        # The language the document was written in, which is not always the one asked for.
        headers={"Content-Disposition": f'attachment; filename="{file_name}"', "Content-Language": locale},
    )


@router.post("/projects/{project_id}/frame-documents/file", status_code=201, dependencies=[ORG])
async def file_frame_document(
    project_id: uuid.UUID, body: FileExportIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """File an export as a CDE revision of the owner area's frame document (rule 21).

    The filed register always masks private names: the gate document goes to many readers (decision m).
    """
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    content, file_name, _locale = await _render(svc, project_id, body.document, body.format, False)
    return await _run(
        svc.file_frame_document(
            project_id,
            which=body.document,
            content=content,
            file_name=file_name,
            mime_type=_MEDIA[body.format],
            actor_id=_uid(user_id),
            change_reason=body.change_reason,
            change_impact=body.change_impact,
            can_manage_governance=_has(payload, "governance.manage"),
        )
    )


# ── organisation: roles, bodies, mandates ──────────────────────────────────


@router.get("/projects/{project_id}/organisation/roles", dependencies=[READ])
async def list_roles(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict:
    """Framework roles, holders (with validity today) and vacancies (rule 14)."""
    await verify_project_access(project_id, user_id, session)
    return await _run(StakeholderService(session).roles_view(project_id, today=_today(today)))


@router.put("/projects/{project_id}/organisation/roles/{role_code}", dependencies=[ORG])
async def put_role_holders(
    project_id: uuid.UUID,
    body: RoleHoldersPut,
    session: SessionDep,
    user_id: CurrentUserId,
    role_code: str = Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"),
) -> dict[str, Any]:
    """Replace the holders of one role; returns conflicts (warnings), area owner hints and frame warnings."""
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    day = _today(None)
    result = await _run(
        svc.put_role_holders(
            project_id,
            role_code,
            [h.model_dump() for h in body.holders],
            actor_id=_uid(user_id),
            custom_label=body.custom_label,
            today=day,
        )
    )
    return {**await _run(svc.roles_view(project_id, today=day)), **result}


@router.get("/projects/{project_id}/organisation/bodies", dependencies=[READ])
async def list_bodies(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(StakeholderService(session).bodies_view(project_id, today=_today(today))))


async def _body_view(svc: StakeholderService, project_id: uuid.UUID, body_id: uuid.UUID) -> dict[str, Any]:
    views = await _run(svc.bodies_view(project_id, today=_today(None)))
    return next(v for v in views if v["id"] == str(body_id))


@router.post("/projects/{project_id}/organisation/bodies", status_code=201, dependencies=[ORG])
async def create_body(
    project_id: uuid.UUID, body: BodyIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    row = await _run(svc.create_body(project_id, _data(body), actor_id=_uid(user_id)))
    return await _body_view(svc, project_id, row.id)


@router.patch("/projects/{project_id}/organisation/bodies/{body_id}", dependencies=[ORG])
async def update_body(
    project_id: uuid.UUID, body_id: uuid.UUID, body: BodyIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    data = _data(body)
    data.pop("code", None)
    await _run(svc.update_body(project_id, body_id, data, actor_id=_uid(user_id)))
    return await _body_view(svc, project_id, body_id)


@router.delete("/projects/{project_id}/organisation/bodies/{body_id}", status_code=204, dependencies=[ORG])
async def delete_body(
    project_id: uuid.UUID, body_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(StakeholderService(session).delete_body(project_id, body_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


@router.put("/projects/{project_id}/organisation/bodies/{body_id}/members", dependencies=[ORG])
async def put_members(
    project_id: uuid.UUID, body_id: uuid.UUID, body: MembersPut, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    await _run(
        svc.put_members(
            project_id, body_id, [m.model_dump() for m in body.members], actor_id=_uid(user_id), today=_today(None)
        )
    )
    return await _body_view(svc, project_id, body_id)


@router.get("/projects/{project_id}/organisation/mandates", dependencies=[READ])
async def get_mandates(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict:
    """The matrix: decision types x roles and bodies, letters, missing deciders, conflicts."""
    await verify_project_access(project_id, user_id, session)
    return await _run(StakeholderService(session).matrix(project_id, today=_today(today)))


@router.put("/projects/{project_id}/organisation/mandates", dependencies=[ORG])
async def put_mandates(project_id: uuid.UUID, body: MandatesPut, session: SessionDep, user_id: CurrentUserId) -> dict:
    """Replace the matrix; 422 ``two_deciders`` / ``self_approval_forbidden`` with violations."""
    await verify_project_access(project_id, user_id, session)
    svc = StakeholderService(session)
    day = _today(None)
    result = await _run(
        svc.put_mandates(project_id, [r.model_dump() for r in body.rows], actor_id=_uid(user_id), today=day)
    )
    return {**await _run(svc.matrix(project_id, today=day)), **result}


@router.get("/projects/{project_id}/organisation/who-decides", dependencies=[READ])
async def who_decides(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    decision_type: str,
    scope: str = "",
    amount: str | None = None,
    currency: str | None = Query(None, max_length=3),
    today: date | None = None,
) -> dict[str, Any]:
    """Rule 11: role or body holders today, and, with an amount, module 2's tier (or ``authority_not_evaluated``)."""
    await verify_project_access(project_id, user_id, session)
    return await _run(
        StakeholderService(session).who_decides(
            project_id, decision_type, scope, today=_today(today), amount=amount, currency=currency
        )
    )


@router.get("/projects/{project_id}/organisation/conflicts", dependencies=[READ])
async def conflicts(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(StakeholderService(session).conflicts(project_id, today=_today(today))))


@router.get("/projects/{project_id}/organisation/export", dependencies=[READ])
async def export_organisation(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
) -> Response:
    """Project organisation and mandates as PDF or XLSX."""
    await verify_project_access(project_id, user_id, session)
    # The organisation tables carry roles and bodies, no private person, so nothing is masked.
    content, file_name, locale = await _render(StakeholderService(session), project_id, "organisation", fmt, True)
    return Response(
        content=content,
        media_type=_MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="{file_name}"', "Content-Language": locale},
    )
