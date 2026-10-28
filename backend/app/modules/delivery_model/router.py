# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Delivery model API, mounted at ``/api/v1/delivery-model``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are looked up by
``(project_id, id)`` and linked procurement rows are checked against the
project, so an id from another project is also 404.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``delivery_model.errors.<code>``. 404 = not
found or not visible, 403 = permission, 409 = state conflict (model not
editable, decision pending, change request required), 422 = invalid input or
a refusing rule (single option, weights, impacted packages without disposition).

There is no approve route: the governance gate on the contracts area approves
the decision (lead decision 2), and this module mirrors it.

Tenant delivery-forms catalogues are created, edited and published through the
governance catalogue API with ``kind=delivery_forms``; this router only lists
what a project may pin.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.delivery_model.catalogue import DELIVERY_FORMS_KIND
from app.modules.delivery_model.errors import DeliveryModelError
from app.modules.delivery_model.messages import available_locales, translate, with_label_texts
from app.modules.delivery_model.schemas import (
    AllocationPut,
    CatalogueChange,
    ConfirmIn,
    ContractItemIn,
    ContractItemPatch,
    FindingOut,
    ModelPatch,
    ModelSet,
    OfiIn,
    OfiPatch,
    OfiRouteIn,
    OfiStatusIn,
    OptionIn,
    OptionPatch,
    PackageIn,
    PackageLinkIn,
    PackagePatch,
    PackageStatusIn,
    Page,
    ProposeIn,
    ReopenIn,
    ScoresPut,
    SeedRisksIn,
    WeightsPatch,
)
from app.modules.delivery_model.service import DeliveryModelService

router = APIRouter(tags=["delivery_model"])

_P = "/projects/{project_id}"
_EDIT, _MANAGE = "delivery_model.edit", "delivery_model.manage"


def _has(payload: dict[str, Any], permission: str) -> bool:
    """Does the caller hold ``permission``? The same answer :class:`RequirePermission` gives."""
    from app.core.permissions import permission_registry

    if permission in (payload.get("permissions") or []):
        return True
    return permission_registry.role_has_permission(payload.get("role", ""), permission)


async def _edit_denied(project_id: uuid.UUID, payload: dict[str, Any], session: Any) -> str | None:
    """Why the caller may not edit the plan, or ``None``.

    SPEC section 6: the plan is edited by a manager or by the owner (or deputy)
    of the area that hosts it. The same answer refuses the request and fills
    ``can.edit`` on the model.
    """
    if not _has(payload, _EDIT):
        return "permission_missing"
    if _has(payload, _MANAGE):
        return None
    owner = await DeliveryModelService(session).is_carrier_area_owner(project_id, _uid(payload.get("sub", "")))
    return None if owner else "not_area_owner"


async def _require_editor(project_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload) -> None:
    denied = await _edit_denied(project_id, payload, session)
    if denied == "permission_missing":
        raise HTTPException(status_code=403, detail=f"Missing permission: {_EDIT}")
    if denied is not None:
        err = DeliveryModelError(denied, 403)
        message = translate(f"delivery_model.errors.{denied}", locale=get_locale() or "en")
        raise HTTPException(status_code=403, detail=err.as_detail(message))


READ = Depends(RequirePermission("delivery_model.read"))
EDIT = Depends(_require_editor)
MANAGE = Depends(RequirePermission(_MANAGE))
# Seeding writes into the risk register: the register's own permission is needed as well.
RISK_CREATE = Depends(RequirePermission("risk.create"))


async def _run[T](awaitable: Any) -> T:
    """Turn a :class:`DeliveryModelError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except DeliveryModelError as exc:
        message = translate(f"delivery_model.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = DeliveryModelError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"delivery_model.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(user_id))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid subject") from exc


async def _model_out(svc: DeliveryModelService, project_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    """The model view with the caller's ``can`` flags, computed by the functions that enforce them."""
    denied = await _edit_denied(project_id, payload, svc.session)
    return await _run(
        svc.model_view(
            project_id,
            can_edit=denied is None,
            can_manage=_has(payload, _MANAGE),
            edit_denied=denied or "permission_missing",
            actor_id=_uid(str(payload.get("sub"))) if payload.get("sub") else None,
        )
    )


def _page(items: list[Any], **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": len(items), "offset": 0, "limit": len(items), **extra}


async def _delivery_svc(project_id: uuid.UUID, user_id: str, session: Any) -> DeliveryModelService:
    await verify_project_access(project_id, user_id, session)
    return DeliveryModelService(session)


# ── catalogues (what a project may pin) ────────────────────────────────────


@router.get("/catalogues", response_model=Page[dict[str, Any]], dependencies=[READ])
async def list_catalogues(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Shipped delivery-forms catalogues and the caller's tenant ones, through the one governance resolver."""
    from app.modules.project_governance.catalogue_store import CatalogueStore

    DeliveryModelService(session)  # registers the kind
    items = await _run(CatalogueStore(session).list_available(resolve_tenant_id(payload), kind=DELIVERY_FORMS_KIND))
    return _page(items)


@router.get(_P + "/catalogue", dependencies=[READ])
async def pinned_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The full body of the catalogue the project pins (forms, parties, categories, criteria, templates)."""
    svc = await _delivery_svc(project_id, user_id, session)
    model = await _run(svc.require_model(project_id))
    body = (await _run(svc.catalogue_for(model))).model_dump(mode="json")
    return with_label_texts(body, get_locale() or "en")


# ── model ──────────────────────────────────────────────────────────────────


@router.get(_P + "/model", dependencies=[READ])
async def get_model(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    return await _model_out(svc, project_id, payload)


@router.put(_P + "/model", status_code=201, dependencies=[MANAGE])
async def set_model(
    project_id: uuid.UUID, body: ModelSet, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(
        svc.set_model(
            project_id,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
            catalogue_source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            catalogue_version=body.catalogue_version,
        )
    )
    return await _model_out(svc, project_id, payload)


@router.patch(_P + "/model", dependencies=[EDIT])
async def patch_model(
    project_id: uuid.UUID, body: ModelPatch, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(
        svc.patch_model(
            project_id,
            actor_id=_uid(user_id),
            underground_risk_sharing=body.underground_risk_sharing,
            owner_capability=body.owner_capability.model_dump() if body.owner_capability else None,
        )
    )
    return await _model_out(svc, project_id, payload)


@router.post(_P + "/model/catalogue", dependencies=[MANAGE])
async def change_catalogue(
    project_id: uuid.UUID,
    body: CatalogueChange,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(
        svc.change_catalogue(
            project_id,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
            catalogue_source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            catalogue_version=body.catalogue_version,
            form_mapping=body.form_mapping,
            category_mapping=body.category_mapping,
        )
    )
    return await _model_out(svc, project_id, payload)


@router.post(_P + "/model/reopen/close", dependencies=[MANAGE])
async def close_reopening(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Give up a reopening: back to ``binding`` with the approved decision and its allocations in force."""
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.close_reopening(project_id, _uid(user_id)))
    return await _model_out(svc, project_id, payload)


@router.post(_P + "/model/reopen", dependencies=[MANAGE])
async def reopen(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    body: ReopenIn | None = None,
) -> dict[str, Any]:
    """Binding -> reopened.

    With gates: while a governance change request on the frame document is
    open. Without gates: with a ``reason`` in the body, which is recorded.
    """
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.reopen(project_id, _uid(user_id), body.reason if body else None))
    return await _model_out(svc, project_id, payload)


# ── comparison ─────────────────────────────────────────────────────────────


@router.get(_P + "/comparison", dependencies=[READ])
async def comparison(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    return await _run(svc.comparison(project_id))


@router.get(_P + "/options", dependencies=[READ])
async def list_options(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    return _page((await _run(svc.comparison(project_id)))["options"])


@router.post(_P + "/options", status_code=201, dependencies=[EDIT])
async def add_option(
    project_id: uuid.UUID, body: OptionIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    row = await _run(
        svc.add_option(project_id, body.form_code, overrides=body.overrides, notes=body.notes, actor_id=_uid(user_id))
    )
    return {"id": str(row.id), "form_code": row.form_code, "overrides": row.overrides, "notes": row.notes}


@router.patch(_P + "/options/{option_id}", dependencies=[EDIT])
async def update_option(
    project_id: uuid.UUID, option_id: uuid.UUID, body: OptionPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    row = await _run(svc.update_option(project_id, option_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return {"id": str(row.id), "form_code": row.form_code, "overrides": row.overrides, "notes": row.notes}


@router.delete(_P + "/options/{option_id}", status_code=204, dependencies=[EDIT])
async def delete_option(
    project_id: uuid.UUID, option_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.delete_option(project_id, option_id, _uid(user_id)))
    return Response(status_code=204)


@router.get(_P + "/criteria", dependencies=[READ])
async def list_criteria(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    cmp = await _run(svc.comparison(project_id))
    return _page(cmp["criteria"], weights_total=cmp["weights_total"])


@router.patch(_P + "/criteria", dependencies=[EDIT])
async def patch_weights(
    project_id: uuid.UUID, body: WeightsPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.patch_weights(project_id, body.weights, _uid(user_id)))
    cmp = await _run(svc.comparison(project_id))
    return _page(cmp["criteria"], weights_total=cmp["weights_total"])


@router.put(_P + "/scores", dependencies=[EDIT])
async def put_scores(
    project_id: uuid.UUID, body: ScoresPut, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.put_scores(project_id, [s.model_dump() for s in body.scores], _uid(user_id)))
    return await _run(svc.comparison(project_id))


@router.post(_P + "/scores/prefill", dependencies=[EDIT])
async def prefill_scores(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Copy catalogue default scores into empty cells (a suggestion the user then edits)."""
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.prefill_scores(project_id, _uid(user_id)))
    return await _run(svc.comparison(project_id))


# ── decision ───────────────────────────────────────────────────────────────


@router.post(_P + "/decision", status_code=201, dependencies=[MANAGE])
async def propose(
    project_id: uuid.UUID, body: ProposeIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    row = await _run(
        svc.propose(
            project_id,
            option_id=body.option_id,
            rationale=body.rationale,
            owner_capability=body.owner_capability.model_dump() if body.owner_capability else None,
            dispositions=dict(body.dispositions),
            actor_id=_uid(user_id),
        )
    )
    return next(d for d in await svc.decision_views(project_id) if d["id"] == str(row.id))


@router.post(_P + "/decision/approve", dependencies=[MANAGE])
async def approve(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Approve the proposed decision by hand, on a project without gates only.

    Where the project has gates the gate decision approves: this answers 409
    ``approved_by_gate_decision`` and the model's ``can.approve`` says it does not apply.
    """
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.approve_by_hand(project_id, _uid(user_id)))
    return await _model_out(svc, project_id, payload)


@router.post(_P + "/decision/withdraw", dependencies=[MANAGE])
async def withdraw(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.withdraw(project_id, _uid(user_id)))
    return await _model_out(svc, project_id, payload)


@router.get(_P + "/decision", dependencies=[READ])
async def current_decision(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    current = next((d for d in await svc.decision_views(project_id) if d["is_current"]), None)
    if current is None:
        raise HTTPException(
            status_code=404,
            detail=DeliveryModelError("decision_missing", 404).as_detail(
                translate("delivery_model.errors.decision_missing", locale=get_locale() or "en")
            ),
        )
    return current


@router.get(_P + "/decisions", dependencies=[READ])
async def decision_history(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    return _page(await svc.decision_views(project_id))


# ── allocations ────────────────────────────────────────────────────────────


@router.get(_P + "/allocations", dependencies=[READ])
async def allocation_matrix(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    return await _run(svc.allocation_matrix(project_id))


@router.put(_P + "/allocations/{category_code}", dependencies=[EDIT])
async def put_allocation(
    project_id: uuid.UUID, category_code: str, body: AllocationPut, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.put_allocation(project_id, category_code, body.model_dump(), _uid(user_id)))
    return await _run(svc.allocation_matrix(project_id))


@router.post(_P + "/allocations/confirm", dependencies=[EDIT])
async def confirm_allocations(
    project_id: uuid.UUID, body: ConfirmIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.confirm_allocations(project_id, body.categories, _uid(user_id)))
    return await _run(svc.allocation_matrix(project_id))


@router.post(_P + "/allocations/seed-risks", dependencies=[EDIT, RISK_CREATE])
async def seed_risks(
    project_id: uuid.UUID, body: SeedRisksIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Preview (default) or create register entries for confirmed allocations without a link."""
    svc = await _delivery_svc(project_id, user_id, session)
    items = await _run(
        svc.seed_risks(
            project_id, body.categories, preview=body.preview, actor_id=_uid(user_id), locale=get_locale() or "en"
        )
    )
    return _page(items, preview=body.preview)


# ── packages ───────────────────────────────────────────────────────────────


async def _package_out(svc: DeliveryModelService, project_id: uuid.UUID, package_id: uuid.UUID) -> dict[str, Any]:
    return next(p for p in await svc.package_views(project_id) if p["id"] == str(package_id))


@router.get(_P + "/packages", dependencies=[READ])
async def list_packages(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    designs: bool | None = None,
    builds: bool | None = None,
    supplies: bool | None = None,
) -> dict[str, Any]:
    """The package plan; the ``designs`` / ``builds`` / ``supplies`` filters answer "who does X" (rule 16)."""
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.require_model(project_id))
    return _page(await svc.responsibility(project_id, designs=designs, builds=builds, supplies=supplies))


@router.post(_P + "/packages", status_code=201, dependencies=[EDIT])
async def create_package(
    project_id: uuid.UUID, body: PackageIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    row = await _run(svc.create_package(project_id, body.model_dump(), _uid(user_id)))
    return await _package_out(svc, project_id, row.id)


@router.post(_P + "/packages/derive", dependencies=[EDIT])
async def derive_packages(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Create the chosen form's template packages that are not in the plan yet."""
    svc = await _delivery_svc(project_id, user_id, session)
    created = await _run(svc.derive_packages(project_id, _uid(user_id), locale=get_locale() or "en"))
    return _page(await svc.package_views(project_id), created=len(created))


@router.get(_P + "/packages/consistency", dependencies=[READ])
async def consistency(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    return await _run(svc.consistency(project_id))


@router.patch(_P + "/packages/{package_id}", dependencies=[EDIT])
async def update_package(
    project_id: uuid.UUID, package_id: uuid.UUID, body: PackagePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.update_package(project_id, package_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _package_out(svc, project_id, package_id)


@router.delete(_P + "/packages/{package_id}", status_code=204, dependencies=[EDIT])
async def delete_package(
    project_id: uuid.UUID, package_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.delete_package(project_id, package_id, _uid(user_id)))
    return Response(status_code=204)


@router.post(_P + "/packages/{package_id}/status", dependencies=[EDIT])
async def set_package_status(
    project_id: uuid.UUID, package_id: uuid.UUID, body: PackageStatusIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.set_package_status(project_id, package_id, body.status, _uid(user_id)))
    return await _package_out(svc, project_id, package_id)


@router.put(_P + "/packages/{package_id}/link", dependencies=[EDIT])
async def link_package(
    project_id: uuid.UUID, package_id: uuid.UUID, body: PackageLinkIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.link_package(project_id, package_id, body.link_kind, body.link_id, _uid(user_id)))
    return await _package_out(svc, project_id, package_id)


@router.delete(_P + "/packages/{package_id}/link", dependencies=[EDIT])
async def unlink_package(
    project_id: uuid.UUID, package_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.unlink_package(project_id, package_id, _uid(user_id)))
    return await _package_out(svc, project_id, package_id)


# ── owner-furnished items ──────────────────────────────────────────────────


async def _ofi_out(svc: DeliveryModelService, project_id: uuid.UUID, ofi_id: uuid.UUID) -> dict[str, Any]:
    return next(o for o in await svc.ofi_views(project_id) if o["id"] == str(ofi_id))


@router.get(_P + "/ofi", dependencies=[READ])
async def list_ofi(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    return _page(await _run(svc.ofi_views(project_id)))


@router.post(_P + "/ofi", status_code=201, dependencies=[EDIT])
async def create_ofi(project_id: uuid.UUID, body: OfiIn, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    row = await _run(svc.create_ofi(project_id, body.model_dump(), _uid(user_id)))
    return await _ofi_out(svc, project_id, row.id)


@router.patch(_P + "/ofi/{ofi_id}", dependencies=[EDIT])
async def update_ofi(
    project_id: uuid.UUID, ofi_id: uuid.UUID, body: OfiPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.update_ofi(project_id, ofi_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _ofi_out(svc, project_id, ofi_id)


@router.delete(_P + "/ofi/{ofi_id}", status_code=204, dependencies=[EDIT])
async def delete_ofi(project_id: uuid.UUID, ofi_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.delete_ofi(project_id, ofi_id, _uid(user_id)))
    return Response(status_code=204)


@router.put(_P + "/ofi/{ofi_id}/route", dependencies=[EDIT])
async def set_ofi_route(
    project_id: uuid.UUID, ofi_id: uuid.UUID, body: OfiRouteIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(
        svc.set_ofi_route(
            project_id,
            ofi_id,
            route=body.procurement_route,
            link_kind=body.link_kind,
            link_id=body.link_id,
            actor_id=_uid(user_id),
        )
    )
    return await _ofi_out(svc, project_id, ofi_id)


@router.post(_P + "/ofi/{ofi_id}/status", dependencies=[EDIT])
async def set_ofi_status(
    project_id: uuid.UUID, ofi_id: uuid.UUID, body: OfiStatusIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.set_ofi_status(project_id, ofi_id, body.status, _uid(user_id)))
    return await _ofi_out(svc, project_id, ofi_id)


# ── contract-side items (module 2) ─────────────────────────────────────────


async def _contract_item_out(svc: DeliveryModelService, project_id: uuid.UUID, item_id: uuid.UUID) -> dict[str, Any]:
    return next(i for i in await svc.contract_item_views(project_id) if i["id"] == str(item_id))


@router.get(_P + "/contract-items", dependencies=[READ])
async def list_contract_items(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    return _page(await _run(svc.contract_item_views(project_id)))


@router.post(_P + "/contract-items", status_code=201, dependencies=[EDIT])
async def create_contract_item(
    project_id: uuid.UUID, body: ContractItemIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    row = await _run(svc.create_contract_item(project_id, body.model_dump(), _uid(user_id)))
    return await _contract_item_out(svc, project_id, row.id)


@router.patch(_P + "/contract-items/{item_id}", dependencies=[EDIT])
async def update_contract_item(
    project_id: uuid.UUID, item_id: uuid.UUID, body: ContractItemPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.update_contract_item(project_id, item_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _contract_item_out(svc, project_id, item_id)


@router.delete(_P + "/contract-items/{item_id}", status_code=204, dependencies=[EDIT])
async def delete_contract_item(
    project_id: uuid.UUID, item_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    svc = await _delivery_svc(project_id, user_id, session)
    await _run(svc.delete_contract_item(project_id, item_id, _uid(user_id)))
    return Response(status_code=204)


# ── readiness, validation, export ──────────────────────────────────────────


@router.get(_P + "/readiness", dependencies=[READ])
async def readiness(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """What the governance gate reads for the contracts area (read only)."""
    svc = await _delivery_svc(project_id, user_id, session)
    return await _run(svc.readiness(project_id))


@router.get(_P + "/validation", response_model=Page[FindingOut], dependencies=[READ])
async def validation(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext
    from app.modules.delivery_model.validators import DELIVERY_RULES

    svc = await _delivery_svc(project_id, user_id, session)
    data = await _run(svc.validation_payload(project_id))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    findings: list[FindingOut] = []
    for rule_cls in DELIVERY_RULES:
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


@router.get(_P + "/export", dependencies=[READ])
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    what: Literal["decision", "matrix", "packages"] = "decision",
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
) -> Response:
    """Decision record, risk allocation matrix or package plan as PDF or XLSX."""
    from app.modules.delivery_model import export as ex
    from app.modules.projects.models import Project

    svc = await _delivery_svc(project_id, user_id, session)
    project = await session.get(Project, project_id)
    name = getattr(project, "name", "") or ""
    locale = get_locale() or "en"
    base = locale.split("-")[0].lower()
    written = locale if locale in available_locales() else base if base in available_locales() else "en"
    if what == "matrix":
        doc = ex.matrix_document(await _run(svc.allocation_matrix(project_id)), project_name=name, locale=locale)
    elif what == "packages":
        doc = ex.packages_document(await _run(svc.package_views(project_id)), project_name=name, locale=locale)
    else:
        cmp = await _run(svc.comparison(project_id))
        current = next((d for d in await svc.decision_views(project_id) if d["is_current"]), None)
        doc = ex.decision_document(cmp, current, project_name=name, locale=locale)
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=ex.render(doc, fmt),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="delivery_{what}.{fmt}"',
            # The language the document was written in, which is not always the one asked for.
            "Content-Language": written,
        },
    )
