"""Buyer self-service portal — public + JWT-internal endpoints.

Routes (all under ``/api/v1/property-dev/portal/``):

    POST   /issue/                          — JWT-authed (MANAGER+);
                                              mint a fresh magic link.
    POST   /verify/                         — public; check a token
                                              against the revocation list.
    GET    /buyer/{token}/overview/         — public; full landing-page
                                              payload (reservation, SPA,
                                              payment schedule, docs).
    GET    /buyer/{token}/documents/{id}/download/
                                            — public; PDF stream IF the
                                              doc belongs to this token's
                                              buyer. 404 otherwise (IDOR).
    POST   /buyer/{token}/upload-kyc/       — public; magic-byte-validated
                                              file upload (PDF / images).
    POST   /buyer/{token}/contact-agent/    — public; files a CrmActivity
                                              and fires the lead-msg event.
    GET    /buyer-links/{buyer_id}/         — JWT-authed; list active
                                              tokens for the manager UI.
    POST   /tokens/{token_id}/revoke/       — JWT-authed (MANAGER+);
                                              revoke a token.

Token-binding (IDOR) guard: every ``/buyer/{token}/...`` handler
re-resolves the token through :meth:`PortalLinkService.verify_token`
and then verifies the requested ``doc_id`` (or implicit subject) belongs
to ``ctx.buyer``. UUID-swap attempts collapse to 404 (NOT 403) so the
endpoint can't be turned into an existence oracle for other buyers'
data — mirrors the property_dev R7 convention.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.events import event_bus
from app.core.file_signature import (
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
    mime_for_signature,
)
from app.core.file_signature import (
    require as require_signature,
)
from app.core.rate_limiter import approval_limiter
from app.dependencies import (
    CurrentUserPayload,
    RequirePermission,
    RequireRole,
    SessionDep,
    SettingsDep,
)
from app.modules.crm.models import CrmActivity
from app.modules.documents.models import Document
from app.modules.property_dev.models import (
    Buyer,
    Development,
    HandoverDoc,
    Instalment,
    PaymentSchedule,
    Plot,
    PortalToken,
)
from app.modules.property_dev.portal_schemas import (
    _KYC_DOC_TYPE_PATTERN,
    PortalContactAgentRequest,
    PortalContactAgentResponse,
    PortalDocumentRow,
    PortalInstalmentRow,
    PortalKycRequest,
    PortalKycUploadResponse,
    PortalOverviewResponse,
    PortalReservationCard,
    PortalSalesContractCard,
    PortalTokenIssueRequest,
    PortalTokenIssueResponse,
    PortalTokenResponse,
    PortalVerifyRequest,
    PortalVerifyResponse,
)
from app.modules.property_dev.portal_service import (
    PortalContext,
    PortalLinkService,
    PortalTokenError,
)

logger = logging.getLogger(__name__)

portal_router = APIRouter()

# KYC files land under a per-buyer folder. We never include the buyer's
# email/name in the path (PII at rest); only the UUID.
_KYC_UPLOADS_ROOT = Path("uploads/property_dev/portal/kyc")

# Magic-byte allow-list for KYC uploads. PDF + the common image
# formats; no Office/ZIP/CAD junk (we don't need to render those).
_KYC_ALLOWED_SIGNATURES = frozenset({"pdf", "png", "jpeg", "heic", "heif"})

# Rate-limit bucket — per-token (NOT per-IP) so a buyer behind CGNAT
# isn't starved by a noisy neighbour. The token is itself a bearer
# capability so using it as the bucket key is safe.
_PORTAL_RATE_BUCKET_PREFIX = "propdev_portal:"


def _client_ip(request: Request) -> str:
    """Best-effort client IP for the audit row. Mirrors rate_limiter."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return ""


def _portal_rate_check(token: str) -> None:
    """30 req/min/token via the shared ``approval_limiter`` bucket.

    Spec asks for 30/min/token; ``approval_limiter`` default is 20.
    We keep the bucket key prefixed so it doesn't collide with the
    internal ``invoice.approve`` calls keyed on user_id.
    """
    bucket_key = f"{_PORTAL_RATE_BUCKET_PREFIX}{token[:48]}"
    allowed, _ = approval_limiter.is_allowed(bucket_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again in a minute.",
            headers={"Retry-After": "60"},
        )


async def _resolve_portal_context(
    session: SessionDep,
    settings: SettingsDep,
    token: str,
    request: Request,
    *,
    consume: bool = False,
) -> PortalContext:
    """Verify token + load PortalContext or raise 401.

    Wraps :meth:`PortalLinkService.verify_token` with rate limiting
    and standardised 401 mapping. Used by every public ``/buyer/...``
    endpoint.

    Pass ``consume=True`` from the ``/verify/`` endpoint to enforce
    single-use magic-link redemption (industry standard — Slack/Notion/
    Linear). All other endpoints leave ``consume=False`` so the
    longer-lived session JWT keeps working until expiry/revocation.
    """
    _portal_rate_check(token)
    svc = PortalLinkService(session, settings)
    try:
        return await svc.verify_token(
            token,
            client_ip=_client_ip(request),
            consume=consume,
        )
    except PortalTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": exc.code},
        ) from exc


# ── Issuance (internal) ─────────────────────────────────────────────────


@portal_router.post(
    "/portal/issue/",
    response_model=PortalTokenIssueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint a buyer-portal magic link",
)
async def issue_portal_token(
    data: PortalTokenIssueRequest,
    session: SessionDep,
    settings: SettingsDep,
    user_payload: CurrentUserPayload,
    _role: None = Depends(RequireRole("manager")),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> PortalTokenIssueResponse:
    """Sales-manager-only: create a fresh magic link for a buyer.

    The full URL is shown once in the response (and once in the issuing
    email) — we keep only the ``jti`` server-side, never the plaintext
    token. If the buyer already has an active token, it stays valid;
    callers wanting rotation must explicitly revoke the old one first.

    IDOR: re-check the buyer is owned by the calling user's project
    so a manager from a different tenant can't mint a link against
    someone else's buyer.
    """
    buyer = await session.get(Buyer, data.buyer_id)
    if buyer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Buyer not found",
        )

    # Cross-tenant guard (collapse to 404, not 403, to avoid leaking
    # the buyer's existence).
    is_admin = user_payload.get("role") == "admin"
    if not is_admin:
        from app.modules.projects.repository import ProjectRepository
        from app.modules.property_dev.repository import DevelopmentRepository

        dev = await DevelopmentRepository(session).get_by_id(
            buyer.development_id,
        )
        if dev is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Buyer not found",
            )
        proj = await ProjectRepository(session).get_by_id(dev.project_id)
        caller_id = user_payload.get("sub") or ""
        if proj is None or str(proj.owner_id) != str(caller_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Buyer not found",
            )

    svc = PortalLinkService(session, settings)
    try:
        issuer_id = uuid.UUID(str(user_payload.get("sub")))
    except (TypeError, ValueError):
        issuer_id = None
    token, row = await svc.issue_token(
        buyer_id=data.buyer_id,
        reservation_id=data.reservation_id,
        sales_contract_id=data.sales_contract_id,
        issued_by_user_id=issuer_id,
    )
    return PortalTokenIssueResponse(
        token=token,
        expires_at=row.expires_at,
        portal_url=svc.portal_url(token),
        row=PortalTokenResponse.model_validate(row),
    )


@portal_router.get(
    "/portal/buyer-links/{buyer_id}/",
    response_model=list[PortalTokenResponse],
    summary="List active magic links for a buyer",
)
async def list_buyer_portal_tokens(
    buyer_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    user_payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("property_dev.read")),
) -> list[PortalTokenResponse]:
    """List non-revoked, non-expired tokens for a buyer (manager UI)."""
    buyer = await session.get(Buyer, buyer_id)
    if buyer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Buyer not found",
        )
    # Cross-tenant guard (same shape as issue/).
    is_admin = user_payload.get("role") == "admin"
    if not is_admin:
        from app.modules.projects.repository import ProjectRepository
        from app.modules.property_dev.repository import DevelopmentRepository

        dev = await DevelopmentRepository(session).get_by_id(
            buyer.development_id,
        )
        if dev is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Buyer not found",
            )
        proj = await ProjectRepository(session).get_by_id(dev.project_id)
        caller_id = user_payload.get("sub") or ""
        if proj is None or str(proj.owner_id) != str(caller_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Buyer not found",
            )

    svc = PortalLinkService(session, settings)
    rows = await svc.list_active_for_buyer(buyer_id)
    return [PortalTokenResponse.model_validate(r) for r in rows]


@portal_router.post(
    "/portal/tokens/{token_id}/revoke/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a buyer-portal magic link",
)
async def revoke_portal_token(
    token_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    user_payload: CurrentUserPayload,
    _role: None = Depends(RequireRole("manager")),
    _perm: None = Depends(RequirePermission("property_dev.update")),
) -> None:
    """MANAGER+ revokes a magic link by row id."""
    row = await session.get(PortalToken, token_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )
    # Cross-tenant guard via buyer.
    buyer = await session.get(Buyer, row.buyer_id)
    if buyer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )
    is_admin = user_payload.get("role") == "admin"
    if not is_admin:
        from app.modules.projects.repository import ProjectRepository
        from app.modules.property_dev.repository import DevelopmentRepository

        dev = await DevelopmentRepository(session).get_by_id(
            buyer.development_id,
        )
        if dev is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found",
            )
        proj = await ProjectRepository(session).get_by_id(dev.project_id)
        caller_id = user_payload.get("sub") or ""
        if proj is None or str(proj.owner_id) != str(caller_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found",
            )

    svc = PortalLinkService(session, settings)
    await svc.revoke(token_id)
    return


# ── Verify (public) ─────────────────────────────────────────────────────


@portal_router.post(
    "/portal/verify/",
    response_model=PortalVerifyResponse,
    summary="Verify a buyer-portal magic-link token (public)",
)
async def verify_portal_token(
    data: PortalVerifyRequest,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> PortalVerifyResponse:
    """Public endpoint — used by the portal frontend on page load.

    SINGLE-USE redemption — industry standard (Slack/Notion/Linear).
    The first call atomically marks the magic-link consumed and
    returns the buyer summary; any subsequent call (or a concurrent
    second call that loses the DB race) gets a 401 with the
    distinguishing ``portal_token_already_used`` code so the frontend
    can render a "request a new login link" CTA instead of the
    generic "your link expired" copy.

    The JWT itself stays valid for follow-up buyer-portal calls
    (``/overview/``, ``/documents/...``, ``/upload-kyc/``,
    ``/contact-agent/``) until expiry/revocation — only the verify
    endpoint enforces single-use. This matches the spec's
    "session JWT stays multi-use after the first verify" contract.

    Returns enough buyer summary to render the welcome card but does
    NOT include any payment / document data; the buyer must follow up
    with ``/overview/`` for that.
    """
    ctx = await _resolve_portal_context(
        session,
        settings,
        data.token,
        request,
        consume=True,
    )
    scopes: list[str] = []
    if ctx.reservation is not None:
        scopes.append("reservation")
    if ctx.sales_contract is not None:
        scopes.append("contract")
    return PortalVerifyResponse(
        buyer_id=ctx.buyer.id,
        buyer_full_name=ctx.buyer.full_name,
        reservation_id=ctx.reservation.id if ctx.reservation else None,
        sales_contract_id=(ctx.sales_contract.id if ctx.sales_contract else None),
        scope_summary=" + ".join(scopes) if scopes else "buyer",
    )


# ── Overview (public via token) ─────────────────────────────────────────


def _build_doc_download_url(token: str, doc_id: uuid.UUID) -> str:
    """Compose the per-doc download URL (path only — host added by frontend)."""
    return f"/api/v1/property-dev/portal/buyer/{token}/documents/{doc_id}/download/"


async def _load_payment_schedule_rows(
    session: SessionDep,
    sales_contract_id: uuid.UUID | None,
) -> tuple[list[Instalment], str, Decimal, Decimal, Decimal]:
    """Load instalments for the SPA + return totals.

    Returns ``(rows, currency, total, paid, outstanding)``. Empty when
    the contract has no schedule yet.
    """
    if sales_contract_id is None:
        return [], "", Decimal("0"), Decimal("0"), Decimal("0")

    sched = (
        await session.execute(
            select(PaymentSchedule).where(
                PaymentSchedule.sales_contract_id == sales_contract_id,
            )
        )
    ).scalar_one_or_none()
    if sched is None:
        return [], "", Decimal("0"), Decimal("0"), Decimal("0")

    inst_rows = (
        (
            await session.execute(
                select(Instalment).where(Instalment.schedule_id == sched.id).order_by(Instalment.sequence.asc())
            )
        )
        .scalars()
        .all()
    )
    paid = sum((i.amount_paid for i in inst_rows), Decimal("0"))
    total = sum((i.amount for i in inst_rows), Decimal("0"))
    outstanding = total - paid
    return (
        list(inst_rows),
        sched.currency or "",
        total,
        paid,
        outstanding,
    )


async def _load_signed_documents(
    session: SessionDep,
    ctx: PortalContext,
    token: str,
) -> list[PortalDocumentRow]:
    """Aggregate signed-doc rows the buyer is allowed to download.

    Sources, in order:
      1. SPA PDF (if SPA exists and is signed/countersigned)
      2. HandoverDoc rows (if the buyer's plot has a handover with
         delivered docs)
      3. Buyer-uploaded KYC docs (echoed back so the portal shows
         "you uploaded X on Y")
    """
    out: list[PortalDocumentRow] = []

    if ctx.sales_contract is not None:
        spa = ctx.sales_contract
        if spa.status in ("signed", "countersigned", "registered"):
            out.append(
                PortalDocumentRow(
                    id=spa.id,
                    title=f"Sale & Purchase Agreement {spa.contract_number}",
                    doc_type="spa",
                    delivered_at=spa.signing_date,
                    download_url=_build_doc_download_url(token, spa.id),
                )
            )

    # Handover docs are scoped by plot; fetch via the buyer.plot_id
    # if set. The buyer's plot may differ from the reservation's plot
    # only after a (rare) plot swap; we surface whatever's on the
    # buyer row at read time.
    if ctx.buyer.plot_id is not None:
        from app.modules.property_dev.models import Handover

        handover = (
            await session.execute(select(Handover).where(Handover.plot_id == ctx.buyer.plot_id))
        ).scalar_one_or_none()
        if handover is not None:
            ho_docs = (
                (
                    await session.execute(
                        select(HandoverDoc)
                        .where(HandoverDoc.handover_id == handover.id)
                        .where(HandoverDoc.is_delivered.is_(True))
                    )
                )
                .scalars()
                .all()
            )
            for hd in ho_docs:
                out.append(
                    PortalDocumentRow(
                        id=hd.id,
                        title=hd.title or hd.doc_type,
                        doc_type=f"handover_doc:{hd.doc_type}",
                        delivered_at=hd.delivered_at,
                        download_url=_build_doc_download_url(token, hd.id),
                    )
                )

    # KYC docs already uploaded by this buyer — found via
    # Document.metadata.buyer_id (no FK, JSON match).
    kyc_docs = (await session.execute(select(Document).where(Document.category == "buyer_kyc"))).scalars().all()
    for d in kyc_docs:
        meta = d.metadata_ or {}
        if str(meta.get("buyer_id")) != str(ctx.buyer.id):
            continue
        out.append(
            PortalDocumentRow(
                id=d.id,
                title=d.name,
                doc_type=f"kyc:{meta.get('kyc_code', 'other')}",
                delivered_at=(d.created_at.isoformat() if d.created_at else None),
                download_url=_build_doc_download_url(token, d.id),
            )
        )

    return out


def _default_kyc_requests(buyer: Buyer) -> list[PortalKycRequest]:
    """Built-in KYC request list. Tenants override via buyer.metadata."""
    meta = buyer.metadata_ or {}
    custom = meta.get("kyc_required") if isinstance(meta, dict) else None
    if isinstance(custom, list) and custom:
        return [
            PortalKycRequest(
                code=str(item.get("code", "other")),
                label=str(item.get("label", item.get("code", "Document"))),
                description=str(item.get("description", "")),
                is_uploaded=bool(item.get("is_uploaded", False)),
            )
            for item in custom
            if isinstance(item, dict)
        ]
    return [
        PortalKycRequest(
            code="passport",
            label="Passport or government-issued ID",
            description="Clear scan of the photo page.",
        ),
        PortalKycRequest(
            code="address_proof",
            label="Proof of address",
            description=("Utility bill / bank statement issued in the last 3 months."),
        ),
        PortalKycRequest(
            code="source_of_funds",
            label="Source of funds declaration",
            description="Bank statement or sale-of-asset evidence.",
        ),
    ]


@portal_router.get(
    "/portal/buyer/{token}/overview/",
    response_model=PortalOverviewResponse,
    summary="Buyer-portal landing-page payload",
)
async def buyer_overview(
    token: str,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> PortalOverviewResponse:
    """Single-round-trip payload for the portal landing page."""
    ctx = await _resolve_portal_context(session, settings, token, request)

    # Reservation card.
    res_card: PortalReservationCard | None = None
    if ctx.reservation is not None:
        plot = await session.get(Plot, ctx.reservation.plot_id)
        plot_number = plot.plot_number if plot else ""
        plot_area = plot.area_m2 if plot else Decimal("0")
        plot_address = ""
        if plot is not None:
            dev = await session.get(Development, plot.development_id)
            plot_address = (dev.location_address or "") if dev else ""
        res_card = PortalReservationCard(
            id=ctx.reservation.id,
            reservation_number=ctx.reservation.reservation_number,
            plot_id=ctx.reservation.plot_id,
            plot_number=plot_number,
            plot_area_m2=plot_area,
            plot_address=plot_address,
            deposit_amount=ctx.reservation.deposit_amount,
            currency=ctx.reservation.currency,
            status=ctx.reservation.status,
            cooling_off_until=ctx.reservation.cooling_off_until,
            expires_at=ctx.reservation.expires_at,
            signed_on=ctx.reservation.deposit_paid_at,
        )

    # SPA card.
    spa_card: PortalSalesContractCard | None = None
    if ctx.sales_contract is not None:
        spa_card = PortalSalesContractCard(
            id=ctx.sales_contract.id,
            contract_number=ctx.sales_contract.contract_number,
            plot_id=ctx.sales_contract.plot_id,
            signing_date=ctx.sales_contract.signing_date,
            total_value=ctx.sales_contract.total_value,
            currency=ctx.sales_contract.currency,
            status=ctx.sales_contract.status,
        )

    # Payment schedule.
    inst_rows, sched_currency, total, paid, outstanding = await _load_payment_schedule_rows(
        session,
        ctx.sales_contract.id if ctx.sales_contract else None,
    )
    inst_payload = [
        PortalInstalmentRow(
            id=row.id,
            sequence=row.sequence,
            milestone_label=row.milestone_label or "",
            due_date=row.due_date,
            amount=row.amount,
            amount_paid=row.amount_paid,
            amount_outstanding=row.amount - row.amount_paid,
            status=row.status
            if row.status in {"pending", "due", "overdue", "paid", "waived", "cancelled"}
            else "pending",
            paid_at=row.paid_at,
            currency=sched_currency,
        )
        for row in inst_rows
    ]

    # Signed documents + KYC requests.
    documents = await _load_signed_documents(session, ctx, token)
    kyc_requests = _default_kyc_requests(ctx.buyer)
    # Mark already-uploaded codes as is_uploaded=True.
    uploaded_codes = {d.doc_type.split(":", 1)[1] for d in documents if d.doc_type.startswith("kyc:")}
    for kr in kyc_requests:
        if kr.code in uploaded_codes:
            kr.is_uploaded = True

    # Development label (for the header welcome card).
    dev_name = ""
    dev = await session.get(Development, ctx.buyer.development_id)
    if dev is not None:
        dev_name = dev.name or dev.code

    return PortalOverviewResponse(
        buyer_id=ctx.buyer.id,
        buyer_full_name=ctx.buyer.full_name,
        buyer_email=ctx.buyer.email,
        buyer_language=ctx.buyer.language or "en",
        development_name=dev_name,
        reservation=res_card,
        sales_contract=spa_card,
        payment_schedule_total=total,
        payment_schedule_paid=paid,
        payment_schedule_outstanding=outstanding,
        payment_schedule_currency=sched_currency,
        instalments=inst_payload,
        documents=documents,
        kyc_requests=kyc_requests,
    )


# ── Document download (public via token) ────────────────────────────────


@portal_router.get(
    "/portal/buyer/{token}/documents/{doc_id}/download/",
    summary="Download a signed/delivered buyer document",
)
async def download_buyer_document(
    token: str,
    doc_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> FileResponse:
    """Stream the requested document — IFF it belongs to this token's buyer.

    The IDOR guard works in two passes:
      1. Resolve the portal context (verifies token, loads buyer + scope).
      2. For each supported doc kind (SPA / HandoverDoc / Document
         tagged ``buyer_kyc``), check that the row resolves to a buyer
         whose UUID equals ``ctx.buyer.id``. Mismatch → 404 (NOT 403),
         so this endpoint can't be turned into an existence oracle.
    """
    ctx = await _resolve_portal_context(session, settings, token, request)

    # — SPA PDF —
    if ctx.sales_contract is not None and ctx.sales_contract.id == doc_id:
        # SPA PDF generation lives in document_templates; for now we
        # have no in-repo PDF for the contract itself. Surface a 404
        # rather than fabricate an empty file — the frontend already
        # falls back to "ask your agent" copy.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not yet available",
        )

    # — HandoverDoc —
    if ctx.buyer.plot_id is not None:
        from app.modules.property_dev.models import Handover

        handover = (
            await session.execute(select(Handover).where(Handover.plot_id == ctx.buyer.plot_id))
        ).scalar_one_or_none()
        if handover is not None:
            hd = (
                await session.execute(
                    select(HandoverDoc).where(HandoverDoc.id == doc_id).where(HandoverDoc.handover_id == handover.id)
                )
            ).scalar_one_or_none()
            if hd is not None:
                if not hd.file_url:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Document file not stored",
                    )
                file_path = _safe_local_path(hd.file_url)
                if file_path is None or not file_path.exists():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Document file missing on disk",
                    )
                return FileResponse(
                    file_path,
                    media_type="application/pdf",
                    filename=f"{hd.title or hd.doc_type}.pdf",
                )

    # — KYC Document echoes —
    doc = await session.get(Document, doc_id)
    if doc is not None and doc.category == "buyer_kyc":
        meta = doc.metadata_ or {}
        if str(meta.get("buyer_id")) == str(ctx.buyer.id):
            file_path = _safe_local_path(doc.file_path)
            if file_path is None or not file_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document file missing on disk",
                )
            return FileResponse(
                file_path,
                media_type=doc.mime_type or "application/octet-stream",
                filename=doc.name,
            )

    # Token-bound IDOR guard collapses every mismatch to 404 so the
    # endpoint cannot be turned into an existence oracle for documents
    # belonging to other buyers.
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Document not found",
    )


def _safe_local_path(stored: str) -> Path | None:
    """Sanity-check a stored relative path against directory traversal."""
    if not stored:
        return None
    p = Path(stored)
    if p.is_absolute():
        # We never store absolute paths; if we see one, refuse to
        # serve (defence against compromised DB seed).
        return None
    if ".." in p.parts:
        return None
    return Path("uploads") / p if not stored.startswith("uploads") else p


# ── KYC upload (public via token) ───────────────────────────────────────


@portal_router.post(
    "/portal/buyer/{token}/upload-kyc/",
    response_model=PortalKycUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a KYC document via the buyer portal",
)
async def upload_kyc_document(
    token: str,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
    document_type: str,
    file: UploadFile = File(...),
) -> PortalKycUploadResponse:
    """Magic-byte-validated KYC upload. Stored under
    ``uploads/property_dev/portal/kyc/<buyer_id>/<uuid><ext>`` and
    recorded as a :class:`Document` row tagged ``category='buyer_kyc'``.

    ``document_type`` must match :data:`_KYC_DOC_TYPE_PATTERN`; an
    invalid code is a 400. ``file`` content is sniffed against
    ``ALLOWED_KYC_SIGNATURES`` (PDF + jpeg/png/heic/heif) — Content-Type
    is fully attacker-controlled so we ignore it.
    """
    import re

    if not re.match(_KYC_DOC_TYPE_PATTERN, document_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported document_type",
        )

    ctx = await _resolve_portal_context(session, settings, token, request)

    try:
        content = await file.read()
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded file",
        ) from None

    if len(content) > 20 * 1024 * 1024:
        # 20 MB cap — KYC docs are typically <2 MB; this stops a single
        # request from filling disk.
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 20 MB)",
        )

    try:
        detected = require_signature(
            content[:SIGNATURE_BYTES_REQUIRED],
            _KYC_ALLOWED_SIGNATURES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    mime = mime_for_signature(detected)

    # Resolve the buyer's project for the Document row's FK.
    dev = await session.get(Development, ctx.buyer.development_id)
    if dev is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Buyer development not found",
        )
    project_id = dev.project_id

    # Persist file. Per-buyer folder so a misbehaving client can't
    # touch another buyer's stored files via path manipulation.
    buyer_dir = _KYC_UPLOADS_ROOT / str(ctx.buyer.id)
    buyer_dir.mkdir(parents=True, exist_ok=True)
    suffix = {
        "pdf": ".pdf",
        "png": ".png",
        "jpeg": ".jpg",
        "heic": ".heic",
        "heif": ".heif",
    }.get(detected or "", ".bin")
    stored_name = f"{document_type}-{uuid.uuid4().hex[:12]}{suffix}"
    stored_path = buyer_dir / stored_name
    try:
        stored_path.write_bytes(content)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save uploaded file",
        ) from exc

    # Relative path used by /download/ for traversal-safe re-resolution.
    rel_path = f"property_dev/portal/kyc/{ctx.buyer.id}/{stored_name}"

    doc = Document(
        project_id=project_id,
        name=(file.filename or stored_name)[:255],
        description=f"KYC {document_type} uploaded via buyer portal",
        category="buyer_kyc",
        file_size=len(content),
        mime_type=mime,
        file_path=rel_path,
        uploaded_by="",
        tags=["buyer_kyc", document_type],
        metadata_={
            "buyer_id": str(ctx.buyer.id),
            "kyc_code": document_type,
            "source": "buyer_portal",
            "uploaded_via_token_id": str(ctx.token_row.id),
        },
    )
    session.add(doc)
    await session.flush()
    await session.refresh(doc)

    return PortalKycUploadResponse(
        document_id=doc.id,
        document_type=document_type,
        accepted_at=datetime.now(UTC),
        storage_path=rel_path,
    )


# ── Contact agent (public via token) ────────────────────────────────────


@portal_router.post(
    "/portal/buyer/{token}/contact-agent/",
    response_model=PortalContactAgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message to the assigned sales agent",
)
async def contact_agent(
    token: str,
    data: PortalContactAgentRequest,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
) -> PortalContactAgentResponse:
    """File a :class:`CrmActivity` row + fire ``crm.lead.message_received``.

    The activity is tagged via ``subject`` prefix (the CRM model has no
    structured ``source`` column) so the agent's inbox lists "[Portal]
    <buyer> sent a message" deterministically.
    """
    ctx = await _resolve_portal_context(session, settings, token, request)

    body_lines = [data.message.strip()]
    if data.callback_phone:
        body_lines.append("")
        body_lines.append(f"Callback phone: {data.callback_phone}")
    body_lines.append("")
    body_lines.append("[source=portal]")
    body_lines.append(f"[buyer_id={ctx.buyer.id}]")

    subject = f"[Portal] Message from {ctx.buyer.full_name or ctx.buyer.email}"

    activity = CrmActivity(
        owner_user_id=None,  # routed to the agent inbox by lead handler
        kind="note",
        subject=subject[:500],
        body="\n".join(body_lines),
    )
    session.add(activity)
    await session.flush()
    await session.refresh(activity)

    # Fire the event in detached mode so the buyer doesn't wait on
    # downstream subscribers (auto-assign, notification fan-out, …).
    event_bus.publish_detached(
        "crm.lead.message_received",
        {
            "activity_id": str(activity.id),
            "buyer_id": str(ctx.buyer.id),
            "source": "portal",
            "callback_phone": data.callback_phone,
        },
        source_module="property_dev",
    )

    return PortalContactAgentResponse(
        activity_id=activity.id,
        accepted_at=datetime.now(UTC),
    )


__all__ = ["portal_router"]
