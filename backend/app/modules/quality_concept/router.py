# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Quality concept API, mounted at ``/api/v1/quality-concept``.

Every route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are looked up by
``(project_id, id)`` and linked evidence is resolved inside the project, so an
id from another project is also 404.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``quality_concept.errors.<code>``. 404 = not
found or not visible, 403 = visible but not allowed (four-eyes), 409 = state
conflict, 422 = invalid input or a refusing rule (``violations`` lists every
finding). Lists are ``{items, total, offset, limit}``.

Stage release is not a route here: ``request-release`` creates a
construction_control hold gate, which is released in construction_control by a
user whose party role satisfies the stage's release party.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm.exc import StaleDataError

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.quality_concept import capabilities as caps
from app.modules.quality_concept import evaluator as ev
from app.modules.quality_concept import permit_conditions, references
from app.modules.quality_concept import schemas as s
from app.modules.quality_concept.catalogue import shipped_catalogue
from app.modules.quality_concept.errors import QualityConceptError
from app.modules.quality_concept.messages import translate
from app.modules.quality_concept.models import (
    AcceptanceUnit,
    AppliedStandard,
    CertificationTarget,
    CommissioningStageDef,
    CreditTarget,
    EvidenceLink,
    ExpertReportPlan,
    PreservationSurvey,
    ProofRequirement,
)
from app.modules.quality_concept.service import ProjectFacts, QualityConceptService

router = APIRouter(tags=["quality_concept"])

READ = Depends(RequirePermission("quality_concept.read"))
EDIT = Depends(RequirePermission("quality_concept.edit"))
WAIVE = Depends(RequirePermission("quality_concept.waive"))


async def _may_manage(project_id: uuid.UUID, user_id: str, payload: dict[str, Any], session: Any) -> bool:
    """Manage permission, or owner (or deputy) of the governance area that hosts quality."""
    try:
        await RequirePermission("quality_concept.manage")(payload)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return await QualityConceptService(session).is_area_owner(project_id, _uid(user_id))
    return True


async def _has(payload: dict[str, Any], permission: str) -> bool:
    """The permission check of a route, asked without raising."""
    try:
        await RequirePermission(permission)(payload)
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return False
    return True


async def _caller(project_id: uuid.UUID, user_id: str, payload: dict[str, Any], session: Any) -> caps.Caller:
    """Who asks and what the routes would let them through; the ``can`` flags are built from it."""
    return caps.Caller(
        user_id=_uid(user_id),
        edit=await _has(payload, "quality_concept.edit"),
        manage=await _may_manage(project_id, user_id, payload, session),
        waive=await _has(payload, "quality_concept.waive"),
    )


async def _manage(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> None:
    """Gate of every route that changes the plan a governance gate reads (404 before 403)."""
    await verify_project_access(project_id, user_id, session)
    if not await _may_manage(project_id, user_id, payload, session):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "manage_required",
                "message_key": "quality_concept.errors.manage_required",
                "message": translate("quality_concept.errors.manage_required", locale=get_locale() or "en"),
            },
        )


MANAGE = Depends(_manage)
P = "/projects/{project_id}"


async def _run[T](awaitable: Awaitable[T]) -> T:
    try:
        return await awaitable
    except StaleDataError as exc:
        # Two requests changed the same versioned row; the loser retries on fresh data.
        message = translate("quality_concept.errors.concurrent_update", locale=get_locale() or "en")
        detail = {
            "code": "concurrent_update",
            "message_key": "quality_concept.errors.concurrent_update",
            "message": message,
        }
        raise HTTPException(status_code=409, detail=detail) from exc
    except QualityConceptError as exc:
        message = translate(f"quality_concept.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("code"):
            raise
        # A neighbouring module refused in its own words; the screens read a code and a key.
        key = "quality_concept.errors.neighbour_refused"
        detail = {
            "code": "neighbour_refused",
            "message_key": key,
            "message": translate(key, locale=get_locale() or "en"),
            "detail": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
        }
        raise HTTPException(status_code=exc.status_code, detail=detail, headers=exc.headers) from exc


async def _refused(code: str) -> None:
    """A refusal decided in the router, answered in the same shape as one of the service."""
    raise QualityConceptError(code, caps.status_of(code))


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _today(value: date | None) -> date:
    return value or datetime.now(UTC).date()


def _page(items: list[Any], offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    total = len(items)
    lim = limit or max(total, 1)
    return {"items": items[offset : offset + lim], "total": total, "offset": offset, "limit": lim}


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _row(row: Any, *skip: str) -> dict[str, Any]:
    out = {c.key: _plain(getattr(row, c.key)) for c in row.__mapper__.column_attrs if c.key not in skip}
    return out


class _Ctx:
    """What the flags of one request are built from, read once."""

    def __init__(
        self, caller: caps.Caller, concept_state: str | None, four_eyes: bool, gates_in_use: bool = True
    ) -> None:
        self.caller = caller
        self.concept_state = concept_state
        self.four_eyes = four_eyes
        # Read only for a plan in force, the one state whose refusal depends on it.
        self.gates_in_use = gates_in_use


async def _project_service(
    project_id: uuid.UUID, user_id: str, session: Any, payload: dict[str, Any] | None = None
) -> QualityConceptService:
    await verify_project_access(project_id, user_id, session)
    svc = QualityConceptService(session)
    svc.caller_id = str(user_id)
    if payload is not None:
        svc.ctx = _Ctx(
            await _caller(project_id, user_id, payload, session),
            # Only the state: a row loaded here would be handed back unrefreshed by a later locked read.
            await svc.concept_state(project_id),
            await svc._four_eyes(project_id),
        )
        if svc.ctx.concept_state == "binding":
            svc.ctx.gates_in_use = await svc.gates_in_use(project_id)
    return svc


async def _with_contacts(svc: QualityConceptService, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each ``<role>_contact_id`` that is set gets ``<role>_contact_label`` beside it; null when the contact is gone."""
    fields = {k for item in items for k in item if k.endswith("_contact_id")}
    names = await references.contact_names(svc.session, {item[k] for item in items for k in fields if item.get(k)})
    return [
        {**item, **{k[:-3] + "_label": names.get(str(item[k])) if item.get(k) else None for k in fields if k in item}}
        for item in items
    ]


# Fields that hold the id of a user; each gets ``<field>_name`` beside it.
_PEOPLE = ("owner_user_id", "created_by", "submitted_by", "requested_by", "decided_by", "released_by", "confirmed_by")


async def _with_people(svc: QualityConceptService, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Names beside user ids: null when the id is null, the user is gone or has no name on file."""
    wanted = {item[k] for item in items for k in _PEOPLE if item.get(k)}
    wanted |= {u for item in items for u in item.get("release_user_ids") or ()}
    names = await references.user_names(svc.session, wanted)
    out = []
    for item in items:
        extra: dict[str, Any] = {f"{k}_name": names.get(str(item[k])) for k in _PEOPLE if k in item}
        if "release_user_ids" in item:
            extra["release_user_names"] = [names.get(str(u)) for u in item["release_user_ids"] or ()]
        out.append({**item, **extra})
    return out


async def _governance_document(
    svc: QualityConceptService, project_id: uuid.UUID, document_id: uuid.UUID | None
) -> dict[str, Any] | None:
    """The frame document the concept is bound to, as the governance module names it."""
    from app.modules.project_governance import public

    if document_id is None:
        return None
    for doc in await public.project_documents(svc.session, project_id):
        if doc.id == document_id:
            return {"id": str(doc.id), "code": doc.code, "label": doc.label, "status": doc.status}
    return None


async def _labelled(svc: QualityConceptService, project_id: uuid.UUID, findings: list[dict]) -> list[dict]:
    """Findings with the name of what ``ref`` points to, and of the linked record in ``params.link``."""
    linked = {f["params"]["link"].partition(":")[2] for f in findings if (f.get("params") or {}).get("link")}
    names = await references.labels(svc.session, project_id, {f.get("ref") for f in findings} | linked)
    out = []
    for f in findings:
        link = (f.get("params") or {}).get("link")
        item = {**f, "label": names.get(str(f.get("ref")))}
        if link:
            item["link_label"] = names.get(link.partition(":")[2])
        out.append(item)
    return out


# ── concept ────────────────────────────────────────────────────────────────


async def _concept_out(
    svc: QualityConceptService, project_id: uuid.UUID, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """The concept with what the caller may do; 404 ``concept_missing`` until it is created."""
    concept = await _run(svc.require_concept(project_id))
    cat = await _run(svc.catalogue_for(concept))
    findings = await svc.completeness(concept)
    errors = [f for f in findings if f.severity == ev.ERROR]
    manage = await _may_manage(project_id, user_id, payload, svc.session)
    submit_reason = "manage_required" if not manage else svc.submit_refusal(concept, errors)
    gates_in_use = await svc.gates_in_use(project_id)
    approval = caps.concept_approval(
        caps.Caller(user_id=_uid(user_id), manage=manage),
        gates_in_use=gates_in_use,
        state=concept.state,
        submitted_by=concept.submitted_by,
        four_eyes=svc.ctx.four_eyes,
    )
    (named,) = await _with_people(svc, [_row(concept)])
    return {
        **named,
        "governance_document": await _governance_document(svc, project_id, concept.governance_doc_id),
        # False on a project that never adopted a phase model: the concept is then approved by hand.
        "gates_in_use": gates_in_use,
        "catalogue_label": {"key": cat.name_key, "text": cat.labels},
        "catalogue_review_status": cat.review_status.value,
        "applicable_packages": await svc.applicable_packages(concept),
        "findings": await _labelled(svc, project_id, [f.as_dict() for f in findings]),
        "can": {
            "manage": manage,
            "edit_plan": manage and concept.state in ("draft", "revising"),
            "submit": submit_reason is None,
            "submit_reason": submit_reason,
            **approval,
        },
    }


@router.get(P + "/concept", dependencies=[READ])
async def get_concept(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    return await _concept_out(svc, project_id, user_id, payload)


@router.post(P + "/concept", status_code=201, dependencies=[MANAGE])
async def create_concept(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Create the project's concept. The one explicit write that brings it into being."""
    svc = await _project_service(project_id, user_id, session, payload)
    if await svc.concept(project_id) is not None:
        await _run(svc.refuse_duplicate_concept())
    await _run(svc.ensure_concept(project_id, _uid(user_id)))
    out = await _concept_out(svc, project_id, user_id, payload)
    await session.commit()
    return out


@router.patch(P + "/concept", dependencies=[MANAGE])
async def patch_concept(
    project_id: uuid.UUID,
    body: s.ConceptPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.patch_concept(project_id, body))
    out = await _concept_out(svc, project_id, user_id, payload)
    await session.commit()
    return out


@router.post(P + "/concept/documentation-set/apply", dependencies=[MANAGE])
async def apply_documentation_set(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, list[str]]:
    """Create the closeout slots and FM data deliverables of the chosen documentation set."""
    svc = await _project_service(project_id, user_id, session, payload)
    out = await _run(svc.apply_documentation_set(project_id, _uid(user_id)))
    await session.commit()
    return out


@router.put(P + "/concept/catalogue", dependencies=[MANAGE])
async def pin_catalogue(
    project_id: uuid.UUID,
    body: s.CataloguePin,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(
        svc.pin_catalogue(
            project_id, resolve_tenant_id(payload), body.catalogue_source, body.catalogue_id, body.catalogue_version
        )
    )
    out = await _concept_out(svc, project_id, user_id, payload)
    await session.commit()
    return out


@router.get(P + "/catalogues", dependencies=[READ])
async def list_catalogues(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Catalogues the caller may pin: shipped, the active pack's and the company's own."""
    svc = await _project_service(project_id, user_id, session, payload)
    concept = await svc.concept(project_id)
    items = await svc.available_catalogues(resolve_tenant_id(payload))
    for item in items:
        item["pinned"] = concept is not None and (item["source"], item["id"]) == (
            concept.catalogue_source,
            concept.catalogue_id,
        )
    return {
        **_page(items),
        "can": {
            "pin": svc.ctx.caller.manage and caps.plan_refusal(svc.ctx.concept_state, svc.ctx.gates_in_use) is None
        },
    }


@router.get(P + "/options", dependencies=[READ])
async def list_options(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    kind: Literal[
        "contact",
        "plant_item",
        "cx_system",
        "schedule_activity",
        "handover_package",
        "certificate_document",
        "retest_of",
    ] = Query(...),
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    owner_kind: Literal["proof", "credit", "stage_progress", "preservation", "expert_report"] | None = None,
    owner_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """What a reference field may hold, by the rule the write applies. ``available`` false names why."""
    svc = await _project_service(project_id, user_id, session, payload)
    found = await references.options(
        session,
        project_id,
        kind,
        caller_id=svc.caller_id,
        q=q,
        limit=limit,
        owner_kind=owner_kind,
        owner_id=owner_id,
    )
    return {**found, "offset": 0, "limit": limit}


@router.get(P + "/concept/catalogue", dependencies=[READ])
async def get_catalogue(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """The pinned catalogue; before a concept exists, the shipped default it would start with."""
    svc = await _project_service(project_id, user_id, session, payload)
    concept = await svc.concept(project_id)
    catalogue = shipped_catalogue() if concept is None else await _run(svc.catalogue_for(concept))
    return catalogue.model_dump(mode="json")


@router.post(P + "/concept/submit", dependencies=[MANAGE])
async def submit_concept(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.submit(project_id, _uid(user_id)))
    out = await _concept_out(svc, project_id, user_id, payload)
    await session.commit()
    return out


@router.post(P + "/concept/approve", dependencies=[MANAGE])
async def approve_concept(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Approval by a person, on a project that has no gates; with gates the gate decision approves."""
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.approve_by_hand(project_id, _uid(user_id)))
    svc.ctx.concept_state = await svc.concept_state(project_id)
    out = await _concept_out(svc, project_id, user_id, payload)
    await session.commit()
    return out


@router.post(P + "/concept/reopen", dependencies=[MANAGE])
async def reopen_concept(
    project_id: uuid.UUID,
    body: s.RationaleIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """A manager reopens the plan in force with a reason, on a project that has no gates."""
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.reopen_by_hand(project_id, body.rationale, _uid(user_id)))
    svc.ctx.concept_state = await svc.concept_state(project_id)
    out = await _concept_out(svc, project_id, user_id, payload)
    await session.commit()
    return out


@router.post(P + "/concept/{action}", dependencies=[MANAGE])
async def concept_action(
    project_id: uuid.UUID,
    action: Literal["return"],
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.act_on_concept(project_id, action, _uid(user_id)))
    out = await _concept_out(svc, project_id, user_id, payload)
    await session.commit()
    return out


@router.get(P + "/concept/revisions", dependencies=[READ])
async def revisions(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    return _page(await _with_people(svc, [_row(r) for r in await svc.revisions(project_id)]))


# ── standards and requirements ─────────────────────────────────────────────


@router.get(P + "/standards", dependencies=[READ])
async def list_standards(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    plan = caps.plan_row(svc.ctx.caller, svc.ctx.concept_state, svc.ctx.gates_in_use)
    return _page([{**_row(r), **plan} for r in await svc.repo.list(AppliedStandard, project_id)])


@router.post(P + "/standards", status_code=201, dependencies=[MANAGE])
async def create_standard(
    project_id: uuid.UUID, body: s.StandardIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.create_standard(project_id, body))
    out = {**_row(row), **caps.plan_row(svc.ctx.caller, svc.ctx.concept_state, svc.ctx.gates_in_use)}
    await session.commit()
    return out


@router.patch(P + "/standards/{row_id}", dependencies=[MANAGE])
async def patch_standard(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.StandardPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc._plan_concept(project_id))
    row = await _run(svc.patch_row(AppliedStandard, project_id, row_id, body.model_dump(exclude_unset=True)))
    out = {**_row(row), **caps.plan_row(svc.ctx.caller, svc.ctx.concept_state, svc.ctx.gates_in_use)}
    await session.commit()
    return out


@router.delete(P + "/standards/{row_id}", status_code=204, dependencies=[MANAGE])
async def delete_standard(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc._plan_concept(project_id))
    await _run(svc.delete_row(AppliedStandard, project_id, row_id))
    await session.commit()
    return Response(status_code=204)


def _requirement_out(r: Any) -> dict[str, Any]:
    keys = (
        "id",
        "category",
        "entity",
        "attribute",
        "constraint_value",
        "unit",
        "source_ref",
        "verification_method",
        "status",
        "rationale",
    )
    return {k: _plain(getattr(r, k, None)) for k in keys}


@router.get(P + "/requirements", dependencies=[READ])
async def list_requirements(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    return _page([_requirement_out(r) for r in await _run(svc.list_requirements(project_id))])


@router.get(P + "/permit-conditions", dependencies=[READ])
async def list_permit_conditions(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Permit conditions of module 2 as derived quality requirements and checks (read only)."""
    await _project_service(project_id, user_id, session, payload)
    return await permit_conditions.load(session, project_id)


@router.post(P + "/requirements", status_code=201, dependencies=[MANAGE])
async def add_requirement(
    project_id: uuid.UUID,
    body: s.QualityRequirementIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.require_concept(project_id))
    out = _requirement_out(await _run(svc.add_requirement(project_id, body, _uid(user_id))))
    await session.commit()
    return out


# ── certification ──────────────────────────────────────────────────────────


async def _certification_out(
    svc: QualityConceptService, project_id: uuid.UUID, row: CertificationTarget
) -> dict[str, Any]:
    credits = [c for c in await svc.repo.list(CreditTarget, project_id) if c.target_id == row.id]
    live = [c for c in credits if c.state != "dropped"]
    caller = svc.ctx.caller
    return {
        **_row(row),
        **caps.certification(caller, state=row.state),
        "credits": [{**_row(c), **caps.credit(caller, state=c.state)} for c in credits],
        "points_targeted": str(sum((c.points_targeted for c in live), Decimal("0"))),
        "points_achieved": str(sum((c.points_achieved or Decimal("0") for c in live), Decimal("0"))),
    }


@router.get(P + "/certifications", dependencies=[READ])
async def list_certifications(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    rows = await _with_contacts(
        svc,
        [await _certification_out(svc, project_id, r) for r in await svc.repo.list(CertificationTarget, project_id)],
    )
    raw = [f.as_dict() for f in await _run(svc.certification_findings(project_id))] if rows else []
    findings = await _labelled(svc, project_id, raw)
    return {**_page(rows), "findings": findings}


@router.post(P + "/certifications", status_code=201, dependencies=[MANAGE])
async def create_certification(
    project_id: uuid.UUID,
    body: s.CertificationIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.require_concept(project_id))
    row = await _run(svc.create_certification(project_id, body))
    out = await _certification_out(svc, project_id, row)
    await session.commit()
    return out


@router.patch(P + "/certifications/{row_id}", dependencies=[MANAGE])
async def patch_certification(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.CertificationPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.patch_certification(project_id, row_id, body.model_dump(exclude_unset=True)))
    out = await _certification_out(svc, project_id, row)
    await session.commit()
    return out


@router.post(P + "/certifications/{row_id}/transition", dependencies=[MANAGE])
async def transition_certification(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.CertificationTransition,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.transition_certification(project_id, row_id, body))
    out = await _certification_out(svc, project_id, row)
    await session.commit()
    return out


@router.delete(P + "/certifications/{row_id}", status_code=204, dependencies=[MANAGE])
async def delete_certification(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.delete_certification(project_id, row_id))
    await session.commit()
    return Response(status_code=204)


@router.post(P + "/certifications/{row_id}/credits", status_code=201, dependencies=[MANAGE])
async def add_credits(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.CreditBulk,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    rows = await _run(svc.add_credits(project_id, row_id, body.items))
    out = _page([{**_row(r), **caps.credit(svc.ctx.caller, state=r.state)} for r in rows])
    await session.commit()
    return out


@router.patch(P + "/credits/{row_id}", dependencies=[EDIT])
async def patch_credit(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.CreditPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    if body.action in caps.CREDIT_DECISIONS and not svc.ctx.caller.manage:
        # Whoever submits the evidence of a credit does not also decide it.
        await _run(_refused("manage_required"))
    row = await _run(svc.patch_credit(project_id, row_id, body))
    out = {**_row(row), **caps.credit(svc.ctx.caller, state=row.state)}
    await session.commit()
    return out


@router.delete(P + "/credits/{row_id}", status_code=204, dependencies=[MANAGE])
async def delete_credit(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.delete_row(CreditTarget, project_id, row_id, owner_kind="credit"))
    await session.commit()
    return Response(status_code=204)


# ── proofs ─────────────────────────────────────────────────────────────────


async def _proofs_out(
    svc: QualityConceptService, project_id: uuid.UUID, proofs: list[ProofRequirement]
) -> list[dict[str, Any]]:
    """Proofs with their delivery and what the caller may do; evidence is read once for all of them."""
    delivery = await svc.proof_delivery(project_id, proofs)
    authors: dict[uuid.UUID, list[uuid.UUID | None]] = {}
    for link in await svc.repo.links_for("proof", [p.id for p in proofs]):
        authors.setdefault(link.owner_id, []).append(link.created_by)
    return [_proof_out(p, delivery.get(p.id), svc.ctx, authors.get(p.id, [])) for p in proofs]


def _proof_out(
    p: ProofRequirement, delivery: ev.Delivery | None, ctx: _Ctx, authors: list[uuid.UUID | None]
) -> dict[str, Any]:
    derived = delivery.state if delivery else "open"
    return {
        **_row(p),
        **caps.proof(
            ctx.caller,
            concept_state=ctx.concept_state,
            gates_in_use=ctx.gates_in_use,
            decision=p.decision,
            requested_by=p.requested_by,
            rationale=p.decision_rationale,
            delivery_state=derived,
            evidence_authors=authors,
            four_eyes=ctx.four_eyes,
        ),
        "derived_state": derived,
        "state": ev.proof_state(derived, p.decision),
        "counted": delivery.counted if delivery else 0,
        "required": delivery.required if delivery else 1,
        "findings": [f.as_dict() for f in delivery.findings] if delivery else [],
    }


@router.get(P + "/proofs", dependencies=[READ])
async def list_proofs(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    package_ref: str | None = Query(default=None, max_length=64),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    filters = {"package_ref": package_ref} if package_ref else {}
    proofs = await svc.repo.list(ProofRequirement, project_id, **filters)
    rows = await _with_contacts(svc, await _proofs_out(svc, project_id, proofs))
    return _page(await _with_people(svc, rows), offset, limit)


@router.post(P + "/proofs", status_code=201, dependencies=[MANAGE])
async def create_proof(
    project_id: uuid.UUID, body: s.ProofIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.create_proof(project_id, body, _uid(user_id)))
    (out,) = await _proofs_out(svc, project_id, [row])
    await session.commit()
    return out


@router.patch(P + "/proofs/{row_id}", dependencies=[MANAGE])
async def patch_proof(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.ProofPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.patch_proof(project_id, row_id, body))
    (out,) = await _proofs_out(svc, project_id, [row])
    await session.commit()
    return out


@router.delete(P + "/proofs/{row_id}", status_code=204, dependencies=[MANAGE])
async def delete_proof(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc._plan_concept(project_id))
    await _run(svc.delete_row(ProofRequirement, project_id, row_id, owner_kind="proof"))
    await session.commit()
    return Response(status_code=204)


@router.post(P + "/proofs/generate", dependencies=[MANAGE])
async def generate_proofs(
    project_id: uuid.UUID,
    body: s.ProofGenerateIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    result = await _run(svc.generate_proofs(project_id, body))
    out = {
        **_page(result["preview"]),
        "created": await _proofs_out(svc, project_id, result["created"]),
        "preview": body.confirm is None,
    }
    await session.commit()
    return out


@router.get(P + "/proofs/coverage", dependencies=[READ])
async def coverage(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    cov = await svc.coverage(project_id)
    return {**_page(cov["packages"]), "findings": await _labelled(svc, project_id, cov["findings"])}


@router.post(P + "/proofs/{row_id}/waiver-request", dependencies=[EDIT])
async def request_waiver(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.WaiverRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.request_waiver(project_id, row_id, body.rationale, _uid(user_id)))
    (out,) = await _proofs_out(svc, project_id, [row])
    await session.commit()
    return out


@router.post(P + "/proofs/{row_id}/waiver-decision", dependencies=[WAIVE])
async def decide_waiver(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.WaiverDecision,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.decide_waiver(project_id, row_id, body.approve, _uid(user_id)))
    (out,) = await _proofs_out(svc, project_id, [row])
    await session.commit()
    return out


@router.post(P + "/proofs/{row_id}/{action}", dependencies=[EDIT])
async def proof_action(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    action: Literal["accept", "reopen"],
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    if action == "accept":
        row = await _run(svc.accept_proof(project_id, row_id, _uid(user_id)))
    else:
        row = await _run(svc.reopen_proof(project_id, row_id))
    (out,) = await _proofs_out(svc, project_id, [row])
    await session.commit()
    return out


# ── evidence links ─────────────────────────────────────────────────────────


def _fact(fact: ev.EvidenceFact | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    return {
        "outcome": fact.outcome,
        "sample": fact.sample,
        "calibration_expired": fact.calibration_expired,
        "expired_at_use": fact.expired_at_use,
        "quantity": _plain(fact.quantity),
    }


@router.get(P + "/evidence-links", dependencies=[READ])
async def list_links(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    owner_kind: Literal["proof", "credit", "stage_progress", "preservation", "expert_report"] = Query(...),
    owner_id: uuid.UUID = Query(...),
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    rows = await _run(svc.links_of(project_id, owner_kind, owner_id))
    names = await references.link_labels(session, project_id, [(r["link"].link_kind, r["link"].link_id) for r in rows])
    return _page(
        [
            {
                **_row(r["link"]),
                "fact": _fact(r["fact"]),
                "label": names.get(str(r["link"].link_id)),
                # False when the linked record is gone or no longer part of this project.
                "exists": r["fact"] is not None,
            }
            for r in rows
        ]
    )


@router.post(P + "/evidence-links", status_code=201, dependencies=[EDIT])
async def add_link(
    project_id: uuid.UUID,
    body: s.EvidenceLinkIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = _row(await _run(svc.add_link(project_id, body, _uid(user_id))))
    await session.commit()
    return out


@router.delete(P + "/evidence-links/{row_id}", status_code=204, dependencies=[EDIT])
async def remove_link(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.delete_row(EvidenceLink, project_id, row_id))
    await session.commit()
    return Response(status_code=204)


@router.get(P + "/evidence-links/candidates", dependencies=[READ])
async def link_candidates(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    link_kind: str = Query(..., max_length=40),
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    return _page(await svc.candidates(project_id, link_kind, q, limit))


# ── stages ─────────────────────────────────────────────────────────────────


@router.get(P + "/stages", dependencies=[READ])
async def list_stages(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    plan = caps.plan_row(svc.ctx.caller, svc.ctx.concept_state, svc.ctx.gates_in_use)
    rows = await svc.repo.list(CommissioningStageDef, project_id, CommissioningStageDef.order)
    return _page(await _with_people(svc, [{**_row(r), **plan} for r in rows]))


@router.post(P + "/stages/apply-catalogue", dependencies=[MANAGE])
async def apply_stages(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.require_concept(project_id))
    out = _page([_row(r) for r in await _run(svc.apply_catalogue_stages(project_id))])
    await session.commit()
    return out


@router.post(P + "/stages", status_code=201, dependencies=[MANAGE])
async def add_stage(
    project_id: uuid.UUID, body: s.StageDefIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = _row(await _run(svc.add_stage(project_id, body)))
    await session.commit()
    return out


@router.patch(P + "/stages/{row_id}", dependencies=[MANAGE])
async def patch_stage(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.StageDefPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = _row(await _run(svc.patch_stage(project_id, row_id, body)))
    await session.commit()
    return out


@router.delete(P + "/stages/{row_id}", status_code=204, dependencies=[MANAGE])
async def delete_stage(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.delete_stage(project_id, row_id))
    await session.commit()
    return Response(status_code=204)


def _progress_out(
    row: Any,
    gates: dict[str, dict[str, Any]],
    ctx: _Ctx,
    computed: str | None = None,
    pass_refusal: str | None = None,
) -> dict:
    """One system at one stage: the hold gate to open in construction control, and the caller's actions."""
    gate = gates.get(str(row.hold_gate_id)) if row.hold_gate_id else None
    state = computed or row.state
    return {
        **_row(row),
        "computed_state": state,
        "hold_gate": gate,
        **caps.stage_progress(
            ctx.caller,
            state=row.state,
            computed_state=state,
            gate_status=gate["status"] if gate else None,
            pass_refusal=pass_refusal,
        ),
    }


async def _one_progress(svc: QualityConceptService, project_id: uuid.UUID, row: Any) -> dict[str, Any]:
    gates = await references.hold_gates(svc.session, project_id, [row.hold_gate_id])
    out = _progress_out(row, gates, svc.ctx, None, await svc.pass_refusal(project_id, row))
    return (await _with_people(svc, [out]))[0]


async def _matrix(svc: QualityConceptService, project_id: uuid.UUID) -> dict[str, Any]:
    from sqlalchemy import select

    from app.modules.commissioning.models import CxSystem

    systems = list((await svc.session.execute(select(CxSystem).where(CxSystem.project_id == project_id))).scalars())
    evaluated = await svc.evaluate_progress(project_id)
    gates = await references.hold_gates(svc.session, project_id, [r.hold_gate_id for r, _x in evaluated])
    # Evidence is read only for the rows a pass could be recorded on.
    refusals = {r.id: await svc.pass_refusal(project_id, r) for r, _x in evaluated if r.state == "in_test"}
    items = [
        {
            **_progress_out(r, gates, svc.ctx, ev.computed_stage_state(r.state, results), refusals.get(r.id)),
            "preconditions": [x.as_dict() for x in results],
        }
        for r, results in evaluated
    ]
    items = await _with_people(svc, items)
    return {
        **_page(items),
        "systems": [
            {"id": str(x.id), "name": x.name, "system_type": x.system_type, "status": x.status} for x in systems
        ],
        "stages": [
            _row(r) for r in await svc.repo.list(CommissioningStageDef, project_id, CommissioningStageDef.order)
        ],
    }


@router.get(P + "/stage-progress", dependencies=[READ])
async def stage_matrix(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    return await _matrix(svc, project_id)


@router.post(P + "/stage-progress/sync", dependencies=[EDIT])
async def sync_progress(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.sync_progress(project_id))
    out = await _matrix(svc, project_id)
    await session.commit()
    return out


@router.post(P + "/stage-progress/{row_id}/open-test", dependencies=[EDIT])
async def open_test(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = await _one_progress(svc, project_id, await _run(svc.open_test(project_id, row_id, _uid(user_id))))
    await session.commit()
    return out


@router.post(P + "/stage-progress/{row_id}/result", dependencies=[EDIT])
async def record_result(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.StageResultIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.record_result(project_id, row_id, body, _uid(user_id)))
    out = await _one_progress(svc, project_id, row)
    await session.commit()
    return out


@router.post(P + "/stage-progress/{row_id}/request-release", status_code=201, dependencies=[EDIT])
async def request_release(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    gate = await _run(svc.request_release(project_id, row_id, _uid(user_id)))
    out = {
        "progress_id": str(row_id),
        "hold_gate": (await references.hold_gates(svc.session, project_id, [gate.id])).get(str(gate.id)),
    }
    await session.commit()
    return out


@router.post(P + "/stage-progress/{row_id}/not-applicable", dependencies=[MANAGE])
async def stage_na(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.RationaleIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.mark_not_applicable(project_id, row_id, body.rationale))
    out = await _one_progress(svc, project_id, row)
    await session.commit()
    return out


@router.post(P + "/stage-progress/{row_id}/reinstate", dependencies=[MANAGE])
async def stage_reinstate(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = await _one_progress(svc, project_id, await _run(svc.reinstate(project_id, row_id)))
    await session.commit()
    return out


@router.put(P + "/stage-progress/{row_id}/depends-on", dependencies=[MANAGE])
async def stage_depends(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.DependsOnIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    row = await _run(svc.set_dependencies(project_id, row_id, body.system_ids))
    out = await _one_progress(svc, project_id, row)
    await session.commit()
    return out


# ── acceptance ─────────────────────────────────────────────────────────────


def _unmet_label(x: ev.UnmetPrecondition, names: dict[str, str]) -> str | None:
    """A stage ref is ``system_id:stage_code``; everything else that has a name is an id."""
    if x.kind == "stage":
        system, _sep, code = x.ref.partition(":")
        return f"{names[system]}: {code}" if system in names else None
    return names.get(x.ref)


async def _units_out(
    svc: QualityConceptService, project_id: uuid.UUID, units: list[AcceptanceUnit], today: date
) -> list[dict[str, Any]]:
    """Units as the screens read them.

    The concept, its catalogue, the effects, the names, the handover acts and the project-wide
    facts behind the preconditions are each read once for the whole list.
    """
    if not units:
        return []
    concept = await _run(svc.require_concept(project_id))
    cat = await _run(svc.catalogue_for(concept))
    open_states = ("planned", "requested", "inspection_scheduled", "refused")
    effects = await svc.repo.effects_of([u.id for u in units])
    shared = ProjectFacts()
    facts = []
    for u in units:
        unmet = await svc.unmet_preconditions(project_id, u, shared) if u.state in open_states else []
        applied = effects.get(u.id, [])
        proposed = (
            await svc.proposed_effects(project_id, u, catalogue=cat, effects=applied)
            if u.state in ev.ACCEPTED_STATES
            else []
        )
        dates = await svc.deemed_dates(project_id, u, concept=concept, catalogue=cat)
        facts.append((cat.regime(u.regime_code), dates, applied, unmet, proposed))
    refs = {x.ref.partition(":")[0] if x.kind == "stage" else x.ref for *_, unmet in facts for x in unmet}
    names = await references.labels(svc.session, project_id, refs)
    acts = await references.handover_packages(svc.session, project_id, [u.handover_package_id for u in units])
    return [
        await _unit_dict(svc, project_id, u, today, fact, names, acts) for u, fact in zip(units, facts, strict=True)
    ]


async def _unit_out(
    svc: QualityConceptService, project_id: uuid.UUID, u: AcceptanceUnit, today: date
) -> dict[str, Any]:
    return (await _units_out(svc, project_id, [u], today))[0]


async def _unit_dict(
    svc: QualityConceptService,
    project_id: uuid.UUID,
    u: AcceptanceUnit,
    today: date,
    fact: tuple[Any, list[Any], list[Any], list[Any], list[Any]],
    names: dict[str, str],
    acts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    regime, dates, applied, unmet, proposed = fact
    # What still blocks a request when every reservable precondition is taken as a reservation.
    blocking, _reserved = ev.acceptance_request_check(
        unmet, reservable=regime.reservable if regime else (), with_reservations=True
    )
    # The server's date decides whether a deemed acceptance is due, as it does on the confirm.
    server_today = datetime.now(UTC).date()
    return {
        **_row(u),
        **caps.acceptance_unit(
            svc.ctx.caller,
            concept_state=svc.ctx.concept_state,
            gates_in_use=svc.ctx.gates_in_use,
            state=u.state,
            has_regime=regime is not None,
            blocked=bool(blocking),
            deemed_due=any(d.deemed_on and d.deemed_on <= server_today for d in dates),
        ),
        "handover_package": acts.get(str(u.handover_package_id)) if u.handover_package_id else None,
        "regime": regime.model_dump(mode="json") if regime else None,
        "deemed": [
            {
                "trigger": d.trigger,
                "from": d.from_date.isoformat(),
                "deemed_on": d.deemed_on.isoformat() if d.deemed_on else None,
                "days_left": (d.deemed_on - today).days if d.deemed_on else None,
                "needs_deadline": d.needs_deadline,
                "source_url": d.source_url,
                "source_title": d.source_title,
                "review_status": d.review_status,
            }
            for d in dates
        ],
        "effects_applied": [_row(e) for e in applied],
        "effects_proposed": [e.model_dump(mode="json") for e in proposed],
        "unmet": [{"kind": x.kind, "ref": x.ref, "label": _unmet_label(x, names)} for x in unmet],
    }


@router.get(P + "/acceptance-units", dependencies=[READ])
async def list_units(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.require_concept(project_id))
    t = _today(today)
    return _page(await _units_out(svc, project_id, await svc.repo.list(AcceptanceUnit, project_id), t))


@router.post(P + "/acceptance-units", status_code=201, dependencies=[MANAGE])
async def create_unit(
    project_id: uuid.UUID,
    body: s.AcceptanceUnitIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.require_concept(project_id))
    out = await _unit_out(svc, project_id, await _run(svc.create_unit(project_id, body)), _today(None))
    await session.commit()
    return out


@router.patch(P + "/acceptance-units/{row_id}", dependencies=[MANAGE])
async def patch_unit(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.AcceptanceUnitPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = await _unit_out(svc, project_id, await _run(svc.patch_unit(project_id, row_id, body)), _today(None))
    await session.commit()
    return out


@router.delete(P + "/acceptance-units/{row_id}", status_code=204, dependencies=[MANAGE])
async def delete_unit(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc._plan_concept(project_id))
    await _run(svc.delete_row(AcceptanceUnit, project_id, row_id))
    await session.commit()
    return Response(status_code=204)


@router.post(P + "/acceptance-units/{row_id}/request", dependencies=[EDIT])
async def request_unit(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.AcceptanceRequestIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    unit = await _run(svc.request_acceptance(project_id, row_id, body, _uid(user_id)))
    out = await _unit_out(svc, project_id, unit, _today(None))
    await session.commit()
    return out


@router.post(P + "/acceptance-units/{row_id}/dates", dependencies=[EDIT])
async def unit_dates(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.AcceptanceRecordIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = await _unit_out(svc, project_id, await _run(svc.record_dates(project_id, row_id, body)), _today(None))
    await session.commit()
    return out


@router.post(P + "/acceptance-units/{row_id}/refuse", dependencies=[MANAGE])
async def refuse_unit(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.AcceptanceRefuseIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = await _unit_out(
        svc, project_id, await _run(svc.refuse(project_id, row_id, body, _uid(user_id))), _today(None)
    )
    await session.commit()
    return out


@router.post(P + "/acceptance-units/{row_id}/effects", dependencies=[MANAGE])
async def confirm_effect(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.EffectConfirmIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = _row(await _run(svc.confirm_effect(project_id, row_id, body, _uid(user_id))))
    await session.commit()
    return out


@router.post(P + "/acceptance-units/{row_id}/{action}", dependencies=[MANAGE])
async def unit_action(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    action: Literal["schedule_inspection", "withdraw", "confirm_deemed"],
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    unit = await _run(svc.act_on_unit(project_id, row_id, action, _uid(user_id)))
    out = await _unit_out(svc, project_id, unit, _today(None))
    await session.commit()
    return out


# ── preservation and expert reports ────────────────────────────────────────


def _survey_out(row: PreservationSurvey, ctx: _Ctx) -> dict[str, Any]:
    return {
        **_row(row),
        **caps.survey(ctx.caller, state=row.state, phase=row.phase, access_refused=bool(row.access_refused_on)),
    }


@router.get(P + "/preservation", dependencies=[READ])
async def list_surveys(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    rows = await _with_contacts(
        svc, [_survey_out(r, svc.ctx) for r in await svc.repo.list(PreservationSurvey, project_id)]
    )
    raw = [f.as_dict() for f in await svc.preservation_findings(project_id, _today(today))]
    findings = await _labelled(svc, project_id, raw)
    return {**_page(rows), "findings": findings}


@router.post(P + "/preservation", status_code=201, dependencies=[EDIT])
async def create_survey(
    project_id: uuid.UUID,
    body: s.PreservationIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = _survey_out(await _run(svc.create_survey(project_id, body)), svc.ctx)
    await session.commit()
    return out


@router.patch(P + "/preservation/{row_id}", dependencies=[EDIT])
async def patch_survey(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.PreservationPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = _survey_out(await _run(svc.patch_survey(project_id, row_id, body)), svc.ctx)
    await session.commit()
    return out


@router.post(P + "/preservation/{row_id}/action", dependencies=[EDIT])
async def survey_action(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.PreservationAction,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = _survey_out(await _run(svc.survey_action(project_id, row_id, body, _uid(user_id))), svc.ctx)
    await session.commit()
    return out


@router.post(P + "/preservation/{row_id}/pair", dependencies=[EDIT])
async def pair_survey(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.PairIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = _survey_out(await _run(svc.pair_survey(project_id, row_id, body.before_id)), svc.ctx)
    await session.commit()
    return out


@router.delete(P + "/preservation/{row_id}", status_code=204, dependencies=[EDIT])
async def delete_survey(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.delete_survey(project_id, row_id))
    await session.commit()
    return Response(status_code=204)


@router.get(P + "/expert-reports", dependencies=[READ])
async def list_expert_reports(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    can = caps.editable(svc.ctx.caller)
    rows = [{**_row(r), **can} for r in await svc.repo.list(ExpertReportPlan, project_id)]
    return _page(await _with_contacts(svc, rows))


@router.post(P + "/expert-reports", status_code=201, dependencies=[EDIT])
async def create_expert_report(
    project_id: uuid.UUID,
    body: s.ExpertReportIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    out = {**_row(await _run(svc.create_expert_report(project_id, body))), **caps.editable(svc.ctx.caller)}
    await session.commit()
    return out


@router.patch(P + "/expert-reports/{row_id}", dependencies=[EDIT])
async def patch_expert_report(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: s.ExpertReportPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    fields = body.model_dump(exclude_unset=True)
    if fields.get("due_dates") is not None:
        fields["due_dates"] = [d.isoformat() for d in fields["due_dates"]]
    await _run(svc._check_contact(fields.get("expert_contact_id")))
    row = await _run(svc.patch_row(ExpertReportPlan, project_id, row_id, fields))
    out = {**_row(row), **caps.editable(svc.ctx.caller)}
    await session.commit()
    return out


@router.delete(P + "/expert-reports/{row_id}", status_code=204, dependencies=[EDIT])
async def delete_expert_report(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> Response:
    svc = await _project_service(project_id, user_id, session, payload)
    await _run(svc.delete_row(ExpertReportPlan, project_id, row_id, owner_kind="expert_report"))
    await session.commit()
    return Response(status_code=204)


# ── readiness, validation, export ──────────────────────────────────────────


@router.get(P + "/readiness", dependencies=[READ])
async def readiness(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    svc = await _project_service(project_id, user_id, session, payload)
    from app.modules.quality_concept import evidence

    out = await svc.readiness(project_id, _today(today))
    # Why the governance gate cannot read this concept, when it cannot; the screen says what to do.
    return {**out, "gate_detail": await evidence.gate_detail(session, project_id)}


@router.get(P + "/validation", dependencies=[READ])
async def validation(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    today: date | None = None,
) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext, rule_registry
    from app.modules.quality_concept.validators import QUALITY_CONCEPT_RULE_SET

    svc = await _project_service(project_id, user_id, session, payload)
    payload = await _run(svc.validation_payload(project_id, _today(today)))
    context = ValidationContext(data=payload, metadata={"locale": get_locale() or "en"})
    items = []
    for rule in rule_registry.get_rules_for_sets([QUALITY_CONCEPT_RULE_SET]):
        for r in await rule.validate(context):
            items.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": getattr(r.severity, "value", r.severity),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
            )
    return _page(items)


@router.get(P + "/export", dependencies=[READ], response_model=None)
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    what: Literal[
        "proofs", "stages", "acceptance", "preservation", "certification", "proof_matrix", "stage_matrix"
    ] = Query(default="proofs"),
    format: Literal["pdf", "xlsx"] = Query(default="xlsx"),
) -> Response:
    from app.modules.quality_concept.export import render, rendered_language

    svc = await _project_service(project_id, user_id, session, payload)
    locale = get_locale() or "en"
    data = await _run(render(svc, project_id, what=what, fmt=format, locale=locale))
    media = (
        "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="quality_{what}.{format}"',
            # The language the document is written in, not the one asked for: the module has fewer
            # languages than the interface, and without this the middleware labels a fallback
            # to English with the reader's own language.
            "Content-Language": rendered_language(locale),
        },
    )
