# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Invoice-approval DMS API routes.

Mounted as a sub-router of the finance module, so every path below lives under
``/api/v1/finance/inbox``:

    POST   /inbox/upload            - capture a supplier invoice from a file
    POST   /inbox/manual            - capture by hand (no-OCR fallback)
    GET    /inbox                   - list captures for a project
    GET    /inbox/{id}              - one capture + validation + booking proposal
    PATCH  /inbox/{id}              - edit the reviewed draft
    POST   /inbox/{id}/enrich       - optional AI field enrichment
    POST   /inbox/{id}/propose-booking - (re)compute a booking suggestion
    POST   /inbox/{id}/code         - confirm the booking  (-> coded)
    POST   /inbox/{id}/approve      - approve              (-> approved, MANAGER)
    POST   /inbox/{id}/reject       - decline              (-> rejected, MANAGER)
    POST   /inbox/{id}/query        - send back a question (-> queried)
    POST   /inbox/{id}/reopen       - reopen to draft
    POST   /inbox/{id}/post         - post to GL + seal    (-> posted, MANAGER)
    GET    /inbox/{id}/document     - stream the original document
    GET    /inbox/{id}/verify       - re-check archive integrity
    GET    /inbox/{id}/audit        - append-only action log
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

from app.core.content_disposition import attachment_disposition
from app.core.rate_limiter import approval_limiter
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.finance.invoice_capture_logic import BookingProposal, Finding, findings_to_dicts
from app.modules.finance.invoice_capture_models import CapturedInvoice
from app.modules.finance.invoice_capture_schemas import (
    ApproveInput,
    ArchiveVerifyResponse,
    AuditEntryResponse,
    AuditListResponse,
    BookingInput,
    BookingProposalResponse,
    CaptureListResponse,
    CaptureManualCreate,
    CaptureResponse,
    CaptureUpdate,
    PurchaseOrderLink,
    QueryInput,
    RejectInput,
)
from app.modules.finance.invoice_capture_service import InvoiceCaptureService
from app.modules.finance.router import _require_project_access

capture_router = APIRouter(prefix="/inbox", tags=["finance-inbox"])


def _get_capture_service(session: SessionDep) -> InvoiceCaptureService:
    return InvoiceCaptureService(session)


async def _require_capture_access(session: SessionDep, capture_id: uuid.UUID, user_id: str | None) -> CapturedInvoice:
    """Load a capture and confirm the caller can reach its project (404 on deny)."""
    row = await session.get(CapturedInvoice, capture_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Captured invoice not found")
    await _require_project_access(session, row.project_id, user_id)
    return row


def _to_response(
    row: CapturedInvoice,
    *,
    validation: list[Finding] | None = None,
    proposal: BookingProposal | None = None,
) -> CaptureResponse:
    resp = CaptureResponse.model_validate(row)
    resp.has_document = bool(row.storage_key)
    if validation is not None:
        resp.validation = [_finding_to_schema(f) for f in validation]
    if proposal is not None:
        resp.booking_proposal = BookingProposalResponse(**proposal.to_dict())
    return resp


def _finding_to_schema(f: Finding):
    from app.modules.finance.invoice_capture_schemas import ValidationFinding

    return ValidationFinding(severity=f.severity, code=f.code, message=f.message, field=f.field)


async def _detailed_response(service: InvoiceCaptureService, row: CapturedInvoice) -> CaptureResponse:
    """Attach live validation + a booking proposal (for single-item views)."""
    validation = await service.build_validation(row)
    proposal = await service.propose_booking(row) if row.status in {"captured", "coded", "queried"} else None
    return _to_response(row, validation=validation, proposal=proposal)


# ── Capture (intake) ─────────────────────────────────────────────────────────


@capture_router.post(
    "/upload",
    response_model=CaptureResponse,
    status_code=201,
    summary="Capture a supplier invoice from a file",
    description="Upload a supplier invoice or delivery-note PDF or image. The original is "
    "stored unaltered and hashed; header fields are extracted for review. Manual entry still "
    "works when no OCR engine is installed.",
)
async def upload_capture(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    doc_kind: str = Query(default="invoice"),
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("finance.capture.create")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_project_access(session, project_id, user_id)
    row = await service.capture_from_upload(project_id=project_id, file=file, user_id=user_id, doc_kind=doc_kind)
    return await _detailed_response(service, row)


@capture_router.post(
    "/manual",
    response_model=CaptureResponse,
    status_code=201,
    summary="Capture an invoice by hand",
    description="Create a captured invoice from typed fields - the graceful-degradation path "
    "when there is no document to scan.",
)
async def manual_capture(
    data: CaptureManualCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.create")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_project_access(session, data.project_id, user_id)
    row = await service.capture_manual(data, user_id)
    return await _detailed_response(service, row)


@capture_router.get(
    "",
    response_model=CaptureListResponse,
    summary="List captured invoices",
    description="List inbox items for a project, optionally filtered by status.",
)
async def list_captures(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("finance.capture.read")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureListResponse:
    await _require_project_access(session, project_id, user_id)
    rows, total = await service.list(project_id=project_id, status_filter=status_filter, limit=limit, offset=offset)
    return CaptureListResponse(items=[_to_response(r) for r in rows], total=total)


@capture_router.get(
    "/{capture_id}",
    response_model=CaptureResponse,
    summary="Get a captured invoice",
    description="One capture with its live validation report and (pre-post) booking proposal.",
)
async def get_capture(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.read")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    row = await _require_capture_access(session, capture_id, user_id)
    return await _detailed_response(service, row)


@capture_router.patch(
    "/{capture_id}",
    response_model=CaptureResponse,
    summary="Edit a captured draft",
    description="Update the reviewed header fields / line items. Rejected once the invoice is "
    "approved or posted (a sealed record is read-only).",
)
async def update_capture(
    capture_id: uuid.UUID,
    data: CaptureUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.create")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_capture_access(session, capture_id, user_id)
    row = await service.update(capture_id, data, user_id)
    return await _detailed_response(service, row)


@capture_router.post(
    "/{capture_id}/enrich",
    response_model=CaptureResponse,
    summary="AI-enrich the captured fields",
    description="Ask a configured AI provider to fill blank fields from the extracted text. "
    "No-op (200) when no provider is configured.",
)
async def enrich_capture(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.create")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_capture_access(session, capture_id, user_id)
    row = await service.enrich_with_llm(capture_id, user_id)
    return await _detailed_response(service, row)


@capture_router.post(
    "/{capture_id}/propose-booking",
    response_model=BookingProposalResponse,
    summary="Suggest a booking",
    description="Compute a debit/credit booking suggestion from the chart of accounts. "
    "A suggestion only - nothing is written until the user codes and posts.",
)
async def propose_booking(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.read")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> BookingProposalResponse:
    row = await _require_capture_access(session, capture_id, user_id)
    proposal = await service.propose_booking(row)
    return BookingProposalResponse(**proposal.to_dict())


# ── State transitions ─────────────────────────────────────────────────────────


@capture_router.post(
    "/{capture_id}/code",
    response_model=CaptureResponse,
    summary="Confirm the booking",
    description="Confirm the expense / tax / payable accounts and cost allocation, moving the "
    "invoice to 'coded'. Validation must pass (complete booking, amounts tie out, no duplicate).",
)
async def code_capture(
    capture_id: uuid.UUID,
    booking: BookingInput,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.create")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_capture_access(session, capture_id, user_id)
    row = await service.code(capture_id, booking, user_id)
    return await _detailed_response(service, row)


@capture_router.post(
    "/{capture_id}/approve",
    response_model=CaptureResponse,
    summary="Approve a captured invoice",
    description="Approve the coded invoice (records the approver and timestamp). MANAGER-only - "
    "reuses the finance.approve gate.",
)
async def approve_capture(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    data: ApproveInput | None = None,
    _perm: None = Depends(RequirePermission("finance.approve")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded. Try again later.")
    await _require_capture_access(session, capture_id, user_id)
    row = await service.approve(capture_id, user_id, acknowledge_match=bool(data and data.acknowledge_match))
    return await _detailed_response(service, row)


@capture_router.put(
    "/{capture_id}/purchase-order",
    response_model=CaptureResponse,
    summary="Link a captured invoice to its purchase order",
    description="Match the invoice against an order and its goods receipts (the procurement matcher, "
    "with the order's own tolerances). Send null to clear the link.",
)
async def link_purchase_order(
    capture_id: uuid.UUID,
    data: PurchaseOrderLink,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.create")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_capture_access(session, capture_id, user_id)
    row = await service.link_purchase_order(capture_id, data.purchase_order_id, user_id)
    return await _detailed_response(service, row)


@capture_router.post(
    "/{capture_id}/reject",
    response_model=CaptureResponse,
    summary="Reject a captured invoice",
    description="Decline the invoice with a reason. MANAGER-only (finance.approve gate).",
)
async def reject_capture(
    capture_id: uuid.UUID,
    data: RejectInput,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.approve")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_capture_access(session, capture_id, user_id)
    row = await service.reject(capture_id, data.reason, user_id)
    return await _detailed_response(service, row)


@capture_router.post(
    "/{capture_id}/query",
    response_model=CaptureResponse,
    summary="Send an invoice back with a query",
    description="Move the invoice to 'queried' with a note asking for more information.",
)
async def query_capture(
    capture_id: uuid.UUID,
    data: QueryInput,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.create")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_capture_access(session, capture_id, user_id)
    row = await service.query(capture_id, data.note, user_id)
    return await _detailed_response(service, row)


@capture_router.post(
    "/{capture_id}/reopen",
    response_model=CaptureResponse,
    summary="Reopen a captured invoice",
    description="Move a coded / queried / rejected invoice back to 'captured' for re-editing.",
)
async def reopen_capture(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.create")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    await _require_capture_access(session, capture_id, user_id)
    row = await service.reopen(capture_id, user_id)
    return await _detailed_response(service, row)


@capture_router.post(
    "/{capture_id}/post",
    response_model=CaptureResponse,
    summary="Post an approved invoice to the ledger",
    description="Post the confirmed booking to the general ledger (double-entry), create the "
    "payable invoice, and seal the tamper-evident archive. MANAGER-only (finance.gl.post_journal). "
    "Idempotent: re-posting a posted invoice returns it unchanged.",
)
async def post_capture(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.gl.post_journal")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> CaptureResponse:
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded. Try again later.")
    await _require_capture_access(session, capture_id, user_id)
    row = await service.post(capture_id, user_id)
    return await _detailed_response(service, row)


# ── Archive: document, integrity, audit ───────────────────────────────────────


@capture_router.get(
    "/{capture_id}/document",
    response_model=None,
    summary="Download the original document",
    description="Stream the stored original document, byte-for-byte as uploaded.",
)
async def download_document(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.read")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> Response:
    await _require_capture_access(session, capture_id, user_id)
    data, mime, filename = await service.read_document(capture_id)
    safe_name = filename.replace('"', "").replace("\n", " ")[:200] or "invoice"
    # RFC 6266 pair (ASCII fallback + UTF-8 filename*): the stored upload name
    # is user-provided and routinely non-ASCII; interpolating it raw would
    # mangle umlauts and 500 on non-Latin-1 names.
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": attachment_disposition(safe_name, inline=True)},
    )


@capture_router.get(
    "/{capture_id}/verify",
    response_model=ArchiveVerifyResponse,
    summary="Verify archive integrity",
    description="Re-hash the stored document and re-derive the booking seal, then compare to the "
    "values recorded at posting. Proves the archive has not been tampered with.",
)
async def verify_archive(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.read")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> ArchiveVerifyResponse:
    await _require_capture_access(session, capture_id, user_id)
    result = await service.verify_archive(capture_id)
    return ArchiveVerifyResponse(**result)


@capture_router.get(
    "/{capture_id}/audit",
    response_model=AuditListResponse,
    summary="Audit trail",
    description="The append-only action log for this invoice: who did what, when, with the status transitions.",
)
async def capture_audit(
    capture_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("finance.capture.read")),
    service: InvoiceCaptureService = Depends(_get_capture_service),
) -> AuditListResponse:
    await _require_capture_access(session, capture_id, user_id)
    rows = await service.audit_trail(capture_id)
    items = [
        AuditEntryResponse(
            action=r.action,
            from_status=r.from_status,
            to_status=r.to_status,
            reason=r.reason,
            actor_id=str(r.actor_id) if r.actor_id else None,
            created_at=r.created_at,
            metadata=r.metadata_ or {},
        )
        for r in rows
    ]
    return AuditListResponse(items=items, total=len(items))


# Re-export for the validation-report findings-to-dict helper (used in tests).
__all__ = ["capture_router", "findings_to_dicts"]
