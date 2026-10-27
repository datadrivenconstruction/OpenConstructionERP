# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Design management API, mounted at ``/api/v1/design-management``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are looked up by
``(project_id, id)`` and every linked CDE container, revision, review cycle or
distribution list is checked against the project, so an id from another
project is also 404 (rule 24).

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``design.errors.<code>``. 404 = not found or not
visible, 403 = visible but not allowed (four-eyes), 409 = state conflict
(duplicate code, binding frame document, wrong state), 422 = invalid input or a
refusing rule (number does not match the scheme, permit package incomplete).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import inspect as sa_inspect

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.design_management import export as dx
from app.modules.design_management.errors import DesignError
from app.modules.design_management.messages import translate
from app.modules.design_management.models import (
    DesignApprovalPoint,
    DesignDistributionRule,
    DesignPermit,
    DesignRelease,
    DesignReport,
    DesignReview,
)
from app.modules.design_management.schemas import (
    ApprovalPointIn,
    CommentIn,
    CommentMove,
    Conclude,
    ConditionDecision,
    ConditionsIn,
    DeliverableIn,
    DistRuleIn,
    DrawingCreate,
    DrawingPatch,
    IssueIn,
    NumberRequest,
    NumberValidate,
    PermitIn,
    PermitItemIn,
    ReleaseIn,
    RenumberApply,
    RenumberPreview,
    ReportIn,
    ReviewIn,
    RoleIn,
    SchemeChange,
    SetupCreate,
    SetupPatch,
    Supersede,
    TitleBlock,
    Transition,
    WbsClose,
    WbsCreate,
    WbsPatch,
    dump,
)
from app.modules.design_management.service import Caller, DesignService

router = APIRouter(tags=["design_management"])

READ = Depends(RequirePermission("design.read"))
EDIT = Depends(RequirePermission("design.edit"))
RELEASE = Depends(RequirePermission("design.release"))
MANAGE = Depends(RequirePermission("design.manage"))


async def _run[T](awaitable: Awaitable[T]) -> T:
    """Turn a :class:`DesignError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except DesignError as exc:
        message = translate(f"design.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = DesignError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"design.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _may(payload: dict[str, Any], permission: str) -> bool:
    """Whether the caller's role holds a permission, by the registry ``RequirePermission`` itself reads.

    The service never sees a role: it gets this boolean and answers both the
    request and the ``can`` flags of the response with it.
    """
    from app.core.permissions import permission_registry

    role = payload.get("role", "") or ""
    return role == "admin" or bool(permission_registry.role_has_permission(role, permission))


def _caller(user_id: str, payload: dict[str, Any]) -> Caller:
    """The caller as the permission registry sees them; the only place a role becomes booleans."""
    return Caller(
        actor_id=_uid(user_id),
        edit=_may(payload, "design.edit"),
        manage=_may(payload, "design.manage"),
        release=_may(payload, "design.release"),
    )


async def _row(svc: DesignService, caller: Caller, row: Any, **extra: Any) -> dict[str, Any]:
    """A record with its ``can`` flags, computed by the functions the writes enforce with."""
    return _out(row, can=await svc.capabilities(row, caller), **extra)


async def _release_out(svc: DesignService, row: Any, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await _row(svc, _caller(user_id, payload), row)


def _page(items: list[Any], offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    window = items[offset : offset + limit] if limit else items[offset:]
    return {"items": window, "total": len(items), "offset": offset, "limit": limit or len(items)}


def _out(row: Any, **extra: Any) -> dict[str, Any]:
    """Every column of an ORM row, JSON-shaped; ``status`` is answered as ``state`` too."""
    out: dict[str, Any] = {}
    for attr in sa_inspect(row).mapper.column_attrs:
        value = getattr(row, attr.key)
        key = "metadata" if attr.key == "metadata_" else attr.key
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        out[key] = value
    if "status" in out:
        out["state"] = out["status"]
    out.update(extra)
    return out


def _require(data: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if not data.get(k)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "field_required",
                "message_key": "design.errors.field_required",
                "message": translate("design.errors.field_required", locale=get_locale() or "en"),
                "violations": [{"code": "field_required", "field": k} for k in missing],
            },
        )


# ── setup ──────────────────────────────────────────────────────────────────


async def _setup_out(svc: DesignService, project_id: uuid.UUID) -> dict[str, Any]:
    setup = await svc.require_setup(project_id)
    scheme = await svc.scheme(setup)
    reports = await svc.reports_catalogue(setup)
    return _out(
        setup,
        scheme=scheme.model_dump(mode="json"),
        reports_catalogue=reports.model_dump(mode="json"),
        phases=await svc.phases(project_id),
        gates_in_use=await svc.gates_in_use(project_id),
    )


@router.get("/projects/{project_id}/setup", dependencies=[READ])
async def get_setup(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _run(_setup_out(svc, project_id))


@router.put("/projects/{project_id}/setup", status_code=201, dependencies=[MANAGE])
async def put_setup(
    project_id: uuid.UUID, body: SetupCreate, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(
        svc.set_setup(project_id, actor_id=_uid(user_id), tenant_id=resolve_tenant_id(payload), **body.model_dump())
    )
    return await _run(_setup_out(svc, project_id))


@router.patch("/projects/{project_id}/setup", dependencies=[MANAGE])
async def patch_setup(
    project_id: uuid.UUID, body: SetupPatch, user_id: CurrentUserId, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(svc.update_setup(project_id, dump(body), actor_id=_uid(user_id)))
    return await _run(_setup_out(svc, project_id))


@router.post("/projects/{project_id}/setup/change", dependencies=[MANAGE])
async def change_scheme(
    project_id: uuid.UUID, body: SchemeChange, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    result = await _run(
        svc.change_scheme(
            project_id,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
            source=body.source,
            scheme_id=body.id,
            version=body.version,
            reports=body.catalogue == "reports",
        )
    )
    return {**(await _run(_setup_out(svc, project_id))), "legacy_drawings": result["legacy"]}


@router.get("/projects/{project_id}/catalogue/hints", dependencies=[READ])
async def report_hints(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _page(await _run(svc.report_hints(project_id)))


# ── WBS ────────────────────────────────────────────────────────────────────


def _wbs_out(row: Any, counts: dict[str, Any], dup_ids: set[str]) -> dict[str, Any]:
    meta = row.metadata_ or {}
    refs = counts.get(str(row.id))
    return {
        "id": str(row.id),
        "parent_id": str(row.parent_id) if row.parent_id else None,
        "code": row.code,
        "name": row.name,
        "level": row.level,
        "sort_order": row.sort_order,
        "kind": meta.get("kind"),
        "discipline": meta.get("discipline"),
        "closed": bool(meta.get("closed")),
        "duplicate_code": str(row.id) in dup_ids,
        "references": dict(refs) if refs else {},
    }


@router.get("/projects/{project_id}/wbs", dependencies=[READ])
async def wbs_tree(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    tree = await _run(svc.wbs_tree(project_id))
    dup_ids = {str(i) for ids in tree["duplicates"].values() for i in ids}
    return {
        **_page([_wbs_out(r, tree["counts"], dup_ids) for r in tree["rows"]]),
        "duplicates": {k: [str(i) for i in v] for k, v in tree["duplicates"].items()},
    }


@router.post("/projects/{project_id}/wbs", status_code=201, dependencies=[EDIT])
async def wbs_create(project_id: uuid.UUID, body: WbsCreate, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc.create_wbs(project_id, dump(body) | {"code": body.code}, actor_id=_uid(user_id)))
    return _wbs_out(row, {}, set())


@router.patch("/projects/{project_id}/wbs/{node_id}", dependencies=[EDIT])
async def wbs_patch(
    project_id: uuid.UUID, node_id: uuid.UUID, body: WbsPatch, user_id: CurrentUserId, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc.patch_wbs(project_id, node_id, dump(body), actor_id=_uid(user_id)))
    return _wbs_out(row, {}, set())


@router.post("/projects/{project_id}/wbs/{node_id}/renumber-preview", dependencies=[READ])
async def wbs_renumber_preview(
    project_id: uuid.UUID, node_id: uuid.UUID, body: RenumberPreview, user_id: CurrentUserId, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _page(await _run(svc.renumber_preview(project_id, node_id, body.code)))


@router.post("/projects/{project_id}/wbs/{node_id}/close", dependencies=[EDIT])
async def wbs_close(
    project_id: uuid.UUID, node_id: uuid.UUID, body: WbsClose, user_id: CurrentUserId, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc.close_wbs(project_id, node_id, closed=body.closed, actor_id=_uid(user_id)))
    return _wbs_out(row, {}, set())


@router.delete("/projects/{project_id}/wbs/{node_id}", status_code=204, dependencies=[EDIT])
async def wbs_delete(project_id: uuid.UUID, node_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(svc.delete_wbs(project_id, node_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


@router.get("/projects/{project_id}/wbs/unresolved", dependencies=[READ])
async def wbs_unresolved(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    refs = await _run(svc.unresolved_wbs(project_id))
    return _page([{"module": r.module, "table": r.table, "row_id": r.row_id, "value": r.value} for r in refs])


# ── roles and approval points ──────────────────────────────────────────────


@router.get("/projects/{project_id}/roles", dependencies=[READ])
async def roles_list(
    project_id: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _page([await _row(svc, _caller(user_id, payload), r) for r in await svc.roles(project_id)])


@router.post("/projects/{project_id}/roles", status_code=201, dependencies=[EDIT])
async def roles_create(
    project_id: uuid.UUID, body: RoleIn, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    data = dump(body)
    _require(data, "party_kind")
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(svc.create_role(project_id, data, actor_id=_uid(user_id), tenant_id=resolve_tenant_id(payload))),
    )


@router.patch("/projects/{project_id}/roles/{role_id}", dependencies=[EDIT])
async def roles_patch(
    project_id: uuid.UUID,
    role_id: uuid.UUID,
    body: RoleIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(
            svc.patch_role(
                project_id, role_id, dump(body), actor_id=_uid(user_id), tenant_id=resolve_tenant_id(payload)
            )
        ),
    )


@router.delete("/projects/{project_id}/roles/{role_id}", status_code=204, dependencies=[EDIT])
async def roles_delete(project_id: uuid.UUID, role_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(svc.delete_role(project_id, role_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


@router.get("/projects/{project_id}/approval-points", dependencies=[READ])
async def ap_list(
    project_id: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(svc.catch_up_approvals(project_id))
    rows = await svc._list(DesignApprovalPoint, project_id, DesignApprovalPoint.code)
    return _page([await _row(svc, _caller(user_id, payload), r) for r in rows])


@router.post("/projects/{project_id}/approval-points", status_code=201, dependencies=[EDIT])
async def ap_create(
    project_id: uuid.UUID,
    body: ApprovalPointIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    data = dump(body)
    _require(data, "kind")
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc, _caller(user_id, payload), await _run(svc.create_approval_point(project_id, data, actor_id=_uid(user_id)))
    )


@router.patch("/projects/{project_id}/approval-points/{ap_id}", dependencies=[EDIT])
async def ap_patch(
    project_id: uuid.UUID,
    ap_id: uuid.UUID,
    body: ApprovalPointIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(svc.patch_approval_point(project_id, ap_id, dump(body), actor_id=_uid(user_id))),
    )


@router.post("/projects/{project_id}/approval-points/{ap_id}/reopen", dependencies=[EDIT])
async def ap_reopen(
    project_id: uuid.UUID, ap_id: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    """Take a rejected approval point back to ``open``; 409 ``approval_point_not_rejected`` otherwise."""
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc, _caller(user_id, payload), await _run(svc.reopen_approval_point(project_id, ap_id, actor_id=_uid(user_id)))
    )


@router.post("/projects/{project_id}/approval-points/{ap_id}/submit", dependencies=[EDIT])
async def ap_submit(
    project_id: uuid.UUID, ap_id: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc, _caller(user_id, payload), await _run(svc.submit_approval_point(project_id, ap_id, actor_id=_uid(user_id)))
    )


# ── deliverables ───────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/deliverables", dependencies=[READ])
async def dl_list(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    phase_code: str | None = None,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    rows = await _run(svc.deliverables(project_id))
    return _page(
        [await _row(svc, _caller(user_id, payload), r) for r in rows if not phase_code or r.phase_code == phase_code]
    )


@router.post("/projects/{project_id}/deliverables", status_code=201, dependencies=[EDIT])
async def dl_create(
    project_id: uuid.UUID, body: DeliverableIn, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    data = dump(body)
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc, _caller(user_id, payload), await _run(svc.create_deliverable(project_id, data, actor_id=_uid(user_id)))
    )


@router.patch("/projects/{project_id}/deliverables/{did}", dependencies=[EDIT])
async def dl_patch(
    project_id: uuid.UUID,
    did: uuid.UUID,
    body: DeliverableIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(svc.patch_deliverable(project_id, did, dump(body), actor_id=_uid(user_id))),
    )


@router.delete("/projects/{project_id}/deliverables/{did}", status_code=204, dependencies=[EDIT])
async def dl_delete(project_id: uuid.UUID, did: uuid.UUID, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(svc.delete_deliverable(project_id, did, actor_id=_uid(user_id)))
    return Response(status_code=204)


# ── numbering ──────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/numbering/preview", dependencies=[READ])
async def num_preview(project_id: uuid.UUID, body: NumberRequest, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _run(svc.preview_number(project_id, dump(body)))


@router.post("/projects/{project_id}/numbering/allocate", dependencies=[EDIT])
async def num_allocate(project_id: uuid.UUID, body: NumberRequest, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _run(svc.allocate_number(project_id, dump(body)))


@router.post("/projects/{project_id}/numbering/validate", dependencies=[READ])
async def num_validate(project_id: uuid.UUID, body: NumberValidate, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _run(svc.validate_number(project_id, body.number))


@router.post("/projects/{project_id}/numbering/bulk-validate", dependencies=[READ])
async def num_bulk(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _page(await _run(svc.bulk_validate(project_id)))


@router.post("/projects/{project_id}/numbering/renumber-preview", dependencies=[MANAGE])
async def num_renumber_preview(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _page(await _run(svc.renumber_preview_drawings(project_id)))


@router.post("/projects/{project_id}/numbering/renumber-apply", dependencies=[MANAGE])
async def num_renumber_apply(project_id: uuid.UUID, body: RenumberApply, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    mapping = {str(k): v for k, v in body.mapping.items()}
    return _page(await _run(svc.renumber_apply(project_id, mapping, actor_id=_uid(user_id))))


# ── drawings (register) ────────────────────────────────────────────────────


def _register_row(entry: dict[str, Any]) -> dict[str, Any]:
    c = entry["container"]
    return _out(
        entry["drawing"],
        number=c.container_code,
        cde_state=c.cde_state,
        suitability_code=c.suitability_code,
        discipline_code=c.discipline_code,
        form_code=c.form_code,
        revision_code=entry["revision_code"],
        current_revision_id=str(c.current_revision_id) if c.current_revision_id else None,
        title_block_mismatch=entry["title_block_mismatch"],
        last_issue=entry["last_issue"],
    )


@router.get("/projects/{project_id}/drawings", dependencies=[READ])
async def drawings_list(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    phase_code: str | None = None,
    discipline_code: str | None = None,
    deliverable_id: uuid.UUID | None = None,
    state: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    rows = await _run(
        svc.register(
            project_id,
            {
                "phase_code": phase_code,
                "discipline_code": discipline_code,
                "deliverable_id": deliverable_id,
                "state": state,
                "q": q,
            },
        )
    )
    return _page([_register_row(e) for e in rows], offset, limit)


@router.post("/projects/{project_id}/drawings", status_code=201, dependencies=[EDIT])
async def drawings_create(project_id: uuid.UUID, body: DrawingCreate, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    drawing, container = await _run(svc.create_drawing(project_id, dump(body), actor_id=_uid(user_id)))
    return _out(drawing, number=container.container_code, cde_state=container.cde_state)


@router.patch("/projects/{project_id}/drawings/{did}", dependencies=[EDIT])
async def drawings_patch(
    project_id: uuid.UUID, did: uuid.UUID, body: DrawingPatch, user_id: CurrentUserId, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _out(await _run(svc.patch_drawing(project_id, did, dump(body), actor_id=_uid(user_id))))


@router.post("/projects/{project_id}/drawings/{did}/supersede", dependencies=[EDIT])
async def drawings_supersede(
    project_id: uuid.UUID, did: uuid.UUID, body: Supersede, user_id: CurrentUserId, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _out(await _run(svc.supersede_drawing(project_id, did, body.by_container_id, actor_id=_uid(user_id))))


@router.post("/projects/{project_id}/drawings/{did}/title-block", dependencies=[EDIT])
async def drawings_title_block(
    project_id: uuid.UUID, did: uuid.UUID, body: TitleBlock, user_id: CurrentUserId, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _out(await _run(svc.read_title_block(project_id, did, body.text, actor_id=_uid(user_id))))


# ── distribution and releases ──────────────────────────────────────────────


@router.get("/projects/{project_id}/distribution-rules", dependencies=[READ])
async def dist_list(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _page(
        [_out(r) for r in await svc._list(DesignDistributionRule, project_id, DesignDistributionRule.created_at)]
    )


@router.post("/projects/{project_id}/distribution-rules", status_code=201, dependencies=[MANAGE])
async def dist_create(project_id: uuid.UUID, body: DistRuleIn, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _out(await _run(svc.create_dist_rule(project_id, dump(body), actor_id=_uid(user_id))))


@router.patch("/projects/{project_id}/distribution-rules/{rid}", dependencies=[MANAGE])
async def dist_patch(
    project_id: uuid.UUID, rid: uuid.UUID, body: DistRuleIn, user_id: CurrentUserId, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return _out(await _run(svc.patch_dist_rule(project_id, rid, dump(body), actor_id=_uid(user_id))))


@router.delete("/projects/{project_id}/distribution-rules/{rid}", status_code=204, dependencies=[MANAGE])
async def dist_delete(project_id: uuid.UUID, rid: uuid.UUID, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(svc.delete_dist_rule(project_id, rid, actor_id=_uid(user_id)))
    return Response(status_code=204)


@router.get("/projects/{project_id}/releases", dependencies=[READ])
async def rel_list(
    project_id: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(svc.catch_up_approvals(project_id))
    rows = await svc._list(DesignRelease, project_id, DesignRelease.code)
    return _page([await _release_out(svc, r, user_id, payload) for r in rows])


@router.post("/projects/{project_id}/releases", status_code=201, dependencies=[EDIT])
async def rel_create(
    project_id: uuid.UUID, body: ReleaseIn, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc.create_release(project_id, dump(body), actor_id=_uid(user_id)))
    return await _release_out(svc, row, user_id, payload)


@router.patch("/projects/{project_id}/releases/{rid}", dependencies=[EDIT])
async def rel_patch(
    project_id: uuid.UUID,
    rid: uuid.UUID,
    body: ReleaseIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc.patch_release(project_id, rid, dump(body), actor_id=_uid(user_id)))
    return await _release_out(svc, row, user_id, payload)


@router.get("/projects/{project_id}/releases/{rid}/preview", dependencies=[READ])
async def rel_preview(project_id: uuid.UUID, rid: uuid.UUID, user_id: CurrentUserId, session: SessionDep):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc._get(DesignRelease, project_id, rid, "release_not_found"))
    plans = await _run(svc.release_plan(project_id, row))
    return _page(
        [
            {
                "recipient_key": p.recipient_key,
                "purpose": p.purpose,
                "revision_ids": [str(r) for r in p.revision_ids],
                "excluded": [{"revision_id": str(r), "reason": c} for r, c in p.excluded],
                "duplicates": [str(r) for r in p.duplicates],
            }
            for p in plans
        ]
    )


@router.post("/projects/{project_id}/releases/{rid}/transition", dependencies=[EDIT])
async def rel_transition(
    project_id: uuid.UUID,
    rid: uuid.UUID,
    body: Transition,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc.release_transition(project_id, rid, body.target, actor_id=_uid(user_id)))
    return await _release_out(svc, row, user_id, payload)


@router.post("/projects/{project_id}/releases/{rid}/issue", dependencies=[RELEASE])
async def rel_issue(
    project_id: uuid.UUID,
    rid: uuid.UUID,
    body: IssueIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(
        svc.issue_release(
            project_id,
            rid,
            actor_id=_uid(user_id),
            duplicate_reason=body.duplicate_reason,
            may_release=_may(payload, "design.release"),
        )
    )
    return await _release_out(svc, row, user_id, payload)


# ── reviews ────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/reviews", dependencies=[READ])
async def rev_list(
    project_id: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    out = []
    for r in await svc._list(DesignReview, project_id, DesignReview.code):
        comments = await svc.review_comments(project_id, r.id)
        out.append(
            await _row(
                svc,
                _caller(user_id, payload),
                r,
                comments_open=sum(1 for c in comments if c.status in ("open", "answered")),
                comments_major_open=sum(
                    1 for c in comments if c.status in ("open", "answered") and c.severity != "minor"
                ),
            )
        )
    return _page(out)


@router.post("/projects/{project_id}/reviews", status_code=201, dependencies=[EDIT])
async def rev_create(
    project_id: uuid.UUID, body: ReviewIn, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(svc.create_review(project_id, dump(body) | {"phase_code": body.phase_code}, actor_id=_uid(user_id))),
    )


@router.post("/projects/{project_id}/reviews/{rid}/transition", dependencies=[EDIT])
async def rev_transition(
    project_id: uuid.UUID,
    rid: uuid.UUID,
    body: Transition,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(svc.review_transition(project_id, rid, body.target, actor_id=_uid(user_id))),
    )


@router.post("/projects/{project_id}/reviews/{rid}/conclude", dependencies=[EDIT])
async def rev_conclude(
    project_id: uuid.UUID,
    rid: uuid.UUID,
    body: Conclude,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(svc.conclude_review(project_id, rid, body.outcome, actor_id=_uid(user_id))),
    )


@router.get("/projects/{project_id}/reviews/{rid}/comments", dependencies=[READ])
async def rev_comments(
    project_id: uuid.UUID, rid: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    review = await _run(svc._get(DesignReview, project_id, rid, "review_not_found"))
    return _page(
        [await _row(svc, _caller(user_id, payload), c) for c in await svc.review_comments(project_id, review.id)]
    )


@router.post("/projects/{project_id}/reviews/{rid}/comments", status_code=201, dependencies=[EDIT])
async def rev_comment_add(
    project_id: uuid.UUID,
    rid: uuid.UUID,
    body: CommentIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(svc.add_comment(project_id, rid, dump(body) | {"text": body.text}, actor_id=_uid(user_id))),
    )


@router.post("/projects/{project_id}/comments/{cid}/transition", dependencies=[EDIT])
async def comment_move(
    project_id: uuid.UUID,
    cid: uuid.UUID,
    body: CommentMove,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(
        svc.comment_transition(
            project_id, cid, body.target, actor_id=_uid(user_id), answer=body.answer, role_id=body.role_id
        )
    )
    return await _row(svc, _caller(user_id, payload), row)


# ── reports ────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/reports", dependencies=[READ])
async def rpt_list(
    project_id: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    rows = await svc._list(DesignReport, project_id, DesignReport.code)
    return _page([await _row(svc, _caller(user_id, payload), r) for r in rows])


@router.post("/projects/{project_id}/reports", status_code=201, dependencies=[EDIT])
async def rpt_create(
    project_id: uuid.UUID, body: ReportIn, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    data = dump(body)
    _require(data, "kind_code")
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc, _caller(user_id, payload), await _run(svc.create_report(project_id, data, actor_id=_uid(user_id)))
    )


@router.patch("/projects/{project_id}/reports/{rid}", dependencies=[EDIT])
async def rpt_patch(
    project_id: uuid.UUID,
    rid: uuid.UUID,
    body: ReportIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(
        svc.patch_report(project_id, rid, dump(body), actor_id=_uid(user_id), may_manage=_may(payload, "design.manage"))
    )
    return await _row(svc, _caller(user_id, payload), row)


@router.post("/projects/{project_id}/reports/{rid}/transition", dependencies=[EDIT])
async def rpt_transition(
    project_id: uuid.UUID,
    rid: uuid.UUID,
    body: Transition,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(
        svc.report_transition(project_id, rid, body.target, actor_id=_uid(user_id), rationale=body.rationale)
    )
    return await _row(svc, _caller(user_id, payload), row)


@router.post("/projects/{project_id}/reports/{rid}/sync", dependencies=[EDIT])
async def rpt_sync(
    project_id: uuid.UUID, rid: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc, _caller(user_id, payload), await _run(svc.sync_report(project_id, rid, actor_id=_uid(user_id)))
    )


# ── permits ────────────────────────────────────────────────────────────────


async def _permit_out(
    svc: DesignService, project_id: uuid.UUID, permit: DesignPermit, caller: Caller
) -> dict[str, Any]:
    checks = await svc.permit_check(project_id, permit)
    items = [
        _out(c["item"], present=c["present"], state_ok=c["state_ok"], current_revision_id=c["current_revision_id"])
        for c in checks
    ]
    missing = [i["id"] for i in items if i["required"] and not i["state_ok"]]
    return await _row(svc, caller, permit, items=items, missing=missing)


@router.get("/projects/{project_id}/permits", dependencies=[READ])
async def permit_list(
    project_id: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    rows = await svc._list(DesignPermit, project_id, DesignPermit.code)
    return _page([await _permit_out(svc, project_id, p, _caller(user_id, payload)) for p in rows])


@router.post("/projects/{project_id}/permits", status_code=201, dependencies=[EDIT])
async def permit_create(
    project_id: uuid.UUID, body: PermitIn, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    data = dump(body)
    _require(data, "profile_code")
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc.create_permit(project_id, data, actor_id=_uid(user_id)))
    return await _permit_out(svc, project_id, row, _caller(user_id, payload))


@router.get("/projects/{project_id}/permits/{pid}", dependencies=[READ])
async def permit_get(
    project_id: uuid.UUID, pid: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc._get(DesignPermit, project_id, pid, "permit_not_found"))
    return await _permit_out(svc, project_id, row, _caller(user_id, payload))


@router.patch("/projects/{project_id}/permits/{pid}", dependencies=[EDIT])
async def permit_patch(
    project_id: uuid.UUID,
    pid: uuid.UUID,
    body: PermitIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(
        svc.patch_permit(project_id, pid, dump(body), actor_id=_uid(user_id), may_manage=_may(payload, "design.manage"))
    )
    return await _permit_out(svc, project_id, row, _caller(user_id, payload))


@router.post("/projects/{project_id}/permits/{pid}/items", status_code=201, dependencies=[EDIT])
async def permit_item_add(
    project_id: uuid.UUID,
    pid: uuid.UUID,
    body: PermitItemIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _row(
        svc,
        _caller(user_id, payload),
        await _run(svc.add_permit_item(project_id, pid, dump(body) | {"kind": body.kind}, actor_id=_uid(user_id))),
    )


@router.delete("/projects/{project_id}/permits/{pid}/items/{item_id}", status_code=204, dependencies=[EDIT])
async def permit_item_remove(
    project_id: uuid.UUID, pid: uuid.UUID, item_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    await _run(svc.remove_permit_item(project_id, pid, item_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


@router.post("/projects/{project_id}/permits/{pid}/transition", dependencies=[EDIT])
async def permit_transition(
    project_id: uuid.UUID,
    pid: uuid.UUID,
    body: Transition,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(
        svc.permit_transition(
            project_id, pid, body.target, actor_id=_uid(user_id), may_manage=_may(payload, "design.manage")
        )
    )
    return await _permit_out(svc, project_id, row, _caller(user_id, payload))


@router.post("/projects/{project_id}/permits/{pid}/sync", dependencies=[EDIT])
async def permit_sync(
    project_id: uuid.UUID, pid: uuid.UUID, user_id: CurrentUserId, payload: CurrentUserPayload, session: SessionDep
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(svc.sync_permit(project_id, pid, actor_id=_uid(user_id)))
    return await _permit_out(svc, project_id, row, _caller(user_id, payload))


@router.post("/projects/{project_id}/permits/{pid}/conditions", dependencies=[EDIT])
async def permit_conditions(
    project_id: uuid.UUID,
    pid: uuid.UUID,
    body: ConditionsIn,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    texts = [c.model_dump(mode="json") for c in body.conditions]
    row = await _run(svc.propose_conditions(project_id, pid, texts, actor_id=_uid(user_id)))
    return await _permit_out(svc, project_id, row, _caller(user_id, payload))


@router.post("/projects/{project_id}/permits/{pid}/conditions/{condition_id}", dependencies=[MANAGE])
async def permit_condition_decide(
    project_id: uuid.UUID,
    pid: uuid.UUID,
    condition_id: uuid.UUID,
    body: ConditionDecision,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
):
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    row = await _run(
        svc.confirm_condition(project_id, pid, str(condition_id), confirm=body.confirm, actor_id=_uid(user_id))
    )
    return await _permit_out(svc, project_id, row, _caller(user_id, payload))


@router.get("/projects/{project_id}/options/{kind}", dependencies=[READ])
async def reference_options(
    project_id: uuid.UUID,
    kind: Literal[
        "contacts",
        "contract_packages",
        "governance_gates",
        "recipient_lists",
        "review_cycles",
        "authority_submissions",
        "forms",
        "wbs_nodes",
    ],
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    """What a reference field may point at, filtered the way the write checks it."""
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    return await _run(svc.options(project_id, kind, actor_id=_uid(user_id), tenant_id=resolve_tenant_id(payload)))


# ── readiness, validation, export, frame documents ─────────────────────────


@router.get("/projects/{project_id}/readiness", dependencies=[READ])
async def readiness(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    out = []
    # Without a phase model there is one row for the whole project, under no phase.
    whole = [{"code": None, "order": 0, "spine_key": None, "name": None}]
    for phase in await _run(svc.phases(project_id)) or whole:
        b = await _run(svc.readiness(project_id, phase["code"]))
        out.append(
            {
                **phase,
                "met": b.met,
                "open_deliverables": b.deliverables,
                "open_reports": b.reports,
                "open_major_comments": b.major_comments,
            }
        )
    return _page(out)


@router.get("/projects/{project_id}/validation", dependencies=[READ])
async def validation(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext, rule_registry
    from app.modules.design_management.validators import DESIGN_RULE_SET

    await verify_project_access(project_id, user_id, session)

    svc = DesignService(session)
    payload = await _run(svc.validation_payload(project_id))
    context = ValidationContext(data=payload, metadata={"locale": get_locale() or "en"})
    results = []
    for rule in rule_registry.get_rules_for_sets([DESIGN_RULE_SET]):
        for r in await rule.validate(context):
            results.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(getattr(r.severity, "value", r.severity)),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
            )
    return _page(results)


async def _export_rows(svc: DesignService, project_id: uuid.UUID, register: str, locale: str) -> list[list[Any]]:
    def t(key: str) -> str:
        return translate(key, locale=locale)

    if register == "register":
        rows = []
        for e in await svc.register(project_id):
            c, d, last = e["container"], e["drawing"], e["last_issue"] or {}
            rows.append(
                [
                    c.container_code,
                    d.title or c.title,
                    e["revision_code"] or "",
                    c.suitability_code or "",
                    t(f"design.cde_state.{c.cde_state}"),
                    d.phase_code or "",
                    c.discipline_code or "",
                    (last.get("at") or "")[:10],
                    ", ".join(last.get("recipients") or []),
                ]
            )
        return rows
    if register == "matrix":
        return [
            [
                svc._recipient_key(r),
                ", ".join(r.discipline_codes or []),
                ", ".join(r.form_codes or []),
                ", ".join(r.phase_codes or []),
                r.min_suitability or "",
                t(f"design.purpose.{r.purpose}") if r.purpose else "",
                r.format,
                r.copies_paper,
            ]
            for r in await svc._list(DesignDistributionRule, project_id)
            if r.active
        ]
    if register == "reports":
        return [
            [
                r.code,
                t(f"design.catalogue.report.{r.kind_code}"),
                r.title,
                r.phase_code or "",
                t(f"design.independent_check.{r.independent_check}"),
                t(f"design.report_state.{r.status}"),
            ]
            for r in await svc._list(DesignReport, project_id, DesignReport.code)
        ]
    rows = []
    for p in await svc._list(DesignPermit, project_id, DesignPermit.code):
        for c in await svc.permit_check(project_id, p):
            item = c["item"]
            rows.append(
                [
                    t(f"design.permit_item.{item.kind}"),
                    f"{p.code}: {item.title}",
                    t("design.export.yes") if item.required else "",
                    t("design.export.yes") if c["state_ok"] else "",
                    str(item.included_revision_id or ""),
                ]
            )
    return rows


@router.get("/projects/{project_id}/export", dependencies=[READ])
async def export(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    register: Literal["register", "matrix", "reports", "permit"] = "register",
    format: Literal["pdf", "xlsx"] = "pdf",
) -> Response:
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    locale = get_locale() or "en"
    project = await _run(svc._project(project_id))
    data = dx.render(
        register,
        await _run(_export_rows(svc, project_id, register, locale)),
        project_name=project.name,
        locale=locale,
        fmt=format,
    )
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "application/pdf"
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="design_{register}_{stamp}.{format}"',
            # The labels were written in ``locale``; say so, or the reader's request language is assumed.
            "Content-Language": locale,
        },
    )


@router.post("/projects/{project_id}/frame-documents/{register}", dependencies=[MANAGE])
async def frame_document(
    project_id: uuid.UUID,
    register: Literal["register", "matrix", "reports", "permit"],
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    """Rule 23: write the register as a CDE revision of the design area's frame document."""
    await verify_project_access(project_id, user_id, session)
    svc = DesignService(session)
    locale = get_locale() or "en"
    project = await _run(svc._project(project_id))
    data = dx.render(
        register,
        await _run(_export_rows(svc, project_id, register, locale)),
        project_name=project.name,
        locale=locale,
        fmt="pdf",
    )
    return await _run(
        svc.generate_frame_document(
            project_id,
            register,
            actor_id=_uid(user_id),
            file_bytes=data,
            file_name=f"design_{register}.pdf",
            governance_manager=_may(payload, "governance.manage"),
        )
    )
