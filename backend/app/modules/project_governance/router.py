# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project governance API, mounted at ``/api/v1/project-governance``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are always
looked up by ``(project_id, id)``, so an id from another project is also 404.

Catalogue routes (``/catalogues``) are scoped to the caller's tenant.

Errors carry ``{"code", "message_key", "message", "violations"?}`` in
``detail``; ``code`` is stable and ``message_key`` is
``governance.errors.<code>``. 404 = not found or not visible, 403 = visible but
not allowed (permission, route entitlement, four-eyes, area ownership),
409 = state conflict (wrong state, concurrent decision), 422 = invalid input or
a rule that blocks (blockers listed in ``violations``).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.project_governance import evaluator as ev
from app.modules.project_governance.catalogue import label_of
from app.modules.project_governance.catalogue_store import CatalogueStore
from app.modules.project_governance.errors import GovernanceError
from app.modules.project_governance.messages import translate
from app.modules.project_governance.schemas import (
    AreaOut,
    AreaUpdate,
    AttachIn,
    CatalogueCreate,
    CatalogueUpdate,
    CatalogueVersionOut,
    ChangeRequestIn,
    ChangeRequestOut,
    CheckConfirm,
    CheckOut,
    ClearIn,
    ConditionIn,
    ConditionOut,
    CriterionTick,
    DecisionIn,
    DecisionOut,
    DocumentCreate,
    DocumentHistoryOut,
    DocumentOut,
    FindingOut,
    GateDetailOut,
    GateOut,
    GatePlan,
    MatrixOut,
    ModelChange,
    ModelOut,
    ModelSet,
    ModelSettings,
    NotApplicableIn,
    Page,
    ReopenIn,
    TenantCatalogueOut,
    WaiveIn,
)
from app.modules.project_governance.service import GovernanceService, effective_condition_status, server_today

router = APIRouter(tags=["project_governance"])


READ = Depends(RequirePermission("governance.read"))
EDIT = Depends(RequirePermission("governance.edit"))
MANAGE = Depends(RequirePermission("governance.manage"))
DECIDE = Depends(RequirePermission("governance.decide"))


async def _run[T](awaitable: Awaitable[T], *, can: dict[str, bool] | None = None) -> T:
    """Turn a :class:`GovernanceError` into the HTTP error the module documents.

    ``can`` rides along in the error body where the screen needs to know what
    the caller may do about the refusal (pin a model when there is none).
    """
    try:
        return await awaitable
    except GovernanceError as exc:
        message = translate(f"governance.errors.{exc.code}", locale=get_locale() or "en")
        detail = exc.as_detail(message)
        if can is not None:
            detail["can"] = can
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _role(payload: dict[str, Any]) -> str:
    """The caller's role, handed on to the approval engine and compared nowhere in this module.

    Accepted exception to "no role strings": a route step may name a role
    instead of a person, and the approval-routes contract decides such a step
    from the caller's role (``ApprovalRouteService.submit_decision(caller_role=...)``).
    Governance passes it through for decide, reopen, resume, waive and
    add_condition and never branches on it; its own authority checks use
    permissions and area ownership.
    """
    return str(payload.get("role") or "")


def _today(value: date | None) -> date:
    """The day a READ is shown for. Writes never take one from the client: see ``server_today``."""
    return value or server_today()


async def _has(payload: dict[str, Any], permission: str) -> bool:
    """The caller's answer from the very dependency that guards the routes."""
    try:
        await RequirePermission(permission)(payload)
    except HTTPException:
        return False
    return True


_NO_LABEL: dict[str, Any] = {"key": None, "text": None}


async def _catalogue(session: Any, project_id: uuid.UUID) -> Any | None:
    """The project's pinned catalogue, or ``None`` before a model is set."""
    svc = GovernanceService(session)
    model = await svc.repo.get_model(project_id)
    return None if model is None else await _run(svc.catalogue_for(model))


def _label(catalogue: Any | None, kind: str, code: str) -> dict[str, Any]:
    """Label of an area, gate or document type; empty when the catalogue does not have it."""
    if catalogue is None:
        return dict(_NO_LABEL)
    items = {"area": catalogue.areas, "gate": catalogue.gates, "doc": catalogue.document_types}[kind]
    for item in items:
        if item.code == code:
            return label_of(item.name_key, item.labels)
    return dict(_NO_LABEL)


def _named[O: AreaOut | GateOut | DocumentOut](
    out_cls: type[O], row: Any, catalogue: Any | None, kind: str, code: str
) -> O:
    out = out_cls.model_validate(row)
    out.name = _label(catalogue, kind, code)
    return out


async def _gates_out(svc: GovernanceService, rows: list[Any], catalogue: Any | None) -> list[GateOut]:
    """Gates with their label and planned date; a linked gate's date is the schedule's."""
    planned = await svc.gate_target_dates(rows)
    out = []
    for row in rows:
        gate = _named(GateOut, row, catalogue, "gate", row.code)
        gate.target_date = planned[row.id]
        out.append(gate)
    return out


async def _gate_out(session: Any, row: Any) -> GateOut:
    return (await _gates_out(GovernanceService(session), [row], await _catalogue(session, row.project_id)))[0]


async def _conditions_out(
    svc: GovernanceService, project_id: uuid.UUID, rows: list[Any], payload: dict[str, Any], user_id: str
) -> list[ConditionOut]:
    """Conditions as the caller sees them today: effective status and what they may do with each.

    The values are set on the response objects only. The session commits after
    a GET, so nothing computed here may be written to a row.
    """
    can = await svc.condition_capabilities(
        project_id,
        rows,
        actor_id=_uid(user_id),
        role=_role(payload),
        can_edit=await _has(payload, "governance.edit"),
        can_decide=await _has(payload, "governance.decide"),
        is_manager=await _has(payload, "governance.manage"),
    )
    today = server_today()
    out = []
    for row in rows:
        item = ConditionOut.model_validate(row)
        item.status = effective_condition_status(row, today)
        item.can = can[row.id]
        out.append(item)
    return out


def _page(items: list[Any], total: int | None = None, offset: int = 0, limit: int = 0) -> dict[str, Any]:
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "offset": offset,
        "limit": limit or len(items),
    }


# ── catalogues (tenant scoped) ─────────────────────────────────────────────


def _tenant(payload: dict[str, Any]) -> str:
    tenant = resolve_tenant_id(payload)
    if not tenant:
        raise HTTPException(status_code=404, detail="Not found")
    return tenant


async def _tenant_out(store: CatalogueStore, row: Any) -> TenantCatalogueOut:
    versions = await store.repo.list_catalogue_versions(row.id)
    out = TenantCatalogueOut.model_validate(row)
    out.versions = [CatalogueVersionOut.model_validate(v) for v in versions]
    out.validation_errors = store.validation_errors(row)
    return out


@router.get("/catalogues", response_model=Page[dict[str, Any]], dependencies=[READ])
async def list_catalogues(
    session: SessionDep,
    payload: CurrentUserPayload,
    kind: str = Query("phase_model", max_length=40),
    country: str | None = Query(None, max_length=2),
) -> dict[str, Any]:
    """Shipped catalogues, the active pack's and the caller's tenant catalogues of one kind.

    ``country`` is the project's country; the item a new project of that
    country should pin carries ``default: true``.
    """
    items = await _run(
        CatalogueStore(session).list_available(resolve_tenant_id(payload), kind=kind, country_code=country)
    )
    return _page(items)


@router.post("/catalogues", response_model=TenantCatalogueOut, status_code=201, dependencies=[MANAGE])
async def create_catalogue(
    body: CatalogueCreate, session: SessionDep, payload: CurrentUserPayload, user_id: CurrentUserId
) -> TenantCatalogueOut:
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
            kind=body.kind,
        )
    )
    return await _tenant_out(store, row)


@router.get("/catalogues/{catalogue_id}", response_model=TenantCatalogueOut, dependencies=[READ])
async def get_catalogue(
    catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload
) -> TenantCatalogueOut:
    store = CatalogueStore(session)
    row = await _run(store.get(_tenant(payload), catalogue_id))
    return await _tenant_out(store, row)


@router.patch("/catalogues/{catalogue_id}", response_model=TenantCatalogueOut, dependencies=[MANAGE])
async def update_catalogue(
    catalogue_id: uuid.UUID, body: CatalogueUpdate, session: SessionDep, payload: CurrentUserPayload
) -> TenantCatalogueOut:
    store = CatalogueStore(session)
    row = await _run(store.update_draft(_tenant(payload), catalogue_id, body=body.body, name=body.name))
    return await _tenant_out(store, row)


@router.post("/catalogues/{catalogue_id}/validate", response_model=dict[str, Any], dependencies=[READ])
async def validate_catalogue(catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload) -> dict:
    store = CatalogueStore(session)
    row = await _run(store.get(_tenant(payload), catalogue_id))
    errors = store.validation_errors(row)
    return {"valid": not errors, "errors": errors}


@router.post("/catalogues/{catalogue_id}/publish", response_model=CatalogueVersionOut, dependencies=[MANAGE])
async def publish_catalogue(
    catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload, user_id: CurrentUserId
) -> CatalogueVersionOut:
    version = await _run(CatalogueStore(session).publish(_tenant(payload), catalogue_id, actor_id=_uid(user_id)))
    return CatalogueVersionOut.model_validate(version)


@router.post("/catalogues/{catalogue_id}/retire", response_model=TenantCatalogueOut, dependencies=[MANAGE])
async def retire_catalogue(
    catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload
) -> TenantCatalogueOut:
    store = CatalogueStore(session)
    row = await _run(store.retire(_tenant(payload), catalogue_id))
    return await _tenant_out(store, row)


@router.get("/catalogues/{catalogue_id}/diff", response_model=dict[str, Any], dependencies=[READ])
async def diff_catalogue(
    catalogue_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    v_from: int = Query(alias="from", ge=1),
    v_to: int = Query(alias="to", ge=1),
) -> dict[str, Any]:
    return await _run(CatalogueStore(session).diff(_tenant(payload), catalogue_id, v_from, v_to))


# ── model ──────────────────────────────────────────────────────────────────


async def _model_out(svc: GovernanceService, model: Any, payload: dict[str, Any]) -> ModelOut:
    out = ModelOut.model_validate(model)
    out.can = {"manage": await _has(payload, "governance.manage")}
    catalogue = await svc.catalogue_for(model)
    out.phases = [
        {"code": p.code, "order": p.order, "spine_key": p.spine_key, "name": label_of(p.name_key, p.labels)}
        for p in catalogue.phases
    ]
    return out


@router.get("/projects/{project_id}/model", response_model=ModelOut, dependencies=[READ])
async def get_model(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> ModelOut:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    # Without a model the screen offers "choose a phase model" only to someone who may.
    can = {"manage": await _has(payload, "governance.manage")}
    return await _run(_model_out(svc, await _run(svc.require_model(project_id), can=can), payload))


@router.put("/projects/{project_id}/model", response_model=ModelOut, status_code=201, dependencies=[MANAGE])
async def set_model(
    project_id: uuid.UUID, body: ModelSet, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> ModelOut:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    model = await _run(
        svc.set_model(
            project_id,
            source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            version=body.catalogue_version,
            four_eyes=body.four_eyes,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
        )
    )
    return await _model_out(svc, model, payload)


@router.post("/projects/{project_id}/model/change", response_model=ModelOut, dependencies=[MANAGE])
async def change_model(
    project_id: uuid.UUID, body: ModelChange, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> ModelOut:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    model = await _run(
        svc.change_model(
            project_id,
            source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            version=body.catalogue_version,
            mapping=body.mapping,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
        )
    )
    return await _model_out(svc, model, payload)


@router.patch("/projects/{project_id}/model", response_model=ModelOut, dependencies=[MANAGE])
async def update_model_settings(
    project_id: uuid.UUID,
    body: ModelSettings,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ModelOut:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    model = await _run(
        svc.update_settings(
            project_id,
            four_eyes=body.four_eyes,
            decision_route_id=body.decision_route_id,
            change_route_id=body.change_route_id,
            fields_set=set(body.model_fields_set),
            actor_id=_uid(user_id),
        )
    )
    return await _model_out(svc, model, payload)


@router.get("/projects/{project_id}/matrix", response_model=MatrixOut, dependencies=[READ])
async def get_matrix(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> MatrixOut:
    """Areas x gates: per cell the check status and the documents required there; next gate with blocker count."""
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    m = await _run(svc.matrix(project_id, today=_today(today)))
    cat = m["catalogue"]
    nxt = m["next_gate"]
    for row in m["areas"]:
        for cell in row["cells"].values():
            for doc in cell["documents"]:
                doc["name"] = _label(cat, "doc", doc["doc_type"])
    return MatrixOut(
        gates=await _gates_out(svc, m["gates"], cat),
        next_gate=(
            None
            if nxt is None
            else {"id": str(nxt.id), "code": nxt.code, "status": nxt.status, "blocker_count": m["blocker_count"]}
        ),
        areas=[
            {
                "area_id": str(row["area"].id),
                "code": row["area"].code,
                "name": _label(cat, "area", row["area"].code),
                "name_override": row["area"].name_override,
                "owner_user_id": str(row["area"].owner_user_id) if row["area"].owner_user_id else None,
                "deputy_user_id": str(row["area"].deputy_user_id) if row["area"].deputy_user_id else None,
                "applicable": row["area"].applicable,
                "cells": row["cells"],
            }
            for row in m["areas"]
        ],
    )


# ── areas ──────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/areas", response_model=Page[AreaOut], dependencies=[READ])
async def list_areas(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    include_retired: bool = False,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    rows = await svc.repo.list_areas(project_id, include_retired=include_retired)
    cat = await _catalogue(session, project_id)
    tracked = {(d.area_id, d.doc_type) for d in await svc.repo.list_documents(project_id)}
    can = svc.area_capabilities(
        rows,
        actor_id=_uid(user_id),
        can_edit=await _has(payload, "governance.edit"),
        is_manager=await _has(payload, "governance.manage"),
    )
    out = []
    for row in rows:
        area = _named(AreaOut, row, cat, "area", row.code)
        area.can = can[row.id]
        area.document_types = [
            {
                "code": d.code,
                "name": label_of(d.name_key, d.labels),
                "required_at_gates": list(d.required_at_gates),
                "tracked": (row.id, d.code) in tracked,
            }
            for d in (cat.document_types if cat is not None else ())
            if d.area == row.code
        ]
        out.append(area)
    return _page(out)


@router.patch("/projects/{project_id}/areas/{area_id}", response_model=AreaOut, dependencies=[MANAGE])
async def update_area(
    project_id: uuid.UUID, area_id: uuid.UUID, body: AreaUpdate, session: SessionDep, user_id: CurrentUserId
) -> AreaOut:
    await verify_project_access(project_id, user_id, session)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    area = await _run(
        GovernanceService(session).update_area(project_id, area_id, changes=changes, actor_id=_uid(user_id))
    )
    cat = await _catalogue(session, project_id)
    return _named(AreaOut, area, cat, "area", area.code)


# ── gates ──────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/gates", response_model=Page[GateOut], dependencies=[READ])
async def list_gates(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, include_historic: bool = False
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    rows = await svc.repo.list_gates(project_id, include_historic=include_historic)
    return _page(await _gates_out(svc, rows, await _catalogue(session, project_id)))


@router.get("/projects/{project_id}/gates/{gate_id}", response_model=GateDetailOut, dependencies=[READ])
async def get_gate(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> GateDetailOut:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    detail = await _run(svc.gate_detail(project_id, gate_id, today=_today(today)))
    cat = await _catalogue(session, project_id)
    for area in detail["areas"]:
        area["name"] = _label(cat, "area", area["code"])
        for doc in area["documents"]:
            doc["name"] = _label(cat, "doc", doc["doc_type"])
        named = {c.code: c for c in cat.criteria_for(detail["gate"].code, area["code"])} if cat is not None else {}
        for row in area["criteria"]:
            crit = named.get(row["code"])
            row["name"] = label_of(crit.name_key, crit.labels) if crit is not None else dict(_NO_LABEL)
        # The rule of the write route, so the screen offers no tick that ends in a refusal.
        area["can_tick"] = (
            detail["gate"].status != "decided"
            and not detail["gate"].historic
            and str(user_id) in (area["owner_user_id"], area["deputy_user_id"])
        )
    can: dict[str, Any] = {"edit": await _has(payload, "governance.edit")}
    if await _has(payload, "governance.decide"):
        # Always the server date: ``can`` has to agree with the write routes, which take no date.
        can |= await _run(
            svc.decide_capability(
                project_id, gate_id, decider_id=_uid(user_id), role=_role(payload), today=server_today()
            )
        )
        can |= await _run(svc.gate_capability(project_id, gate_id, actor_id=_uid(user_id), role=_role(payload)))
    else:
        missing = "missing_permission"
        can |= {"outcomes": {o: {"allowed": False, "reason": missing} for o in ev.OUTCOMES}}
        for key in ("decide", "go", "resume", "reopen", "add_condition"):
            can |= {key: False, f"{key}_reason": missing}
        can["acknowledge"] = []
    return GateDetailOut(
        gate=(await _gates_out(svc, [detail["gate"]], cat))[0],
        blockers=detail["blockers"],
        areas=detail["areas"],
        decisions=[DecisionOut.model_validate(d) for d in detail["decisions"]],
        can=can,
    )


@router.post("/projects/{project_id}/gates/{gate_id}/prepare", response_model=GateOut, dependencies=[EDIT])
async def prepare_gate(
    project_id: uuid.UUID, gate_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> GateOut:
    await verify_project_access(project_id, user_id, session)
    gate = await _run(GovernanceService(session).start_preparation(project_id, gate_id, actor_id=_uid(user_id)))
    return await _gate_out(session, gate)


@router.post("/projects/{project_id}/gates/{gate_id}/submit", response_model=GateOut, dependencies=[EDIT])
async def submit_gate(
    project_id: uuid.UUID, gate_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> GateOut:
    await verify_project_access(project_id, user_id, session)
    gate = await _run(GovernanceService(session).submit_gate(project_id, gate_id, actor_id=_uid(user_id)))
    return await _gate_out(session, gate)


@router.post(
    "/projects/{project_id}/gates/{gate_id}/decide", response_model=DecisionOut, status_code=201, dependencies=[DECIDE]
)
async def decide_gate(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    body: DecisionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> DecisionOut:
    """Record a decision. It is judged on the server date; the client cannot supply one."""
    await verify_project_access(project_id, user_id, session)
    request = ev.DecisionRequest(
        outcome=body.outcome,
        rationale=body.rationale,
        decider_id=str(user_id),
        conditions=tuple(
            ev.ProposedCondition(
                area_code=c.area_code,
                document_type=c.document_type,
                text=c.text,
                owner_user_id=str(c.owner_user_id) if c.owner_user_id else None,
                due_date=c.due_date,
                severity=c.severity,
            )
            for c in body.conditions
        ),
        proceed_at_risk_areas=tuple(body.proceed_at_risk_areas),
        accepted_not_applicable=tuple(body.accepted_not_applicable),
        hold_resume_date=body.hold_resume_date,
        acknowledged_evidence=tuple((e.area_code, e.code) for e in body.acknowledged_evidence),
    )
    decision = await _run(
        GovernanceService(session).decide(
            project_id, gate_id, request=request, decider_id=_uid(user_id), role=_role(payload), today=server_today()
        )
    )
    return DecisionOut.model_validate(decision)


@router.post("/projects/{project_id}/gates/{gate_id}/reopen", response_model=GateOut, dependencies=[DECIDE])
async def reopen_gate(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    body: ReopenIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> GateOut:
    await verify_project_access(project_id, user_id, session)
    gate = await _run(
        GovernanceService(session).reopen(
            project_id, gate_id, rationale=body.rationale, actor_id=_uid(user_id), role=_role(payload)
        )
    )
    return await _gate_out(session, gate)


@router.post("/projects/{project_id}/gates/{gate_id}/resume", response_model=GateOut, dependencies=[DECIDE])
async def resume_gate(
    project_id: uuid.UUID, gate_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> GateOut:
    await verify_project_access(project_id, user_id, session)
    gate = await _run(
        GovernanceService(session).resume(project_id, gate_id, actor_id=_uid(user_id), role=_role(payload))
    )
    return await _gate_out(session, gate)


@router.patch("/projects/{project_id}/gates/{gate_id}", response_model=GateOut, dependencies=[MANAGE])
async def plan_gate(
    project_id: uuid.UUID, gate_id: uuid.UUID, body: GatePlan, session: SessionDep, user_id: CurrentUserId
) -> GateOut:
    """Plan a gate: link it to a schedule activity, which then owns the date, or give it a date of its own."""
    await verify_project_access(project_id, user_id, session)
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    gate = await _run(
        GovernanceService(session).plan_gate(project_id, gate_id, changes=changes, actor_id=_uid(user_id))
    )
    return await _gate_out(session, gate)


@router.get("/projects/{project_id}/gates/{gate_id}/decisions", response_model=Page[DecisionOut], dependencies=[READ])
async def list_gate_decisions(
    project_id: uuid.UUID, gate_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    await _run(svc.get_gate(project_id, gate_id))
    rows = await svc.repo.list_decisions(project_id, gate_id)
    return _page([DecisionOut.model_validate(r) for r in rows])


@router.put("/projects/{project_id}/gates/{gate_id}/checks/{area_id}", response_model=CheckOut, dependencies=[EDIT])
async def confirm_check(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    area_id: uuid.UUID,
    body: CheckConfirm,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CheckOut:
    await verify_project_access(project_id, user_id, session)
    check = await _run(
        GovernanceService(session).confirm_check(
            project_id, gate_id, area_id, status=body.status, rag=body.rag, note=body.note, actor_id=_uid(user_id)
        )
    )
    return CheckOut.model_validate(check)


@router.put(
    "/projects/{project_id}/gates/{gate_id}/checks/{area_id}/criteria/{code}",
    response_model=CheckOut,
    dependencies=[EDIT],
)
async def tick_criterion(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    area_id: uuid.UUID,
    code: str,
    body: CriterionTick,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CheckOut:
    """Tick or untick one readiness criterion of the area. The server records who and when."""
    await verify_project_access(project_id, user_id, session)
    check = await _run(
        GovernanceService(session).tick_criterion(
            project_id, gate_id, area_id, code, met=body.met, note=body.note, actor_id=_uid(user_id)
        )
    )
    return CheckOut.model_validate(check)


@router.post(
    "/projects/{project_id}/gates/{gate_id}/checks/{area_id}/not-applicable",
    response_model=CheckOut,
    dependencies=[EDIT],
)
async def check_not_applicable(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    area_id: uuid.UUID,
    body: NotApplicableIn,
    session: SessionDep,
    user_id: CurrentUserId,
) -> CheckOut:
    await verify_project_access(project_id, user_id, session)
    check = await _run(
        GovernanceService(session).mark_check_not_applicable(
            project_id, gate_id, area_id, rationale=body.rationale, actor_id=_uid(user_id)
        )
    )
    return CheckOut.model_validate(check)


@router.post(
    "/projects/{project_id}/gates/{gate_id}/conditions",
    response_model=ConditionOut,
    status_code=201,
    dependencies=[DECIDE],
)
async def add_condition(
    project_id: uuid.UUID,
    gate_id: uuid.UUID,
    body: ConditionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ConditionOut:
    await verify_project_access(project_id, user_id, session)
    cond = ev.ProposedCondition(
        area_code=body.area_code,
        document_type=body.document_type,
        text=body.text,
        owner_user_id=str(body.owner_user_id) if body.owner_user_id else None,
        due_date=body.due_date,
        severity=body.severity,
    )
    svc = GovernanceService(session)
    row = await _run(svc.add_condition(project_id, gate_id, cond=cond, actor_id=_uid(user_id), role=_role(payload)))
    return (await _conditions_out(svc, project_id, [row], payload, user_id))[0]


# ── documents ──────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/documents", response_model=Page[DocumentOut], dependencies=[READ])
async def list_documents(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    rows = await svc.repo.list_documents(project_id)
    cat = await _catalogue(session, project_id)
    can = await svc.document_capabilities(
        project_id,
        rows,
        actor_id=_uid(user_id),
        can_edit=await _has(payload, "governance.edit"),
        is_manager=await _has(payload, "governance.manage"),
    )
    out = []
    for row in rows:
        doc = _named(DocumentOut, row, cat, "doc", row.doc_type)
        doc.can = can[row.id]
        out.append(doc)
    return _page(out)


@router.post("/projects/{project_id}/documents", response_model=DocumentOut, status_code=201, dependencies=[EDIT])
async def create_document(
    project_id: uuid.UUID,
    body: DocumentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> DocumentOut:
    await verify_project_access(project_id, user_id, session)
    doc = await _run(
        GovernanceService(session).create_document(
            project_id,
            area_id=body.area_id,
            doc_type=body.doc_type,
            actor_id=_uid(user_id),
            is_manager=await _has(payload, "governance.manage"),
        )
    )
    cat = await _catalogue(session, project_id)
    return _named(DocumentOut, doc, cat, "doc", doc.doc_type)


@router.post("/projects/{project_id}/documents/{document_id}/attach", response_model=DocumentOut, dependencies=[EDIT])
async def attach_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: AttachIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> DocumentOut:
    await verify_project_access(project_id, user_id, session)
    doc = await _run(
        GovernanceService(session).attach_container(
            project_id,
            document_id,
            container_id=body.container_id,
            actor_id=_uid(user_id),
            is_manager=await _has(payload, "governance.manage"),
        )
    )
    cat = await _catalogue(session, project_id)
    return _named(DocumentOut, doc, cat, "doc", doc.doc_type)


@router.post("/projects/{project_id}/documents/{document_id}/submit", response_model=DocumentOut, dependencies=[EDIT])
async def submit_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> DocumentOut:
    await verify_project_access(project_id, user_id, session)
    doc = await _run(
        GovernanceService(session).submit_document(
            project_id, document_id, actor_id=_uid(user_id), is_manager=await _has(payload, "governance.manage")
        )
    )
    cat = await _catalogue(session, project_id)
    return _named(DocumentOut, doc, cat, "doc", doc.doc_type)


@router.post("/projects/{project_id}/documents/{document_id}/return", response_model=DocumentOut, dependencies=[EDIT])
async def return_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> DocumentOut:
    await verify_project_access(project_id, user_id, session)
    doc = await _run(
        GovernanceService(session).return_document(
            project_id, document_id, actor_id=_uid(user_id), is_manager=await _has(payload, "governance.manage")
        )
    )
    cat = await _catalogue(session, project_id)
    return _named(DocumentOut, doc, cat, "doc", doc.doc_type)


@router.get(
    "/projects/{project_id}/documents/{document_id}/history", response_model=DocumentHistoryOut, dependencies=[READ]
)
async def document_history(
    project_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> DocumentHistoryOut:
    await verify_project_access(project_id, user_id, session)
    data = await _run(GovernanceService(session).document_history(project_id, document_id))
    return DocumentHistoryOut(
        document_id=data["document_id"],
        revisions=data["revisions"],
        change_requests=[ChangeRequestOut.model_validate(c) for c in data["change_requests"]],
    )


@router.post(
    "/projects/{project_id}/documents/{document_id}/change-requests",
    response_model=ChangeRequestOut,
    status_code=201,
    dependencies=[EDIT],
)
async def create_change_request(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: ChangeRequestIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ChangeRequestOut:
    await verify_project_access(project_id, user_id, session)
    cr = await _run(
        GovernanceService(session).create_change_request(
            project_id,
            document_id,
            reason=body.reason,
            impact=body.impact,
            proposed_revision_id=body.proposed_revision_id,
            actor_id=_uid(user_id),
            is_manager=await _has(payload, "governance.manage"),
        )
    )
    return ChangeRequestOut.model_validate(cr)


@router.get("/projects/{project_id}/change-requests", response_model=Page[ChangeRequestOut], dependencies=[READ])
async def list_change_requests(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    rows = await GovernanceService(session).repo.list_change_requests(project_id)
    return _page([ChangeRequestOut.model_validate(r) for r in rows])


# ── conditions ─────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/conditions", response_model=Page[ConditionOut], dependencies=[READ])
async def list_conditions(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    status: Literal["open", "cleared", "waived", "overdue"] | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Conditions with their status as of today: one past its due date is overdue whether or not the sweep ran."""
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    rows, total = await svc.repo.list_conditions(
        project_id, status=status, today=server_today(), offset=offset, limit=limit
    )
    return _page(await _conditions_out(svc, project_id, rows, payload, user_id), total, offset, limit)


@router.post("/projects/{project_id}/conditions/escalate", response_model=Page[ConditionOut], dependencies=[DECIDE])
async def escalate_conditions(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Escalate this project's late conditions now, without waiting for the hourly sweep."""
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    rows = await _run(svc.escalate_overdue(project_id, today=server_today()))
    return _page(await _conditions_out(svc, project_id, rows, payload, user_id))


@router.post("/projects/{project_id}/conditions/{condition_id}/clear", response_model=ConditionOut, dependencies=[EDIT])
async def clear_condition(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: ClearIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ConditionOut:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    row = await _run(
        svc.clear_condition(
            project_id,
            condition_id,
            evidence=body.evidence,
            actor_id=_uid(user_id),
            is_manager=await _has(payload, "governance.manage"),
        )
    )
    return (await _conditions_out(svc, project_id, [row], payload, user_id))[0]


@router.post(
    "/projects/{project_id}/conditions/{condition_id}/waive", response_model=ConditionOut, dependencies=[DECIDE]
)
async def waive_condition(
    project_id: uuid.UUID,
    condition_id: uuid.UUID,
    body: WaiveIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ConditionOut:
    await verify_project_access(project_id, user_id, session)
    svc = GovernanceService(session)
    row = await _run(
        svc.waive_condition(
            project_id, condition_id, rationale=body.rationale, actor_id=_uid(user_id), role=_role(payload)
        )
    )
    return (await _conditions_out(svc, project_id, [row], payload, user_id))[0]


# ── validation and export ──────────────────────────────────────────────────


@router.get("/projects/{project_id}/validation", response_model=Page[FindingOut], dependencies=[READ])
async def validate_project(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    """Run the ``project_governance`` rule set against the project's current state."""
    from app.core.validation.engine import ValidationContext
    from app.modules.project_governance.validators import GOVERNANCE_RULES

    await verify_project_access(project_id, user_id, session)
    data = await _run(GovernanceService(session).validation_payload(project_id, today=_today(today)))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    findings: list[FindingOut] = []
    for rule_cls in GOVERNANCE_RULES:
        for r in await rule_cls().validate(context):
            findings.append(
                FindingOut(
                    rule_id=r.rule_id,
                    passed=r.passed,
                    severity=str(r.severity),
                    message=r.message,
                    element_ref=r.element_ref,
                    suggestion=r.suggestion,
                )
            )
    return _page(findings)


@router.get("/projects/{project_id}/export", dependencies=[READ])
async def export_trail(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
) -> Response:
    """The decision trail as PDF or XLSX."""
    from app.modules.project_governance.export import render, written_locale
    from app.modules.projects.models import Project

    await verify_project_access(project_id, user_id, session)
    project = await session.get(Project, project_id)
    trail = await GovernanceService(session).trail(project_id)
    locale = written_locale(get_locale())
    content = render(trail, project_name=getattr(project, "name", "") or "", locale=locale, fmt=fmt)
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="governance_trail.{fmt}"',
            # The language the trail was written in, which is not always the one asked for.
            "Content-Language": locale,
        },
    )
