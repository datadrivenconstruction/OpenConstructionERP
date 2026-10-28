# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Staffing API, mounted at ``/api/v1/staffing``.

Every project-scoped route lives under ``/projects/{project_id}/...`` and
awaits ``verify_project_access`` in its own body before it reads anything, so
a project the caller cannot see answers 404 exactly like a missing one. Child
rows are looked up by ``(project_id, id)``; a roster member, credential or
row of another project is 404.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``staffing.errors.<code>``. 404 = not found or
not visible, 403 = permission or no relationship to the person, 409 = state
conflict, 422 = invalid input or a refusing rule.

Plan side (``staffing.read`` / ``staffing.edit``) shows names, roles, FTE,
dates and the cleared-to-work flag only. Personnel routes depend on
``staffing.read`` and the service applies rule 13: a relationship to the
person (owner of the hosting governance area, line manager, or the person)
plus the personnel tier. There is no approve route: the governance gate
approves the plan.

Authorisation is decided here and handed down as booleans (:func:`_actor`);
the service never sees a role or a token. No write route takes the date of
its own action from the client: ending a file or a fill happens today, on the
server's clock. Views carry ``can`` objects, ``{"allowed", "reason"}``,
computed by the function that enforces the action.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.core.tenant_scope import resolve_tenant_id
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.staffing.catalogue import STAFFING_MODEL_KIND
from app.modules.staffing.errors import StaffingError
from app.modules.staffing.messages import translate
from app.modules.staffing.permissions import (
    MANAGE,
    PERSONNEL_ASSIGN,
    PERSONNEL_EDIT,
    PERSONNEL_ERASE,
    PERSONNEL_READ,
    has_permission,
)
from app.modules.staffing.schemas import (
    CatalogueChange,
    DocumentLink,
    FileIn,
    FilePatch,
    FillIn,
    FindingOut,
    HandoverIn,
    HandoverPatch,
    LeaveIn,
    LeavePatch,
    Page,
    PlanPatch,
    PlanSet,
    PositionIn,
    PositionPatch,
    PositionsFromCatalogue,
    PositionStatusIn,
    RationaleIn,
    StatusIn,
    TravelIn,
    TravelPatch,
)
from app.modules.staffing.service import Actor, StaffingService

router = APIRouter(tags=["staffing"])

READ = Depends(RequirePermission("staffing.read"))
EDIT = Depends(RequirePermission("staffing.edit"))
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _run[T](awaitable: Any) -> T:
    """Turn a :class:`StaffingError` (or a store error from module 1) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except StaffingError as exc:
        message = translate(f"staffing.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = StaffingError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"staffing.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    return uuid.UUID(str(user_id))


def _actor(user_id: str, payload: dict[str, Any]) -> Actor:
    """The caller as the service sees them: an id and what the permission checks allow."""
    token = dict(payload or {})
    return Actor(
        _uid(user_id),
        personnel_read=has_permission(token, PERSONNEL_READ),
        personnel_edit=has_permission(token, PERSONNEL_EDIT),
        personnel_erase=has_permission(token, PERSONNEL_ERASE),
        assign_owner=has_permission(token, PERSONNEL_ASSIGN),
        manage=has_permission(token, MANAGE),
        edit=has_permission(token, "staffing.edit"),
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
    """Shipped staffing catalogues and the caller's tenant ones, through the one governance resolver."""
    from app.modules.project_governance.catalogue_store import CatalogueStore

    StaffingService(session)  # registers the kind
    items = await _run(CatalogueStore(session).list_available(resolve_tenant_id(payload), kind=STAFFING_MODEL_KIND))
    return _page(items)


@router.get("/projects/{project_id}/catalogue", dependencies=[READ])
async def pinned_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _run(StaffingService(session).catalogue_view(project_id))


# ── plan ───────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/plan", dependencies=[READ])
async def get_plan(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """The plan header. Catches up with a governance approval whose event did not arrive."""
    await verify_project_access(project_id, user_id, session)
    return await _run(StaffingService(session).plan_view(project_id, _actor(user_id, payload)))


@router.put("/projects/{project_id}/plan", status_code=201, dependencies=[EDIT])
async def set_plan(
    project_id: uuid.UUID, body: PlanSet, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(
        svc.set_plan(
            project_id,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
            catalogue_source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            catalogue_version=body.catalogue_version,
            requires_accommodation=body.requires_accommodation,
            commissioning_date=body.commissioning_date,
        )
    )
    return await _run(svc.plan_view(project_id, _actor(user_id, payload)))


@router.patch("/projects/{project_id}/plan", dependencies=[EDIT])
async def patch_plan(
    project_id: uuid.UUID, body: PlanPatch, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(svc.patch_plan(project_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _run(svc.plan_view(project_id, _actor(user_id, payload)))


@router.post("/projects/{project_id}/plan/catalogue", dependencies=[EDIT])
async def change_catalogue(
    project_id: uuid.UUID,
    body: CatalogueChange,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Re-pin the catalogue with a role mapping; unmapped positions become ``custom`` (rule 21)."""
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(
        svc.change_catalogue(
            project_id,
            actor_id=_uid(user_id),
            tenant_id=resolve_tenant_id(payload),
            catalogue_source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            catalogue_version=body.catalogue_version,
            role_mapping=body.role_mapping,
        )
    )
    return await _run(svc.plan_view(project_id, _actor(user_id, payload)))


@router.post("/projects/{project_id}/plan/catalogue/preview", dependencies=[EDIT])
async def preview_catalogue_change(
    project_id: uuid.UUID,
    body: CatalogueChange,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """What the catalogue change would do to each position, computed by the function the change uses. Read only."""
    await verify_project_access(project_id, user_id, session)
    return await _run(
        StaffingService(session).preview_catalogue_change(
            project_id,
            tenant_id=resolve_tenant_id(payload),
            catalogue_source=body.catalogue_source,
            catalogue_id=body.catalogue_id,
            catalogue_version=body.catalogue_version,
            role_mapping=body.role_mapping,
        )
    )


@router.post("/projects/{project_id}/plan/submit", dependencies=[EDIT])
async def submit_plan(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Draft or revising -> in review (rule 6). Approval is the governance gate of the hosting area."""
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(svc.submit(project_id, _uid(user_id)))
    return await _run(svc.plan_view(project_id, _actor(user_id, payload)))


@router.post("/projects/{project_id}/plan/approve", dependencies=[Depends(RequirePermission(MANAGE))])
async def approve_plan(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """In review -> binding by hand, on a project without gates. With gates the gate decision approves."""
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(svc.approve_by_hand(project_id, _uid(user_id)))
    return await _run(svc.plan_view(project_id, _actor(user_id, payload)))


@router.post("/projects/{project_id}/plan/return", dependencies=[EDIT])
async def return_plan(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(svc.return_plan(project_id, _uid(user_id)))
    return await _run(svc.plan_view(project_id, _actor(user_id, payload)))


@router.get("/projects/{project_id}/plan/findings", dependencies=[READ])
async def plan_findings(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """What submission would refuse right now (rule 6 plus rules 1 and 4).

    These findings are about the plan: positions, FTE, dates, handovers. None reads a personnel file, so
    nothing is withheld from a reader of the plan and ``restricted_people`` is 0. Findings about a
    person's documents are served by ``/validation``, which withholds them by rule 13.
    """
    await verify_project_access(project_id, user_id, session)
    found = await _run(StaffingService(session).submission_findings(project_id))
    return _page([f.as_dict() for f in found], restricted_people=0)


# ── positions ──────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/positions", dependencies=[READ])
async def list_positions(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(StaffingService(session).position_views(project_id, _actor(user_id, payload))))


async def _position_view(
    svc: StaffingService, project_id: uuid.UUID, position_id: uuid.UUID, actor: Actor | None = None
) -> dict[str, Any]:
    return next(v for v in await svc.position_views(project_id, actor) if v["id"] == str(position_id))


@router.post("/projects/{project_id}/positions", status_code=201, dependencies=[EDIT])
async def create_position(
    project_id: uuid.UUID, body: PositionIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Create a position. Naming its line manager (``owner_user_id``) needs ``staffing.personnel.assign`` or
    the hosting area's owner; planning it against the catalogue's key-role flags needs ``staffing.manage``."""
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    row = await _run(svc.create_position(project_id, body.model_dump(), actor))
    return await _position_view(svc, project_id, row.id, actor)


@router.post("/projects/{project_id}/positions/from-catalogue", status_code=201, dependencies=[EDIT])
async def positions_from_catalogue(
    project_id: uuid.UUID,
    body: PositionsFromCatalogue,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    rows = await _run(svc.positions_from_catalogue(project_id, body.phase, body.role_codes, body.entry_date, actor))
    ids = {str(r.id) for r in rows}
    return _page([v for v in await svc.position_views(project_id, actor) if v["id"] in ids])


@router.patch("/projects/{project_id}/positions/{position_id}", dependencies=[EDIT])
async def update_position(
    project_id: uuid.UUID,
    position_id: uuid.UUID,
    body: PositionPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Edit a position. ``owner_user_id`` and the gate fields (``key_role``, ``required_before``,
    ``handover_role``) are guarded as on create; the gate fields also stand still outside ``open``."""
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    await _run(svc.update_position(project_id, position_id, body.model_dump(exclude_unset=True), actor))
    return await _position_view(svc, project_id, position_id, actor)


@router.post("/projects/{project_id}/positions/{position_id}/resource-request", dependencies=[EDIT])
async def request_resource(
    project_id: uuid.UUID, position_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Open one request in the resources module for a recruiting position; its id is kept on the position."""
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(svc.request_resource(project_id, position_id, _uid(user_id)))
    return await _position_view(svc, project_id, position_id)


@router.post("/projects/{project_id}/positions/{position_id}/status", dependencies=[EDIT])
async def set_position_status(
    project_id: uuid.UUID, position_id: uuid.UUID, body: PositionStatusIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """open / recruiting / on_hold / cancelled. ``filled`` is derived and refused (rule 2)."""
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(svc.set_position_status(project_id, position_id, body.status, _uid(user_id)))
    return await _position_view(svc, project_id, position_id)


@router.delete("/projects/{project_id}/positions/{position_id}", status_code=204, dependencies=[EDIT])
async def delete_position(
    project_id: uuid.UUID, position_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(StaffingService(session).delete_position(project_id, position_id, _uid(user_id)))
    return Response(status_code=204)


# ── fills ──────────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/positions/{position_id}/fills", status_code=201, dependencies=[EDIT])
async def create_fill(
    project_id: uuid.UUID, position_id: uuid.UUID, body: FillIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    row = await _run(svc.create_fill(project_id, position_id, body.model_dump(), _uid(user_id)))
    view = await _position_view(svc, project_id, position_id)
    return next(f for f in view["fills"] if f["id"] == str(row.id))


@router.post("/projects/{project_id}/fills/{fill_id}/confirm", dependencies=[EDIT])
async def confirm_fill(
    project_id: uuid.UUID, fill_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Rule 4: refused with ``person_overallocated`` past 1.0 FTE on any day; cross-project load and a
    missing bed on a remote site warn. The position's own line manager does not confirm it."""
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    fill, warnings = await _run(svc.confirm_fill(project_id, fill_id, _actor(user_id, payload)))
    view = await _position_view(svc, project_id, fill.position_id)
    return {"fill": next(f for f in view["fills"] if f["id"] == str(fill.id)), "warnings": warnings}


@router.post("/projects/{project_id}/fills/{fill_id}/end", dependencies=[EDIT])
async def end_fill(
    project_id: uuid.UUID, fill_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """End a confirmed fill today. No body: the day is the server's."""
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    fill = await _run(svc.end_fill(project_id, fill_id, _uid(user_id)))
    view = await _position_view(svc, project_id, fill.position_id)
    return next(f for f in view["fills"] if f["id"] == str(fill.id))


@router.delete("/projects/{project_id}/fills/{fill_id}", status_code=204, dependencies=[EDIT])
async def delete_fill(
    project_id: uuid.UUID, fill_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(StaffingService(session).delete_fill(project_id, fill_id, _uid(user_id)))
    return Response(status_code=204)


# ── handovers ──────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/handovers", dependencies=[READ])
async def list_handovers(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(StaffingService(session).handover_views(project_id)))


@router.post("/projects/{project_id}/handovers", status_code=201, dependencies=[EDIT])
async def create_handover(
    project_id: uuid.UUID, body: HandoverIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    row = await _run(svc.create_handover(project_id, body.model_dump(), _uid(user_id)))
    return next(h for h in await svc.handover_views(project_id) if h["id"] == str(row.id))


@router.patch("/projects/{project_id}/handovers/{handover_id}", dependencies=[EDIT])
async def update_handover(
    project_id: uuid.UUID, handover_id: uuid.UUID, body: HandoverPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    await _run(svc.update_handover(project_id, handover_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return next(h for h in await svc.handover_views(project_id) if h["id"] == str(handover_id))


@router.delete("/projects/{project_id}/handovers/{handover_id}", status_code=204, dependencies=[EDIT])
async def delete_handover(
    project_id: uuid.UUID, handover_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(StaffingService(session).delete_handover(project_id, handover_id, _uid(user_id)))
    return Response(status_code=204)


# ── views over the plan ────────────────────────────────────────────────────


@router.get("/projects/{project_id}/org-chart", dependencies=[READ])
async def org_chart(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    return await _run(StaffingService(session).org_chart(project_id))


@router.get("/projects/{project_id}/compliance", dependencies=[READ])
async def compliance(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """People x document kinds, status only. Cells only for people whose file the caller may open (rule 13);
    for everybody else the counts per document kind in ``summary``."""
    await verify_project_access(project_id, user_id, session)
    body = await _run(StaffingService(session).compliance_matrix(project_id, _actor(user_id, payload)))
    return {**body, "offset": 0, "limit": body["total"]}


@router.get("/projects/{project_id}/planned-vs-actual", dependencies=[READ])
async def planned_vs_actual(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Working FTE-days planned per position vs field time of the linked resources, both on the project's
    calendar (rule 19, read only)."""
    await verify_project_access(project_id, user_id, session)
    return _page(await _run(StaffingService(session).planned_vs_actual(project_id)))


@router.get("/projects/{project_id}/readiness", dependencies=[READ])
async def readiness(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, gate_code: str = Query(..., max_length=64)
) -> dict[str, Any]:
    """What the governance gate ``gate_code`` reads of the staffing plan (read only)."""
    await verify_project_access(project_id, user_id, session)
    return await _run(StaffingService(session).readiness(project_id, gate_code))


@router.get("/projects/{project_id}/validation", response_model=Page[FindingOut], dependencies=[READ])
async def validation(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext
    from app.modules.staffing.validators import STAFFING_RULES

    await verify_project_access(project_id, user_id, session)
    data = await _run(StaffingService(session).validation_payload(project_id, _actor(user_id, payload)))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    findings: list[FindingOut] = []
    for rule_cls in STAFFING_RULES:
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
    # People whose document findings are withheld from this caller (rule 13): the list is not the whole picture.
    return _page(findings, restricted_people=data["restricted_people"])


@router.get("/projects/{project_id}/export", dependencies=[READ])
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    what: Literal["plan", "org_chart", "compliance"] = "plan",
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
) -> Response:
    """Staffing plan, organisation chart or compliance matrix. No personal data beyond names (rule 20)."""
    from app.modules.projects.models import Project
    from app.modules.staffing import export as ex

    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    catalogue = await _run(svc.catalogue_for(await _run(svc.require_plan(project_id))))
    project = await session.get(Project, project_id)
    labels = {
        "catalogue": catalogue,
        "project_name": getattr(project, "name", "") or "",
        "locale": get_locale() or "en",
    }
    if what == "org_chart":
        doc = ex.org_chart_document(await _run(svc.org_chart(project_id)), **labels)
    elif what == "compliance":
        # The same actor-aware matrix as the screen: no cell the caller could not open the file for.
        doc = ex.compliance_document(await _run(svc.compliance_matrix(project_id, _actor(user_id, payload))), **labels)
    else:
        doc = ex.plan_document(await _run(svc.position_views(project_id)), **labels)
    return _file(ex.render(doc, fmt), fmt, f"staffing_{what}", labels["locale"])


# ── personnel files (rule 13 in the service) ───────────────────────────────


@router.get("/projects/{project_id}/personnel-files", dependencies=[READ])
async def list_files(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Names, roles, dates, cleared flag and ``can_open`` only; no document fields."""
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    items = await _run(svc.file_list(project_id, actor))
    return _page(items, candidates=await _run(svc.file_candidates(project_id, actor)))


@router.post("/projects/{project_id}/personnel-files", status_code=201, dependencies=[READ])
async def create_file(
    project_id: uuid.UUID, body: FileIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    row = await _run(svc.create_file(project_id, body.model_dump(), actor))
    return await _run(svc.file_view(project_id, row, actor))


@router.get("/projects/{project_id}/personnel-files/{file_id}", dependencies=[READ])
async def get_file(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """The file; every read writes a ``personnel_file.read`` audit row."""
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    pfile = await _run(svc.open_file(project_id, file_id, actor))
    return await _run(svc.file_view(project_id, pfile, actor))


@router.get("/projects/{project_id}/personnel-files/{file_id}/access-log", dependencies=[READ])
async def file_access_log(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = StaffingService(session)
    pfile = await _run(svc.open_file(project_id, file_id, _actor(user_id, payload)))
    return _page(await _run(svc.access_log(project_id, pfile)))


@router.get("/projects/{project_id}/personnel-files/{file_id}/export", dependencies=[READ])
async def export_own_file(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
) -> Response:
    """The person's own file, to that person only (GDPR Art. 15 and 20). No bulk export exists."""
    from app.modules.staffing import export as ex

    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    pfile = await _run(svc.open_file(project_id, file_id, actor))
    await _run(svc.require_own_file(project_id, pfile, actor))
    view = await _run(svc.file_view(project_id, pfile, actor))
    catalogue = await _run(svc.catalogue_for(await _run(svc.require_plan(project_id))))
    locale = get_locale() or "en"
    doc = ex.own_file_document(view, catalogue=catalogue, locale=locale)
    return _file(ex.render(doc, fmt), fmt, "personnel_file", locale)


@router.patch("/projects/{project_id}/personnel-files/{file_id}", dependencies=[READ])
async def update_file(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    body: FilePatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    pfile = await _run(svc.update_file(project_id, file_id, body.model_dump(exclude_unset=True), actor))
    return await _run(svc.file_view(project_id, pfile, actor))


@router.post("/projects/{project_id}/personnel-files/{file_id}/end", dependencies=[READ])
async def end_file(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """The assignment ends today and retention starts. No body: a date from the client could place the
    retention end in the past. A file that is not ``active`` answers 409 ``file_not_active``."""
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    pfile = await _run(svc.end_file(project_id, file_id, actor))
    return await _run(svc.file_view(project_id, pfile, actor))


@router.post("/projects/{project_id}/personnel-files/{file_id}/hold", dependencies=[READ])
async def hold_file(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    body: RationaleIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Legal hold on an ended file: blocks the retention end until released."""
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    pfile = await _run(svc.hold_file(project_id, file_id, body.rationale, actor))
    return await _run(svc.file_view(project_id, pfile, actor))


@router.post("/projects/{project_id}/personnel-files/{file_id}/release", dependencies=[READ])
async def release_file(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    pfile = await _run(svc.release_file(project_id, file_id, actor))
    return await _run(svc.file_view(project_id, pfile, actor))


@router.post("/projects/{project_id}/personnel-files/{file_id}/erase", dependencies=[READ])
async def erase_file(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    body: RationaleIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Erasure request (Art. 17), ``staffing.personnel.erase`` only; refused with
    ``retention_obligation_active`` while a statutory duty runs."""
    await verify_project_access(project_id, user_id, session)
    pfile = await _run(
        StaffingService(session).erase_file(project_id, file_id, body.rationale, _actor(user_id, payload))
    )
    return {
        "id": str(pfile.id),
        "status": pfile.status,
        "anonymised_at": pfile.anonymised_at and pfile.anonymised_at.isoformat(),
    }


# ── documents ──────────────────────────────────────────────────────────────


async def _document_view(svc: StaffingService, project_id: uuid.UUID, pfile: Any, kind: str, actor: Actor) -> dict:
    view = await svc.file_view(project_id, pfile, actor)
    return next(d for d in view["documents"] if d["document_kind"] == kind)


@router.post("/projects/{project_id}/personnel-files/{file_id}/documents", dependencies=[READ])
async def record_document(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    body: DocumentLink,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Record a document of this person: kind, validity window, last 4 of the number. The validity record
    is created by the service; ``number_last4`` longer than 4 is ``full_number_rejected`` (rule 12)."""
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    row = await _run(svc.record_document(project_id, file_id, body.model_dump(), actor))
    pfile = await _run(svc.open_file(project_id, file_id, actor, edit=True))
    return await _run(_document_view(svc, project_id, pfile, row.document_kind, actor))


@router.post("/projects/{project_id}/personnel-files/{file_id}/documents/{document_id}/verify", dependencies=[READ])
async def verify_document(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    row = await _run(svc.verify_document(project_id, file_id, document_id, actor))
    pfile = await _run(svc.open_file(project_id, file_id, actor, edit=True))
    return await _run(_document_view(svc, project_id, pfile, row.document_kind, actor))


@router.post("/projects/{project_id}/personnel-files/{file_id}/documents/{document_kind}/waive", dependencies=[READ])
async def waive_document(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    document_kind: str,
    body: RationaleIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc, actor = StaffingService(session), _actor(user_id, payload)
    row = await _run(svc.waive_document(project_id, file_id, document_kind, body.rationale, actor))
    pfile = await _run(svc.open_file(project_id, file_id, actor, edit=True))
    return await _run(_document_view(svc, project_id, pfile, row.document_kind, actor))


# ── travel ─────────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/personnel-files/{file_id}/travel", status_code=201, dependencies=[READ])
async def create_travel(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    body: TravelIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    from app.modules.staffing.service import _travel_view

    await verify_project_access(project_id, user_id, session)
    row = await _run(
        StaffingService(session).create_travel(project_id, file_id, body.model_dump(), _actor(user_id, payload))
    )
    return _travel_view(row)


@router.patch("/projects/{project_id}/personnel-files/{file_id}/travel/{travel_id}", dependencies=[READ])
async def update_travel(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    travel_id: uuid.UUID,
    body: TravelPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    from app.modules.staffing.service import _travel_view

    await verify_project_access(project_id, user_id, session)
    row = await _run(
        StaffingService(session).update_travel(
            project_id, file_id, travel_id, body.model_dump(exclude_unset=True), _actor(user_id, payload)
        )
    )
    return _travel_view(row)


@router.post("/projects/{project_id}/personnel-files/{file_id}/travel/{travel_id}/status", dependencies=[READ])
async def set_travel_status(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    travel_id: uuid.UUID,
    body: StatusIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    from app.modules.staffing.service import _travel_view

    await verify_project_access(project_id, user_id, session)
    row = await _run(
        StaffingService(session).update_travel(
            project_id, file_id, travel_id, {"status": body.status}, _actor(user_id, payload)
        )
    )
    return _travel_view(row)


@router.delete(
    "/projects/{project_id}/personnel-files/{file_id}/travel/{travel_id}", status_code=204, dependencies=[READ]
)
async def delete_travel(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    travel_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(StaffingService(session).delete_travel(project_id, file_id, travel_id, _actor(user_id, payload)))
    return Response(status_code=204)


# ── leave ──────────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/personnel-files/{file_id}/leave", status_code=201, dependencies=[READ])
async def create_leave(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    body: LeaveIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Type and dates only; overlap with a mobilisation or a key-role gate warns (rule 16)."""
    from app.modules.staffing.service import _leave_view

    await verify_project_access(project_id, user_id, session)
    row, warnings = await _run(
        StaffingService(session).create_leave(project_id, file_id, body.model_dump(), _actor(user_id, payload))
    )
    return {**_leave_view(row), "warnings": warnings}


@router.patch("/projects/{project_id}/personnel-files/{file_id}/leave/{leave_id}", dependencies=[READ])
async def update_leave(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    leave_id: uuid.UUID,
    body: LeavePatch,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    from app.modules.staffing.service import _leave_view

    await verify_project_access(project_id, user_id, session)
    row = await _run(
        StaffingService(session).update_leave(
            project_id, file_id, leave_id, body.model_dump(exclude_unset=True), _actor(user_id, payload)
        )
    )
    return _leave_view(row)


@router.post("/projects/{project_id}/personnel-files/{file_id}/leave/{leave_id}/status", dependencies=[READ])
async def set_leave_status(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    leave_id: uuid.UUID,
    body: StatusIn,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """approved / taken / cancelled."""
    from app.modules.staffing.service import _leave_view

    await verify_project_access(project_id, user_id, session)
    row = await _run(
        StaffingService(session).set_leave_status(project_id, file_id, leave_id, body.status, _actor(user_id, payload))
    )
    return _leave_view(row)


@router.delete(
    "/projects/{project_id}/personnel-files/{file_id}/leave/{leave_id}", status_code=204, dependencies=[READ]
)
async def delete_leave(
    project_id: uuid.UUID,
    file_id: uuid.UUID,
    leave_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _run(StaffingService(session).delete_leave(project_id, file_id, leave_id, _actor(user_id, payload)))
    return Response(status_code=204)


# ── upcoming ───────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/upcoming", dependencies=[READ])
async def upcoming(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    days: int = Query(90, ge=1, le=365),
) -> dict[str, Any]:
    """Expiring documents, mobilisations in 14 days and leave, limited to files the caller may open."""
    await verify_project_access(project_id, user_id, session)
    return await _run(StaffingService(session).upcoming(project_id, _actor(user_id, payload), days))
