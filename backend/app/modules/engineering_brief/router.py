# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Engineering brief API, mounted at ``/api/v1/engineering_brief``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and awaits ``verify_project_access``
in its own body before it reads anything, so a project the caller cannot see answers 404 exactly like a
missing one. Child rows are looked up by ``(project_id, id)``; a requirement, concept item, programme
line, milestone, schedule activity or permit requirement of another project is 404 or 422.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in ``detail``;
``message_key`` is ``engineering_brief.errors.<code>``. 404 = not found or not visible, 403 = permission
or the approver is the submitter, 409 = state conflict, 422 = invalid input or a refusing rule.

There is an approve route for one case only: a project that runs without gates. With gates the
governance gate approves the brief. Authorisation is decided here and handed down as booleans
(:func:`_actor`); the service never sees a role or a token. Views carry ``can`` objects,
``{"allowed", "reason", "applies"}``, computed by the function that enforces the action.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.engineering_brief.catalogue import ENGINEERING_BRIEF_KIND
from app.modules.engineering_brief.errors import EngineeringBriefError
from app.modules.engineering_brief.messages import translate
from app.modules.engineering_brief.permissions import MANAGE, has_permission
from app.modules.engineering_brief.schemas import (
    BackplanIn,
    BriefPatch,
    BriefSet,
    ConceptIn,
    ConceptPatch,
    ConceptStatusIn,
    FindingOut,
    IssueIn,
    MilestoneIn,
    MilestonePatch,
    MilestonesFromCatalogue,
    Page,
    ProgrammeIn,
    ProgrammePatch,
    RequirementIn,
    RequirementPatch,
    StudyIn,
    StudyPatch,
)
from app.modules.engineering_brief.service import (
    Actor,
    EngineeringBriefService,
    concept_dict,
    json_safe,
    programme_dict,
)

router = APIRouter(tags=["engineering_brief"])

READ = Depends(RequirePermission("engineering_brief.read"))
EDIT = Depends(RequirePermission("engineering_brief.edit"))
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _run[T](awaitable: Any) -> T:
    """Turn an :class:`EngineeringBriefError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except EngineeringBriefError as exc:
        message = translate(f"engineering_brief.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = EngineeringBriefError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"engineering_brief.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _actor(user_id: str, payload: dict[str, Any]) -> Actor:
    """The caller as the service sees them: an id and what the permission checks allow."""
    token = dict(payload or {})
    return Actor(
        _uid(user_id),
        manage=has_permission(token, MANAGE),
        edit=has_permission(token, "engineering_brief.edit"),
    )


def _page(items: list[Any], **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": len(items), "offset": 0, "limit": len(items), **extra}


def _file(content: bytes, fmt: str, name: str, locale: str) -> Response:
    """A rendered export. ``locale`` is the language its labels were written in, declared to the reader."""
    return Response(
        content=content,
        media_type="application/pdf" if fmt == "pdf" else _XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{name}.{fmt}"',
            "Content-Language": locale,
        },
    )


# ── catalogues ─────────────────────────────────────────────────────────────


@router.get("/catalogues", response_model=Page[dict[str, Any]], dependencies=[READ])
async def list_catalogues(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Shipped engineering brief catalogues and the caller's tenant ones, through the one governance resolver."""
    from app.modules.project_governance.catalogue_store import CatalogueStore

    EngineeringBriefService(session)  # registers the kind
    items = await _run(CatalogueStore(session).list_available(resolve_tenant_id(payload), kind=ENGINEERING_BRIEF_KIND))
    return _page(items)


@router.get("/projects/{project_id}/catalogue", dependencies=[READ])
async def pinned_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _run(EngineeringBriefService(session).catalogue_view(project_id))


# ── brief ──────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/brief", dependencies=[READ])
async def get_brief(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """The brief header. Catches up with a governance approval whose event did not arrive."""
    await verify_project_access(project_id, user_id, session)
    return await _run(EngineeringBriefService(session).brief_view(project_id, _actor(user_id, payload)))


@router.put("/projects/{project_id}/brief", status_code=201, dependencies=[EDIT])
async def set_brief(
    project_id: uuid.UUID, body: BriefSet, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    await _run(
        svc.set_brief(
            project_id,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
            catalogue_source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            catalogue_version=body.catalogue_version,
            title=body.title,
            summary=body.summary,
            operation_proof_date=body.operation_proof_date,
        )
    )
    return await _run(svc.brief_view(project_id, _actor(user_id, payload)))


@router.patch("/projects/{project_id}/brief", dependencies=[EDIT])
async def patch_brief(
    project_id: uuid.UUID, body: BriefPatch, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    await _run(svc.patch_brief(project_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _run(svc.brief_view(project_id, _actor(user_id, payload)))


@router.post("/projects/{project_id}/brief/submit", dependencies=[EDIT])
async def submit_brief(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Draft or revising -> in review. Approval is the governance gate of the hosting area."""
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    await _run(svc.submit(project_id, _uid(user_id)))
    return await _run(svc.brief_view(project_id, _actor(user_id, payload)))


@router.post("/projects/{project_id}/brief/approve", dependencies=[Depends(RequirePermission(MANAGE))])
async def approve_brief(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """In review -> binding by hand, on a project without gates. With gates the gate decision approves."""
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    await _run(svc.approve_by_hand(project_id, _uid(user_id)))
    return await _run(svc.brief_view(project_id, _actor(user_id, payload)))


@router.post("/projects/{project_id}/brief/return", dependencies=[EDIT])
async def return_brief(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    await _run(svc.return_brief(project_id, _uid(user_id)))
    return await _run(svc.brief_view(project_id, _actor(user_id, payload)))


@router.get("/projects/{project_id}/brief/findings", dependencies=[READ])
async def brief_findings(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """What submission would refuse right now, with the warnings beside the errors."""
    await verify_project_access(project_id, user_id, session)
    found = await _run(EngineeringBriefService(session).submission_findings(project_id))
    return _page([f.as_dict() for f in found])


# ── requirements ───────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/requirements", dependencies=[READ])
async def list_requirements(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(EngineeringBriefService(session).requirement_views(project_id)))


async def _requirement_view(
    svc: EngineeringBriefService, project_id: uuid.UUID, requirement_id: uuid.UUID
) -> dict[str, Any]:
    return next(v for v in await svc.requirement_views(project_id) if v["id"] == str(requirement_id))


@router.post("/projects/{project_id}/requirements", status_code=201, dependencies=[EDIT])
async def create_requirement(
    project_id: uuid.UUID, body: RequirementIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    row = await _run(svc.create_requirement(project_id, body.model_dump(), _uid(user_id)))
    return await _requirement_view(svc, project_id, row.id)


@router.patch("/projects/{project_id}/requirements/{requirement_id}", dependencies=[EDIT])
async def update_requirement(
    project_id: uuid.UUID,
    requirement_id: uuid.UUID,
    body: RequirementPatch,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    await _run(svc.update_requirement(project_id, requirement_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _requirement_view(svc, project_id, requirement_id)


@router.delete("/projects/{project_id}/requirements/{requirement_id}", status_code=204, dependencies=[EDIT])
async def delete_requirement(
    project_id: uuid.UUID, requirement_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(EngineeringBriefService(session).delete_requirement(project_id, requirement_id, _uid(user_id)))
    return Response(status_code=204)


# ── technical concept ──────────────────────────────────────────────────────


@router.get("/projects/{project_id}/concept", dependencies=[READ])
async def list_concepts(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(EngineeringBriefService(session).concept_views(project_id)))


@router.post("/projects/{project_id}/concept", status_code=201, dependencies=[EDIT])
async def create_concept(
    project_id: uuid.UUID, body: ConceptIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(EngineeringBriefService(session).create_concept(project_id, body.model_dump(), _uid(user_id)))
    return json_safe(concept_dict(row))


@router.post("/projects/{project_id}/concept/from-catalogue", status_code=201, dependencies=[EDIT])
async def concepts_from_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """One open item for every required topic of the catalogue that has none yet."""
    await verify_project_access(project_id, user_id, session)
    rows = await _run(EngineeringBriefService(session).concepts_from_catalogue(project_id, _uid(user_id)))
    return _page([json_safe(concept_dict(r)) for r in rows])


@router.patch("/projects/{project_id}/concept/{concept_id}", dependencies=[EDIT])
async def update_concept(
    project_id: uuid.UUID, concept_id: uuid.UUID, body: ConceptPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        EngineeringBriefService(session).update_concept(
            project_id, concept_id, body.model_dump(exclude_unset=True), _uid(user_id)
        )
    )
    return json_safe(concept_dict(row))


@router.post("/projects/{project_id}/concept/{concept_id}/status", dependencies=[EDIT])
async def set_concept_status(
    project_id: uuid.UUID, concept_id: uuid.UUID, body: ConceptStatusIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        EngineeringBriefService(session).set_concept_status(project_id, concept_id, body.status, _uid(user_id))
    )
    return json_safe(concept_dict(row))


@router.delete("/projects/{project_id}/concept/{concept_id}", status_code=204, dependencies=[EDIT])
async def delete_concept(
    project_id: uuid.UUID, concept_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(EngineeringBriefService(session).delete_concept(project_id, concept_id, _uid(user_id)))
    return Response(status_code=204)


# ── programme ──────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/programme", dependencies=[READ])
async def list_programme(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(EngineeringBriefService(session).programme_views(project_id)))


@router.post("/projects/{project_id}/programme", status_code=201, dependencies=[EDIT])
async def create_programme(
    project_id: uuid.UUID, body: ProgrammeIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(EngineeringBriefService(session).create_programme(project_id, body.model_dump(), _uid(user_id)))
    return json_safe(programme_dict(row))


@router.patch("/projects/{project_id}/programme/{line_id}", dependencies=[EDIT])
async def update_programme(
    project_id: uuid.UUID, line_id: uuid.UUID, body: ProgrammePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _run(
        EngineeringBriefService(session).update_programme(
            project_id, line_id, body.model_dump(exclude_unset=True), _uid(user_id)
        )
    )
    return json_safe(programme_dict(row))


@router.delete("/projects/{project_id}/programme/{line_id}", status_code=204, dependencies=[EDIT])
async def delete_programme(
    project_id: uuid.UUID, line_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(EngineeringBriefService(session).delete_programme(project_id, line_id, _uid(user_id)))
    return Response(status_code=204)


# ── framework schedule ─────────────────────────────────────────────────────


@router.get("/projects/{project_id}/milestones", dependencies=[READ])
async def list_milestones(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Milestones with the gate and permit each is bound to and the findings about it."""
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(EngineeringBriefService(session).milestone_views(project_id)))


async def _milestone_view(
    svc: EngineeringBriefService, project_id: uuid.UUID, milestone_id: uuid.UUID
) -> dict[str, Any]:
    return next(v for v in await svc.milestone_views(project_id) if v["id"] == str(milestone_id))


@router.post("/projects/{project_id}/milestones", status_code=201, dependencies=[EDIT])
async def create_milestone(
    project_id: uuid.UUID, body: MilestoneIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    row = await _run(svc.create_milestone(project_id, body.model_dump(), _uid(user_id)))
    return await _milestone_view(svc, project_id, row.id)


@router.post("/projects/{project_id}/milestones/from-catalogue", status_code=201, dependencies=[EDIT])
async def milestones_from_catalogue(
    project_id: uuid.UUID, body: MilestonesFromCatalogue, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """The catalogue's backward-planned chain, dated from the operating proof. Dates are proposals."""
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    rows = await _run(svc.milestones_from_catalogue(project_id, body.codes, _uid(user_id)))
    ids = {str(r.id) for r in rows}
    return _page([v for v in await svc.milestone_views(project_id) if v["id"] in ids])


@router.post("/projects/{project_id}/milestones/from-gates", status_code=201, dependencies=[EDIT])
async def milestones_from_gates(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """A gate milestone for every gate of the project that has none."""
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    rows = await _run(svc.milestones_from_gates(project_id, _uid(user_id), get_locale() or "en"))
    ids = {str(r.id) for r in rows}
    return _page([v for v in await svc.milestone_views(project_id) if v["id"] in ids])


@router.post("/projects/{project_id}/milestones/backplan", dependencies=[EDIT])
async def backplan(
    project_id: uuid.UUID, body: BackplanIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """The dates a plan backwards from the operating proof gives; written only with ``apply``."""
    await verify_project_access(project_id, user_id, session)
    return await _run(EngineeringBriefService(session).backplan(project_id, body.apply, _uid(user_id)))


@router.post("/projects/{project_id}/milestones/publish", dependencies=[Depends(RequirePermission(MANAGE))])
async def publish_schedule(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Write the milestones as activities of a schedule and link the gate milestones to their gates."""
    await verify_project_access(project_id, user_id, session)
    return await _run(EngineeringBriefService(session).publish_schedule(project_id, _uid(user_id)))


@router.patch("/projects/{project_id}/milestones/{milestone_id}", dependencies=[EDIT])
async def update_milestone(
    project_id: uuid.UUID, milestone_id: uuid.UUID, body: MilestonePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    await _run(svc.update_milestone(project_id, milestone_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _milestone_view(svc, project_id, milestone_id)


@router.delete("/projects/{project_id}/milestones/{milestone_id}", status_code=204, dependencies=[EDIT])
async def delete_milestone(
    project_id: uuid.UUID, milestone_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(EngineeringBriefService(session).delete_milestone(project_id, milestone_id, _uid(user_id)))
    return Response(status_code=204)


# ── studies ────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/studies", dependencies=[READ])
async def list_studies(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(EngineeringBriefService(session).study_views(project_id)))


@router.post("/projects/{project_id}/studies", status_code=201, dependencies=[EDIT])
async def create_study(
    project_id: uuid.UUID, body: StudyIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    row = await _run(svc.create_study(project_id, body.model_dump(), _uid(user_id)))
    return svc.study_dict(row)


@router.patch("/projects/{project_id}/studies/{study_id}", dependencies=[EDIT])
async def update_study(
    project_id: uuid.UUID, study_id: uuid.UUID, body: StudyPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    row = await _run(svc.update_study(project_id, study_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return svc.study_dict(row)


@router.delete("/projects/{project_id}/studies/{study_id}", status_code=204, dependencies=[EDIT])
async def delete_study(
    project_id: uuid.UUID, study_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(EngineeringBriefService(session).delete_study(project_id, study_id, _uid(user_id)))
    return Response(status_code=204)


# ── the issued requirements specification ──────────────────────────────────


@router.get("/projects/{project_id}/specification", dependencies=[READ])
async def list_specification_issues(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """The issued versions of the requirements specification and whether the latest is still current."""
    await verify_project_access(project_id, user_id, session)
    return await _run(EngineeringBriefService(session).issue_views(project_id))


@router.post("/projects/{project_id}/specification/issue", status_code=201, dependencies=[EDIT])
async def issue_specification(
    project_id: uuid.UUID, body: IssueIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Render the requirements brief as a PDF into the documents module and record a numbered issue."""
    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    row = await _run(svc.issue_specification(project_id, _uid(user_id), body.note, get_locale() or "en"))
    return svc.issue_dict(row)


# ── readiness, validation, export ──────────────────────────────────────────


@router.get("/projects/{project_id}/gates", response_model=Page[dict[str, Any]], dependencies=[READ])
async def list_gates(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The governance gates of the project, for the gate selector of a milestone (read only)."""
    await verify_project_access(project_id, user_id, session)
    gates = await _run(EngineeringBriefService(session)._gates(project_id))
    return _page(json_safe(gates))


@router.get("/projects/{project_id}/readiness", dependencies=[READ])
async def readiness(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, gate_code: str = Query(..., max_length=64)
) -> dict[str, Any]:
    """What the governance gate ``gate_code`` reads of the brief (read only)."""
    await verify_project_access(project_id, user_id, session)
    return await _run(EngineeringBriefService(session).readiness(project_id, gate_code))


@router.get("/projects/{project_id}/validation", response_model=Page[FindingOut], dependencies=[READ])
async def validation(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext
    from app.modules.engineering_brief.validators import BRIEF_RULES

    await verify_project_access(project_id, user_id, session)
    data = await _run(EngineeringBriefService(session).validation_payload(project_id))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    findings: list[FindingOut] = []
    for rule_cls in BRIEF_RULES:
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
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    what: Literal["requirements", "concept", "programme", "schedule"] = "requirements",
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
) -> Response:
    """Requirements brief, technical concept, programme or framework schedule as a printable register."""
    from app.modules.engineering_brief import export as ex
    from app.modules.projects.models import Project

    await verify_project_access(project_id, user_id, session)
    svc = EngineeringBriefService(session)
    catalogue = await _run(svc.catalogue_for(await _run(svc.require_brief(project_id))))
    project = await session.get(Project, project_id)
    labels = {
        "catalogue": catalogue,
        "project_name": getattr(project, "name", "") or "",
        "locale": get_locale() or "en",
    }
    if what == "concept":
        doc = ex.concept_document(await _run(svc.concept_views(project_id)), **labels)
    elif what == "programme":
        doc = ex.programme_document(await _run(svc.programme_views(project_id)), **labels)
    elif what == "schedule":
        doc = ex.schedule_document(await _run(svc.milestone_views(project_id)), **labels)
    else:
        doc = ex.requirements_document(await _run(svc.requirement_views(project_id)), **labels)
    return _file(ex.render(doc, fmt), fmt, f"engineering_brief_{what}", labels["locale"])
