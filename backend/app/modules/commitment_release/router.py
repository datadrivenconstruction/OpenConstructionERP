# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commitment release API, mounted at ``/api/v1/commitment-release``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are looked up by
``(project_id, id)`` and linked documents are checked against the project, so
an id from another project is also 404.

Catalogue routes (``/authority-schedules``, ``/abort-bases``) are scoped to the
caller's tenant and go through module 1's shared catalogue store.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``commitment.errors.<code>``. 404 = not found or
not visible, 403 = visible but not allowed (not the item owner, four-eyes),
409 = state conflict (pending release, document counted elsewhere, concurrent
request), 422 = invalid input or a refusing rule (missing FX rate, open
preconditions under ``block``, no route for the tier).

Release authority is not a permission: the decider is whoever the approval
route of the required tier entitles, and they decide in the approval screen.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.commitment_release import evaluator as ev
from app.modules.commitment_release.catalogue import ABORT_BASIS_KIND, AUTHORITY_SCHEDULE_KIND, parse_amount
from app.modules.commitment_release.errors import CommitmentError
from app.modules.commitment_release.messages import label_texts, translate
from app.modules.commitment_release.schemas import (
    AbortIn,
    AbortTermsOut,
    AbortTermsPut,
    AssignmentOut,
    AssignmentsPut,
    CheckIn,
    CheckOut,
    DecideIn,
    EvaluateIn,
    FindingOut,
    HoldIn,
    ItemCreate,
    ItemPatch,
    LinkIn,
    LinkOut,
    MatrixOut,
    MatrixSet,
    Page,
    PreconditionConfirm,
    PreconditionIn,
    ReleaseOut,
    ReleaseRequest,
    RoutesGenerate,
    ScenarioIn,
    ScheduleCreate,
    ScheduleUpdate,
    TierRoutePin,
    TransferIn,
    WithdrawIn,
)
from app.modules.commitment_release.service import CommitmentService

router = APIRouter(tags=["commitment_release"])

READ = Depends(RequirePermission("commitment.read"))
EDIT = Depends(RequirePermission("commitment.edit"))
MANAGE = Depends(RequirePermission("commitment.manage"))
CATALOGUE = Depends(RequirePermission("commitment.catalogue"))


async def _run[T](awaitable: Awaitable[T]) -> T:
    """Turn a :class:`CommitmentError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except CommitmentError as exc:
        message = translate(f"commitment.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = CommitmentError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"commitment.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _may_manage(payload: dict[str, Any]) -> bool:
    """Whether the caller holds ``commitment.manage``, by the same rule ``RequirePermission`` applies.

    The service takes this as a boolean and never sees a role.
    """
    return _holds(payload, "commitment.manage")


def _holds(payload: dict[str, Any], permission: str) -> bool:
    """Whether the caller holds ``permission``: an admin, a grant on the token, or the role's own."""
    from app.core.permissions import permission_registry

    role = str(payload.get("role") or "")
    return (
        role == "admin"
        or permission in (payload.get("permissions") or [])
        or permission_registry.role_has_permission(role, permission)
    )


def _today(value: date | None) -> date:
    """The server date, or the date a READ asked for. A write never passes a client date:
    the FX date and the validity of an assignment are not the caller's to choose."""
    return value or datetime.now(UTC).date()


def _page(items: list[Any], **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": len(items), "offset": 0, "limit": len(items), **extra}


def _tenant(payload: dict[str, Any]) -> str:
    tenant = resolve_tenant_id(payload)
    if not tenant:
        raise HTTPException(status_code=404, detail="Not found")
    return tenant


# ── catalogue admin (tenant scoped) ────────────────────────────────────────


async def _schedule_out(store: Any, row: Any) -> dict[str, Any]:
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


async def _own_schedule(store: Any, tenant: str, catalogue_id: uuid.UUID) -> Any:
    row = await _run(store.get(tenant, catalogue_id))
    if row.kind != AUTHORITY_SCHEDULE_KIND:
        raise HTTPException(status_code=404, detail={"code": "unknown_catalogue"})
    return row


@router.get("/authority-schedules", response_model=Page[dict[str, Any]], dependencies=[READ])
async def list_schedules(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Shipped authority schedules and the caller's tenant schedules."""
    from app.modules.project_governance.catalogue_store import CatalogueStore

    CommitmentService(session)  # registers the kinds
    items = await _run(CatalogueStore(session).list_available(resolve_tenant_id(payload), kind=AUTHORITY_SCHEDULE_KIND))
    return _page(items)


@router.post("/authority-schedules", status_code=201, dependencies=[CATALOGUE])
async def create_schedule(
    body: ScheduleCreate, session: SessionDep, payload: CurrentUserPayload, user_id: CurrentUserId
) -> dict[str, Any]:
    """Clone a shipped or own schedule into a tenant draft, or start an empty one."""
    from app.modules.project_governance.catalogue_store import CatalogueStore

    CommitmentService(session)
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
            kind=AUTHORITY_SCHEDULE_KIND,
        )
    )
    return await _schedule_out(store, row)


@router.get("/authority-schedules/{catalogue_id}", dependencies=[READ])
async def get_schedule(catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    CommitmentService(session)
    store = CatalogueStore(session)
    return await _schedule_out(store, await _own_schedule(store, _tenant(payload), catalogue_id))


@router.patch("/authority-schedules/{catalogue_id}", dependencies=[CATALOGUE])
async def update_schedule(
    catalogue_id: uuid.UUID, body: ScheduleUpdate, session: SessionDep, payload: CurrentUserPayload
) -> dict[str, Any]:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    CommitmentService(session)
    store = CatalogueStore(session)
    tenant = _tenant(payload)
    await _own_schedule(store, tenant, catalogue_id)
    row = await _run(store.update_draft(tenant, catalogue_id, body=body.body, name=body.name))
    return await _schedule_out(store, row)


@router.post("/authority-schedules/{catalogue_id}/publish", dependencies=[CATALOGUE])
async def publish_schedule(
    catalogue_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload, user_id: CurrentUserId
) -> dict[str, Any]:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    CommitmentService(session)
    store = CatalogueStore(session)
    tenant = _tenant(payload)
    await _own_schedule(store, tenant, catalogue_id)
    v = await _run(store.publish(tenant, catalogue_id, actor_id=_uid(user_id)))
    return {"version": v.version, "content_hash": v.content_hash, "published_at": v.published_at.isoformat()}


@router.get("/authority-schedules/{catalogue_id}/diff", dependencies=[READ])
async def diff_schedule(
    catalogue_id: uuid.UUID,
    session: SessionDep,
    payload: CurrentUserPayload,
    v_from: int = Query(..., alias="from", ge=1),
    v_to: int = Query(..., alias="to", ge=1),
) -> dict[str, Any]:
    from app.modules.project_governance.catalogue_store import CatalogueStore

    CommitmentService(session)
    store = CatalogueStore(session)
    tenant = _tenant(payload)
    await _own_schedule(store, tenant, catalogue_id)
    return await _run(store.diff(tenant, catalogue_id, v_from, v_to))


@router.post("/authority-schedules/evaluate", dependencies=[READ])
async def evaluate_schedule(body: EvaluateIn, session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """The test calculator: which tier a type and amount need under one schedule version."""
    from app.modules.project_governance.catalogue_store import resolve_catalogue

    CommitmentService(session)
    # The id comes from the request: it resolves for the caller's own tenant only (404 otherwise).
    schedule = await _run(
        resolve_catalogue(
            session,
            body.schedule_source,
            body.schedule_id,
            body.schedule_version,
            kind=AUTHORITY_SCHEDULE_KIND,
            tenant_id=_tenant(payload),
        )
    )
    try:
        r = ev.required_tier(schedule, body.commitment_type, parse_amount(body.amount), body.flags)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "commitment_type_unknown"}) from exc
    return {
        "required_tier": r.tier_code,
        "escalate_outside": r.escalate_outside,
        "band_code": r.band_code,
        "raised_by": list(r.raised_by),
        "currency": schedule.currency,
        "approver": schedule.tier(r.tier_code).approver.model_dump() if r.tier_code else None,
    }


@router.get("/abort-bases", response_model=Page[dict[str, Any]], dependencies=[READ])
async def list_abort_bases(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Shipped abort bases (with their review status) and the caller's own."""
    from app.modules.commitment_release.catalogue import parameter_fields
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind
    from app.modules.project_governance.catalogue_store import CatalogueStore

    svc = CommitmentService(session)
    items = await _run(CatalogueStore(session).list_available(resolve_tenant_id(payload), kind=ABORT_BASIS_KIND))
    shipped = {b.id: b for b in get_catalogue_kind(ABORT_BASIS_KIND).shipped()}
    for it in items:
        if it["source"] == "shipped":
            b = shipped.get(it["id"])
        elif it["latest_version"] is not None:
            # The listing is the caller's own tenant plus the active pack, so each published body is
            # read the way a stored pin is.
            b = await _run(svc.abort_basis(it["source"], it["id"], it["latest_version"]))
        else:
            # A draft that was never published cannot be chosen for abort terms yet.
            b = None
        it["method"] = b.method if b is not None else None
        it["parameters"] = {k: v.model_dump(mode="json") for k, v in b.parameters.items()} if b is not None else {}
        it["parameter_fields"] = parameter_fields(b) if b is not None else []
        it["source_url"] = b.source_url if b is not None else None
    return _page(items)


# ── matrix ─────────────────────────────────────────────────────────────────


async def _matrix_out(svc: CommitmentService, matrix: Any) -> MatrixOut:
    out = MatrixOut.model_validate(matrix)
    project = await svc._project(matrix.project_id)
    schedule = await svc.schedule_for(matrix)
    out.base_currency = (project.currency or "").upper()
    out.schedule_currency = svc.schedule_currency(schedule, project)
    states = await svc.route_states(matrix)
    locale = get_locale() or "en"
    out.tiers = [
        {
            "code": t.code,
            "name": {"key": t.name_key or None, "text": label_texts(t.name_key, t.labels, locale)},
            "approver": t.approver.model_dump(),
            "steps_mode": t.steps_mode,
            "four_eyes": t.four_eyes,
            "route_id": (matrix.tier_routes or {}).get(t.code),
            "route_state": states.get(t.code, "none"),
        }
        for t in schedule.tiers
    ]
    out.commitment_types = [
        {"code": t.code, "name": {"key": t.name_key or None, "text": label_texts(t.name_key, t.labels, locale)}}
        for t in schedule.commitment_types
    ]
    out.novelty_flags = [
        {
            "code": f.code,
            "name": {"key": f.name_key or None, "text": label_texts(f.name_key, f.labels, locale)},
            "min_tier": f.min_tier,
        }
        for f in schedule.novelty_flags
    ]
    return out


@router.get("/projects/{project_id}/capabilities", dependencies=[READ])
async def project_capabilities(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """What the caller may do on this project's matrix, before and after it exists.

    ``can.manage`` covers starting the matrix and every setting of it; ``add_item`` and
    ``save_scenario`` need a matrix. Each flag is ``{allowed, reason}`` with an error code.
    """
    await verify_project_access(project_id, user_id, session)
    edit = _holds(payload, "commitment.edit")
    exists = await CommitmentService(session).get_matrix(project_id) is not None

    def flag(code: str | None) -> dict[str, Any]:
        return {"allowed": code is None, "reason": code}

    needs_matrix = None if exists else "matrix_missing"
    working = needs_matrix or (None if edit else "edit_required")
    return {
        "matrix_exists": exists,
        "can": {
            "manage": flag(None if _may_manage(payload) else "manage_required"),
            "add_item": flag(working),
            "save_scenario": flag(working),
        },
    }


@router.get("/projects/{project_id}/references", dependencies=[READ])
async def project_references(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Gates, areas, frame documents and funding applications a form may pick from. Never 404 for a
    project without a governance model: the lists are empty and ``has_model`` is false."""
    await verify_project_access(project_id, user_id, session)
    return await _run(CommitmentService(session).references(project_id))


@router.get("/projects/{project_id}/items/{item_id}/transfer-targets", dependencies=[MANAGE])
async def transfer_targets(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Projects (this one first) and their open items the item may be transferred to."""
    from app.dependencies import accessible_project_ids

    await verify_project_access(project_id, user_id, session)
    return _page(
        await _run(
            CommitmentService(session).transfer_targets(
                project_id, item_id, accessible=await accessible_project_ids(session, user_id), manage=True
            )
        )
    )


@router.get("/projects/{project_id}/matrix", response_model=MatrixOut, dependencies=[READ])
async def get_matrix(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> MatrixOut:
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    return await _run(_matrix_out(svc, await _run(svc.require_matrix(project_id))))


@router.put("/projects/{project_id}/matrix", response_model=MatrixOut, dependencies=[MANAGE])
async def set_matrix(
    project_id: uuid.UUID, body: MatrixSet, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> MatrixOut:
    """Create the matrix or change schedule pin, enforcement, FX policy. Needs ``commitment.manage``."""
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    matrix = await _run(
        svc.set_matrix(
            project_id,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
            schedule_source=body.schedule_source,
            schedule_id=body.schedule_id,
            schedule_version=body.schedule_version,
            enforcement=body.enforcement,
            fx_policy=body.fx_policy,
            require_link=body.require_link,
            legal_entity_id=body.legal_entity_id,
        )
    )
    return await _run(_matrix_out(svc, matrix))


@router.get("/projects/{project_id}/assignments", response_model=Page[AssignmentOut], dependencies=[READ])
async def list_assignments(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    rows = await CommitmentService(session).repo.list_assignments(project_id)
    return _page([AssignmentOut.model_validate(r) for r in rows])


@router.put("/projects/{project_id}/assignments", response_model=Page[AssignmentOut], dependencies=[MANAGE])
async def put_assignments(
    project_id: uuid.UUID, body: AssignmentsPut, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Replace who fills each project-role tier; untouched generated tier routes follow."""
    await verify_project_access(project_id, user_id, session)
    rows = await _run(
        CommitmentService(session).put_assignments(
            project_id, [a.model_dump() for a in body.assignments], actor_id=_uid(user_id), today=_today(None)
        )
    )
    return _page([AssignmentOut.model_validate(r) for r in rows])


@router.post("/projects/{project_id}/routes/generate", dependencies=[MANAGE])
async def generate_routes(
    project_id: uuid.UUID, body: RoutesGenerate, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Generate one approval route per tier. Routes edited by a manager are kept unless ``force``."""
    await verify_project_access(project_id, user_id, session)
    report = await _run(
        CommitmentService(session).generate_routes(
            project_id, actor_id=_uid(user_id), today=_today(None), force=body.force
        )
    )
    return {"tiers": report}


@router.put("/projects/{project_id}/routes/{tier_code}", response_model=MatrixOut, dependencies=[MANAGE])
async def pin_tier_route(
    project_id: uuid.UUID, tier_code: str, body: TierRoutePin, session: SessionDep, user_id: CurrentUserId
) -> MatrixOut:
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    matrix = await _run(svc.pin_tier_route(project_id, tier_code, body.route_id, actor_id=_uid(user_id)))
    return await _run(_matrix_out(svc, matrix))


@router.delete("/projects/{project_id}/routes/{tier_code}", response_model=MatrixOut, dependencies=[MANAGE])
async def unpin_tier_route(
    project_id: uuid.UUID, tier_code: str, session: SessionDep, user_id: CurrentUserId
) -> MatrixOut:
    """Give a tier back to its generated route. A pinned route is never replaced any other way."""
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    matrix = await _run(svc.unpin_tier_route(project_id, tier_code, actor_id=_uid(user_id), today=_today(None)))
    return await _run(_matrix_out(svc, matrix))


# ── items ──────────────────────────────────────────────────────────────────


async def _view(
    svc: CommitmentService,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    today: date,
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    data = await _run(
        svc.item_views(
            project_id,
            today=today,
            item_ids=[item_id],
            with_exposure=True,
            actor_id=_uid(user_id),
            manage=_may_manage(payload),
        )
    )
    if not data["items"]:
        raise HTTPException(status_code=404, detail={"code": "item_not_found"})
    return data["items"][0]


@router.get("/projects/{project_id}/items", dependencies=[READ])
async def list_items(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
    with_exposure: bool = False,
) -> dict[str, Any]:
    """Items with derived planned / released / committed, flags, decision dates; ``totals`` in base currency.

    Each item carries ``can``: what the caller may do to it now, with the refusal code when not.
    """
    await verify_project_access(project_id, user_id, session)
    data = await _run(
        CommitmentService(session).item_views(
            project_id,
            today=_today(today),
            with_exposure=with_exposure,
            actor_id=_uid(user_id),
            manage=_may_manage(payload),
        )
    )
    return _page(data["items"], totals=data["totals"])


@router.post("/projects/{project_id}/items", status_code=201, dependencies=[EDIT])
async def create_item(
    project_id: uuid.UUID, body: ItemCreate, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    item = await _run(
        svc.create_item(
            project_id, body.model_dump(exclude_none=True), actor_id=_uid(user_id), manage=_may_manage(payload)
        )
    )
    return await _view(svc, project_id, item.id, _today(None), user_id, payload)


@router.get("/projects/{project_id}/items/{item_id}", dependencies=[READ])
async def get_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    await _run(svc.get_item(project_id, item_id))
    return await _view(svc, project_id, item_id, _today(today), user_id, payload)


@router.patch("/projects/{project_id}/items/{item_id}", dependencies=[EDIT])
async def patch_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Owner of the item or a manager. ``commitment_type`` is fixed once a release was requested.

    What a gate reads (``gate_code``, ``governance_area_code``, ``deferred``) and the owner need
    ``commitment.manage`` and change only while the item is ``planned``; ``split_group`` and
    ``flags`` are frozen once a release was requested.
    """
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    await _run(
        svc.update_item(
            project_id,
            item_id,
            body.model_dump(exclude_unset=True),
            actor_id=_uid(user_id),
            manage=_may_manage(payload),
        )
    )
    return await _view(svc, project_id, item_id, _today(None), user_id, payload)


@router.post("/projects/{project_id}/items/{item_id}/hold", dependencies=[MANAGE])
async def hold_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: HoldIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    await _run(
        svc.set_hold(
            project_id,
            item_id,
            hold=body.hold,
            actor_id=_uid(user_id),
            reason=body.reason,
            manage=_may_manage(payload),
        )
    )
    return await _view(svc, project_id, item_id, _today(None), user_id, payload)


@router.post(
    "/projects/{project_id}/items/{item_id}/links", response_model=LinkOut, status_code=201, dependencies=[EDIT]
)
async def add_link(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: LinkIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> LinkOut:
    """Count a document in this item (owner or manager). 404 when it is another project's; 409 when another item counts it."""
    await verify_project_access(project_id, user_id, session)
    link = await _run(
        CommitmentService(session).add_link(
            project_id, item_id, body.kind, body.document_id, actor_id=_uid(user_id), manage=_may_manage(payload)
        )
    )
    return LinkOut.model_validate(link)


@router.delete("/projects/{project_id}/items/{item_id}/links/{link_id}", status_code=204, dependencies=[EDIT])
async def remove_link(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    link_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(
        CommitmentService(session).remove_link(
            project_id, item_id, link_id, actor_id=_uid(user_id), manage=_may_manage(payload)
        )
    )
    return Response(status_code=204)


@router.post("/projects/{project_id}/items/{item_id}/preconditions", status_code=201, dependencies=[EDIT])
async def add_precondition(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: PreconditionIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    await _run(
        svc.add_precondition(
            project_id,
            item_id,
            kind=body.kind,
            ref_id=body.ref_id,
            text=body.text,
            actor_id=_uid(user_id),
            manage=_may_manage(payload),
        )
    )
    return await _view(svc, project_id, item_id, _today(None), user_id, payload)


@router.delete(
    "/projects/{project_id}/items/{item_id}/preconditions/{precondition_id}", status_code=204, dependencies=[MANAGE]
)
async def remove_precondition(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    precondition_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    reason: str = Query("", max_length=2000),
) -> Response:
    """Remove a precondition: a manager, with a reason, while no release request is running."""
    await verify_project_access(project_id, user_id, session)
    await _run(
        CommitmentService(session).remove_precondition(
            project_id, item_id, precondition_id, reason=reason, actor_id=_uid(user_id), manage=_may_manage(payload)
        )
    )
    return Response(status_code=204)


@router.post("/projects/{project_id}/items/{item_id}/preconditions/{precondition_id}/confirm", dependencies=[EDIT])
async def confirm_precondition(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    precondition_id: uuid.UUID,
    body: PreconditionConfirm,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Tick (or untick) a manual precondition; linked kinds are computed and refuse a tick.

    Whoever confirms a precondition cannot approve the item's release under four eyes.
    """
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    await _run(
        svc.confirm_precondition(
            project_id,
            item_id,
            precondition_id,
            met=body.met,
            evidence_ref=body.evidence_ref,
            actor_id=_uid(user_id),
            manage=_may_manage(payload),
        )
    )
    return await _view(svc, project_id, item_id, _today(None), user_id, payload)


# ── releases ───────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/items/{item_id}/releases/preview", dependencies=[READ])
async def preview_release(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ReleaseRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """The tier, its approvers and the FX rate a request would use; nothing is written."""
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    e = await _run(svc.preview_release(project_id, item_id, body.amount, body.currency, today=_today(None)))
    return svc.evaluation_out(e)


@router.post(
    "/projects/{project_id}/items/{item_id}/releases", response_model=ReleaseOut, status_code=201, dependencies=[EDIT]
)
async def request_release(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ReleaseRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ReleaseOut:
    """Start the approval of the required tier (owner or manager). 409 ``release_pending`` when one is running."""
    await verify_project_access(project_id, user_id, session)
    decision = await _run(
        CommitmentService(session).request_release(
            project_id,
            item_id,
            amount=body.amount,
            currency=body.currency,
            tranche_note=body.tranche_note,
            external_approval_ref=body.external_approval_ref,
            actor_id=_uid(user_id),
            today=_today(None),
            manage=_may_manage(payload),
        )
    )
    return ReleaseOut.model_validate(decision)


@router.post("/projects/{project_id}/items/{item_id}/releases/withdraw", response_model=ReleaseOut, dependencies=[EDIT])
async def withdraw_release(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: WithdrawIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ReleaseOut:
    await verify_project_access(project_id, user_id, session)
    decision = await _run(
        CommitmentService(session).withdraw_release(
            project_id, item_id, actor_id=_uid(user_id), manage=_may_manage(payload), reason=body.reason
        )
    )
    return ReleaseOut.model_validate(decision)


@router.post("/projects/{project_id}/items/{item_id}/releases/decide", response_model=ReleaseOut, dependencies=[READ])
async def decide_release(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: DecideIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ReleaseOut:
    """Approve or reject the pending request as a holder of its tier.

    Release authority is not a permission: 403 ``not_entitled_decider`` unless the caller is the
    step's approver, their delegate, another active assignee of an ``any`` tier, or a deputy.
    403 ``four_eyes_violation`` for the requester, the owner and whoever confirmed a precondition.
    A rejection without ``comment`` is 422 ``rationale_required``.
    """
    await verify_project_access(project_id, user_id, session)
    decision = await _run(
        CommitmentService(session).decide_release(
            project_id,
            item_id,
            decision=body.decision,
            comment=body.comment,
            conditions=body.conditions,
            valid_until=body.valid_until,
            actor_id=_uid(user_id),
            # Passed through to approval_routes, which checks a role step against it.
            caller_role=str(payload.get("role") or "") or None,
            today=_today(None),
        )
    )
    return ReleaseOut.model_validate(decision)


@router.get("/projects/{project_id}/items/{item_id}/abort/preview", dependencies=[READ])
async def preview_abort(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """What stopping the item would need today: the loss, the tier, and whether an outside reference is required.

    Read only, and the same evaluation the abort request runs. 422 ``abort_exposure_unknown`` while
    the abort terms do not give a residual loss.
    """
    await verify_project_access(project_id, user_id, session)
    return await _run(CommitmentService(session).preview_abort(project_id, item_id, today=_today(None)))


@router.post(
    "/projects/{project_id}/items/{item_id}/abort", response_model=ReleaseOut, status_code=201, dependencies=[EDIT]
)
async def request_abort(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: AbortIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> ReleaseOut:
    """Ask to stop the item. Decided on the tier its residual loss calls for; then the item is ``aborted``.

    422 ``abort_exposure_unknown`` while the abort terms do not give a residual loss.
    """
    await verify_project_access(project_id, user_id, session)
    decision = await _run(
        CommitmentService(session).request_abort(
            project_id,
            item_id,
            reason=body.reason,
            actor_id=_uid(user_id),
            today=_today(None),
            manage=_may_manage(payload),
            external_approval_ref=body.external_approval_ref,
        )
    )
    return ReleaseOut.model_validate(decision)


@router.post("/projects/{project_id}/items/{item_id}/transfer", dependencies=[MANAGE])
async def transfer_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: TransferIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """End the item as ``transferred``: its links move to the target item, its decisions stay.

    The target is an item of this project, or of another project the caller can see when the
    source has no linked documents (409 ``transfer_links_stay_in_project`` otherwise).
    """
    await verify_project_access(project_id, user_id, session)
    target_project = body.target_project_id or project_id
    if target_project != project_id:
        await verify_project_access(target_project, user_id, session)
    svc = CommitmentService(session)
    await _run(
        svc.transfer_item(
            project_id,
            item_id,
            target_project_id=target_project,
            target_item_id=body.target_item_id,
            reason=body.reason,
            actor_id=_uid(user_id),
            manage=True,
        )
    )
    return await _view(svc, project_id, item_id, _today(None), user_id, payload)


@router.get("/projects/{project_id}/items/{item_id}/releases", response_model=Page[ReleaseOut], dependencies=[READ])
async def release_history(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    rows = await _run(CommitmentService(session).history(project_id, item_id))
    return _page([ReleaseOut.model_validate(r) for r in rows])


# ── abort terms and exposure ───────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/items/{item_id}/abort-terms", response_model=Page[AbortTermsOut], dependencies=[READ]
)
async def get_abort_terms(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = CommitmentService(session)
    item = await _run(svc.get_item(project_id, item_id))
    rows = await svc.repo.list_abort_terms(project_id, [item.id])
    return _page([AbortTermsOut.model_validate(r) for r in rows])


@router.put("/projects/{project_id}/items/{item_id}/abort-terms", response_model=AbortTermsOut, dependencies=[EDIT])
async def put_abort_terms(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    body: AbortTermsPut,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> AbortTermsOut:
    """Terms for the item (``link_id`` null) or one of its links. Every edit is audited."""
    await verify_project_access(project_id, user_id, session)
    data = body.model_dump(mode="json")
    row = await _run(
        CommitmentService(session).put_abort_terms(
            project_id,
            item_id,
            data,
            actor_id=_uid(user_id),
            manage=_may_manage(payload),
            tenant_id=resolve_tenant_id(payload),
        )
    )
    return AbortTermsOut.model_validate(row)


@router.get("/projects/{project_id}/exposure", dependencies=[READ])
async def exposure(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, as_of: date | None = None
) -> dict[str, Any]:
    """Residual loss per item if the project stopped on ``as_of``; unknown terms are null, never 0."""
    await verify_project_access(project_id, user_id, session)
    return await _run(CommitmentService(session).exposure(project_id, as_of=_today(as_of)))


@router.post("/projects/{project_id}/scenarios", status_code=201, dependencies=[EDIT])
async def save_scenario(
    project_id: uuid.UUID, body: ScenarioIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Save what stopping the project on ``as_of`` would cost.

    The one write that takes a day from the caller: the day is the what-if question itself. It is
    stored on the scenario row and nowhere else; no release, rate or decision reads it.
    """
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        CommitmentService(session).save_scenario(
            project_id, as_of=_today(body.as_of), label=body.label, actor_id=_uid(user_id)
        )
    )
    return {"id": str(row.id), "as_of": row.as_of, "label": row.label, "payload": row.payload}


@router.get("/projects/{project_id}/scenarios", dependencies=[READ])
async def list_scenarios(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    rows = await CommitmentService(session).repo.list_scenarios(project_id)
    return _page([{"id": str(r.id), "as_of": r.as_of, "label": r.label, "payload": r.payload} for r in rows])


# ── guard check, validation, export ────────────────────────────────────────


@router.post("/projects/{project_id}/check", response_model=CheckOut, dependencies=[READ])
async def check(project_id: uuid.UUID, body: CheckIn, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """What the guard would say for binding ``new_amount`` on a document: ``ok | warn | block`` with reasons."""
    await verify_project_access(project_id, user_id, session)
    return await _run(
        CommitmentService(session).check_document(
            project_id,
            kind=body.kind,
            document_id=body.document_id,
            new_amount=Decimal(body.new_amount),
            currency=body.currency,
            actor_id=_uid(user_id),
        )
    )


@router.get("/projects/{project_id}/validation", response_model=Page[FindingOut], dependencies=[READ])
async def validation(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext
    from app.modules.commitment_release.validators import COMMITMENT_RULES

    await verify_project_access(project_id, user_id, session)
    data = await _run(CommitmentService(session).validation_payload(project_id, today=_today(today)))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    findings: list[FindingOut] = []
    for rule_cls in COMMITMENT_RULES:
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
async def export_matrix(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
    as_of: date | None = None,
) -> Response:
    """The matrix with exposure as PDF or XLSX."""
    from app.modules.commitment_release.export import render
    from app.modules.projects.models import Project

    await verify_project_access(project_id, user_id, session)
    day = _today(as_of)
    data = await _run(CommitmentService(session).item_views(project_id, today=day, with_exposure=True))
    project = await session.get(Project, project_id)
    locale = get_locale() or "en"
    content = render(
        data["items"],
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
            "Content-Disposition": f'attachment; filename="commitment_matrix.{fmt}"',
            # The language the document was rendered in, not merely the one asked for.
            "Content-Language": locale,
        },
    )
