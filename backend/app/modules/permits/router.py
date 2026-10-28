# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permits API, mounted at ``/api/v1/permits``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are looked up by
``(project_id, id)`` and every soft link (activity, CDE revision, review cycle,
submission, inspection, observation, gate condition) is checked against the
project, so an id from another project is also 404 (rule 24).

Catalogue routes (``/catalogues``) are tenant scoped and go through module 1's
shared catalogue store with kind ``permit_type``.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``permits.errors.<code>``. 404 not found or not
visible, 403 visible but not allowed (not the owner, four-eyes), 409 state
conflict (already decided, roadmap binding), 422 invalid input or refusing rule.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.permits import guards
from app.modules.permits import service as sv
from app.modules.permits.catalogue import PERMIT_TYPE_KIND
from app.modules.permits.errors import PermitError
from app.modules.permits.messages import translate
from app.modules.permits.schemas import (
    AcceptIn,
    ApplicationCreate,
    ApplicationPatch,
    AssignIn,
    BreachIn,
    CatalogueCreate,
    CatalogueUpdate,
    ClockEventIn,
    ConditionIn,
    ConditionPatch,
    ConfirmIn,
    DecisionCorrection,
    DecisionIn,
    DependenciesPut,
    DischargeIn,
    EvidenceIn,
    InterruptionIn,
    NoteIn,
    PermitTransitionIn,
    ProposalsIn,
    ProposeIn,
    RequirementCreate,
    RequirementFromConditionIn,
    RequirementPatch,
    RoadmapSet,
    StartNoticeIn,
    TransitionIn,
)
from app.modules.permits.service import PermitService

router = APIRouter(tags=["permits"])

READ = Depends(RequirePermission("permits.read"))
EDIT = Depends(RequirePermission("permits.edit"))
MANAGE = Depends(RequirePermission("permits.manage"))
VERIFY = Depends(RequirePermission("permits.verify"))
CATALOGUE = Depends(RequirePermission("permits.catalogue"))

CONDITION_VIEWS = ("before_start", "before_occupation", "ongoing_hse", "overdue", "mine")


async def _run[T](awaitable: Awaitable[T]) -> T:
    """Turn a :class:`PermitError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except PermitError as exc:
        message = translate(f"permits.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = PermitError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"permits.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _can(payload: dict[str, Any], permission: str) -> bool:
    """Whether the caller holds ``permission``, by the same test :class:`RequirePermission` applies.

    The service never sees a role: what the caller may do reaches it as a boolean.
    """
    from app.core.permissions import permission_registry

    if permission in (payload.get("permissions") or []):
        return True
    return permission_registry.role_has_permission(str(payload.get("role") or ""), permission)


def _caller(payload: dict[str, Any], user_id: str) -> guards.Caller:
    """Who asks and what they hold, for the ``can`` flags a record is served with."""
    return guards.Caller(
        actor_id=_uid(user_id),
        edit=_can(payload, "permits.edit"),
        manage=_can(payload, "permits.manage"),
        verify=_can(payload, "permits.verify"),
    )


def _today(value: date | None) -> date:
    return value or datetime.now(UTC).date()


def _page(items: list[Any], offset: int = 0, limit: int | None = None, **extra: Any) -> dict[str, Any]:
    window = items[offset : offset + limit] if limit else items[offset:]
    return {"items": window, "total": len(items), "offset": offset, "limit": limit or len(window), **extra}


def _tenant(payload: dict[str, Any]) -> str:
    tenant = resolve_tenant_id(payload)
    if not tenant:
        raise HTTPException(status_code=404, detail="Not found")
    return tenant


async def _permits_service(project_id: uuid.UUID, user_id: str, session: Any) -> PermitService:
    """The service of one project, handed out only after the caller's access to that project is checked.

    Every project route gets its service here and nowhere else, so no handler can reach a
    row without the check (the name is pinned in tests/unit/test_idor_router_guards.py).
    """
    await verify_project_access(project_id, user_id, session)
    return PermitService(session)


# ── catalogue admin (tenant scoped) ────────────────────────────────────────


async def _catalogue_out(store: Any, row: Any) -> dict[str, Any]:
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


async def _own_catalogue(store: Any, tenant: str, catalogue_id: uuid.UUID) -> Any:
    row = await _run(store.get(tenant, catalogue_id))
    if row.kind != PERMIT_TYPE_KIND:
        raise HTTPException(status_code=404, detail={"code": "unknown_catalogue"})
    return row


def _store(session: Any) -> Any:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    PermitService(session)  # registers the kind
    return CatalogueStore(session)


@router.get("/catalogues", dependencies=[READ])
async def list_catalogues(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Shipped permit-type catalogues (with clocks, sources and review status) and the tenant's own."""
    from app.modules.permits.catalogue import shipped_catalogues

    items = await _run(_store(session).list_available(resolve_tenant_id(payload), kind=PERMIT_TYPE_KIND))
    shipped = shipped_catalogues()
    for item in items:
        c = shipped.get(item["id"]) if item["source"] == "shipped" else None
        if c is not None:
            item["jurisdiction"] = c.jurisdiction
            item["extends"] = c.extends
    return _page(items)


@router.get("/catalogues/shipped/{catalogue_id}", dependencies=[READ])
async def get_shipped_catalogue(catalogue_id: str, session: SessionDep) -> dict[str, Any]:
    """One shipped catalogue with its parent chain resolved, for the catalogue screen."""
    from app.modules.permits.catalogue import merged, shipped_catalogues

    PermitService(session)
    shipped = shipped_catalogues()
    if catalogue_id not in shipped:
        raise HTTPException(status_code=404, detail={"code": "unknown_catalogue"})
    return merged(shipped[catalogue_id], shipped.__getitem__).model_dump(mode="json")


@router.post("/catalogues", status_code=201, dependencies=[CATALOGUE])
async def create_catalogue(
    body: CatalogueCreate, session: SessionDep, payload: CurrentUserPayload, user_id: CurrentUserId
) -> dict[str, Any]:
    store = _store(session)
    row = await _run(
        store.create(
            _tenant(payload),
            code=body.code,
            name=body.name,
            based_on_source=body.based_on_source,
            based_on_id=body.based_on_id,
            based_on_version=body.based_on_version,
            actor_id=_uid(user_id),
            kind=PERMIT_TYPE_KIND,
        )
    )
    return await _catalogue_out(store, row)


@router.get("/catalogues/{catalogue_id}", dependencies=[READ])
async def get_catalogue(catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    store = _store(session)
    return await _catalogue_out(store, await _own_catalogue(store, _tenant(payload), catalogue_id))


@router.patch("/catalogues/{catalogue_id}", dependencies=[CATALOGUE])
async def update_catalogue(
    catalogue_id: uuid.UUID, body: CatalogueUpdate, session: SessionDep, payload: CurrentUserPayload
) -> dict[str, Any]:
    store = _store(session)
    tenant = _tenant(payload)
    await _own_catalogue(store, tenant, catalogue_id)
    row = await _run(store.update_draft(tenant, catalogue_id, body=body.body, name=body.name))
    return await _catalogue_out(store, row)


@router.post("/catalogues/{catalogue_id}/publish", dependencies=[CATALOGUE])
async def publish_catalogue(
    catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload, user_id: CurrentUserId
) -> dict[str, Any]:
    store = _store(session)
    tenant = _tenant(payload)
    await _own_catalogue(store, tenant, catalogue_id)
    v = await _run(store.publish(tenant, catalogue_id, actor_id=_uid(user_id)))
    return {"version": v.version, "content_hash": v.content_hash, "published_at": v.published_at.isoformat()}


@router.get("/catalogues/{catalogue_id}/diff", dependencies=[READ])
async def diff_catalogue(
    catalogue_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    v_from: int = Query(..., alias="from", ge=1),
    v_to: int = Query(..., alias="to", ge=1),
) -> dict[str, Any]:
    store = _store(session)
    tenant = _tenant(payload)
    await _own_catalogue(store, tenant, catalogue_id)
    return await _run(store.diff(tenant, catalogue_id, v_from, v_to))


# ── roadmap ────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/roadmap", dependencies=[READ])
async def get_roadmap(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    view = await _run(svc.roadmap_view(project_id))
    return {**view, "can": await svc.roadmap_can(project_id, _caller(payload, user_id))}


@router.put("/projects/{project_id}/roadmap", dependencies=[MANAGE])
async def put_roadmap(
    project_id: uuid.UUID, body: RoadmapSet, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Create the roadmap (country default catalogue) or re-pin it / change settings."""
    svc = await _permits_service(project_id, user_id, session)
    # Only what the request names: an explicit null reaches the service, which clears a link
    # with it and refuses it for a setting that cannot be empty.
    data = body.model_dump(exclude_unset=True)
    pin = {k: v for k in ("catalogue_source", "catalogue_id", "catalogue_version") if (v := data.pop(k, None))}
    juris = data.pop("jurisdiction", None)
    row = await _run(
        svc.set_roadmap(
            project_id,
            tenant_id=resolve_tenant_id(payload),
            actor_id=_uid(user_id),
            jurisdiction=juris,
            settings=data,
            **pin,
        )
    )
    return sv.roadmap_out(row)


@router.post("/projects/{project_id}/roadmap/propose", dependencies=[READ])
async def propose(
    project_id: uuid.UUID, body: ProposeIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Rule 1: requirements the confirmed permit route implies. Nothing is written."""
    svc = await _permits_service(project_id, user_id, session)
    return await _run(svc.propose(project_id, body.route_assessment_id))


@router.post("/projects/{project_id}/roadmap/accept", status_code=201, dependencies=[MANAGE])
async def accept(project_id: uuid.UUID, body: AcceptIn, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    rows = await _run(
        svc.accept_proposals(
            project_id,
            body.permit_type_codes,
            actor_id=_uid(user_id),
            assessment_id=body.route_assessment_id,
            change_request_id=body.change_request_id,
        )
    )
    return _page([sv.requirement_out(r) for r in rows])


# ── requirements and timeline ──────────────────────────────────────────────


@router.get("/projects/{project_id}/requirements", dependencies=[READ])
async def list_requirements(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    category: str | None = None,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    roadmap = await _run(svc.get_roadmap(project_id))
    types = await _run(svc._types(roadmap))
    snap = await svc.state_snapshot(project_id)
    caller = _caller(payload, user_id)
    doc = await svc._roadmap_document(project_id)
    binding = doc is not None and doc.status == "binding"
    applications = await svc.repo.list_applications(project_id)
    items = []
    for r in snap["requirements"]:
        t = types.get(r.permit_type_code)
        if category and (t is None or t.category != category):
            continue
        items.append(
            {
                **sv.requirement_out(r),
                "state": snap["states"].get(str(r.id)),
                "category": t.category if t else None,
                "name_key": t.name_key if t else None,
                "depends_on": [{"id": e.depends_on, "on": e.on} for e in snap["edges"] if e.requirement == str(r.id)],
                "can": svc.requirement_can(r, [a for a in applications if a.requirement_id == r.id], caller, binding),
            }
        )
    return _page(items)


@router.post("/projects/{project_id}/requirements", status_code=201, dependencies=[MANAGE])
async def create_requirement(
    project_id: uuid.UUID, body: RequirementCreate, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    return sv.requirement_out(await _run(svc.create_requirement(project_id, body.model_dump(), actor_id=_uid(user_id))))


@router.patch("/projects/{project_id}/requirements/{requirement_id}", dependencies=[EDIT])
async def patch_requirement(
    project_id: uuid.UUID,
    requirement_id: uuid.UUID,
    body: RequirementPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """The responsible user or a manager. ``applicable``, ``conflict_accepted`` and the responsible user: manage."""
    svc = await _permits_service(project_id, user_id, session)
    data = body.model_dump(exclude_unset=True)
    row = await _run(
        svc.update_requirement(
            project_id, requirement_id, data, actor_id=_uid(user_id), can_manage=_can(payload, "permits.manage")
        )
    )
    return sv.requirement_out(row)


@router.delete("/projects/{project_id}/requirements/{requirement_id}", status_code=204, dependencies=[MANAGE])
async def delete_requirement(
    project_id: uuid.UUID,
    requirement_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    change_request_id: uuid.UUID | None = None,
) -> Response:
    svc = await _permits_service(project_id, user_id, session)
    await _run(
        svc.delete_requirement(project_id, requirement_id, actor_id=_uid(user_id), change_request_id=change_request_id)
    )
    return Response(status_code=204)


@router.put("/projects/{project_id}/requirements/{requirement_id}/dependencies", dependencies=[MANAGE])
async def put_dependencies(
    project_id: uuid.UUID,
    requirement_id: uuid.UUID,
    body: DependenciesPut,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    rows = await _run(
        svc.set_dependencies(
            project_id,
            requirement_id,
            [d.model_dump() for d in body.dependencies],
            actor_id=_uid(user_id),
            change_request_id=body.change_request_id,
        )
    )
    return _page([{"id": str(r.depends_on_id), "on": r.dep_type} for r in rows])


@router.post("/projects/{project_id}/requirements/{requirement_id}/push-milestone", dependencies=[EDIT])
async def push_milestone(
    project_id: uuid.UUID,
    requirement_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """Rule 6: explicit user action only; writes the forecast decision as a schedule milestone."""
    svc = await _permits_service(project_id, user_id, session)
    return await _run(svc.push_milestone(project_id, requirement_id, actor_id=_uid(user_id)))


@router.get("/projects/{project_id}/timeline", dependencies=[READ])
async def timeline(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    out = await _run(svc.timeline(project_id, _today(today)))
    return _page(out["items"], edges=out["edges"])


# ── applications ───────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/applications", dependencies=[READ])
async def list_applications(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    requirement_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    rows = [a for a in await svc.repo.list_applications(project_id) if requirement_id in (None, a.requirement_id)]
    # An application exists only under a roadmap, so the roadmap is there whenever a row is.
    roadmap = await _run(svc.get_roadmap(project_id)) if rows else None
    caller = _caller(payload, user_id)
    return _page([{**sv.application_out(a), "can": await svc.application_can(a, roadmap, caller)} for a in rows])


@router.post("/projects/{project_id}/applications", status_code=201, dependencies=[EDIT])
async def create_application(
    project_id: uuid.UUID, body: ApplicationCreate, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    return sv.application_out(await _run(svc.create_application(project_id, body.model_dump(), actor_id=_uid(user_id))))


@router.get("/projects/{project_id}/applications/{application_id}", dependencies=[READ])
async def get_application(
    project_id: uuid.UUID,
    application_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    """Application drawer: state, clock with stop/extension history, decisions, what the caller may do."""
    svc = await _permits_service(project_id, user_id, session)
    app = await svc.repo.get_application(project_id, application_id)
    if app is None:
        raise HTTPException(status_code=404, detail={"code": "application_not_found"})
    deemed = await _run(svc.deemed_status(project_id, application_id, _today(today)))
    every = await svc.repo.list_decisions(project_id)
    newest = sv._current_decisions(every).get(str(application_id))
    caller = _caller(payload, user_id)
    can = await svc.application_can(app, await _run(svc.get_roadmap(project_id)), caller, deep=True)
    return {
        **sv.application_out(app),
        "clock": deemed["clock"],
        "clock_events": [sv.clock_event_out(e) for e in await svc.repo.list_clock_events(project_id, application_id)],
        "decisions": [
            {**sv.decision_out(d), "can": svc.decision_can(d, newest, caller)}
            for d in every
            if d.application_id == application_id
        ],
        # The moves this project's lifecycle offers from here, in the order the work goes. Whether
        # the caller may make one, and why not, is ``can.transition[target]``.
        "allowed_targets": [t for t in guards.TARGET_ORDER if can["transition"][t]["applies"]],
        "can": can,
    }


@router.patch("/projects/{project_id}/applications/{application_id}", dependencies=[EDIT])
async def patch_application(
    project_id: uuid.UUID,
    application_id: uuid.UUID,
    body: ApplicationPatch,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    data = body.model_dump(exclude_unset=True)
    return sv.application_out(
        await _run(svc.update_application(project_id, application_id, data, actor_id=_uid(user_id)))
    )


@router.post("/projects/{project_id}/applications/{application_id}/transition", dependencies=[EDIT])
async def transition_application(
    project_id: uuid.UUID,
    application_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    app = await _run(
        svc.transition_application(
            project_id,
            application_id,
            body.target,
            actor_id=_uid(user_id),
            can_manage=_can(payload, "permits.manage"),
            on_date=body.on_date,
            reason=body.reason or None,
        )
    )
    return sv.application_out(app)


@router.post("/projects/{project_id}/applications/{application_id}/clock-events", status_code=201, dependencies=[EDIT])
async def add_clock_event(
    project_id: uuid.UUID,
    application_id: uuid.UUID,
    body: ClockEventIn,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(svc.add_clock_event(project_id, application_id, body.model_dump(), actor_id=_uid(user_id)))
    return sv.clock_event_out(row)


@router.get("/projects/{project_id}/applications/{application_id}/deemed", dependencies=[READ])
async def deemed(
    project_id: uuid.UUID,
    application_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    today: date | None = None,
) -> dict[str, Any]:
    """Rule 7: the proposed deemed outcome; it takes effect only through a recorded decision."""
    svc = await _permits_service(project_id, user_id, session)
    return await _run(svc.deemed_status(project_id, application_id, _today(today)))


@router.post("/projects/{project_id}/applications/{application_id}/decision", status_code=201, dependencies=[MANAGE])
async def record_decision(
    project_id: uuid.UUID,
    application_id: uuid.UUID,
    body: DecisionIn,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    data = body.model_dump()
    data["conditions"] = [c.model_dump() for c in body.conditions]
    out = await _run(svc.record_decision(project_id, application_id, data, actor_id=_uid(user_id)))
    follow = out.get("follow_up_requirement")
    return {
        "decision": sv.decision_out(out["decision"]),
        "permit": sv.permit_out(out["permit"]) if out.get("permit") else None,
        "follow_up_requirement": sv.requirement_out(follow) if follow else None,
        "next": out.get("next", []),
    }


@router.post("/projects/{project_id}/decisions/{decision_id}/complete-register", dependencies=[MANAGE])
async def complete_register(
    project_id: uuid.UUID, decision_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    return sv.decision_out(await _run(svc.complete_register(project_id, decision_id, actor_id=_uid(user_id))))


@router.post("/projects/{project_id}/decisions/{decision_id}/correct", status_code=201, dependencies=[MANAGE])
async def correct_decision(
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    body: DecisionCorrection,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """A correction is a new decision revision superseding the old one; the outcome cannot be corrected."""
    svc = await _permits_service(project_id, user_id, session)
    data = body.model_dump(exclude_unset=True)
    return sv.decision_out(await _run(svc.correct_decision(project_id, decision_id, data, actor_id=_uid(user_id))))


# ── permits ────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/permits", dependencies=[READ])
async def list_permits(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    return _page(await svc.permit_rows(project_id, _today(today), _caller(payload, user_id)))


@router.post("/projects/{project_id}/permits/{permit_id}/start-notice", dependencies=[EDIT])
async def start_notice(
    project_id: uuid.UUID, permit_id: uuid.UUID, body: StartNoticeIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    return sv.permit_out(await _run(svc.notify_start(project_id, permit_id, body.on_date, actor_id=_uid(user_id))))


@router.post("/projects/{project_id}/permits/{permit_id}/interruption", dependencies=[EDIT])
async def interruption_notice(
    project_id: uuid.UUID, permit_id: uuid.UUID, body: InterruptionIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Rule 9: started work has stopped; the permit lapses if it stays stopped beyond the catalogue period."""
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(
        svc.notify_interruption(project_id, permit_id, body.on_date, resumed=False, actor_id=_uid(user_id))
    )
    return sv.permit_out(row)


@router.post("/projects/{project_id}/permits/{permit_id}/resumption", dependencies=[EDIT])
async def resumption_notice(
    project_id: uuid.UUID, permit_id: uuid.UUID, body: InterruptionIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Rule 9: interrupted work has resumed; the lapse clock of the interruption stops."""
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(svc.notify_interruption(project_id, permit_id, body.on_date, resumed=True, actor_id=_uid(user_id)))
    return sv.permit_out(row)


@router.post("/projects/{project_id}/permits/{permit_id}/transition", dependencies=[MANAGE])
async def transition_permit(
    project_id: uuid.UUID,
    permit_id: uuid.UUID,
    body: PermitTransitionIn,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(
        svc.transition_permit(project_id, permit_id, body.target, actor_id=_uid(user_id), reason=body.reason or None)
    )
    return sv.permit_out(row)


@router.post("/projects/{project_id}/permits/{permit_id}/conditions", status_code=201, dependencies=[MANAGE])
async def create_condition(
    project_id: uuid.UUID, permit_id: uuid.UUID, body: ConditionIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(svc.create_condition(project_id, permit_id, body.model_dump(), actor_id=_uid(user_id)))
    return sv.condition_out(row)


@router.post("/projects/{project_id}/permits/{permit_id}/condition-proposals", status_code=201, dependencies=[EDIT])
async def propose_conditions(
    project_id: uuid.UUID, permit_id: uuid.UUID, body: ProposalsIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Rule 15: store AI-extracted proposals with confidence; unconfirmed, they count nowhere."""
    svc = await _permits_service(project_id, user_id, session)
    rows = await _run(
        svc.propose_conditions(project_id, permit_id, [p.model_dump() for p in body.proposals], actor_id=_uid(user_id))
    )
    return _page([sv.condition_out(r) for r in rows])


@router.post(
    "/projects/{project_id}/permits/{permit_id}/condition-proposals/extract", status_code=201, dependencies=[EDIT]
)
async def extract_conditions(
    project_id: uuid.UUID, permit_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Rule 15: read the permit's decision notice with the AI provider the caller has configured.

    What it finds is stored as unconfirmed proposals with a confidence each; a person
    confirms or rejects every one. No body: the document is the notice of the decision.
    """
    svc = await _permits_service(project_id, user_id, session)
    out = await _run(svc.extract_conditions(project_id, permit_id, actor_id=_uid(user_id)))
    return _page(
        [sv.condition_out(r) for r in out["items"]],
        already_known=out["already_known"],
        rejected=out["rejected"],
        document_cut=out["document_cut"],
    )


# ── condition register ─────────────────────────────────────────────────────


@router.get("/projects/{project_id}/conditions", dependencies=[READ])
async def list_conditions(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    trigger: str | None = None,
    topic: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    state: str | None = None,
    overdue: bool | None = None,
    hse: bool | None = None,
    view: Literal["before_start", "before_occupation", "ongoing_hse", "overdue", "mine"] | None = None,
    include_proposals: bool = False,
    today: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(0, ge=0, le=1000),
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    rows = await svc.condition_rows(project_id, _today(today), _caller(payload, user_id))

    def keep(r: dict[str, Any]) -> bool:
        if not include_proposals and not r["confirmed"]:
            return False
        live = r["state"] not in ("superseded",)
        checks = [
            trigger is None or r["trigger"] == trigger,
            topic is None or r["topic"] == topic,
            owner_user_id is None or r["owner_user_id"] == str(owner_user_id),
            state is None or r["state"] == state,
            overdue is None or r["overdue"] == overdue,
            hse is None or r["hse_relevant"] == hse,
            view != "before_start" or (r["trigger"] == "before_start" and live),
            view != "before_occupation" or (r["trigger"] == "before_occupation" and live),
            view != "ongoing_hse" or ((r["trigger"] == "ongoing" or r["hse_relevant"]) and live),
            view != "overdue" or r["overdue"],
            view != "mine" or (r["owner_user_id"] == str(user_id) and live),
        ]
        return all(checks)

    return _page([r for r in rows if keep(r)], offset, limit or None)


@router.get("/projects/{project_id}/conditions/{condition_id}", dependencies=[READ])
async def get_condition(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """One condition with its evidence, its discharges and what the caller may do to it."""
    svc = await _permits_service(project_id, user_id, session)
    c = await svc.repo.get_condition(project_id, condition_id)
    if c is None:
        raise HTTPException(status_code=404, detail={"code": "condition_not_found"})
    evidence = await svc.evidence_rows(project_id, condition_id)
    return {
        **sv.condition_out(c),
        "evidence": evidence,
        "discharges": [sv.discharge_out(d) for d in await svc.repo.list_discharges(project_id, condition_id)],
        "can": svc.condition_can(c, _caller(payload, user_id), len(evidence), await svc._involved(c)),
    }


@router.patch("/projects/{project_id}/conditions/{condition_id}", dependencies=[EDIT])
async def patch_condition(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: ConditionPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(
        svc.update_condition(
            project_id,
            condition_id,
            body.model_dump(exclude_unset=True),
            actor_id=_uid(user_id),
            can_manage=_can(payload, "permits.manage"),
        )
    )
    return sv.condition_out(row)


@router.post("/projects/{project_id}/conditions/assign", dependencies=[MANAGE])
async def assign_owner(
    project_id: uuid.UUID, body: AssignIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    rows = await _run(
        svc.assign_owner(project_id, list(body.condition_ids), body.owner_user_id, actor_id=_uid(user_id))
    )
    return _page([sv.condition_out(r) for r in rows])


@router.post("/projects/{project_id}/conditions/{condition_id}/evidence", status_code=201, dependencies=[EDIT])
async def add_evidence(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: EvidenceIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(
        svc.add_evidence(
            project_id,
            condition_id,
            body.model_dump(),
            actor_id=_uid(user_id),
            can_manage=_can(payload, "permits.manage"),
        )
    )
    return sv.evidence_out(row)


@router.delete(
    "/projects/{project_id}/conditions/{condition_id}/evidence/{evidence_id}", status_code=204, dependencies=[EDIT]
)
async def remove_evidence(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    evidence_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    svc = await _permits_service(project_id, user_id, session)
    await _run(
        svc.remove_evidence(
            project_id, condition_id, evidence_id, actor_id=_uid(user_id), can_manage=_can(payload, "permits.manage")
        )
    )
    return Response(status_code=204)


@router.post("/projects/{project_id}/conditions/{condition_id}/submit-evidence", dependencies=[EDIT])
async def submit_evidence(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(
        svc.submit_evidence(
            project_id, condition_id, actor_id=_uid(user_id), can_manage=_can(payload, "permits.manage")
        )
    )
    return sv.condition_out(row)


@router.post("/projects/{project_id}/conditions/{condition_id}/discharge", dependencies=[VERIFY])
async def discharge(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: DischargeIn,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """Rule 13, always four-eyes: the verifier is not the owner, the submitter or anyone who added evidence."""
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(svc.discharge(project_id, condition_id, body.model_dump(), actor_id=_uid(user_id)))
    return sv.discharge_out(row)


async def _ongoing(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    target: str,
    data: dict[str, Any],
    svc: PermitService,
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Both ongoing transitions; ``svc`` comes from the handler, which has checked project access."""
    row = await _run(
        svc.ongoing(
            project_id, condition_id, target, data, actor_id=_uid(user_id), can_manage=_can(payload, "permits.manage")
        )
    )
    return sv.condition_out(row)


@router.post("/projects/{project_id}/conditions/{condition_id}/breach", dependencies=[EDIT])
async def breach(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: BreachIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Rule 16: raise a breach of an ongoing condition, optionally from an HSE observation or inspection."""
    svc = await _permits_service(project_id, user_id, session)
    return await _ongoing(project_id, condition_id, "breach", body.model_dump(), svc, user_id, payload)


@router.post("/projects/{project_id}/conditions/{condition_id}/in-compliance", dependencies=[EDIT])
async def in_compliance(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: NoteIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    return await _ongoing(project_id, condition_id, "in_compliance", body.model_dump(), svc, user_id, payload)


@router.post("/projects/{project_id}/conditions/{condition_id}/confirm", dependencies=[EDIT])
async def confirm_proposal(
    project_id: uuid.UUID, condition_id: uuid.UUID, body: ConfirmIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _permits_service(project_id, user_id, session)
    row = await _run(svc.confirm_proposal(project_id, condition_id, body.accept, actor_id=_uid(user_id)))
    return {"condition": sv.condition_out(row) if row else None, "accepted": body.accept}


@router.post("/projects/{project_id}/conditions/{condition_id}/requirement", status_code=201, dependencies=[EDIT])
async def condition_requirement(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: RequirementFromConditionIn,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """Rule 23: a measurable limit becomes a linked requirement; the condition text stays here."""
    svc = await _permits_service(project_id, user_id, session)
    return await _run(svc.condition_to_requirement(project_id, condition_id, body.model_dump(), actor_id=_uid(user_id)))


@router.post("/projects/{project_id}/conditions/escalate", dependencies=[MANAGE])
async def escalate(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Rules 9 and 17 on demand, as of the server's date; the scheduled sweep does the same every hour."""
    svc = await _permits_service(project_id, user_id, session)
    return await _run(svc.escalate(project_id, actor_id=_uid(user_id)))


# ── readiness, validation, export ──────────────────────────────────────────


@router.get("/projects/{project_id}/readiness", dependencies=[READ])
async def readiness(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    gate: Literal["start", "handover", "roadmap", "register"] = "start",
    phase: str | None = Query(None, max_length=64),
    today: date | None = None,
) -> dict[str, Any]:
    """One readiness check. ``phase`` (a phase code of the project's governance model) narrows the
    roadmap check to what the gate into that phase needs, by the phase's catalogue tags."""
    svc = await _permits_service(project_id, user_id, session)
    if gate == "roadmap" and phase:
        return await _run(svc.readiness_for_phase(project_id, phase, _today(today)))
    return await _run(svc.readiness(project_id, gate, _today(today)))


@router.get("/projects/{project_id}/validation", dependencies=[READ])
async def validation(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext
    from app.modules.permits.validators import PERMIT_RULES

    svc = await _permits_service(project_id, user_id, session)
    data = await _run(svc.validation_payload(project_id, _today(today)))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    findings = []
    for rule_cls in PERMIT_RULES:
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


@router.get("/projects/{project_id}/export", dependencies=[READ])
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    register: Literal["roadmap", "conditions", "permits"] = "conditions",
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
    today: date | None = None,
) -> Response:
    """One register as PDF or XLSX; also the content of the governance frame documents (rule 18)."""
    from app.modules.permits.export import render, written_locale
    from app.modules.projects.models import Project

    svc = await _permits_service(project_id, user_id, session)
    day = _today(today)
    locale = written_locale(get_locale())
    rows = await _run(svc.register_rows(project_id, register, day))
    project = await session.get(Project, project_id)
    content = render(
        register,
        rows,
        project_name=getattr(project, "name", "") or "",
        locale=locale,
        as_of=day.isoformat(),
        fmt=fmt,
    )
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="permits_{register}.{fmt}"',
            # The language the register was written in, which is not always the one asked for.
            "Content-Language": locale,
        },
    )


@router.post("/projects/{project_id}/frame-document/publish", status_code=201, dependencies=[MANAGE])
async def publish_frame_document(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    register: Literal["roadmap", "permits", "conditions"] = "roadmap",
) -> dict[str, Any]:
    """Rule 18: store a register export as a new CDE revision of the frame document that hosts permits."""
    svc = await _permits_service(project_id, user_id, session)
    return await _run(
        svc.publish_frame_document(project_id, register, actor_id=_uid(user_id), locale=get_locale() or "en")
    )
