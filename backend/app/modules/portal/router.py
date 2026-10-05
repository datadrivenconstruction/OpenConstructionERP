# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Customer & Partner Portal - FastAPI routes.

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
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from app.core.rate_limiter import client_identifier, registration_limiter
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub.models import NON_3D_MODEL_FORMATS, BIMModel
from app.modules.bim_hub.schemas import BIMElementListResponse, BIMElementResponse
from app.modules.bim_hub.service import BIMHubService
from app.modules.portal.dependencies import (
    PortalSessionToken,
    RequirePortalSession,
)
from app.modules.portal.login_email import EmailKind, EmailStatus, send_login_email
from app.modules.portal.models import PortalUser
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
    PortalBimModelEntry,
    PortalBimModelList,
    PortalChangeOrderEntry,
    PortalChangeOrderList,
    PortalInvoiceEntry,
    PortalInvoiceList,
    PortalMilestoneEntry,
    PortalMilestoneList,
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
from app.modules.portal.service import PortalService, now_utc

router = APIRouter(tags=["portal"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> PortalService:
    return PortalService(session)


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def _link_email_args(kind: EmailKind, user: PortalUser, token: str, expires_at: datetime) -> dict[str, Any]:
    # Plain values, read now: the self-service email is sent after the
    # response, when the request's session is already closed.
    return {
        "kind": kind,
        "email": user.email,
        "full_name": user.full_name or "",
        "language": user.language,
        "role": user.portal_role,
        "token": token,
        "expires_at": expires_at,
        "now": now_utc(),
    }


async def _email_link(kind: EmailKind, user: PortalUser, token: str, expires_at: datetime) -> EmailStatus:
    """Email a portal user their magic link, in their own language."""
    return await send_login_email(**_link_email_args(kind, user, token, expires_at))


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
    """Invite a new portal user (idempotent) and return the magic-link once."""
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
    email_status: EmailStatus | Literal["not_requested"] = "not_requested"
    if data.send_email:
        # Commit first: a link mailed out of a transaction that then fails
        # would not open.
        await service.session.commit()
        email_status = await _email_link("invite", user, plain, expires_at)
    return PortalUserInviteResponse(
        user=PortalUserResponse.model_validate(user),
        magic_link_token=plain,
        magic_link_expires_at=expires_at,
        email_status=email_status,
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
    """List portal users with optional role/status filters."""
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
    """Resend the invitation magic-link to an existing portal user.

    A suspended user cannot sign in, so mailing them an invitation would only
    confuse; reactivate them first.
    """
    user = await service.get_portal_user(portal_user_id)
    if user.status == "suspended":
        raise HTTPException(status.HTTP_409_CONFLICT, "This portal user is suspended. Reactivate them first.")
    user, plain, expires_at = await service.invite_portal_user(
        email=user.email,
        role=user.portal_role,
        language=user.language,
        full_name=user.full_name,
        timezone_=user.timezone,
        granted_by=user_id,
        created_ip=_client_ip(request),
    )
    await service.session.commit()
    return PortalUserInviteResponse(
        user=PortalUserResponse.model_validate(user),
        magic_link_token=plain,
        magic_link_expires_at=expires_at,
        email_status=await _email_link("invite", user, plain, expires_at),
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
    background: BackgroundTasks,
    service: PortalService = Depends(_get_service),
) -> MagicLinkResponse:
    """Email a sign-in link to a registered portal user.

    Always answers 202 with the same body, whether or not the address is
    registered, so the endpoint never tells a caller who is a client. The
    request itself does no work that depends on the address: the lookup, the
    new link and the email all happen after the response, so a registered
    address does not answer slower than an unknown one either. The token
    never appears in the body.
    """
    allowed, _ = registration_limiter.is_allowed(client_identifier(request))
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Try again later.")
    background.add_task(_mint_and_email_login_link, data.email, _client_ip(request))
    return MagicLinkResponse()


async def _mint_and_email_login_link(email: str, created_ip: str | None) -> None:
    """Mint a sign-in link for ``email`` if it belongs to a portal user, and mail it.

    Runs after the response, in its own session: the request's session is
    closed by then. Never raises, there is nobody left to answer.

    Without a mail transport nothing is minted. A new link retires the old
    ones, and on such a server the link the builder copied by hand is the
    client's only way in: minting one that nobody receives would lock them
    out, and would let anyone who knows the address do it to them.
    """
    from app.config import get_settings
    from app.core.email import email_delivery_enabled
    from app.database import async_session_factory

    if not email_delivery_enabled(get_settings()):
        return
    try:
        async with async_session_factory() as session:
            minted = await PortalService(session).request_magic_link(email, created_ip=created_ip)
            if minted is None:
                return
            user, plain, expires_at = minted
            args = _link_email_args("login", user, plain, expires_at)
            await session.commit()
    except Exception:
        logger.exception("Portal sign-in link could not be issued")
        return
    await send_login_email(**args)


@router.post("/auth/consume", response_model=SessionResponse)
async def portal_consume_magic_link(
    data: MagicLinkConsume,
    request: Request,
    service: PortalService = Depends(_get_service),
) -> SessionResponse:
    """Consume a magic link and receive a session token."""
    user, sess, plain, expires_at, redirect_path = await service.consume_magic_link(
        data.token,
        purpose="login",
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SessionResponse(
        session_token=plain,
        expires_at=expires_at,
        portal_user=PortalUserResponse.model_validate(user),
        redirect_path=redirect_path,
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


@router.get("/me/documents", response_model=PortalSharedDocumentList)
async def portal_me_documents(
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> PortalSharedDocumentList:
    """List the documents shared with the caller through document access rules.

    Only documents the caller was explicitly granted (a non-expired
    ``document`` access rule) are returned; a rule whose document has since
    been deleted is silently skipped.
    """
    docs = await service.list_accessible_documents(user.id)
    items = [PortalSharedDocument.model_validate(d) for d in docs]
    return PortalSharedDocumentList(items=items, total=len(items))


@router.get("/me/documents/{document_id}/content")
async def portal_me_document_content(
    document_id: uuid.UUID,
    request: Request,
    user: RequirePortalSession,
    service: PortalService = Depends(_get_service),
) -> FileResponse:
    """Stream a document shared with the caller.

    RLS is enforced BEFORE the document is looked up, so the client-supplied id
    is never used to read anything until the grant is proven, and an ungranted
    caller gets an identical 403 whether or not the id exists (no existence
    oracle). The file is served with a Range-capable FileResponse so a PDF or
    video seeks without buffering the whole file.
    """
    import mimetypes
    import os

    from fastapi import HTTPException
    from sqlalchemy import select

    from app.modules.documents.models import Document

    if not await service.enforce_rls(user.id, "document", document_id, required="view"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this document",
        )

    row = (await service.session.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="File no longer exists")
    path = row.file_path
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=410, detail="File is no longer on disk")

    await service.record_document_access(
        portal_user_id=user.id,
        document_type="document",
        document_id=document_id,
        action="view",
        ip_address=_client_ip(request),
    )

    media_type = row.mime_type or mimetypes.guess_type(row.name)[0] or "application/octet-stream"
    inline = media_type.split("/", 1)[0] in {"video", "audio", "image"}
    return FileResponse(
        path,
        media_type=media_type,
        filename=row.name,
        content_disposition_type="inline" if inline else "attachment",
    )


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


@router.get(
    "/me/invoices",
    response_model=PortalInvoiceList,
)
async def portal_list_invoices(
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
    project_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PortalInvoiceList:
    """List issued invoices the caller can see.

    Same dual access model as change orders: a per-invoice ``invoice`` grant
    for specific invoices, or a ``project`` grant that exposes every issued
    invoice under that project. Only issued, client-facing (receivable)
    invoices are returned - drafts and payable/vendor invoices stay invisible.
    """
    from sqlalchemy import func as _func
    from sqlalchemy import or_
    from sqlalchemy import select as _select

    from app.modules.finance.models import Invoice as _Invoice

    accessible_invoices = await service.list_accessible_resources(user.id, "invoice")
    accessible_projects = await service.list_accessible_resources(user.id, "project")
    if not accessible_invoices and not accessible_projects:
        return PortalInvoiceList(items=[], total=0)

    # A per-invoice grant on project B must not unlock project A, so the scope
    # predicate (project OR specific invoice) is ALWAYS applied, even when a
    # project_id filter is supplied.
    scope_ors = []
    if accessible_projects:
        scope_ors.append(_Invoice.project_id.in_(accessible_projects))
    if accessible_invoices:
        scope_ors.append(_Invoice.id.in_(accessible_invoices))
    scope_predicate = or_(*scope_ors)

    base = (
        _select(_Invoice)
        .where(_Invoice.invoice_direction == "receivable")
        .where(_Invoice.status != "draft")
        .where(scope_predicate)
    )
    if project_id is not None:
        base = base.where(_Invoice.project_id == project_id)

    count_stmt = _select(_func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = base.order_by(_Invoice.created_at.desc()).offset(offset).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())
    today = now_utc().date()

    items = [
        PortalInvoiceEntry(
            id=inv.id,
            project_id=inv.project_id,
            invoice_number=inv.invoice_number,
            invoice_date=inv.invoice_date or "",
            due_date=inv.due_date,
            currency_code=inv.currency_code or "",
            amount_total=inv.amount_total,
            status=inv.status,
            days_overdue=(late := _days_overdue(inv.due_date, inv.status, today)),
            is_overdue=late is not None,
        )
        for inv in rows
    ]
    return PortalInvoiceList(items=items, total=total)


#: Invoice states that owe nothing, so a past due date is not overdue.
#: Statuses in which the client still owes the invoice. ``pending`` has not
#: gone out yet, and ``paid``, ``cancelled`` and ``credit_note_issued`` owe
#: nothing, so none of them can be overdue whatever the due date says.
_OWED_INVOICE_STATUSES = frozenset({"approved", "sent"})


def _days_overdue(due_date: str | None, status_: str | None, today: date) -> int | None:
    """Days an unsettled invoice is past its due date, or ``None`` when it is not.

    Only an invoice the client still owes can be late, and a blank due date
    never counts. ``due_date`` is stored as text, so an unreadable value
    counts as "no due date" rather than failing the list.
    """
    if not due_date or (status_ or "") not in _OWED_INVOICE_STATUSES:
        return None
    try:
        due = date.fromisoformat(due_date.strip()[:10])
    except ValueError:
        return None
    late = (today - due).days
    return late if late > 0 else None


# ── Portal-side BIM/CAD model visibility (view-only) ──────────────────────


async def _portal_can_view_bim(
    service: PortalService,
    session: SessionDep,
    user_id: uuid.UUID,
    model: BIMModel,
) -> bool:
    """Dual-grant RLS check for a BIM model: per-model OR per-project.

    ``session`` is accepted for symmetry with the rest of this module's
    RLS helpers even though the lookup here only needs ``service`` - it
    keeps the call site identical whether or not a future check needs a
    raw query.
    """
    del session  # not needed directly; service already carries the session
    if await service.enforce_rls(user_id, "bim", model.id, required="view"):
        return True
    accessible_projects = await service.list_accessible_resources(user_id, "project")
    return model.project_id in accessible_projects


@router.get(
    "/me/bim-models",
    response_model=PortalBimModelList,
)
async def portal_list_bim_models(
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
    project_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> PortalBimModelList:
    """List BIM/CAD models shared with the caller, for the view-only viewer.

    Same dual access model as change orders / invoices: a per-model ``bim``
    grant for specific models, or a ``project`` grant that exposes every
    model under that project. Only ``status == "ready"`` models with a
    real 3D mesh are returned - 2D-only formats (DWG/DXF/DGN, see
    ``NON_3D_MODEL_FORMATS``) and models still converting or errored never
    appear here, since there is nothing a read-only 3D viewer could show.
    """
    from sqlalchemy import func as _func
    from sqlalchemy import not_, or_
    from sqlalchemy import select as _select

    accessible_models = await service.list_accessible_resources(user.id, "bim")
    accessible_projects = await service.list_accessible_resources(user.id, "project")
    if not accessible_models and not accessible_projects:
        return PortalBimModelList(items=[], total=0)

    # A per-model grant on project B must not unlock project A, so the scope
    # predicate (project OR specific model) is ALWAYS applied, even when a
    # project_id filter is supplied.
    scope_ors = []
    if accessible_projects:
        scope_ors.append(BIMModel.project_id.in_(accessible_projects))
    if accessible_models:
        scope_ors.append(BIMModel.id.in_(accessible_models))
    scope_predicate = or_(*scope_ors)

    # Mirrors bim_hub.models.is_non_3d_format(): a NULL/empty model_format is
    # 3D-eligible, everything else is excluded iff it substring-matches one
    # of the 2D-drawing formats (case-insensitive).
    non_3d_ors = [BIMModel.model_format.ilike(f"%{fmt}%") for fmt in NON_3D_MODEL_FORMATS]
    format_predicate = or_(BIMModel.model_format.is_(None), not_(or_(*non_3d_ors)))

    base = _select(BIMModel).where(BIMModel.status == "ready").where(scope_predicate).where(format_predicate)
    if project_id is not None:
        base = base.where(BIMModel.project_id == project_id)

    count_stmt = _select(_func.count()).select_from(base.subquery())
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = base.order_by(BIMModel.created_at.desc()).offset(offset).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())

    items = [
        PortalBimModelEntry(
            id=m.id,
            project_id=m.project_id,
            name=m.name,
            discipline=m.discipline or "",
            model_format=m.model_format or "",
            element_count=m.element_count,
            status=m.status,
        )
        for m in rows
    ]
    return PortalBimModelList(items=items, total=total)


@router.get(
    "/me/bim-models/{model_id}/elements",
    response_model=BIMElementListResponse,
)
async def portal_bim_model_elements(
    model_id: uuid.UUID,
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50000, ge=1, le=50000),
) -> BIMElementListResponse:
    """Return a skeleton element list for a shared BIM model, read-only.

    Mirrors the ``skeleton=True`` branch of bim_hub's internal
    ``GET /models/{model_id}/elements`` (plain id/mesh_ref/name/element_type/
    bounding_box rows, no BOQ links / documents / tasks / validation joins)
    so the portal 3D viewer can match meshes to elements without exposing
    any cost data, links or authoring surface. The model is loaded first so
    the RLS check below has its ``project_id``; only then is a 403 raised
    for an ungranted caller.
    """
    model = await session.get(BIMModel, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BIM model not found")
    if not await _portal_can_view_bim(service, session, user.id, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this BIM model")

    bim_service = BIMHubService(session)
    plain_items, plain_total = await bim_service.list_elements(model_id, offset=offset, limit=limit)

    items: list[BIMElementResponse] = []
    for e in plain_items:
        resp = BIMElementResponse.model_validate(e)
        resp.properties = {}
        resp.quantities = {}
        resp.metadata = {}
        items.append(resp)
    return BIMElementListResponse(items=items, total=plain_total, offset=offset, limit=limit)


@router.get("/me/bim-models/{model_id}/geometry", response_model=None)
async def portal_bim_model_geometry(
    model_id: uuid.UUID,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
    token: str | None = Query(
        default=None,
        description=(
            "Portal session token, as an alternative to the Authorization "
            "header - the browser's glTF/COLLADA geometry loader used by "
            "the read-only viewer cannot attach custom headers."
        ),
    ),
    authorization: str | None = Header(default=None),
) -> FileResponse | RedirectResponse | Response:
    """Serve the GLB/DAE geometry blob for a BIM model shared with the caller.

    Auth accepts either an ``Authorization: Bearer <session_token>`` header
    or a ``?token=`` query parameter, validated the same way
    :func:`app.modules.portal.dependencies.get_current_portal_user` does
    (:meth:`PortalService.verify_session`) - the query fallback exists only
    because static geometry loaders cannot set headers. RLS is the same
    dual grant as the model list. Geometry resolution and the disk-streaming
    behaviour (Range-capable ``FileResponse`` with zero in-memory copy for
    local disk, a presigned redirect for S3 - see issue #291) are delegated
    straight to :mod:`app.modules.bim_hub.file_storage`, the same module the
    internal BIM viewer uses, so both surfaces stay in sync.
    """
    auth_token = token
    if not auth_token and authorization and authorization.lower().startswith("bearer "):
        auth_token = authorization[7:]
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal session required",
        )
    user = await service.verify_session(auth_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired portal session",
        )

    model = await session.get(BIMModel, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BIM model not found")
    if not await _portal_can_view_bim(service, session, user.id, model):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this BIM model")

    project_id = str(model.project_id)
    found = await bim_file_storage.find_geometry_key(project_id, model_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="3D geometry is not available for this model yet",
        )
    key, ext = found
    media_type = bim_file_storage.GEOMETRY_MEDIA_TYPES.get(ext, "application/octet-stream")
    cache_headers = {"Cache-Control": "no-store, no-cache, must-revalidate"}

    # Prefer a presigned URL so the browser fetches directly from the bucket
    # (S3). Local backend returns None -> fall back to streaming below.
    presigned = bim_file_storage.presigned_geometry_url(key)
    if presigned:
        return RedirectResponse(url=presigned, status_code=307)

    from app.core.storage import get_storage_backend

    backend = get_storage_backend()
    disk_path = backend.local_path(key)
    if disk_path is not None:
        # Streams with HTTP Range support and zero in-memory copy - see the
        # issue #291 note on the internal endpoint this mirrors.
        return FileResponse(disk_path, media_type=media_type, headers=cache_headers)

    geo_bytes = await backend.get(key)
    return Response(content=geo_bytes, media_type=media_type, headers=cache_headers)


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


#: How far ahead the client's milestone list looks by default.
_MILESTONE_WINDOW_DAYS = 14


@router.get(
    "/projects/{project_id}/milestones",
    response_model=PortalMilestoneList,
)
async def portal_list_milestones(
    project_id: uuid.UUID,
    user: RequirePortalSession,
    session: SessionDep,
    service: PortalService = Depends(_get_service),
    days: int = Query(default=_MILESTONE_WINDOW_DAYS, ge=1, le=90),
) -> PortalMilestoneList:
    """The project's next milestones, for a client who can see the project.

    Access follows the progress reports: a non-expired ``project`` rule, else
    404 so the endpoint never confirms a project exists. Only milestones a
    person marked ``client_visible`` are listed, from every schedule of the
    project that is not archived. The list holds the milestones expected
    within ``days`` and the ones that are late, so a slip stays in view
    instead of dropping out of the window.
    """
    from sqlalchemy import select as _select

    from app.modules.schedule.models import Activity as _Activity
    from app.modules.schedule.models import Schedule as _Schedule

    if not await service.enforce_rls(user.id, "project", project_id, required="view"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    stmt = (
        _select(_Activity)
        .join(_Schedule, _Schedule.id == _Activity.schedule_id)
        .where(_Schedule.project_id == project_id)
        .where(_Schedule.status != "archived")
        .where(_Activity.activity_type == "milestone")
        .where(_Activity.client_visible.is_(True))
    )
    rows = list((await session.execute(stmt)).scalars().all())
    baseline_finish = await _baseline_finish_dates(session, project_id, {act.schedule_id for act in rows})

    today = now_utc().date()
    items: list[PortalMilestoneEntry] = []
    for act in rows:
        entry = _milestone_entry(act, today, baseline_finish.get(str(act.id)))
        if entry is None:
            continue
        if entry.is_late or (not entry.is_done and 0 <= entry.days_until <= days):
            items.append(entry)
    items.sort(key=lambda e: (e.expected_date, e.name))
    return PortalMilestoneList(items=items, window_days=days)


def _read_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        return None


async def _baseline_finish_dates(session: Any, project_id: uuid.UUID, schedule_ids: set[uuid.UUID]) -> dict[str, str]:
    """Activity id to finish date in the newest active baseline of each schedule.

    A baseline is the plan as agreed; the live ``end_date`` is where the
    milestone sits now. With no baseline there is nothing to compare against
    and the client simply sees one date.
    """
    if not schedule_ids:
        return {}
    from sqlalchemy import or_ as _or
    from sqlalchemy import select as _select

    from app.modules.schedule.models import ScheduleBaseline as _Baseline
    from app.modules.schedule.snapshot_envelope import normalize_envelope

    stmt = (
        _select(_Baseline)
        .where(_Baseline.is_active.is_(True))
        .where(
            _or(
                _Baseline.schedule_id.in_(schedule_ids),
                (_Baseline.schedule_id.is_(None)) & (_Baseline.project_id == project_id),
            )
        )
        .order_by(_Baseline.created_at.desc())
    )
    newest: dict[Any, Any] = {}
    for baseline in (await session.execute(stmt)).scalars().all():
        newest.setdefault(baseline.schedule_id, baseline)
    # A schedule's own baseline wins over a project-wide one.
    ordered = [b for key, b in newest.items() if key is None] + [b for key, b in newest.items() if key is not None]
    finish: dict[str, str] = {}
    for baseline in ordered:
        for row in normalize_envelope(baseline.snapshot_data)["activities"]:
            if isinstance(row, dict) and row.get("id") and row.get("end_date"):
                finish[str(row["id"])] = str(row["end_date"])
    return finish


def _milestone_entry(act: Any, today: date, baseline_end: str | None = None) -> PortalMilestoneEntry | None:
    """Project an activity for the client, or ``None`` when it has no usable date.

    The expected date is the activity's live end date, which rescheduling
    moves when the work before it slips. The planned date is the same
    activity's finish in the active baseline, when one was taken, so the
    client sees how far it moved. ``early_finish`` is not a date: CPM stores
    it as a day offset from the schedule start.
    """
    expected = _read_date(act.end_date) or _read_date(act.start_date)
    if expected is None:
        return None
    planned = _read_date(baseline_end) or expected
    try:
        done = act.status == "completed" or float(act.progress_pct or 0) >= 100
    except (TypeError, ValueError):
        done = act.status == "completed"
    days_until = (expected - today).days
    return PortalMilestoneEntry(
        id=act.id,
        name=act.name,
        planned_date=planned.isoformat(),
        expected_date=expected.isoformat(),
        status=act.status,
        is_done=done,
        is_late=not done and days_until < 0,
        days_until=days_until,
    )


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
    not entitled to. Only published ``report_type == "progress_report"``
    rows are returned - other report types and unpublished drafts stay
    invisible to the client portal.
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

    # Only reports a person released to the client. A freshly generated one
    # may still be a draft carrying internal notes.
    base = (
        _select(_GR)
        .where(_GR.project_id == project_id)
        .where(_GR.report_type == "progress_report")
        .where(_GR.published_at.is_not(None))
    )
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
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    try:
        report = await reporting.get_report(report_id)
    except HTTPException as exc:
        raise not_found from exc

    # Cross-tenant / wrong-type / unreleased guard, checked before the body is
    # read so a draft answers exactly like a missing id (never 410): the report
    # must live under the project the caller proved access to, be a progress
    # report, and have been published to the portal.
    if report.project_id != project_id or report.report_type != "progress_report" or report.published_at is None:
        raise not_found

    try:
        _report, html_body = await reporting.get_report_content(report_id)
    except HTTPException as exc:
        # A 410 (body gone) is still useful to the client, so pass it through.
        if exc.status_code == status.HTTP_410_GONE:
            raise
        raise not_found from exc

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


__all__ = ["router"]
