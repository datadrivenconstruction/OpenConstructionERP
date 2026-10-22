# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement concept API, mounted at ``/api/v1/procurement-concept``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` first, so a project the caller cannot see answers 404
exactly like a missing one. Child rows (packages, candidates, soundings,
profiles) are looked up by ``(project_id, id)``: an id of another project is
404 too. Frameworks are tenant-level (``/frameworks``) and scoped to the
caller's tenant; another tenant's framework is 404.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail`` with ``message_key = procurement_concept.errors.<code>``.
404 = not found or not visible, 403 = visible but not allowed (not the
procurement owner), 409 = state conflict (plan locked, binding, execution
exists), 422 = invalid input or a refusing rule (``violations`` lists all).

There is no approve route: the governance gate on the frame document approves
the concept (Decision 10) and this module mirrors it. Who may steer is a
permission (``procurement_concept.manage``) or ownership of the governance
area that hosts procurement; the router resolves the permission and hands the
service a boolean, never a role name. Write routes take no client date.

Catalogue editing (clone, edit, publish) is module 1's, with
``kind=procurement_procedures``: ``/api/v1/project-governance/catalogues``.
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
from app.modules.procurement_concept import permit_conditions
from app.modules.procurement_concept.errors import ProcurementError
from app.modules.procurement_concept.messages import translate
from app.modules.procurement_concept.schemas import (
    CandidateIn,
    CandidatePatch,
    ConceptActionIn,
    ConceptSet,
    ExecutionIn,
    ExecutionLinkIn,
    FrameworkIn,
    FrameworkPatch,
    FrameworkStateIn,
    PackagePut,
    PackageStateIn,
    ProfileIn,
    ReferenceIn,
    RuleOverrideIn,
    ScheduleConfirm,
    ScoresPut,
    SoundingIn,
    SoundingPatch,
)
from app.modules.procurement_concept.service import ProcurementConceptService

router = APIRouter(tags=["procurement_concept"])

READ = Depends(RequirePermission("procurement_concept.read"))
EDIT = Depends(RequirePermission("procurement_concept.edit"))
MANAGE_PERMISSION = "procurement_concept.manage"
EDIT_PERMISSION = "procurement_concept.edit"
FRAMEWORKS_PERMISSION = "procurement_concept.frameworks.manage"
FRAMEWORKS = Depends(RequirePermission("procurement_concept.frameworks.manage"))


async def _run[T](awaitable: Awaitable[T]) -> T:
    """Turn a :class:`ProcurementError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except ProcurementError as exc:
        message = translate(f"procurement_concept.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = ProcurementError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"procurement_concept.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


async def _has(payload: dict[str, Any], permission: str) -> bool:
    """The caller's answer from the very dependency that guards the routes."""
    try:
        await RequirePermission(permission)(payload)
    except HTTPException:
        return False
    return True


async def _manage(payload: dict[str, Any]) -> bool:
    return await _has(payload, MANAGE_PERMISSION)


async def _access(
    svc: ProcurementConceptService, project_id: uuid.UUID, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """What this caller may do in the project; the lists hang their ``can`` flags on it."""
    return await svc.access(
        project_id,
        _uid(user_id),
        can_edit=await _has(payload, EDIT_PERMISSION),
        can_manage=await _manage(payload),
    )


def _jurisdictions_out(cat: Any) -> list[dict[str, Any]]:
    return [
        {
            "code": j.code,
            "name_key": j.name_key,
            "labels": j.labels,
            "client_types": list(j.client_types),
            "private_client_type": j.private_client_type,
        }
        for j in cat.jurisdictions
    ]


def _today(value: date | None) -> date:
    return value or datetime.now(UTC).date()


def _page(items: list[Any], **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": len(items), "offset": 0, "limit": len(items), **extra}


async def _concept_out(
    svc: ProcurementConceptService, project_id: uuid.UUID, user_id: str, can_manage: bool
) -> dict[str, Any]:
    c = await svc.get_concept(project_id)
    cat = await svc.catalogue_of(c)
    state = await svc.effective_state(c)
    gate = await svc.release_gate(project_id, c)
    hosting = await svc.hosting(project_id)
    return {
        "id": str(c.id),
        "project_id": str(project_id),
        "catalogue_source": c.catalogue_source,
        "catalogue_id": c.catalogue_id,
        "catalogue_version": c.catalogue_version,
        "jurisdiction": c.jurisdiction,
        "client_type": c.client_type,
        "public_client": c.public_client,
        "vat_rate_pct": format(c.vat_rate_pct, "f"),
        "state": state,
        "stored_state": c.state,
        "governance_document_id": str(c.governance_document_id) if c.governance_document_id else None,
        "release_gate_code": c.release_gate_code,
        # The gate actually used: the named one, else the one the governance catalogue tags; null = unresolved.
        "resolved_release_gate_code": gate.code if gate is not None else None,
        # True when the model opens procurement in its first phase and no gate is named: null above is then final.
        "released_from_start": await svc.released_from_start(project_id, c),
        # False on a project that never adopted a phase model: no gate is missing, gates are not used.
        "gates_in_use": await svc.gates_in_use(project_id),
        "governance_area_code": hosting.area_code,
        "default_profile_id": str(c.default_profile_id) if c.default_profile_id else None,
        "submitted_by": str(c.submitted_by) if c.submitted_by else None,
        "approved_by": str(c.approved_by) if c.approved_by else None,
        "approved_at": c.approved_at.isoformat() if c.approved_at else None,
        "four_eyes_violated": bool(c.approved_by and c.approved_by == c.submitted_by),
        "jurisdictions": _jurisdictions_out(cat),
        "review_status": cat.review_status.value,
        "can": await svc.capabilities(project_id, _uid(user_id), can_manage),
    }


# ── catalogue (read-only view of the pinned one) ─────────────────────────


@router.get("/catalogues", dependencies=[READ])
async def list_catalogues(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Shipped and own-tenant catalogues of kind ``procurement_procedures`` (editing lives in governance)."""
    from app.modules.procurement_concept.catalogue import PROCUREMENT_KIND, register_kind
    from app.modules.project_governance.catalogue_store import CatalogueStore, resolve_catalogue
    from app.modules.project_governance.errors import GovernanceError

    register_kind()
    tenant_id = resolve_tenant_id(payload)
    rows = await _run(CatalogueStore(session).list_available(tenant_id, kind=PROCUREMENT_KIND))
    for row in rows:
        # The concept form picks jurisdiction and client type from the catalogue it is about to pin.
        row["jurisdictions"] = []
        if row.get("latest_version") is None:
            continue  # a company catalogue with no published version cannot be pinned yet
        try:
            body = await resolve_catalogue(
                session, row["source"], row["id"], row["latest_version"], kind=PROCUREMENT_KIND, tenant_id=tenant_id
            )
        except GovernanceError:
            continue
        row["jurisdictions"] = _jurisdictions_out(body)
    return _page(rows)


@router.get("/projects/{project_id}/catalogue", dependencies=[READ])
async def pinned_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The pinned catalogue body (procedures, jurisdictions with thresholds and sources, criteria, lead times)."""
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    concept = await _run(svc.get_concept(project_id))
    cat = await _run(svc.catalogue_of(concept))
    return cat.model_dump(mode="json")


# ── concept ──────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/concept", dependencies=[READ])
async def get_concept(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _run(_concept_out(ProcurementConceptService(session), project_id, user_id, await _manage(payload)))


@router.put("/projects/{project_id}/concept", dependencies=[EDIT])
async def set_concept(
    project_id: uuid.UUID, body: ConceptSet, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Create or change the concept: catalogue pin, jurisdiction, client type, VAT basis, release gate."""
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    can_manage = await _manage(payload)
    await _run(
        svc.set_concept(
            project_id,
            body.model_dump(exclude_unset=True),
            actor_id=_uid(user_id),
            can_manage=can_manage,
            tenant_id=resolve_tenant_id(payload),
        )
    )
    return await _run(_concept_out(svc, project_id, user_id, can_manage))


_ACTIONS = {"submit": "in_review", "return": "draft"}


@router.post("/projects/{project_id}/concept/{action}", dependencies=[EDIT])
async def concept_action(
    project_id: uuid.UUID,
    action: Literal["submit", "return", "approve", "reopen"],
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    body: ConceptActionIn | None = None,
) -> dict[str, Any]:
    """Submit the concept, or take it back; approve or reopen it by hand on a project without gates.

    Where the project has gates the gate decision approves and a change request reopens: ``approve``
    and ``reopen`` are then refused with 409 and the concept's ``can`` says they do not apply.
    ``reopen`` takes ``{"reason": "..."}``, which is recorded; the other actions take no body.
    """
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    can_manage = await _manage(payload)
    if action == "approve":
        await _run(svc.approve_by_hand(project_id, actor_id=_uid(user_id), can_manage=can_manage))
    elif action == "reopen":
        reason = (body.reason if body is not None else None) or ""
        await _run(svc.reopen_by_hand(project_id, reason, actor_id=_uid(user_id), can_manage=can_manage))
    else:
        await _run(svc.transition(project_id, _ACTIONS[action], actor_id=_uid(user_id), can_manage=can_manage))
    return await _run(_concept_out(svc, project_id, user_id, can_manage))


@router.get("/projects/{project_id}/readiness", dependencies=[READ])
async def readiness(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _run(ProcurementConceptService(session).readiness(project_id))


@router.get("/projects/{project_id}/findings", dependencies=[READ])
async def findings(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    """Every rule finding (``code``, ``severity``, ``ref``, ``blocks_approval``, ``message_key``)."""
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(ProcurementConceptService(session).findings(project_id, today=_today(today))))


# ── packages ─────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/packages", dependencies=[READ])
async def list_packages(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    """The package board: mod3 ContractPackages joined with award attributes, threshold badge, schedule.

    Every row carries ``can`` (edit, set_advance, hold, resume, cancel, confirm_shortlist, create_execution), each
    ``{allowed, reason}`` from the checks the writes enforce.
    """
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    access = await _run(_access(svc, project_id, user_id, payload))
    return _page(await _run(svc.package_views(project_id, today=_today(today), access=access)))


@router.get("/projects/{project_id}/permit-conditions", dependencies=[READ])
async def list_permit_conditions(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Permit conditions of module 2 as requirements every open lot inherits (read only)."""
    await verify_project_access(project_id, user_id, session)
    return await permit_conditions.load(session, project_id)


@router.get("/projects/{project_id}/gates", dependencies=[READ])
async def list_gates(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The project's governance gates, for choosing the gate that releases procurement."""
    await verify_project_access(project_id, user_id, session)
    data = await _run(ProcurementConceptService(session).gate_options(project_id))
    return _page(
        data["items"],
        release_gate_code=data["release_gate_code"],
        resolved_release_gate_code=data["resolved_release_gate_code"],
        released_from_start=data["released_from_start"],
        gates_in_use=data["gates_in_use"],
    )


@router.get("/projects/{project_id}/advance-releases", dependencies=[READ])
async def list_advance_releases(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """What an advance package may name as its release: acts of the release gate and released commitments."""
    await verify_project_access(project_id, user_id, session)
    data = await _run(ProcurementConceptService(session).advance_release_options(project_id))
    return _page(data["items"], commitments=data["commitments"])


@router.get("/projects/{project_id}/tender-packages", dependencies=[READ])
async def list_tender_packages(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Tender packages of this project that ``execution/link`` can take."""
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(ProcurementConceptService(session).tender_package_options(project_id)))


@router.get("/projects/{project_id}/cost-refs", dependencies=[READ])
async def list_cost_refs(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Bill of quantities sections of this project a package may name as ``cost_ref_kind`` + ``cost_ref_id``."""
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(ProcurementConceptService(session).cost_reference_options(project_id)))


@router.put("/projects/{project_id}/packages/{package_id}", dependencies=[EDIT])
async def put_package(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    body: PackagePut,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    row = await _run(
        svc.put_package(
            project_id,
            package_id,
            body.model_dump(exclude_unset=True),
            actor_id=_uid(user_id),
            can_manage=await _manage(payload),
            tenant_id=resolve_tenant_id(payload),
        )
    )
    return svc._award_out(row)


@router.post("/projects/{project_id}/packages/{package_id}/state", dependencies=[EDIT])
async def package_state(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    body: PackageStateIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Hold, resume or cancel. ``in_tender`` / ``awarded`` are read back from execution, never set here."""
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    row = await _run(
        svc.set_package_state(
            project_id, package_id, body.action, actor_id=_uid(user_id), can_manage=await _manage(payload)
        )
    )
    return svc._award_out(row)


@router.get("/projects/{project_id}/packages/{package_id}/threshold", dependencies=[READ])
async def threshold_check(
    project_id: uuid.UUID, package_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    """Threshold explanation with sources and the procedure picker (allowed + reason per procedure)."""
    await verify_project_access(project_id, user_id, session)
    return await _run(ProcurementConceptService(session).threshold_check(project_id, package_id, today=_today(today)))


@router.get("/projects/{project_id}/packages/{package_id}/rule-snapshots", dependencies=[READ])
async def rule_snapshots(
    project_id: uuid.UUID, package_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Frozen records of the rules each procedure of the package was set under, with their overrides."""
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(ProcurementConceptService(session).rule_snapshots(project_id, package_id)))


@router.post(
    "/projects/{project_id}/packages/{package_id}/rule-snapshots/{snapshot_id}/overrides",
    status_code=201,
    dependencies=[EDIT],
)
async def override_rule(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    body: RuleOverrideIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Override one rule outcome of a snapshot; a reason is required and the snapshot itself is not changed."""
    await verify_project_access(project_id, user_id, session)
    return await _run(
        ProcurementConceptService(session).override_rule(
            project_id,
            package_id,
            snapshot_id,
            body.model_dump(),
            actor_id=_uid(user_id),
            can_manage=await _manage(payload),
        )
    )


@router.get("/projects/{project_id}/consistency", dependencies=[READ])
async def consistency(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(ProcurementConceptService(session).consistency_report(project_id)))


@router.post("/projects/{project_id}/packages/{package_id}/execution", status_code=201, dependencies=[EDIT])
async def create_execution(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    body: ExecutionIn | None = None,
) -> dict[str, Any]:
    """Create ONE bid package (works, design, services) or ONE RFQ (supply) and link it to the package."""
    await verify_project_access(project_id, user_id, session)
    body = body or ExecutionIn()
    return await _run(
        ProcurementConceptService(session).create_execution(
            project_id,
            package_id,
            vehicle=body.vehicle,
            submission_deadline=body.submission_deadline,
            actor_id=_uid(user_id),
            can_manage=await _manage(payload),
        )
    )


@router.post("/projects/{project_id}/packages/{package_id}/execution/link", status_code=201, dependencies=[EDIT])
async def link_execution(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    body: ExecutionLinkIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Link an existing tender package of this project as the execution vehicle (nothing is created)."""
    await verify_project_access(project_id, user_id, session)
    return await _run(
        ProcurementConceptService(session).link_tender_package(
            project_id,
            package_id,
            body.tender_package_id,
            actor_id=_uid(user_id),
            can_manage=await _manage(payload),
        )
    )


@router.get("/projects/{project_id}/frameworks", dependencies=[READ])
async def project_frameworks(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Framework agreements a package of this project may call off (the project's company's and the caller's)."""
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    rows = await _run(svc.project_frameworks(project_id, resolve_tenant_id(payload)))
    return _page(await _frameworks_out(svc, rows, payload))


# ── prequalification ─────────────────────────────────────────────────────


def _profile_out(p: Any) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "package_id": str(p.package_id) if p.package_id else None,
        "name": p.name,
        "criteria": p.criteria,
        "pass_mark": format(p.pass_mark, "f"),
        "validity_months": p.validity_months,
    }


@router.get("/projects/{project_id}/prequal-profiles", dependencies=[READ])
async def list_profiles(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Profiles, each with ``in_use`` and ``can`` (edit, delete); the list carries ``can.create``."""
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    access = await _run(_access(svc, project_id, user_id, payload))
    items, can = await _run(svc.profile_views(project_id, access))
    return _page(
        [
            {**_profile_out(p), "in_use": flags["delete"]["reason"] == "profile_in_use", "can": flags}
            for p, flags in items
        ],
        can=can,
    )


@router.post("/projects/{project_id}/prequal-profiles", status_code=201, dependencies=[EDIT])
async def create_profile(
    project_id: uuid.UUID, body: ProfileIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        ProcurementConceptService(session).save_profile(
            project_id, body.model_dump(), actor_id=_uid(user_id), can_manage=await _manage(payload)
        )
    )
    return _profile_out(row)


@router.put("/projects/{project_id}/prequal-profiles/{profile_id}", dependencies=[EDIT])
async def update_profile(
    project_id: uuid.UUID,
    profile_id: uuid.UUID,
    body: ProfileIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        ProcurementConceptService(session).save_profile(
            project_id,
            body.model_dump(),
            actor_id=_uid(user_id),
            can_manage=await _manage(payload),
            profile_id=profile_id,
        )
    )
    return _profile_out(row)


@router.delete("/projects/{project_id}/prequal-profiles/{profile_id}", status_code=204, dependencies=[EDIT])
async def delete_profile(
    project_id: uuid.UUID,
    profile_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(
        ProcurementConceptService(session).delete_profile(
            project_id, profile_id, actor_id=_uid(user_id), can_manage=await _manage(payload)
        )
    )
    return Response(status_code=204)


@router.get("/projects/{project_id}/packages/{package_id}/candidates", dependencies=[READ])
async def list_candidates(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Candidate matrix: totals, evidence chips, references, the shortlist findings, and ``can``."""
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    data = await _run(svc.candidate_views(project_id, package_id))
    access = await _run(_access(svc, project_id, user_id, payload))
    return {**data, "offset": 0, "limit": data["total"], "can": await svc.shortlist_can(data, access)}


@router.post("/projects/{project_id}/packages/{package_id}/candidates", status_code=201, dependencies=[EDIT])
async def add_candidate(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    body: CandidateIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Add a candidate. Putting it straight on the short or excluded list needs steering rights."""
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        ProcurementConceptService(session).add_candidate(
            project_id, package_id, body.model_dump(), actor_id=_uid(user_id), can_manage=await _manage(payload)
        )
    )
    return {"id": str(row.id), "list": row.list_kind}


@router.patch("/projects/{project_id}/candidates/{candidate_id}", dependencies=[EDIT])
async def patch_candidate(
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: CandidatePatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Change a candidate. Moving it between the long, short and excluded lists needs steering rights."""
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        ProcurementConceptService(session).patch_candidate(
            project_id,
            candidate_id,
            body.model_dump(exclude_unset=True),
            actor_id=_uid(user_id),
            can_manage=await _manage(payload),
        )
    )
    return {"id": str(row.id), "list": row.list_kind}


@router.delete("/projects/{project_id}/candidates/{candidate_id}", status_code=204, dependencies=[EDIT])
async def delete_candidate(
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    """Remove a candidate (steering rights: it decides who may bid)."""
    await verify_project_access(project_id, user_id, session)
    await _run(
        ProcurementConceptService(session).delete_candidate(
            project_id, candidate_id, actor_id=_uid(user_id), can_manage=await _manage(payload)
        )
    )
    return Response(status_code=204)


@router.put("/projects/{project_id}/candidates/{candidate_id}/scores", dependencies=[EDIT])
async def put_scores(
    project_id: uuid.UUID, candidate_id: uuid.UUID, body: ScoresPut, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    rows = await _run(
        ProcurementConceptService(session).put_scores(
            project_id, candidate_id, [s.model_dump() for s in body.scores], actor_id=_uid(user_id)
        )
    )
    return _page(
        [
            {"criterion_code": r.criterion_code, "passed": r.passed, "score": None if r.score is None else str(r.score)}
            for r in rows
        ]
    )


@router.post("/projects/{project_id}/candidates/{candidate_id}/references", status_code=201, dependencies=[EDIT])
async def add_reference(
    project_id: uuid.UUID, candidate_id: uuid.UUID, body: ReferenceIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        ProcurementConceptService(session).add_reference(
            project_id, candidate_id, body.model_dump(), actor_id=_uid(user_id)
        )
    )
    return {"id": str(row.id), "verified": row.verified_at is not None}


@router.delete(
    "/projects/{project_id}/candidates/{candidate_id}/references/{reference_id}", status_code=204, dependencies=[EDIT]
)
async def delete_reference(
    project_id: uuid.UUID, candidate_id: uuid.UUID, reference_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(ProcurementConceptService(session).delete_reference(project_id, candidate_id, reference_id))
    return Response(status_code=204)


@router.post("/projects/{project_id}/packages/{package_id}/shortlist", dependencies=[EDIT])
async def confirm_shortlist(
    project_id: uuid.UUID,
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    row = await _run(
        svc.confirm_shortlist(project_id, package_id, actor_id=_uid(user_id), can_manage=await _manage(payload))
    )
    return svc._award_out(row)


# ── market sounding ──────────────────────────────────────────────────────


def _sounding_out(s: Any) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "package_ids": s.package_ids,
        "trade": s.trade,
        "held_on": s.held_on,
        "method": s.method,
        "participant_candidate_ids": s.participant_candidate_ids,
        "findings": s.findings,
        "capacity_signal": s.capacity_signal,
        "price_signal": s.price_signal,
        "lead_time_signal_days": s.lead_time_signal_days,
        "mitigation": s.mitigation,
        "resplit": s.resplit,
        "unmitigated": s.capacity_signal in ("tight", "insufficient") and not s.mitigation.strip() and not s.resplit,
    }


@router.get("/projects/{project_id}/market-soundings", dependencies=[READ])
async def list_soundings(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Market soundings. Recording one is data entry: the edit permission is all it takes."""
    await verify_project_access(project_id, user_id, session)
    svc = ProcurementConceptService(session)
    edit = (await _run(_access(svc, project_id, user_id, payload)))["edit"]
    return _page(
        [_sounding_out(s) for s in await _run(svc.list_soundings(project_id))],
        can={"create": edit, "edit": edit, "delete": edit},
    )


@router.post("/projects/{project_id}/market-soundings", status_code=201, dependencies=[EDIT])
async def create_sounding(
    project_id: uuid.UUID, body: SoundingIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        ProcurementConceptService(session).save_sounding(project_id, body.model_dump(), actor_id=_uid(user_id))
    )
    return _sounding_out(row)


@router.patch("/projects/{project_id}/market-soundings/{sounding_id}", dependencies=[EDIT])
async def patch_sounding(
    project_id: uuid.UUID, sounding_id: uuid.UUID, body: SoundingPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        ProcurementConceptService(session).save_sounding(
            project_id, body.model_dump(exclude_unset=True), actor_id=_uid(user_id), sounding_id=sounding_id
        )
    )
    return _sounding_out(row)


@router.delete("/projects/{project_id}/market-soundings/{sounding_id}", status_code=204, dependencies=[EDIT])
async def delete_sounding(
    project_id: uuid.UUID, sounding_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(ProcurementConceptService(session).delete_sounding(project_id, sounding_id, actor_id=_uid(user_id)))
    return Response(status_code=204)


# ── award schedule ───────────────────────────────────────────────────────


@router.get("/projects/{project_id}/schedule", dependencies=[READ])
async def schedule(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    """Backward-pass proposals per package (award = need - lead time; start = award - procedure days)."""
    await verify_project_access(project_id, user_id, session)
    data = await _run(ProcurementConceptService(session).schedule_view(project_id, today=_today(today)))
    return _page(data["items"], release_date=data["release_date"], release_gate_code=data["release_gate_code"])


@router.post("/projects/{project_id}/schedule/confirm", dependencies=[EDIT])
async def confirm_schedule(
    project_id: uuid.UUID,
    body: ScheduleConfirm,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """The human confirms proposals: start and award milestones are written to the project schedule."""
    await verify_project_access(project_id, user_id, session)
    rows = await _run(
        ProcurementConceptService(session).confirm_schedule(
            project_id, body.package_ids, actor_id=_uid(user_id), can_manage=await _manage(payload)
        )
    )
    return _page(rows)


# ── validation and export ────────────────────────────────────────────────


@router.get("/projects/{project_id}/validation", dependencies=[READ])
async def validation(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, today: date | None = None
) -> dict[str, Any]:
    """Rule set ``procurement_concept``: one result per rule and ref."""
    from app.core.validation.engine import ValidationContext
    from app.modules.procurement_concept.validators import PROCUREMENT_RULES

    await verify_project_access(project_id, user_id, session)
    data = await _run(ProcurementConceptService(session).findings(project_id, today=_today(today)))
    context = ValidationContext(data={"findings": data}, metadata={"locale": get_locale() or "en"})
    out = []
    for rule_cls in PROCUREMENT_RULES:
        for r in await rule_cls().validate(context):
            out.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(r.severity),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
            )
    return _page(out)


@router.get("/projects/{project_id}/export", dependencies=[READ])
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
    part: Literal["concept", "packages", "shortlist", "schedule"] = "concept",
    package_id: uuid.UUID | None = None,
) -> Response:
    """The concept record, package list, shortlist (``package_id``) or award schedule as PDF or XLSX."""
    from app.modules.procurement_concept.export import render, written_locale
    from app.modules.projects.models import Project

    await verify_project_access(project_id, user_id, session)
    project = await session.get(Project, project_id)
    locale = written_locale(get_locale())
    content = await _run(
        render(
            ProcurementConceptService(session),
            project_id,
            part=part,
            package_id=package_id,
            project_name=getattr(project, "name", "") or "",
            locale=locale,
            fmt=fmt,
        )
    )
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="procurement_{part}.{fmt}"',
            # The language the document was written in, which is not always the one asked for.
            "Content-Language": locale,
        },
    )


# ── frameworks (tenant level) ────────────────────────────────────────────


def _framework_out(f: Any) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "code": f.code,
        "title": f.title,
        "subcontractor_id": str(f.subcontractor_id) if f.subcontractor_id else None,
        "vendor_id": str(f.vendor_id) if f.vendor_id else None,
        "supplier_name": f.supplier_name,
        "scope": f.scope,
        "package_kinds": f.package_kinds,
        "lots": f.lots,
        "max_value": format(f.max_value, "f"),
        "currency": f.currency,
        "start_date": f.start_date,
        "end_date": f.end_date,
        "call_off_mode": f.call_off_mode,
        "source_procedure_ref": f.source_procedure_ref,
        "state": f.state,
    }


async def _frameworks_out(
    svc: ProcurementConceptService, rows: list[Any], payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Frameworks with ``can`` (edit, and the state moves the state machine allows this caller)."""
    allowed = await _has(payload, FRAMEWORKS_PERMISSION)
    tenant = resolve_tenant_id(payload)
    return [{**_framework_out(f), "can": svc.framework_can(f, tenant, allowed)} for f in rows]


@router.get("/frameworks", dependencies=[READ])
async def list_frameworks(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    svc = ProcurementConceptService(session)
    rows = await _run(svc.list_frameworks(resolve_tenant_id(payload)))
    create = None if await _has(payload, FRAMEWORKS_PERMISSION) else "permission_denied"
    return _page(
        await _frameworks_out(svc, rows, payload),
        can={"create": {"allowed": create is None, "reason": create, "applies": True}},
    )


@router.post("/frameworks", status_code=201, dependencies=[FRAMEWORKS])
async def create_framework(
    body: FrameworkIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    row = await _run(
        ProcurementConceptService(session).create_framework(
            resolve_tenant_id(payload), body.model_dump(), actor_id=_uid(user_id)
        )
    )
    return _framework_out(row)


@router.get("/frameworks/{framework_id}", dependencies=[READ])
async def get_framework(framework_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    svc = ProcurementConceptService(session)
    row = await _run(svc._framework(resolve_tenant_id(payload), framework_id))
    return (await _frameworks_out(svc, [row], payload))[0]


@router.patch("/frameworks/{framework_id}", dependencies=[FRAMEWORKS])
async def patch_framework(
    framework_id: uuid.UUID,
    body: FrameworkPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    row = await _run(
        ProcurementConceptService(session).patch_framework(
            resolve_tenant_id(payload), framework_id, body.model_dump(exclude_unset=True), actor_id=_uid(user_id)
        )
    )
    return _framework_out(row)


@router.post("/frameworks/{framework_id}/state", dependencies=[FRAMEWORKS])
async def framework_state(
    framework_id: uuid.UUID,
    body: FrameworkStateIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    row = await _run(
        ProcurementConceptService(session).transition_framework(
            resolve_tenant_id(payload), framework_id, body.target, actor_id=_uid(user_id)
        )
    )
    return _framework_out(row)


@router.get("/frameworks/{framework_id}/ledger", dependencies=[READ])
async def framework_ledger(framework_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Call-off ledger: linked packages and tagged purchase orders, call-off and remaining value."""
    data = await _run(ProcurementConceptService(session).ledger(resolve_tenant_id(payload), framework_id))
    return {**data, "offset": 0, "limit": data["total"]}
