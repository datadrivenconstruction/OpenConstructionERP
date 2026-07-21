# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Customer & Partner Portal - FastAPI routes.

Two surfaces, mounted under ``/api/v1/portal/``:

    Internal-admin (``RequirePermission``-gated)
    --------------------------------------------
        POST   /admin/users/invite
        GET    /admin/users
        GET    /admin/users/{id}
        PATCH  /admin/users/{id}
        POST   /admin/users/{id}/resend-invite
        POST   /admin/access-rules
        GET    /admin/access-rules
        DELETE /admin/access-rules/{id}
        GET    /admin/document-access-log

    Portal-user-facing (``RequirePortalSession``-gated unless noted)
    ---------------------------------------------------------------
        POST   /auth/magic-link    - no auth (rate-limited upstream)
        POST   /auth/consume       - no auth
        POST   /auth/logout
        GET    /me
        GET    /me/accessible/{resource_type}
        GET    /me/notifications
        POST   /me/notifications/{id}/read
        POST   /me/document-access
        GET    /me/documents
        GET    /me/documents/{id}/content
"""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.portal.dependencies import (
    PortalSessionToken,
    RequirePortalSession,
)
from app.modules.portal.schemas import (
    AccessRuleCreate,
    AccessRuleList,
    AccessRuleResponse,
    DocumentAccessLogCreate,
    DocumentAccessLogEntry,
    MagicLinkConsume,
    MagicLinkRequest,
    MagicLinkResponse,
    NotificationListResponse,
    NotificationResponse,
    PaymentApplicationDetailResponse,
    PaymentApplicationLineDetail,
    PaymentApplicationListItem,
    PaymentApplicationListResponse,
    PaymentApplicationSubmitPayload,
    PortalAgreementSummary,
    PortalAgreementSummaryList,
    PortalChangeOrderEntry,
    PortalChangeOrderList,
    PortalProgressReportEntry,
    PortalProgressReportList,
    PortalProjectSummary,
    PortalProjectSummaryList,
    PortalSelfPatch,
    PortalSharedDocument,
    PortalSharedDocumentList,
    PortalTicketCreate,
    PortalTicketList,
    PortalTicketResponse,
    PortalUserInvite,
    PortalUserInviteResponse,
    PortalUserList,
    PortalUserPatch,
    PortalUserResponse,
    PortalWorkPackageEntry,
    SessionResponse,
)
from app.modules.portal.service import PortalService

router = APIRouter(tags=["portal"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> PortalService:
    return PortalService(session)


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


# ── Internal-admin endpoints ──────────────────────────────────────────────


@router.post(
    "/admin/users/invite",
    response_model=PortalUserInviteResponse,
    status_code=201,
)
async def admin_invite_user(
    data: PortalUserInvite,
    request: Request,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("portal.admin.users.invite")),
    service: PortalService = Depends(_get_service),
) -> PortalUserInviteResponse:
    """‌⁠‍Invite a new portal user (idempotent) and return the magic-link once."""
    user, plain, expires_at = await service.invite_portal_user(
        email=data.email,
        role=data.portal_role,
        language=data.language,
        full_name=data.full_name,
        timezone_=data.timezone,
        granted_by=user_id,
        redirect_path=data.redirect_path,
        created_ip=_client_ip(request),
    )
    return PortalUserInviteResponse(
        user=PortalUserResponse.model_validate(user),
        magic_link_token=plain,
        magic_link_expires_at=expires_at,
    )


@router.get("/admin/users", response_model=PortalUserList)
async def admin_list_users(
    _perm: None = Depends(RequirePermission("portal.admin.users.read")),
    service: PortalService = Depends(_get_service),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    portal_role: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> PortalUserList:
    """‌⁠‍List portal users with optional role/status filters."""
    items, total = await service.list_portal_users(
        offset=offset,
        limit=limit,
        portal_role=portal_role,
        status_filter=status_filter,
    )
    return PortalUserList(
        items=[PortalUserResponse.model_validate(u) for u in items],
        total=total,
    )


@router.get("/admin/users/{portal_user_id}", response_model=PortalUserResponse)
async def admin_get_user(
    portal_user_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("portal.admin.users.read")),
    service: PortalService = Depends(_get_service),
) -> PortalUserResponse:
    user = await service.get_portal_user(portal_user_id)
    return PortalUserResponse.model_validate(user)


@router.patch(
    "/admin/users/{portal_user_id}",
    response_model=PortalUserResponse,
)
async def admin_patch_user(
    portal_user_id: uuid.UUID,
    data: PortalUserPatch,
    _perm: None = Depends(RequirePermission("portal.admin.users.suspend")),
    service: PortalService = Depends(_get_service),
) -> PortalUserResponse:
    """Suspend / reactivate / rename a portal user.

    Suspending also revokes every live session for that user.
    """
    fields = data.model_dump(exclude_unset=True)
    user = await service.patch_portal_user(portal_user_id, **fields)
    if fields.get("status") == "suspended":
        await service.revoke_all_for_user(portal_user_id)
    return PortalUserResponse.model_validate(user)


@router.post(
    "/admin/users/{portal_user_id}/resend-invite",
    response_model=PortalUserInviteResponse,
)
async def admin_resend_invite(
    portal_user_id: uuid.UUID,
    request: Request,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("portal.admin.users.invite")),
    service: PortalService = Depends(_get_service),
) -> PortalUserInviteResponse:
    """Resend the invitation magic-link to an existing portal user."""
    user = await service.get_portal_user(portal_user_id)
    user, plain, expires_at = await service.invite_portal_user(
        email=user.email,
        role=user.portal_role,
        language=user.language,
        full_name=user.full_name,
        timezone_=user.timezone,
        granted_by=user_id,
        created_ip=_client_ip(request),
    )
    return PortalUserInviteResponse(
        user=PortalUserResponse.model_validate(user),
        magic_link_token=plain,
        magic_link_expires_at=expires_at,
    )


@router.post(
    "/admin/access-rules",
    response_model=AccessRuleResponse,
    status_code=201,
)
async def admin_grant_access(
    data: AccessRuleCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(
        RequirePermission("portal.admin.access_rules.manage"),
    ),
    service: PortalService = Depends(_get_service),
) -> AccessRuleResponse:
    """Idempotently grant a portal user access to a resource."""
    rule = await service.grant_access(
        portal_user_id=data.portal_user_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        permission=data.permission,
        granted_by=user_id,
        expires_at=data.expires_at,
    )
    return AccessRuleResponse.model_validate(rule)


@router.get("/admin/access-rules", response_model=AccessRuleList)
async def admin_list_access_rules(
    _perm: None = Depends(
        RequirePermission("portal.admin.access_rules.manage"),
    ),
    service: PortalService = Depends(_get_service),
    portal_user_id: uuid.UUID | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> AccessRuleList:
    """List access rules (optionally filtered by user / resource type).

    Without this, the admin UI could only display grants made in the
    current browser session - every rule vanished from the table on reload
    and seeded/previously-granted rules were never visible at all.
    """
    items, total = await service.list_access_rules(
        portal_user_id=portal_user_id,
        resource_type=resource_type,
        offset=offset,
        limit=limit,
    )
    return AccessRuleList(
        items=[AccessRuleResponse.model_validate(r) for r in items],
        total=total,
    )


@router.delete("/admin/access-rules/{rule_id}", status_code=204)
async def admin_revoke_access(
    rule_id: uuid.UUID,
    _perm: None = Depends(
        RequirePermission("portal.admin.access_rules.manage"),
    ),
    service: PortalService = Depends(_get_service),
) -> None:
    """Revoke a specific access rule by its ID."""
    await service.revoke_access_rule(rule_id)


@router.get(
    "/admin/document-access-log",
    response_model=list[DocumentAccessLogEntry],
)
async def admin_document_access_log(
    _perm: None = Depends(RequirePermission("portal.admin.audit.read")),
    service: PortalService = Depends(_get_service),
    portal_user_id: uuid.UUID | None = Query(default=None),
    document_type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DocumentAccessLogEntry]:
    items, _total = await service.list_document_access(
        portal_user_id=portal_user_id,
        document_type=document_type,
        offset=offset,
        limit=limit,
    )
    return [DocumentAccessLogEntry.model_validate(i) for i in items]


# ── Portal-user-facing endpoints ──────────────────────────────────────────


@router.post(
    "/auth/magic-link",
    response_model=MagicLinkResponse,
    status_code=202,
)
async def portal_request_magic_link(
    data: MagicLinkRequest,
    request: Request,
    service: PortalService = Depends(_get_service),
) -> MagicLinkResponse:
    """Request a magic link. Always returns 202 regardless of whether the
    email exists, to avoid leaking which addresses are registered.

    NOTE: this endpoint does NOT return the plaintext token in the body.
    A future ``notifications`` subscriber should observe the
    ``portal.notification.created`` event (or a dedicated subscriber) and
    email the link. Until then, the plaintext token is only obtainable via
    the internal admin ``POST /admin/users/invite`` flow.
    """
    await service.request_magic_link(
        data.email,
        created_ip=_client_ip(request),
    )
    return MagicLinkResponse()


@router.post("/auth/consume", response_model=SessionResponse)
async def portal_consume_magic_link(
    data: MagicLinkConsume,
    request: Request,
    service: PortalService = Depends(_get_service),
) -> SessionResponse:
    """Consume a magic link and receive a session token."""
    user, sess, plain, expires_at = await service.consume_magic_link(
        data.token,
        purpose="login",
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SessionResponse(
        session_token=plain,
        expires_at=expires_at,
        portal_user=PortalUserResponse.model_validate(user),
    )


@router.post("/auth/logout", status_code=204)
async def portal_logout(
    token: PortalSessionToken,
    _user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> JSONResponse:
    """Revoke the current portal session."""
    await service.revoke_session(token)
    return JSONResponse(content=None, status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=PortalUserResponse)
async def portal_me(user: RequirePortalSession) -> PortalUserResponse:
    """Return the current portal user's profile."""
    return PortalUserResponse.model_validate(user)


@router.get(
    "/me/accessible/{resource_type}",
    response_model=list[uuid.UUID],
)
async def portal_me_accessible(
    resource_type: str,
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> list[uuid.UUID]:
    """List resource IDs of ``resource_type`` the caller can see."""
    return await service.list_accessible_resources(user.id, resource_type)


@router.get("/me/notifications", response_model=NotificationListResponse)
async def portal_me_notifications(
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
    unread_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> NotificationListResponse:
    items, total, unread = await service.list_notifications(
        user.id,
        unread_only=unread_only,
        offset=offset,
        limit=limit,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(i) for i in items],
        total=total,
        unread_count=unread,
    )


@router.post(
    "/me/notifications/{notification_id}/read",
    response_model=NotificationResponse,
)
async def portal_me_notification_read(
    notification_id: uuid.UUID,
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> NotificationResponse:
    notif = await service.mark_notification_read(notification_id, user.id)
    return NotificationResponse.model_validate(notif)


@router.post(
    "/me/document-access",
    response_model=DocumentAccessLogEntry,
    status_code=201,
)
async def portal_me_document_access(
    data: DocumentAccessLogCreate,
    request: Request,
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> DocumentAccessLogEntry:
    """Audit log a portal-side document access (view/download/sign).

    Enforces RLS: refuses if the caller has no access rule on the document.
    """
    if not await service.enforce_rls(
        user.id,
        data.document_type,
        data.document_id,
        required="view" if data.action == "view" else ("sign" if data.action == "sign" else "view"),
    ):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this document",
        )
    entry = await service.record_document_access(
        portal_user_id=user.id,
        document_type=data.document_type,
        document_id=data.document_id,
        action=data.action,
        ip_address=_client_ip(request),
    )
    return DocumentAccessLogEntry.model_validate(entry)


@router.patch("/me", response_model=PortalUserResponse)
async def portal_me_patch(
    data: PortalSelfPatch,
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> PortalUserResponse:
    """Self-edit the small subset of profile fields a portal user can change.

    Explicitly excludes ``status`` and ``email`` - only an internal admin
    can suspend an account, and email changes go through the invite flow
    so the new address is verifiable.
    """
    updates = data.model_dump(exclude_unset=True)
    user = await service.patch_portal_user(user.id, **updates)
    return PortalUserResponse.model_validate(user)


# ── Portal-side ticket intake ─────────────────────────────────────────────


@router.post(
    "/me/tickets",
    response_model=PortalTicketResponse,
    status_code=201,
)
async def portal_create_ticket(
    data: PortalTicketCreate,
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
) -> PortalTicketResponse:
    """Portal-user-facing ticket intake.

    Enforces RLS: the caller must have an active ``service_contract`` access
    rule for ``data.contract_id``. On success, a real ``ServiceTicket`` row
    is created with ``source="portal"`` and ``reported_by="<portal_user_id>"``
    so the dispatcher can triage portal vs phone tickets via the ``source``
    column. ``reported_by`` holds the bare portal-user UUID (36 chars) - a
    ``portal:`` prefix would overflow the 36-char ``reported_by`` field of
    ``ServiceTicketCreate`` / the ``ServiceTicket.reported_by`` column and
    422/500 every portal ticket.
    """
    from fastapi import HTTPException

    if not await service.enforce_rls(
        user.id,
        "service_contract",
        data.contract_id,
        required="submit",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to file tickets on this contract",
        )

    # Late import to keep the portal module's dependency surface tight.
    from app.modules.service.schemas import ServiceTicketCreate
    from app.modules.service.service import ServiceService

    svc = ServiceService(session)
    ticket = await svc.create_ticket(
        ServiceTicketCreate(
            contract_id=data.contract_id,
            asset_id=data.asset_id,
            title=data.title,
            description=data.description,
            priority=data.priority,
            reported_by=str(user.id),
            source="portal",
        ),
        user_id=str(user.id),
    )
    return PortalTicketResponse.model_validate(ticket)


@router.get(
    "/me/tickets",
    response_model=PortalTicketList,
)
async def portal_list_tickets(
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PortalTicketList:
    """List tickets the caller filed.

    Returns only tickets where ``source == "portal"`` and
    ``reported_by == "<my_id>"`` AND the caller still has a
    ``service_contract`` access rule on the parent contract - i.e. tickets
    stay visible to the buyer who filed them as long as their contract
    access has not been revoked. ``source == "portal"`` is part of the
    predicate so a portal user UUID can never alias an internal
    ``reported_by`` value from a phone/email ticket.
    """
    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    from app.modules.service.models import ServiceTicket as _ST

    accessible_contracts = await service.list_accessible_resources(
        user.id,
        "service_contract",
    )
    if not accessible_contracts:
        return PortalTicketList(items=[], total=0)

    base = (
        _select(_ST)
        .where(_ST.contract_id.in_(accessible_contracts))
        .where(_ST.source == "portal")
        .where(_ST.reported_by == str(user.id))
    )

    # Total via SQL aggregate - do not materialise every row just to count.
    count_stmt = _select(_func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = base.order_by(_ST.created_at.desc()).offset(offset).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())

    return PortalTicketList(
        items=[PortalTicketResponse.model_validate(r) for r in rows],
        total=total,
    )


# ── Portal-side change-order visibility ───────────────────────────────────


@router.get(
    "/me/change-orders",
    response_model=PortalChangeOrderList,
)
async def portal_list_change_orders(
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
    project_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PortalChangeOrderList:
    """List executed change orders the caller can see.

    Two access models are supported in parallel:

    1. **Per-CO grants.** The caller has individual
       ``change_order`` resource rules for specific COs.
    2. **Per-project grants.** The caller has a ``project`` resource rule
       - they then see every approved/executed CO under that project.

    Returns only status in
    (``approved``, ``executed``, ``rejected``, ``closed``) - drafts and
    in-flight workflow rows stay invisible. Output is the buyer-facing
    redacted projection (no internal notes, no markup, no submission trail).
    """
    from sqlalchemy import func as _func
    from sqlalchemy import or_
    from sqlalchemy import select as _select

    from app.modules.changeorders.models import ChangeOrder as _CO

    accessible_cos = await service.list_accessible_resources(
        user.id,
        "change_order",
    )
    accessible_projects = await service.list_accessible_resources(
        user.id,
        "project",
    )
    if not accessible_cos and not accessible_projects:
        return PortalChangeOrderList(items=[], total=0)

    visible_statuses = ("approved", "executed", "rejected", "closed")

    # The caller may see a CO iff it is under a project they were granted
    # OR it is one of the specific COs granted to them. This predicate is
    # ALWAYS applied - even when ``project_id`` is supplied - so that a
    # per-CO grant on project B cannot be used to read every CO of an
    # unrelated project A. (Previously, holding any per-CO grant disabled
    # the project-scope check entirely → cross-project data leak.)
    scope_ors = []
    if accessible_projects:
        scope_ors.append(_CO.project_id.in_(accessible_projects))
    if accessible_cos:
        scope_ors.append(_CO.id.in_(accessible_cos))
    # scope_ors is non-empty here (guarded by the early return above).
    scope_predicate = or_(*scope_ors)

    base = _select(_CO).where(_CO.status.in_(visible_statuses)).where(scope_predicate)
    if project_id is not None:
        base = base.where(_CO.project_id == project_id)

    # Total via SQL aggregate (matches the repository pattern; no Python
    # row materialisation just to count).
    count_stmt = _select(_func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = base.order_by(_CO.created_at.desc()).offset(offset).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())

    items: list[PortalChangeOrderEntry] = []
    for co in rows:
        items.append(
            PortalChangeOrderEntry(
                id=co.id,
                code=co.code,
                title=co.title,
                description=co.description or "",
                status=co.status,
                approved_amount=co.approved_amount if co.approved_amount is not None else co.cost_impact,
                approved_time_days=co.approved_time_days,
                currency=co.currency or "",
                approved_at=co.approved_at,
            )
        )
    return PortalChangeOrderList(items=items, total=total)


# ── Portal-side progress-report visibility ────────────────────────────────


def _report_period(snapshot: dict | None) -> str | None:
    """Best-effort extraction of a human reporting period from a snapshot.

    Looks for the period label written by the progress section, falling
    back to ``None`` so the frontend can hide the field cleanly.
    """
    if not isinstance(snapshot, dict):
        return None
    progress = snapshot.get("progress")
    if isinstance(progress, dict):
        milestones = progress.get("milestone_status")
        if isinstance(milestones, list) and milestones:
            first = milestones[0]
            if isinstance(first, dict) and first.get("period"):
                return str(first["period"])
        if progress.get("as_of_date"):
            return str(progress["as_of_date"])
    return None


@router.get(
    "/me/projects",
    response_model=PortalProjectSummaryList,
)
async def portal_me_projects(
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> PortalProjectSummaryList:
    """List the projects the caller can see, by name.

    Backs the portal Progress Reports tab so a client / subcontractor can pick
    a project by name instead of pasting a UUID. Scoped server-side to the
    caller's non-expired ``project`` access rules - it never reveals a project
    the user was not explicitly granted.
    """
    projects = await service.list_accessible_projects(user.id)
    items = [PortalProjectSummary(id=p.id, name=p.name, project_code=p.project_code) for p in projects]
    return PortalProjectSummaryList(items=items, total=len(items))


@router.get(
    "/projects/{project_id}/progress-reports",
    response_model=PortalProgressReportList,
)
async def portal_list_progress_reports(
    project_id: uuid.UUID,
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PortalProgressReportList:
    """List generated progress reports for a project the caller can see.

    Access is granted by a non-expired ``project`` access rule on
    ``project_id``. A caller with no such rule gets a 404 (never 403) so
    the endpoint never confirms the existence of projects the caller is
    not entitled to. Only ``report_type == "progress_report"`` rows are
    returned - other report types stay invisible to the client portal.
    """
    from fastapi import HTTPException
    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    from app.modules.reporting.models import GeneratedReport as _GR

    if not await service.enforce_rls(user.id, "project", project_id, required="view"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    base = _select(_GR).where(_GR.project_id == project_id).where(_GR.report_type == "progress_report")
    count_stmt = _select(_func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = base.order_by(_GR.created_at.desc()).offset(offset).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())

    items = [
        PortalProgressReportEntry(
            id=r.id,
            title=r.title,
            generated_at=r.generated_at,
            report_type=r.report_type,
            format=r.format,
            period=_report_period(r.data_snapshot),
            has_content=bool(r.storage_key),
        )
        for r in rows
    ]
    return PortalProgressReportList(items=items, total=total)


@router.get(
    "/projects/{project_id}/progress-reports/{report_id}/content",
    response_class=HTMLResponse,
    responses={
        200: {"content": {"text/html": {}}},
        404: {"description": "Report not found or no access"},
        410: {"description": "Report body not yet rendered or removed from storage"},
    },
)
async def portal_get_progress_report_content(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
) -> HTMLResponse:
    """Return the rendered HTML body of one progress report.

    Double-gated: the caller must hold a ``project`` access rule on
    ``project_id`` (else 404) AND the report must belong to that project
    and be a ``progress_report`` (else 404, never 403, so cross-tenant
    probing learns nothing). 410 is surfaced when the metadata row exists
    but the rendered body is not reachable from storage.
    """
    from fastapi import HTTPException

    from app.modules.reporting.service import ReportingService

    if not await service.enforce_rls(user.id, "project", project_id, required="view"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    reporting = ReportingService(session)
    try:
        report, html_body = await reporting.get_report_content(report_id)
    except HTTPException as exc:
        # Collapse the reporting module's 404/410. A 410 (body gone) is
        # still useful to the client, so pass it through; a 404 stays 404.
        if exc.status_code == status.HTTP_410_GONE:
            raise
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        ) from exc

    # Cross-tenant / wrong-type guard: the report must live under the
    # project the caller proved access to and be a progress report.
    if report.project_id != project_id or report.report_type != "progress_report":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    return HTMLResponse(content=html_body)


# ── Portal-side payment-application submission ────────────────────────────


def _payment_application_detail(
    pa: object,
    wp_map: dict,
    raw_lines: list,
) -> PaymentApplicationDetailResponse:
    """Project a PaymentApplication + its lines into the portal detail view."""
    lines = []
    for line in raw_lines:
        name, planned = wp_map.get(line.work_package_id, ("", None))
        lines.append(
            PaymentApplicationLineDetail(
                work_package_id=line.work_package_id,
                work_package_name=name,
                planned_value=planned if planned is not None else 0,
                claimed_amount=line.claimed_amount,
                certified_amount=line.certified_amount,
                approved_amount=line.approved_amount,
            )
        )
    return PaymentApplicationDetailResponse(
        id=pa.id,
        agreement_id=pa.agreement_id,
        application_number=pa.application_number,
        period_start=pa.period_start,
        period_end=pa.period_end,
        gross_amount=pa.gross_amount,
        retention_amount=pa.retention_amount,
        net_amount=pa.net_amount,
        currency=pa.currency or "",
        status=pa.status,
        submitted_at=pa.submitted_at,
        lines=lines,
    )


@router.get(
    "/me/payment-applications",
    response_model=PaymentApplicationListResponse,
)
async def portal_me_payment_applications_list(
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
    agreement_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PaymentApplicationListResponse:
    """List the caller's payment applications.

    RLS: scoped to the ``agreement`` resources the portal user holds. A
    subcontractor never sees applications under another subcontractor's
    agreement. An ``agreement_id`` outside the accessible set yields an empty
    list (indistinguishable from one with no applications).
    """
    rows, total = await service.list_payment_applications_for_user(
        user.id,
        agreement_id=agreement_id,
        status_filter=status_filter,
        offset=offset,
        limit=limit,
    )
    return PaymentApplicationListResponse(
        items=[PaymentApplicationListItem.model_validate(r) for r in rows],
        total=total,
    )


@router.get(
    "/me/payment-applications/{payment_application_id}",
    response_model=PaymentApplicationDetailResponse,
)
async def portal_me_payment_application_detail(
    payment_application_id: uuid.UUID,
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> PaymentApplicationDetailResponse:
    """Return one payment application with its work-package lines.

    RLS: 404 (never 403) on a missing id OR one whose agreement the caller
    cannot access, so a portal user cannot probe for the existence of another
    subcontractor's application.
    """
    from fastapi import HTTPException

    pa = await service.get_payment_application_for_user(user.id, payment_application_id)
    if pa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment application not found",
        )

    wp_map = await service.work_package_names_for_agreement(pa.agreement_id)
    raw_lines = await service.list_payment_application_lines(pa.id)
    return _payment_application_detail(pa, wp_map, raw_lines)


@router.post(
    "/me/payment-applications",
    response_model=PaymentApplicationDetailResponse,
    status_code=201,
)
async def portal_me_payment_application_submit(
    data: PaymentApplicationSubmitPayload,
    request: Request,
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> PaymentApplicationDetailResponse:
    """Submit a new payment application against an accessible agreement.

    RLS: the caller must hold ``submit`` permission on ``data.agreement_id``
    and every line's work package must belong to that agreement; otherwise the
    request 404s (never 403). Retention / net / application-number / currency
    are computed server-side from the agreement - the client cannot drive them.
    """
    pa = await service.submit_payment_application_for_user(
        user.id,
        agreement_id=data.agreement_id,
        period_start=data.period_start,
        period_end=data.period_end,
        lines=data.lines,
        client_ip=_client_ip(request),
    )
    wp_map = await service.work_package_names_for_agreement(pa.agreement_id)
    raw_lines = await service.list_payment_application_lines(pa.id)
    return _payment_application_detail(pa, wp_map, raw_lines)


@router.get(
    "/me/payment-agreements",
    response_model=PortalAgreementSummaryList,
)
async def portal_me_payment_agreements(
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> PortalAgreementSummaryList:
    """List the agreements the caller can submit payment applications against.

    Scoped by RLS to the caller's ``agreement`` access rules and to claimable
    (active / completed) agreements only. Each carries its work packages so the
    submit form can render the line grid in one call.
    """
    pairs = await service.list_submittable_agreements_for_user(user.id)
    items = [
        PortalAgreementSummary(
            id=agr.id,
            title=agr.title,
            currency=agr.currency or "",
            retention_percent=agr.retention_percent,
            status=agr.status,
            work_packages=[
                PortalWorkPackageEntry(id=wp.id, name=wp.name, planned_value=wp.planned_value) for wp in wps
            ],
        )
        for agr, wps in pairs
    ]
    return PortalAgreementSummaryList(items=items, total=len(items))


# ── Portal-side shared-document library ───────────────────────────────────


@router.get(
    "/me/documents",
    response_model=PortalSharedDocumentList,
)
async def portal_me_documents(
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> PortalSharedDocumentList:
    """List the documents an admin has shared with the caller.

    Scoped server-side to the caller's non-expired ``document`` access rules
    - it never reveals a document the portal user was not explicitly granted.
    Returns metadata only (id, name, size, mime type, project); the bytes are
    fetched separately via ``GET /me/documents/{document_id}/content``, which
    re-checks the grant before streaming.
    """
    docs = await service.list_accessible_documents(user.id)
    items = [PortalSharedDocument.model_validate(d) for d in docs]
    return PortalSharedDocumentList(items=items, total=len(items))


@router.get(
    "/me/documents/{document_id}/content",
    responses={
        200: {"description": "The shared document's file bytes (Range-capable)"},
        403: {"description": "No access rule grants this document to the caller"},
        404: {"description": "The document row no longer exists"},
        410: {"description": "Metadata exists but the file is gone from disk"},
    },
)
async def portal_me_document_content(
    document_id: uuid.UUID,
    request: Request,
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
) -> FileResponse:
    """Stream one shared document's bytes to the portal caller.

    Security (critical): the FIRST thing this does is enforce RLS - the
    caller must hold a non-expired ``document`` access rule of at least
    ``view`` on exactly this ``document_id``, else the request is refused 403
    before the document row is ever loaded. The client-supplied id is never
    trusted without that check, so a portal user can never pull a document
    that was not explicitly shared with them. ``enforce_rls`` consults only
    the access-rule table, so the 403 is returned identically whether or not
    the id exists - an ungranted caller cannot even probe for existence.

    Disk handling mirrors the public share-file endpoint: 404 when the
    document row is gone, 410 when the metadata row exists but the blob is no
    longer on disk. On success the access is written to the same audit log the
    internal admin surface reads, and the file is returned via a Range-capable
    ``FileResponse`` (real media type; inline for image / audio / video so the
    browser can preview and seek, attachment otherwise).
    """
    from fastapi import HTTPException
    from sqlalchemy import select as _select

    from app.modules.documents.models import Document

    # 1. RLS FIRST - refuse before touching the document row.
    if not await service.enforce_rls(user.id, "document", document_id, required="view"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this document",
        )

    # 2. The grant is proven; only now resolve the row.
    doc = (await session.execute(_select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File no longer exists",
        )

    file_path = doc.file_path
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="File is no longer on disk",
        )

    # 3. Audit the access (same log the admin document-access surface reads).
    await service.record_document_access(
        portal_user_id=user.id,
        document_type="document",
        document_id=document_id,
        action="view",
        ip_address=_client_ip(request),
    )

    # 4. Stream it. FileResponse honours the Range header (206 partial) on its
    #    own, so large PDFs and video preview / seek work without extra plumbing.
    media_type = doc.mime_type or "application/octet-stream"
    inline = media_type.startswith(("image/", "audio/", "video/"))
    return FileResponse(
        path=file_path,
        filename=doc.name,
        media_type=media_type,
        content_disposition_type="inline" if inline else "attachment",
    )


__all__ = ["router"]
