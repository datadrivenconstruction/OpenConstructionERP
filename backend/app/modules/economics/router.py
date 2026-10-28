# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Economics API, mounted at ``/api/v1/economics``.

Every route lives under ``/projects/{project_id}/...`` and calls
``verify_project_access`` before it reads anything, so a project the caller
cannot see answers 404 exactly like a missing one. Child rows are looked up by
``(project_id, id)``, so an id from another project is also 404.

Errors carry ``{"code", "message_key", "message", "violations"?, "info"?}`` in
``detail``; ``message_key`` is ``economics.errors.<code>``. 404 = not found or
not visible, 403 = permission, 409 = state conflict (plan not editable, nothing
proposed, change request required), 422 = invalid input or a refusing rule
(a proposal with open errors).

There is no approve route for a project that uses gates: the governance gate
approves and this module mirrors it. ``POST .../approve`` exists for a project
without gates and answers 409 ``approved_by_gate_decision`` otherwise.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.economics.errors import EconomicsError
from app.modules.economics.messages import translate
from app.modules.economics.schemas import (
    FlowLineIn,
    FlowLinePatch,
    FrameGenerateIn,
    FrameLineIn,
    FrameLinePatch,
    InsuranceIn,
    InsurancePatch,
    PlanPatch,
    ProcessArea,
    ProcessIn,
    ProposeIn,
    ReopenIn,
    SecurityIn,
    SecurityPatch,
    SourceIn,
    SourcePatch,
    TaxIn,
    TrancheIn,
    TranchePatch,
)
from app.modules.economics.service import EconomicsService

router = APIRouter(tags=["economics"])

_P = "/projects/{project_id}"
READ = Depends(RequirePermission("economics.read"))
EDIT = Depends(RequirePermission("economics.edit"))
MANAGE = Depends(RequirePermission("economics.manage"))


def _has(payload: dict[str, Any], permission: str) -> bool:
    """Does the caller hold ``permission``? The same answer :class:`RequirePermission` gives."""
    from app.core.permissions import permission_registry

    if permission in (payload.get("permissions") or []):
        return True
    return permission_registry.role_has_permission(payload.get("role", ""), permission)


async def _run[T](awaitable: Any) -> T:
    """Turn an :class:`EconomicsError` (or a store error from governance) into the documented HTTP error."""
    from app.modules.project_governance.errors import GovernanceError

    try:
        return await awaitable
    except EconomicsError as exc:
        message = translate(f"economics.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc
    except GovernanceError as exc:
        err = EconomicsError(exc.code, exc.status_code, violations=exc.violations, detail=exc.detail)
        message = translate(f"economics.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=err.as_detail(message)) from exc


def _uid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(user_id))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid subject") from exc


async def _economics_svc(project_id: uuid.UUID, user_id: str, session: Any) -> EconomicsService:
    await verify_project_access(project_id, user_id, session)
    return EconomicsService(session)


def _page(items: list[Any], **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": len(items), "offset": 0, "limit": len(items), **extra}


async def _plan_out(svc: EconomicsService, project_id: uuid.UUID, payload: dict[str, Any]) -> dict[str, Any]:
    return await _run(
        svc.plan_view(
            project_id,
            actor_id=_uid(str(payload.get("sub"))) if payload.get("sub") else None,
            can_edit=_has(payload, "economics.edit"),
            can_manage=_has(payload, "economics.manage"),
        )
    )


# ── plan ───────────────────────────────────────────────────────────────────


@router.get(_P + "/plan", dependencies=[READ])
async def get_plan(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    return await _plan_out(svc, project_id, payload)


@router.put(_P + "/plan", status_code=201, dependencies=[MANAGE])
async def start_plan(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.start(project_id, _uid(user_id)))
    return await _plan_out(svc, project_id, payload)


@router.patch(_P + "/plan", dependencies=[EDIT])
async def patch_plan(
    project_id: uuid.UUID, body: PlanPatch, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.patch_plan(project_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _plan_out(svc, project_id, payload)


# ── business case ──────────────────────────────────────────────────────────


@router.get(_P + "/business-case", dependencies=[READ])
async def get_business_case(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    return await _run(svc.business_case(project_id))


@router.post(_P + "/business-case/lines", status_code=201, dependencies=[EDIT])
async def add_flow_line(
    project_id: uuid.UUID, body: FlowLineIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.add_flow_line(project_id, body.model_dump(), _uid(user_id)))
    return await _run(svc.business_case(project_id))


@router.patch(_P + "/business-case/lines/{line_id}", dependencies=[EDIT])
async def patch_flow_line(
    project_id: uuid.UUID, line_id: uuid.UUID, body: FlowLinePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.patch_flow_line(project_id, line_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _run(svc.business_case(project_id))


@router.delete(_P + "/business-case/lines/{line_id}", dependencies=[EDIT])
async def delete_flow_line(
    project_id: uuid.UUID, line_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.delete_flow_line(project_id, line_id, _uid(user_id)))
    return await _run(svc.business_case(project_id))


# ── cost frame ─────────────────────────────────────────────────────────────


@router.get(_P + "/cost-frame", dependencies=[READ])
async def get_cost_frame(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    return await _run(svc.cost_frame(project_id))


@router.post(_P + "/cost-frame/lines", status_code=201, dependencies=[EDIT])
async def add_frame_line(
    project_id: uuid.UUID, body: FrameLineIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.add_frame_line(project_id, body.model_dump(), _uid(user_id)))
    return await _run(svc.cost_frame(project_id))


@router.patch(_P + "/cost-frame/lines/{line_id}", dependencies=[EDIT])
async def patch_frame_line(
    project_id: uuid.UUID, line_id: uuid.UUID, body: FrameLinePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.patch_frame_line(project_id, line_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _run(svc.cost_frame(project_id))


@router.delete(_P + "/cost-frame/lines/{line_id}", dependencies=[EDIT])
async def delete_frame_line(
    project_id: uuid.UUID, line_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.delete_frame_line(project_id, line_id, _uid(user_id)))
    return await _run(svc.cost_frame(project_id))


@router.post(_P + "/cost-frame/generate", dependencies=[EDIT])
async def generate_frame(
    project_id: uuid.UUID, body: FrameGenerateIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Derive frame lines from the classification codes the project's bill uses."""
    svc = await _economics_svc(project_id, user_id, session)
    await _run(
        svc.generate_frame(
            project_id, depth=body.depth, amounts=body.amounts, replace=body.replace, actor_id=_uid(user_id)
        )
    )
    return await _run(svc.cost_frame(project_id))


# ── financing ──────────────────────────────────────────────────────────────


@router.get(_P + "/financing", dependencies=[READ])
async def get_financing(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    return await _run(svc.financing(project_id))


@router.post(_P + "/financing/sources", status_code=201, dependencies=[EDIT])
async def add_source(
    project_id: uuid.UUID, body: SourceIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.add_source(project_id, body.model_dump(), _uid(user_id)))
    return await _run(svc.financing(project_id))


@router.patch(_P + "/financing/sources/{source_id}", dependencies=[EDIT])
async def patch_source(
    project_id: uuid.UUID, source_id: uuid.UUID, body: SourcePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.patch_source(project_id, source_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _run(svc.financing(project_id))


@router.delete(_P + "/financing/sources/{source_id}", dependencies=[EDIT])
async def delete_source(
    project_id: uuid.UUID, source_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.delete_source(project_id, source_id, _uid(user_id)))
    return await _run(svc.financing(project_id))


@router.post(_P + "/financing/sources/{source_id}/tranches", status_code=201, dependencies=[EDIT])
async def add_tranche(
    project_id: uuid.UUID, source_id: uuid.UUID, body: TrancheIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.add_tranche(project_id, source_id, body.model_dump(), _uid(user_id)))
    return await _run(svc.financing(project_id))


@router.patch(_P + "/financing/tranches/{tranche_id}", dependencies=[EDIT])
async def patch_tranche(
    project_id: uuid.UUID, tranche_id: uuid.UUID, body: TranchePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.patch_tranche(project_id, tranche_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _run(svc.financing(project_id))


@router.delete(_P + "/financing/tranches/{tranche_id}", dependencies=[EDIT])
async def delete_tranche(
    project_id: uuid.UUID, tranche_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.delete_tranche(project_id, tranche_id, _uid(user_id)))
    return await _run(svc.financing(project_id))


# ── lifecycle, readiness, validation ───────────────────────────────────────


@router.post(_P + "/propose", dependencies=[MANAGE])
async def propose(
    project_id: uuid.UUID, body: ProposeIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.propose(project_id, body.rationale, _uid(user_id)))
    return await _plan_out(svc, project_id, payload)


@router.post(_P + "/withdraw", dependencies=[MANAGE])
async def withdraw(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.withdraw(project_id, _uid(user_id)))
    return await _plan_out(svc, project_id, payload)


@router.post(_P + "/approve", dependencies=[MANAGE])
async def approve(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """Approve by hand: only on a project without gates, and never by the person who proposed under four-eyes."""
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.approve_by_hand(project_id, _uid(user_id)))
    return await _plan_out(svc, project_id, payload)


@router.post(_P + "/reopen", dependencies=[MANAGE])
async def reopen(
    project_id: uuid.UUID, body: ReopenIn, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.reopen(project_id, _uid(user_id), body.reason))
    return await _plan_out(svc, project_id, payload)


@router.post(_P + "/reopen/close", dependencies=[MANAGE])
async def close_reopening(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.close_reopening(project_id, _uid(user_id)))
    return await _plan_out(svc, project_id, payload)


@router.get(_P + "/readiness", dependencies=[READ])
async def readiness(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """What the governance gate reads for the commercial area (read only)."""
    svc = await _economics_svc(project_id, user_id, session)
    return await _run(svc.readiness(project_id))


@router.get(_P + "/validation", dependencies=[READ])
async def validation(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    from app.core.validation.engine import ValidationContext
    from app.modules.economics.validators import ECONOMICS_RULES

    svc = await _economics_svc(project_id, user_id, session)
    data = await _run(svc.validation_payload(project_id))
    context = ValidationContext(data=data, metadata={"locale": get_locale() or "en"})
    findings: list[dict[str, Any]] = []
    for rule_cls in ECONOMICS_RULES:
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


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(_P + "/export", dependencies=[READ])
async def export(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    what: Literal["frame", "case", "financing"] = "frame",
    fmt: Literal["pdf", "xlsx"] = Query("pdf", alias="format"),
) -> Response:
    """The cost frame, the business case or the financing plan as a printable document."""
    from app.core.regional_format import document_country
    from app.modules.economics import export as ex
    from app.modules.projects.models import Project

    svc = await _economics_svc(project_id, user_id, session)
    locale = get_locale() or "en"
    project = await session.get(Project, project_id)
    labels = {
        "project_name": getattr(project, "name", "") or "",
        "locale": locale,
        "country": document_country(
            getattr(project, "country_code", None), getattr(project, "region", None), getattr(project, "currency", None)
        ),
    }
    if what == "case":
        doc = ex.case_document(await _run(svc.business_case(project_id)), **labels)
    elif what == "financing":
        doc = ex.financing_document(await _run(svc.financing(project_id)), **labels)
    else:
        doc = ex.frame_document(await _run(svc.cost_frame(project_id)), **labels)
    return Response(
        content=ex.render(doc, fmt),
        media_type="application/pdf" if fmt == "pdf" else _XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="economics_{what}.{fmt}"',
            "Content-Language": locale,
        },
    )


# ── registers: securities, insurance, tax treatment, process set-up ────────


@router.get(_P + "/registers", dependencies=[READ])
async def get_registers(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    return await _run(svc.registers(project_id))


@router.post(_P + "/registers/securities", status_code=201, dependencies=[EDIT])
async def add_security(
    project_id: uuid.UUID, body: SecurityIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.add_security(project_id, body.model_dump(), _uid(user_id)))
    return await _run(svc.registers(project_id))


@router.patch(_P + "/registers/securities/{row_id}", dependencies=[EDIT])
async def patch_security(
    project_id: uuid.UUID, row_id: uuid.UUID, body: SecurityPatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.patch_security(project_id, row_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _run(svc.registers(project_id))


@router.delete(_P + "/registers/securities/{row_id}", dependencies=[EDIT])
async def delete_security(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.delete_security(project_id, row_id, _uid(user_id)))
    return await _run(svc.registers(project_id))


@router.post(_P + "/registers/insurances", status_code=201, dependencies=[EDIT])
async def add_insurance(
    project_id: uuid.UUID, body: InsuranceIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.add_insurance(project_id, body.model_dump(), _uid(user_id)))
    return await _run(svc.registers(project_id))


@router.patch(_P + "/registers/insurances/{row_id}", dependencies=[EDIT])
async def patch_insurance(
    project_id: uuid.UUID, row_id: uuid.UUID, body: InsurancePatch, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.patch_insurance(project_id, row_id, body.model_dump(exclude_unset=True), _uid(user_id)))
    return await _run(svc.registers(project_id))


@router.delete(_P + "/registers/insurances/{row_id}", dependencies=[EDIT])
async def delete_insurance(
    project_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.delete_insurance(project_id, row_id, _uid(user_id)))
    return await _run(svc.registers(project_id))


@router.put(_P + "/registers/tax", dependencies=[EDIT])
async def put_tax(project_id: uuid.UUID, body: TaxIn, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.put_tax(project_id, body.model_dump(), _uid(user_id)))
    return await _run(svc.registers(project_id))


@router.put(_P + "/registers/process/{area}", dependencies=[EDIT])
async def put_process(
    project_id: uuid.UUID, area: ProcessArea, body: ProcessIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    svc = await _economics_svc(project_id, user_id, session)
    await _run(svc.put_process(project_id, area, body.model_dump(), _uid(user_id)))
    return await _run(svc.registers(project_id))
