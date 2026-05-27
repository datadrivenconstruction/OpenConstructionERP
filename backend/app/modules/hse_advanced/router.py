"""‌⁠‍HSE Advanced API routes — JSA, PTW, toolbox, PPE, audits, CAPA, KPI."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.hse_advanced.schemas import (
    AuditCreate,
    AuditFindingCreate,
    AuditFindingResponse,
    AuditResponse,
    AuditUpdate,
    CAPACreate,
    CAPAEffectivenessPayload,
    CAPAFiveWhysPayload,
    CAPAResponse,
    CAPAUpdate,
    CAPAVerificationPayload,
    CATransitionRequest,
    CertificationCreate,
    CertificationResponse,
    CertificationUpdate,
    CorrectiveActionCreate,
    CorrectiveActionResponse,
    HSEDashboardResponse,
    IncidentEscalationMatrix,
    InvestigationCreate,
    InvestigationResponse,
    InvestigationUpdate,
    JSACreate,
    JSAResponse,
    JSATemplateCloneRequest,
    JSATemplateCreate,
    JSATemplateResponse,
    JSATemplateUpdate,
    JSAUpdate,
    KPIResponse,
    PermitApprovalPayload,
    PermitClosurePayload,
    PermitCreate,
    PermitDashboardEntry,
    PermitDashboardResponse,
    PermitPrerequisitesPayload,
    PermitPrerequisiteStatus,
    PermitResponse,
    PermitUpdate,
    PPEIssueCreate,
    PPEIssueResponse,
    PPEIssueUpdate,
    ToolboxAttendanceEntry,
    ToolboxAttendanceResponse,
    ToolboxTalkCreate,
    ToolboxTalkResponse,
    ToolboxTalkUpdate,
    ToolboxTopicCreate,
    ToolboxTopicResponse,
    ToolboxTopicUpdate,
)
from app.modules.hse_advanced.service import (
    HSEAdvancedService,
    compute_ltifr,
    compute_trir,
    incident_escalation_matrix,
)

router = APIRouter()


def _get_service(session: SessionDep) -> HSEAdvancedService:
    return HSEAdvancedService(session)


async def _guard_project(
    project_id: uuid.UUID | None,
    user_id: str | None,
    session: SessionDep,
) -> None:
    """Verify cross-project access on a HSE row's ``project_id``.

    Round-3 Wave F audit found that ``RequirePermission(...)`` only checks
    role/permission scope — it does NOT prove the caller has access to the
    *specific* project the row belongs to. Without this guard, any user
    holding ``hse_advanced.update`` could PATCH / DELETE / state-transition
    a JSA / permit / audit / CAPA on a project they cannot otherwise see,
    by guessing or scraping a UUID. ``verify_project_access`` returns 404
    on both "missing" and "denied" so the response is opaque to attackers.
    """
    if project_id is None:
        return
    await verify_project_access(project_id, user_id, session)


# ── Investigations ─────────────────────────────────────────────────────────


@router.get("/investigations/", response_model=list[InvestigationResponse])
async def list_investigations(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    incident_ref: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[InvestigationResponse]:
    """‌⁠‍List investigations, optionally scoped to a project or incident.

    The HSE Advanced dashboard surfaces a "project's investigations" view
    even though investigations are keyed by ``incident_ref`` rather than
    by ``project_id`` directly. We resolve this either through an
    ``incident_ref`` filter (single incident drill-down) or through a
    join on the safety module's incident table when ``project_id`` is
    supplied (HSE dashboard view).
    """
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
        rows, _ = await service.investigation_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )
    elif incident_ref is not None:
        rows, _ = await service.investigation_repo.list_for_incident(
            incident_ref,
            offset=offset,
            limit=limit,
        )
    else:
        # No scope provided — return empty list rather than 422 so the
        # dashboard renders cleanly when no project is active.
        return []
    return [InvestigationResponse.model_validate(r) for r in rows]


@router.post(
    "/investigations/",
    response_model=InvestigationResponse,
    status_code=201,
)
async def create_investigation(
    data: InvestigationCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> InvestigationResponse:
    """‌⁠‍Create a root-cause investigation for an incident."""
    obj = await service.create_investigation(data, user_id=user_id)
    return InvestigationResponse.model_validate(obj)


@router.get("/investigations/{item_id}", response_model=InvestigationResponse)
async def get_investigation(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> InvestigationResponse:
    obj = await service.get_investigation(item_id)
    return InvestigationResponse.model_validate(obj)


@router.patch("/investigations/{item_id}", response_model=InvestigationResponse)
async def update_investigation(
    item_id: uuid.UUID,
    data: InvestigationUpdate,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> InvestigationResponse:
    obj = await service.update_investigation(item_id, data)
    return InvestigationResponse.model_validate(obj)


@router.post("/investigations/{item_id}/complete", response_model=InvestigationResponse)
async def complete_investigation(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("hse_advanced.close_investigation")),
    service: HSEAdvancedService = Depends(_get_service),
) -> InvestigationResponse:
    obj = await service.complete_investigation(item_id, user_id=user_id)
    return InvestigationResponse.model_validate(obj)


@router.post("/investigations/{item_id}/abandon", response_model=InvestigationResponse)
async def abandon_investigation(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("hse_advanced.close_investigation")),
    service: HSEAdvancedService = Depends(_get_service),
) -> InvestigationResponse:
    obj = await service.abandon_investigation(item_id, user_id=user_id)
    return InvestigationResponse.model_validate(obj)


# ── JSA ────────────────────────────────────────────────────────────────────


@router.get("/jsa/", response_model=list[JSAResponse])
async def list_jsa(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[JSAResponse]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.jsa_repo.list_for_project(project_id, offset=offset, limit=limit, status=status_filter)
    return [JSAResponse.model_validate(r) for r in rows]


@router.post("/jsa/", response_model=JSAResponse, status_code=201)
async def create_jsa(
    data: JSACreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSAResponse:
    await verify_project_access(data.project_id, user_id, session)
    obj = await service.create_jsa(data, user_id=user_id)
    return JSAResponse.model_validate(obj)


@router.get("/jsa/{item_id}", response_model=JSAResponse)
async def get_jsa(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSAResponse:
    obj = await service.get_jsa(item_id)
    return JSAResponse.model_validate(obj)


@router.patch("/jsa/{item_id}", response_model=JSAResponse)
async def update_jsa(
    item_id: uuid.UUID,
    data: JSAUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSAResponse:
    existing = await service.get_jsa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.update_jsa(item_id, data, user_id=user_id)
    return JSAResponse.model_validate(obj)


@router.delete("/jsa/{item_id}", status_code=204)
async def delete_jsa(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    existing = await service.get_jsa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    await service.delete_jsa(item_id, user_id=user_id)


@router.post("/jsa/{item_id}/submit", response_model=JSAResponse)
async def submit_jsa(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSAResponse:
    # R8: IDOR guard — FSM transitions were missing the project-access check
    # that PATCH/DELETE already have. Any user holding hse_advanced.update
    # could drive the state machine of a JSA on a project they cannot see.
    existing = await service.get_jsa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.submit_jsa(item_id)
    return JSAResponse.model_validate(obj)


@router.post("/jsa/{item_id}/approve", response_model=JSAResponse)
async def approve_jsa(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.approve_jsa")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSAResponse:
    existing = await service.get_jsa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    approver_uuid: uuid.UUID | None = None
    try:
        approver_uuid = uuid.UUID(str(user_id)) if user_id else None
    except (TypeError, ValueError):
        approver_uuid = None
    obj = await service.approve_jsa(item_id, approver_id=approver_uuid)
    return JSAResponse.model_validate(obj)


@router.post("/jsa/{item_id}/activate", response_model=JSAResponse)
async def activate_jsa(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSAResponse:
    existing = await service.get_jsa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.activate_jsa(item_id)
    return JSAResponse.model_validate(obj)


@router.post("/jsa/{item_id}/archive", response_model=JSAResponse)
async def archive_jsa(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSAResponse:
    existing = await service.get_jsa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.archive_jsa(item_id)
    return JSAResponse.model_validate(obj)


# ── PTW ───────────────────────────────────────────────────────────────────


@router.get("/permits/", response_model=list[PermitResponse])
async def list_permits(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type"),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[PermitResponse]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.permit_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status_filter,
        permit_type=type_filter,
    )
    return [PermitResponse.model_validate(r) for r in rows]


@router.post("/permits/", response_model=PermitResponse, status_code=201)
async def request_permit(
    data: PermitCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    await verify_project_access(data.project_id, user_id, session)
    obj = await service.request_permit(data, user_id=user_id)
    return PermitResponse.model_validate(obj)


@router.get("/permits/{item_id}", response_model=PermitResponse)
async def get_permit(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    obj = await service.get_permit(item_id)
    return PermitResponse.model_validate(obj)


@router.patch("/permits/{item_id}", response_model=PermitResponse)
async def update_permit(
    item_id: uuid.UUID,
    data: PermitUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    existing = await service.get_permit(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.update_permit(item_id, data, user_id=user_id)
    return PermitResponse.model_validate(obj)


@router.delete("/permits/{item_id}", status_code=204)
async def delete_permit(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    existing = await service.get_permit(item_id)
    await _guard_project(existing.project_id, user_id, session)
    await service.delete_permit(item_id, user_id=user_id)


@router.post("/permits/{item_id}/approve", response_model=PermitResponse)
async def approve_permit(
    item_id: uuid.UUID,
    payload: PermitApprovalPayload,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("hse_advanced.approve_permit")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    approver_uuid: uuid.UUID | None = None
    try:
        approver_uuid = uuid.UUID(str(user_id)) if user_id else None
    except (TypeError, ValueError):
        approver_uuid = None
    obj = await service.approve_permit(item_id, approver_id=approver_uuid, conditions=payload.conditions)
    return PermitResponse.model_validate(obj)


@router.post("/permits/{item_id}/activate", response_model=PermitResponse)
async def activate_permit(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    obj = await service.activate_permit(item_id)
    return PermitResponse.model_validate(obj)


@router.post("/permits/{item_id}/suspend", response_model=PermitResponse)
async def suspend_permit(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    obj = await service.suspend_permit(item_id)
    return PermitResponse.model_validate(obj)


@router.post("/permits/{item_id}/close", response_model=PermitResponse)
async def close_permit(
    item_id: uuid.UUID,
    payload: PermitClosurePayload,
    _perm: None = Depends(RequirePermission("hse_advanced.close_permit")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    obj = await service.close_permit(
        item_id,
        closure_checklist_passed=payload.closure_checklist_passed,
        closure_notes=payload.closure_notes,
    )
    return PermitResponse.model_validate(obj)


@router.post("/permits/{item_id}/cancel", response_model=PermitResponse)
async def cancel_permit(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    obj = await service.cancel_permit(item_id)
    return PermitResponse.model_validate(obj)


# ── Toolbox talks ────────────────────────────────────────────────────────


@router.get("/toolbox-talks/", response_model=list[ToolboxTalkResponse])
async def list_toolbox_talks(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[ToolboxTalkResponse]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.talk_repo.list_for_project(project_id, offset=offset, limit=limit)
    return [ToolboxTalkResponse.model_validate(r) for r in rows]


@router.post("/toolbox-talks/", response_model=ToolboxTalkResponse, status_code=201)
async def record_toolbox_talk(
    data: ToolboxTalkCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> ToolboxTalkResponse:
    await verify_project_access(data.project_id, user_id, session)
    obj = await service.record_toolbox_talk(data, user_id=user_id)
    return ToolboxTalkResponse.model_validate(obj)


@router.get("/toolbox-talks/{item_id}", response_model=ToolboxTalkResponse)
async def get_toolbox_talk(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> ToolboxTalkResponse:
    obj = await service.get_toolbox_talk(item_id)
    return ToolboxTalkResponse.model_validate(obj)


@router.patch("/toolbox-talks/{item_id}", response_model=ToolboxTalkResponse)
async def update_toolbox_talk(
    item_id: uuid.UUID,
    data: ToolboxTalkUpdate,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> ToolboxTalkResponse:
    obj = await service.update_toolbox_talk(item_id, data)
    return ToolboxTalkResponse.model_validate(obj)


@router.delete("/toolbox-talks/{item_id}", status_code=204)
async def delete_toolbox_talk(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    await service.get_toolbox_talk(item_id)
    await service.talk_repo.delete(item_id)


@router.post(
    "/toolbox-talks/{item_id}/attendance",
    response_model=list[ToolboxAttendanceResponse],
)
async def add_attendance(
    item_id: uuid.UUID,
    entries: list[ToolboxAttendanceEntry],
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[ToolboxAttendanceResponse]:
    rows = await service.add_attendance(item_id, entries)
    return [ToolboxAttendanceResponse.model_validate(r) for r in rows]


# ── Toolbox topic library ───────────────────────────────────────────────


@router.get("/toolbox-topics/", response_model=list[ToolboxTopicResponse])
async def list_topics(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    is_active: bool | None = Query(
        default=True,
        description=(
            "Tri-state filter (Round-3 Wave B convention): True = only active, False = only inactive, omit/null = both."
        ),
    ),
    language: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[ToolboxTopicResponse]:
    rows, _ = await service.topic_repo.list_topics(offset=offset, limit=limit, is_active=is_active, language=language)
    return [ToolboxTopicResponse.model_validate(r) for r in rows]


@router.post("/toolbox-topics/", response_model=ToolboxTopicResponse, status_code=201)
async def create_topic(
    data: ToolboxTopicCreate,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> ToolboxTopicResponse:
    obj = await service.create_topic(data)
    return ToolboxTopicResponse.model_validate(obj)


@router.patch("/toolbox-topics/{item_id}", response_model=ToolboxTopicResponse)
async def update_topic(
    item_id: uuid.UUID,
    data: ToolboxTopicUpdate,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> ToolboxTopicResponse:
    obj = await service.update_topic(item_id, data)
    return ToolboxTopicResponse.model_validate(obj)


@router.delete("/toolbox-topics/{item_id}", status_code=204)
async def delete_topic(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    await service.topic_repo.delete(item_id)


# ── PPE ────────────────────────────────────────────────────────────────────


@router.get("/ppe-issues/", response_model=list[PPEIssueResponse])
async def list_ppe(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    recipient_user_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[PPEIssueResponse]:
    rows, _ = await service.ppe_repo.list_issues(
        offset=offset,
        limit=limit,
        recipient_user_id=recipient_user_id,
        status=status_filter,
    )
    return [PPEIssueResponse.model_validate(r) for r in rows]


@router.post("/ppe-issues/", response_model=PPEIssueResponse, status_code=201)
async def issue_ppe(
    data: PPEIssueCreate,
    _perm: None = Depends(RequirePermission("hse_advanced.issue_ppe")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PPEIssueResponse:
    obj = await service.issue_ppe(data)
    return PPEIssueResponse.model_validate(obj)


@router.get("/ppe-issues/{item_id}", response_model=PPEIssueResponse)
async def get_ppe(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PPEIssueResponse:
    obj = await service.get_ppe_issue(item_id)
    return PPEIssueResponse.model_validate(obj)


@router.patch("/ppe-issues/{item_id}", response_model=PPEIssueResponse)
async def update_ppe(
    item_id: uuid.UUID,
    data: PPEIssueUpdate,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PPEIssueResponse:
    obj = await service.update_ppe_issue(item_id, data)
    return PPEIssueResponse.model_validate(obj)


@router.delete("/ppe-issues/{item_id}", status_code=204)
async def delete_ppe(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    await service.get_ppe_issue(item_id)
    await service.ppe_repo.delete(item_id)


@router.post("/ppe-issues/{item_id}/return", response_model=PPEIssueResponse)
async def return_ppe(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PPEIssueResponse:
    obj = await service.return_ppe(item_id)
    return PPEIssueResponse.model_validate(obj)


# ── Audits ────────────────────────────────────────────────────────────────


@router.get("/audits/", response_model=list[AuditResponse])
async def list_audits(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[AuditResponse]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.audit_repo.list_for_project(project_id, offset=offset, limit=limit, status=status_filter)
    return [AuditResponse.model_validate(r) for r in rows]


@router.post("/audits/", response_model=AuditResponse, status_code=201)
async def create_audit(
    data: AuditCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> AuditResponse:
    await verify_project_access(data.project_id, user_id, session)
    obj = await service.create_audit(data, user_id=user_id)
    return AuditResponse.model_validate(obj)


@router.get("/audits/{item_id}", response_model=AuditResponse)
async def get_audit(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> AuditResponse:
    obj = await service.get_audit(item_id)
    return AuditResponse.model_validate(obj)


@router.patch("/audits/{item_id}", response_model=AuditResponse)
async def update_audit(
    item_id: uuid.UUID,
    data: AuditUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> AuditResponse:
    existing = await service.get_audit(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.update_audit(item_id, data, user_id=user_id)
    return AuditResponse.model_validate(obj)


@router.delete("/audits/{item_id}", status_code=204)
async def delete_audit(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    existing = await service.get_audit(item_id)
    await _guard_project(existing.project_id, user_id, session)
    await service.delete_audit(item_id, user_id=user_id)


@router.post("/audits/{item_id}/complete", response_model=AuditResponse)
async def complete_audit(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.conduct_audit")),
    service: HSEAdvancedService = Depends(_get_service),
) -> AuditResponse:
    existing = await service.get_audit(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.complete_audit(item_id, user_id=user_id)
    return AuditResponse.model_validate(obj)


@router.post(
    "/audits/{item_id}/findings",
    response_model=AuditFindingResponse,
    status_code=201,
)
async def create_finding(
    item_id: uuid.UUID,
    payload: AuditFindingCreate,
    _perm: None = Depends(RequirePermission("hse_advanced.conduct_audit")),
    service: HSEAdvancedService = Depends(_get_service),
) -> AuditFindingResponse:
    obj = await service.create_finding(item_id, payload)
    return AuditFindingResponse.model_validate(obj)


@router.get("/audits/{item_id}/findings", response_model=list[AuditFindingResponse])
async def list_findings(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[AuditFindingResponse]:
    rows = await service.finding_repo.list_for_audit(item_id)
    return [AuditFindingResponse.model_validate(r) for r in rows]


@router.delete("/audit-findings/{finding_id}", status_code=204)
async def delete_finding(
    finding_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    await service.delete_finding(finding_id)


# ── CAPA ──────────────────────────────────────────────────────────────────


@router.get("/capas/", response_model=list[CAPAResponse])
async def list_capas(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[CAPAResponse]:
    await verify_project_access(project_id, user_id, session)
    rows, _ = await service.capa_repo.list_for_project(project_id, offset=offset, limit=limit, status=status_filter)
    return [CAPAResponse.model_validate(r) for r in rows]


@router.post("/capas/", response_model=CAPAResponse, status_code=201)
async def create_capa(
    data: CAPACreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CAPAResponse:
    await verify_project_access(data.project_id, user_id, session)
    obj = await service.create_capa(data, user_id=user_id)
    return CAPAResponse.model_validate(obj)


@router.get("/capas/{item_id}", response_model=CAPAResponse)
async def get_capa(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CAPAResponse:
    obj = await service.get_capa(item_id)
    return CAPAResponse.model_validate(obj)


@router.patch("/capas/{item_id}", response_model=CAPAResponse)
async def update_capa(
    item_id: uuid.UUID,
    data: CAPAUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CAPAResponse:
    existing = await service.get_capa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.update_capa(item_id, data, user_id=user_id)
    return CAPAResponse.model_validate(obj)


@router.delete("/capas/{item_id}", status_code=204)
async def delete_capa(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    existing = await service.get_capa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    await service.delete_capa(item_id, user_id=user_id)


@router.post("/capas/{item_id}/complete", response_model=CAPAResponse)
async def complete_capa(
    item_id: uuid.UUID,
    payload: CAPAVerificationPayload,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.close_capa")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CAPAResponse:
    existing = await service.get_capa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.close_capa(
        item_id,
        verification_notes=payload.verification_notes,
        user_id=user_id,
    )
    return CAPAResponse.model_validate(obj)


@router.post("/capas/{item_id}/escalate", response_model=CAPAResponse)
async def escalate_capa(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.escalate_capa")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CAPAResponse:
    existing = await service.get_capa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.escalate_capa(item_id, user_id=user_id)
    return CAPAResponse.model_validate(obj)


@router.post("/capas/{item_id}/cancel", response_model=CAPAResponse)
async def cancel_capa(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CAPAResponse:
    existing = await service.get_capa(item_id)
    await _guard_project(existing.project_id, user_id, session)
    obj = await service.cancel_capa(item_id, user_id=user_id)
    return CAPAResponse.model_validate(obj)


# ── Certifications ────────────────────────────────────────────────────────


@router.get("/certifications/", response_model=list[CertificationResponse])
async def list_certifications(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    owner_user_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[CertificationResponse]:
    rows, _ = await service.cert_repo.list_certs(
        offset=offset,
        limit=limit,
        owner_user_id=owner_user_id,
        status=status_filter,
    )
    return [CertificationResponse.model_validate(r) for r in rows]


@router.post("/certifications/", response_model=CertificationResponse, status_code=201)
async def create_certification(
    data: CertificationCreate,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CertificationResponse:
    obj = await service.create_certification(data)
    return CertificationResponse.model_validate(obj)


@router.get("/certifications/expiring", response_model=list[CertificationResponse])
async def list_expiring_certifications(
    days: int = Query(default=30, ge=1, le=365),
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[CertificationResponse]:
    rows = await service.expiring_certifications(days=days)
    return [CertificationResponse.model_validate(r) for r in rows]


@router.get("/certifications/{item_id}", response_model=CertificationResponse)
async def get_certification(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CertificationResponse:
    obj = await service.get_certification(item_id)
    return CertificationResponse.model_validate(obj)


@router.patch("/certifications/{item_id}", response_model=CertificationResponse)
async def update_certification(
    item_id: uuid.UUID,
    data: CertificationUpdate,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CertificationResponse:
    obj = await service.update_certification(item_id, data)
    return CertificationResponse.model_validate(obj)


@router.delete("/certifications/{item_id}", status_code=204)
async def delete_certification(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    await service.get_certification(item_id)
    await service.cert_repo.delete(item_id)


# ── KPI + Dashboard ──────────────────────────────────────────────────────


@router.get("/kpi/project/{project_id}", response_model=KPIResponse)
async def project_kpi(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    hours_worked: Decimal = Query(default=Decimal("0"), ge=0),
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    service: HSEAdvancedService = Depends(_get_service),
) -> KPIResponse:
    """Return TRIR / LTIFR / days-without-LTI for a project.

    Recordable / LTI counts are read off the existing safety module; the
    formulae are pure helpers exposed from this module's service layer.
    """
    await verify_project_access(project_id, user_id, session)

    # Pull lightweight counts from the safety module without coupling tightly.
    from sqlalchemy import select

    from app.modules.safety.models import SafetyIncident

    inc_stmt = select(SafetyIncident).where(SafetyIncident.project_id == project_id)
    incs = list((await session.execute(inc_stmt)).scalars().all())

    # OSHA 29 CFR 1904.7: a case is recordable if it involves medical
    # treatment beyond first aid, hospitalisation or fatality — OR any
    # days away from work / restricted duty. Counting only the treatment
    # types would undercount (a lost-time case logged with no/“first_aid”
    # treatment_type is still recordable), which is mathematically
    # impossible (recordable >= lti must always hold) and corrupts TRIR.
    recordable_treatments = {"medical", "hospital", "fatality"}
    recordable = sum(1 for i in incs if (i.treatment_type or "") in recordable_treatments or (i.days_lost or 0) > 0)
    lti = sum(1 for i in incs if (i.days_lost or 0) > 0)

    trir = compute_trir(recordable, hours_worked)
    ltifr = compute_ltifr(lti, hours_worked)

    lti_dates = [i.incident_date for i in incs if (i.days_lost or 0) > 0]
    from app.modules.hse_advanced.service import days_without_lti as _dwlti

    dwlti = _dwlti(lti_dates)

    return KPIResponse(
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        hours_worked=hours_worked,
        recordable_count=recordable,
        lti_count=lti,
        trir=trir,
        ltifr=ltifr,
        days_without_lti=dwlti if dwlti < 9999 else None,
    )


@router.get("/dashboard/project/{project_id}", response_model=HSEDashboardResponse)
async def project_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: HSEAdvancedService = Depends(_get_service),
) -> HSEDashboardResponse:
    """HSE dashboard summary for a project."""
    await verify_project_access(project_id, user_id, session)

    active_permits = await service.permit_repo.count_status(project_id, "active")
    overdue_capas = await service.capa_repo.count_status(project_id, "overdue")
    open_capas = await service.capa_repo.count_status(project_id, "open")
    audits_completed = await service.audit_repo.list_for_project(project_id, status="completed", limit=100)

    talks_this_month = await service.talk_repo.count_in_month(project_id, date.today())

    # JSA count
    jsa_rows, jsa_total = await service.jsa_repo.list_for_project(project_id, limit=1)

    # Expiring certs (org-wide, simple count)
    expiring = await service.cert_repo.expiring_within(30, date.today())

    # Average audit score
    avg_score: float | None = None
    completed_rows = audits_completed[0]
    if completed_rows:
        totals = [
            (float(a.score_total) / float(a.max_score) * 100.0)
            for a in completed_rows
            if a.score_total is not None and a.max_score and float(a.max_score) > 0
        ]
        if totals:
            avg_score = round(sum(totals) / len(totals), 2)

    return HSEDashboardResponse(
        project_id=project_id,
        jsa_count=jsa_total,
        active_permits=active_permits,
        overdue_capas=overdue_capas,
        open_capas=open_capas,
        audits_completed=len(completed_rows),
        toolbox_talks_this_month=talks_this_month,
        expiring_certs_30d=len(expiring),
        avg_audit_score=avg_score,
    )


@router.get("/permits/dashboard/{project_id}", response_model=PermitDashboardResponse)
async def permit_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitDashboardResponse:
    """Active + pending + recently-closed permits for a project."""
    await verify_project_access(project_id, user_id, session)

    active = await service.permit_repo.active_today(project_id)
    pending_rows, _ = await service.permit_repo.list_for_project(project_id, status="requested", limit=100)

    today = datetime.now(UTC).date()
    closed_rows, _ = await service.permit_repo.list_for_project(project_id, status="closed", limit=100)

    def _utc_date(dt: datetime | None) -> date | None:
        """Normalise a possibly-naive stored timestamp to a UTC date."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).date()

    closed_today = [p for p in closed_rows if _utc_date(p.updated_at) == today]

    def _to_entry(p: object) -> PermitDashboardEntry:
        return PermitDashboardEntry(
            permit_id=p.id,  # type: ignore[attr-defined]
            permit_number=p.permit_number,  # type: ignore[attr-defined]
            permit_type=p.permit_type,  # type: ignore[attr-defined]
            status=p.status,  # type: ignore[attr-defined]
            work_start=p.work_start,  # type: ignore[attr-defined]
            work_end=p.work_end,  # type: ignore[attr-defined]
        )

    return PermitDashboardResponse(
        project_id=project_id,
        active=[_to_entry(p) for p in active],
        pending=[_to_entry(p) for p in pending_rows],
        closed_today=[_to_entry(p) for p in closed_today],
    )


# ── PTW prerequisites ─────────────────────────────────────────────────────


@router.get("/permits/{item_id}/prerequisites", response_model=PermitPrerequisiteStatus)
async def permit_prereq_status(
    item_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitPrerequisiteStatus:
    """Inspect a permit's prerequisite checklist completion."""
    permit = await service.get_permit(item_id)
    return service.permit_prerequisite_status(permit)


@router.patch("/permits/{item_id}/prerequisites", response_model=PermitResponse)
async def update_permit_prereqs(
    item_id: uuid.UUID,
    payload: PermitPrerequisitesPayload,
    _perm: None = Depends(RequirePermission("hse_advanced.update_prereqs")),
    service: HSEAdvancedService = Depends(_get_service),
) -> PermitResponse:
    obj = await service.update_permit_prerequisites(item_id, payload)
    return PermitResponse.model_validate(obj)


# ── CAPA 5-Whys + Effectiveness ───────────────────────────────────────────


@router.post("/capas/{item_id}/five-whys", response_model=CAPAResponse)
async def set_five_whys(
    item_id: uuid.UUID,
    payload: CAPAFiveWhysPayload,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CAPAResponse:
    """Record a 5-Whys structured root-cause chain on a CAPA."""
    obj = await service.set_capa_five_whys(item_id, payload)
    return CAPAResponse.model_validate(obj)


@router.post("/capas/{item_id}/effectiveness", response_model=CAPAResponse)
async def verify_effectiveness(
    item_id: uuid.UUID,
    payload: CAPAEffectivenessPayload,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("hse_advanced.verify_effectiveness")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CAPAResponse:
    """ISO 9001 §10.2.1 — verify a completed CAPA's effectiveness."""
    verifier: uuid.UUID | None = None
    try:
        verifier = uuid.UUID(str(user_id)) if user_id else None
    except (TypeError, ValueError):
        verifier = None
    obj = await service.verify_capa_effectiveness(
        item_id,
        payload,
        verified_by=verifier,
    )
    return CAPAResponse.model_validate(obj)


# ── JSA template library ──────────────────────────────────────────────────


@router.get("/jsa-templates/", response_model=list[JSATemplateResponse])
async def list_jsa_templates(
    trade: str | None = Query(default=None, max_length=100),
    region: str | None = Query(default=None, max_length=32),
    is_active: bool | None = Query(
        default=True,
        description=(
            "Tri-state filter (Round-3 Wave B convention): True = only active, False = only inactive, omit/null = both."
        ),
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("hse_advanced.jsa_template.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[JSATemplateResponse]:
    rows, _ = await service.jsa_template_repo.list_templates(
        trade=trade,
        region=region,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return [JSATemplateResponse.model_validate(r) for r in rows]


@router.post("/jsa-templates/", response_model=JSATemplateResponse, status_code=201)
async def create_jsa_template(
    data: JSATemplateCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("hse_advanced.jsa_template.write")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSATemplateResponse:
    tpl = await service.create_jsa_template(data, user_id=user_id)
    return JSATemplateResponse.model_validate(tpl)


@router.patch("/jsa-templates/{tpl_id}", response_model=JSATemplateResponse)
async def update_jsa_template(
    tpl_id: uuid.UUID,
    data: JSATemplateUpdate,
    _perm: None = Depends(RequirePermission("hse_advanced.jsa_template.write")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSATemplateResponse:
    tpl = await service.update_jsa_template(tpl_id, data)
    return JSATemplateResponse.model_validate(tpl)


@router.delete("/jsa-templates/{tpl_id}", status_code=204)
async def delete_jsa_template(
    tpl_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("hse_advanced.jsa_template.delete")),
    service: HSEAdvancedService = Depends(_get_service),
) -> None:
    await service.delete_jsa_template(tpl_id)


@router.post("/jsa-templates/{tpl_id}/clone", response_model=JSAResponse, status_code=201)
async def clone_jsa_template(
    tpl_id: uuid.UUID,
    request: JSATemplateCloneRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> JSAResponse:
    from app.dependencies import verify_project_access as _verify

    await _verify(request.project_id, user_id, session)
    jsa = await service.clone_jsa_template_to_project(
        tpl_id,
        request,
        user_id=user_id,
    )
    return JSAResponse.model_validate(jsa)


# ── Incident escalation matrix (lookup) ───────────────────────────────────


@router.get("/incident-escalation-matrix", response_model=IncidentEscalationMatrix)
async def get_incident_escalation_matrix(
    regime: str = Query(
        default="iso45001",
        pattern=r"^(osha|hse_uk|dguv|iso45001)$",
    ),
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
) -> IncidentEscalationMatrix:
    """Return the severity → role → SLA matrix for a regulatory regime."""
    return incident_escalation_matrix(regime)


# ── OSHA Form 300 CSV export + slim corrective-action FSM (v3086) ────────


_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _project_slug(project_id: uuid.UUID, name: str | None) -> str:
    """Render a filename-safe slug, falling back to the UUID."""
    base = (name or "").strip().lower()
    base = _SLUG_RE.sub("-", base).strip("-")
    return base or str(project_id)


@router.get("/osha-300-log.csv", include_in_schema=True)
async def osha_300_log_csv(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    year: int = Query(..., ge=1900, le=2100),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> Response:
    """OSHA Form 300 incident log CSV for a project + calendar year.

    See OSHA 29 CFR 1904.7 for the recordable-incident definition. We
    include only rows flagged ``osha_recordable=True``; rows whose
    ``incident_date`` does not fall in the requested year are skipped.
    """
    await verify_project_access(project_id, user_id, session)

    # Look up the project's name for a friendly download filename.
    from app.modules.projects.models import Project

    proj = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    project_name = getattr(proj, "name", None) if proj is not None else None
    slug = _project_slug(project_id, project_name)

    body = await service.generate_osha_300_csv(project_id, year)
    filename = f"osha-300-{slug}-{year}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/corrective-actions/",
    response_model=list[CorrectiveActionResponse],
)
async def list_corrective_actions(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    incident_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("hse_advanced.read")),
    service: HSEAdvancedService = Depends(_get_service),
) -> list[CorrectiveActionResponse]:
    """List slim incident-scoped corrective actions.

    Scope precedence: ``incident_id`` (single-incident drill-down) >
    ``project_id`` (project-wide view, resolved via the safety module's
    incident table). With neither, returns an empty list rather than a
    422 so the dashboard renders cleanly when no project is active.
    """
    if incident_id is None and project_id is None:
        return []

    if project_id is not None and incident_id is None:
        await verify_project_access(project_id, user_id, session)
        # Resolve project-scope by joining via incident_id ∈ project's
        # incidents — cheaper than a SQL join in this slim model.
        from app.modules.safety.models import SafetyIncident

        inc_ids = list(
            (await session.execute(select(SafetyIncident.id).where(SafetyIncident.project_id == project_id)))
            .scalars()
            .all()
        )
        if not inc_ids:
            return []
        from app.modules.safety.models import HSECorrectiveAction

        stmt = select(HSECorrectiveAction).where(HSECorrectiveAction.incident_id.in_(inc_ids))
        if status_filter is not None:
            stmt = stmt.where(HSECorrectiveAction.status == status_filter)
        stmt = stmt.offset(offset).limit(limit)
        rows = list((await session.execute(stmt)).scalars().all())
    else:
        rows = await service.list_corrective_actions(
            incident_id=incident_id,
            status_filter=status_filter,
            offset=offset,
            limit=limit,
        )
    return [CorrectiveActionResponse.model_validate(r) for r in rows]


@router.post(
    "/corrective-actions/",
    response_model=CorrectiveActionResponse,
    status_code=201,
)
async def create_corrective_action(
    data: CorrectiveActionCreate,
    _perm: None = Depends(RequirePermission("hse_advanced.create")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CorrectiveActionResponse:
    """Open a new corrective action against an incident (status=pending)."""
    obj = await service.create_corrective_action(
        incident_id=data.incident_id,
        description=data.description,
        assigned_to_user_id=data.assigned_to_user_id,
        due_date=data.due_date,
    )
    return CorrectiveActionResponse.model_validate(obj)


@router.post(
    "/corrective-actions/{ca_id}/transition",
    response_model=CorrectiveActionResponse,
)
async def transition_corrective_action(
    ca_id: uuid.UUID,
    payload: CATransitionRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("hse_advanced.update")),
    service: HSEAdvancedService = Depends(_get_service),
) -> CorrectiveActionResponse:
    """Advance a corrective action along the FSM.

    Allowed: ``pending → in_progress → verified → closed``. Any other
    transition is rejected with HTTP 409.
    """
    obj = await service.transition_corrective_action(
        ca_id,
        to_status=payload.to_status,
        user_id=user_id,
        verification_notes=payload.verification_notes,
    )
    return CorrectiveActionResponse.model_validate(obj)
