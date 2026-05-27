"""‌⁠‍HTTP API for the subcontractors module.

Mounted at /api/v1/subcontractors/. All endpoints require an authenticated
user and module-level permissions registered in :mod:`permissions`.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.core.file_signature import (
    ALLOWED_DOCUMENT_TYPES,
    SIGNATURE_BYTES_REQUIRED,
    FileSignatureMismatch,
    mime_for_signature,
)
from app.core.file_signature import require as require_signature
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.subcontractors.models import LienWaiver
from app.modules.subcontractors.schemas import (
    AgreementCreate,
    AgreementResponse,
    AgreementUpdate,
    BlockRequest,
    CertificateCreate,
    CertificateResponse,
    CertificateUpdate,
    ExpiryAlert,
    InsuranceExpiryEntry,
    LienWaiverFormFields,
    LienWaiverResponse,
    PaymentApplicationCreate,
    PaymentApplicationResponse,
    PaymentApplicationUpdate,
    PrequalificationCreate,
    PrequalificationResponse,
    PrequalificationUpdate,
    PrequalRequest,
    RatingCreate,
    RatingResponse,
    RetentionLedgerEntryResponse,
    RetentionReleasePayload,
    SOVSummaryResponse,
    SubcontractorContactCreate,
    SubcontractorContactResponse,
    SubcontractorContactUpdate,
    SubcontractorCreate,
    SubcontractorDashboard,
    SubcontractorResponse,
    SubcontractorUpdate,
    TaxIdValidationRequest,
    TaxIdValidationResponse,
    WorkPackageCreate,
    WorkPackageResponse,
    WorkPackageUpdate,
)
from app.modules.subcontractors.service import SubcontractorService, validate_tax_id

logger = logging.getLogger(__name__)

# Cap upload bytes — 10 MiB is well above any realistic lien waiver scan
# (typical 1-2 pages PDF / phone photo) and below the proxy default.
LIEN_WAIVER_MAX_BYTES: int = 10 * 1024 * 1024

# Per-subcontractor folder under uploads/. Mirrors the per-module
# convention used elsewhere (punchlist/photos, geo_hub/rasters, …).
LIEN_WAIVERS_DIR: Path = Path("uploads/subcontractors/lien_waivers")

router = APIRouter()


def _service(session: SessionDep) -> SubcontractorService:
    return SubcontractorService(session)


async def _verify_agreement_project(
    agreement_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
    svc: SubcontractorService,
) -> None:
    """‌⁠‍Look up the parent agreement and gate by its (required) project_id."""
    agreement = await svc.agreements.get_by_id(agreement_id)
    if agreement is None or agreement.project_id is None:
        return
    await verify_project_access(agreement.project_id, user_id, session)


async def _verify_work_package_project(
    work_package_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
    svc: SubcontractorService,
) -> None:
    """‌⁠‍Look up wp → agreement → project_id and verify."""
    wp = await svc.work_packages.get_by_id(work_package_id)
    if wp is None:
        return
    await _verify_agreement_project(wp.agreement_id, user_id, session, svc)


async def _verify_payment_application_project(
    payment_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
    svc: SubcontractorService,
) -> None:
    """Look up payment → agreement → project_id and verify."""
    pa = await svc.payments.get_by_id(payment_id)
    if pa is None:
        return
    await _verify_agreement_project(pa.agreement_id, user_id, session, svc)


# ── Subcontractors ──────────────────────────────────────────────────────


@router.get("/subcontractors/", response_model=list[SubcontractorResponse])
async def list_subcontractors(
    session: SessionDep,
    _user: CurrentUserId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    prequalification_status: str | None = Query(default=None),
    trade_category: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[SubcontractorResponse]:
    """List subcontractors with optional status / trade filters."""
    svc = SubcontractorService(session)
    rows, _ = await svc.subs.list_all(
        offset=offset,
        limit=limit,
        prequalification_status=prequalification_status,
        trade_category=trade_category,
        active_only=active_only,
    )
    return [SubcontractorResponse.model_validate(r) for r in rows]


@router.post("/subcontractors/", response_model=SubcontractorResponse, status_code=201)
async def create_subcontractor(
    data: SubcontractorCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("subcontractors.create")),
) -> SubcontractorResponse:
    """Create a new subcontractor."""
    svc = SubcontractorService(session)
    entity = await svc.create_subcontractor(data, user_id=user_id)
    return SubcontractorResponse.model_validate(entity)


@router.get("/subcontractors/{sub_id}", response_model=SubcontractorResponse)
async def get_subcontractor(
    sub_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> SubcontractorResponse:
    """Return a single subcontractor."""
    svc = SubcontractorService(session)
    entity = await svc.get_subcontractor(sub_id)
    return SubcontractorResponse.model_validate(entity)


@router.patch("/subcontractors/{sub_id}", response_model=SubcontractorResponse)
async def update_subcontractor(
    sub_id: uuid.UUID,
    data: SubcontractorUpdate,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> SubcontractorResponse:
    """Update a subcontractor."""
    svc = SubcontractorService(session)
    entity = await svc.update_subcontractor(sub_id, data)
    return SubcontractorResponse.model_validate(entity)


@router.delete("/subcontractors/{sub_id}", status_code=204)
async def delete_subcontractor(
    sub_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.delete")),
) -> None:
    """Delete a subcontractor."""
    svc = SubcontractorService(session)
    await svc.delete_subcontractor(sub_id)


@router.get(
    "/subcontractors/{sub_id}/dashboard",
    response_model=SubcontractorDashboard,
)
async def subcontractor_dashboard(
    sub_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> SubcontractorDashboard:
    """Return aggregated stats for a single subcontractor."""
    svc = SubcontractorService(session)
    return await svc.dashboard(sub_id)


# ── Contacts ───────────────────────────────────────────────────────────


@router.get(
    "/subcontractors/{sub_id}/contacts",
    response_model=list[SubcontractorContactResponse],
)
async def list_subcontractor_contacts(
    sub_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[SubcontractorContactResponse]:
    """List contacts for a subcontractor."""
    svc = SubcontractorService(session)
    rows = await svc.contacts.list_by_subcontractor(sub_id)
    return [SubcontractorContactResponse.model_validate(r) for r in rows]


@router.post(
    "/contacts/",
    response_model=SubcontractorContactResponse,
    status_code=201,
)
async def create_subcontractor_contact(
    data: SubcontractorContactCreate,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> SubcontractorContactResponse:
    """Add a contact under a subcontractor."""
    svc = SubcontractorService(session)
    entity = await svc.create_contact(data)
    return SubcontractorContactResponse.model_validate(entity)


@router.patch("/contacts/{contact_id}", response_model=SubcontractorContactResponse)
async def update_subcontractor_contact(
    contact_id: uuid.UUID,
    data: SubcontractorContactUpdate,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> SubcontractorContactResponse:
    """Update a subcontractor contact."""
    svc = SubcontractorService(session)
    entity = await svc.update_contact(contact_id, data)
    return SubcontractorContactResponse.model_validate(entity)


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_subcontractor_contact(
    contact_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> None:
    """Remove a subcontractor contact."""
    svc = SubcontractorService(session)
    await svc.delete_contact(contact_id)


# ── Prequalifications ──────────────────────────────────────────────────


@router.get("/prequalifications/", response_model=list[PrequalificationResponse])
async def list_prequalifications(
    session: SessionDep,
    _user: CurrentUserId,
    subcontractor_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[PrequalificationResponse]:
    """List prequalification applications."""
    svc = SubcontractorService(session)
    if subcontractor_id is not None:
        rows = await svc.prequal.list_for_subcontractor(subcontractor_id)
    elif status_filter is not None:
        rows = await svc.prequal.list_by_status(status_filter)
    else:
        rows = await svc.prequal.list_by_status("submitted")
    return [PrequalificationResponse.model_validate(r) for r in rows]


@router.post(
    "/prequalifications/",
    response_model=PrequalificationResponse,
    status_code=201,
)
async def create_prequalification(
    data: PrequalificationCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("subcontractors.create")),
) -> PrequalificationResponse:
    """Create a draft prequalification application."""
    svc = SubcontractorService(session)
    entity = await svc.create_prequalification(data, user_id=user_id)
    return PrequalificationResponse.model_validate(entity)


@router.patch(
    "/prequalifications/{prequal_id}",
    response_model=PrequalificationResponse,
)
async def update_prequalification(
    prequal_id: uuid.UUID,
    data: PrequalificationUpdate,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> PrequalificationResponse:
    """Update answers / notes on a prequalification application."""
    svc = SubcontractorService(session)
    entity = await svc.update_prequalification(prequal_id, data)
    return PrequalificationResponse.model_validate(entity)


@router.post(
    "/prequalifications/{prequal_id}/submit",
    response_model=PrequalificationResponse,
)
async def submit_prequalification(
    prequal_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> PrequalificationResponse:
    """Move a draft prequalification to `submitted`."""
    svc = SubcontractorService(session)
    entity = await svc.submit_prequalification(prequal_id)
    return PrequalificationResponse.model_validate(entity)


@router.post(
    "/prequalifications/{prequal_id}/approve",
    response_model=PrequalificationResponse,
)
async def approve_prequalification(
    prequal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    notes: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("subcontractors.approve_prequalification")),
) -> PrequalificationResponse:
    """Approve a prequalification application."""
    svc = SubcontractorService(session)
    entity = await svc.approve_prequalification(prequal_id, reviewer_id=user_id, notes=notes)
    return PrequalificationResponse.model_validate(entity)


@router.post(
    "/prequalifications/{prequal_id}/reject",
    response_model=PrequalificationResponse,
)
async def reject_prequalification(
    prequal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    notes: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("subcontractors.approve_prequalification")),
) -> PrequalificationResponse:
    """Reject a prequalification application."""
    svc = SubcontractorService(session)
    entity = await svc.reject_prequalification(prequal_id, reviewer_id=user_id, notes=notes)
    return PrequalificationResponse.model_validate(entity)


# ── Certificates ───────────────────────────────────────────────────────


@router.get("/certificates/", response_model=list[CertificateResponse])
async def list_certificates(
    session: SessionDep,
    _user: CurrentUserId,
    subcontractor_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[CertificateResponse]:
    """List all certificates held by a subcontractor."""
    svc = SubcontractorService(session)
    rows = await svc.certs.list_by_subcontractor(subcontractor_id)
    return [CertificateResponse.model_validate(r) for r in rows]


@router.get("/certificates/expiring", response_model=list[ExpiryAlert])
async def list_expiring_certificates(
    session: SessionDep,
    _user: CurrentUserId,
    days: int = Query(default=60, ge=1, le=365),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[ExpiryAlert]:
    """List certificates expiring within `days`."""
    svc = SubcontractorService(session)
    return await svc.list_expiring_certificates(days=days)


@router.post("/certificates/", response_model=CertificateResponse, status_code=201)
async def create_certificate(
    data: CertificateCreate,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.create")),
) -> CertificateResponse:
    """Record a new certificate for a subcontractor."""
    svc = SubcontractorService(session)
    entity = await svc.record_certificate(data)
    return CertificateResponse.model_validate(entity)


@router.patch("/certificates/{certificate_id}", response_model=CertificateResponse)
async def update_certificate(
    certificate_id: uuid.UUID,
    data: CertificateUpdate,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> CertificateResponse:
    """Update a certificate."""
    svc = SubcontractorService(session)
    entity = await svc.update_certificate(certificate_id, data)
    return CertificateResponse.model_validate(entity)


@router.delete("/certificates/{certificate_id}", status_code=204)
async def delete_certificate(
    certificate_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.delete")),
) -> None:
    """Delete a certificate."""
    svc = SubcontractorService(session)
    await svc.delete_certificate(certificate_id)


# ── Agreements ─────────────────────────────────────────────────────────


@router.get("/agreements/", response_model=list[AgreementResponse])
async def list_agreements(
    session: SessionDep,
    user_id: CurrentUserId,
    subcontractor_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[AgreementResponse]:
    """List agreements, filtered by subcontractor and/or project."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    svc = SubcontractorService(session)
    if subcontractor_id is not None:
        rows = await svc.agreements.list_for_subcontractor(subcontractor_id, status=status_filter)
    elif project_id is not None:
        rows = await svc.agreements.list_for_project(project_id, status=status_filter)
    else:
        rows = []
    return [AgreementResponse.model_validate(r) for r in rows]


@router.post("/agreements/", response_model=AgreementResponse, status_code=201)
async def create_agreement(
    data: AgreementCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("subcontractors.create")),
) -> AgreementResponse:
    """Create a draft subcontract agreement."""
    await verify_project_access(data.project_id, user_id, session)
    svc = SubcontractorService(session)
    entity = await svc.create_agreement(data, user_id=user_id)
    return AgreementResponse.model_validate(entity)


@router.patch("/agreements/{agreement_id}", response_model=AgreementResponse)
async def update_agreement(
    agreement_id: uuid.UUID,
    data: AgreementUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> AgreementResponse:
    """Update / transition a subcontract agreement."""
    svc = SubcontractorService(session)
    await _verify_agreement_project(agreement_id, user_id, session, svc)
    entity = await svc.update_agreement(agreement_id, data)
    return AgreementResponse.model_validate(entity)


@router.delete("/agreements/{agreement_id}", status_code=204)
async def delete_agreement(
    agreement_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.delete")),
) -> None:
    """Delete a subcontract agreement."""
    svc = SubcontractorService(session)
    await _verify_agreement_project(agreement_id, user_id, session, svc)
    await svc.delete_agreement(agreement_id)


# ── Work packages ──────────────────────────────────────────────────────


@router.get("/work-packages/", response_model=list[WorkPackageResponse])
async def list_work_packages(
    session: SessionDep,
    user_id: CurrentUserId,
    agreement_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[WorkPackageResponse]:
    """List work packages for an agreement."""
    svc = SubcontractorService(session)
    await _verify_agreement_project(agreement_id, user_id, session, svc)
    rows = await svc.work_packages.list_for_agreement(agreement_id)
    return [WorkPackageResponse.model_validate(r) for r in rows]


@router.post("/work-packages/", response_model=WorkPackageResponse, status_code=201)
async def create_work_package(
    data: WorkPackageCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.create")),
) -> WorkPackageResponse:
    """Create a work package under an agreement."""
    svc = SubcontractorService(session)
    await _verify_agreement_project(data.agreement_id, user_id, session, svc)
    entity = await svc.create_work_package(data)
    return WorkPackageResponse.model_validate(entity)


@router.patch("/work-packages/{wp_id}", response_model=WorkPackageResponse)
async def update_work_package(
    wp_id: uuid.UUID,
    data: WorkPackageUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> WorkPackageResponse:
    """Update a work package."""
    svc = SubcontractorService(session)
    await _verify_work_package_project(wp_id, user_id, session, svc)
    entity = await svc.update_work_package(wp_id, data)
    return WorkPackageResponse.model_validate(entity)


@router.delete("/work-packages/{wp_id}", status_code=204)
async def delete_work_package(
    wp_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.delete")),
) -> None:
    """Delete a work package."""
    svc = SubcontractorService(session)
    await _verify_work_package_project(wp_id, user_id, session, svc)
    await svc.delete_work_package(wp_id)


# ── Payment applications ───────────────────────────────────────────────


@router.get("/payment-applications/", response_model=list[PaymentApplicationResponse])
async def list_payment_applications(
    session: SessionDep,
    user_id: CurrentUserId,
    agreement_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[PaymentApplicationResponse]:
    """List payment applications for an agreement."""
    svc = SubcontractorService(session)
    await _verify_agreement_project(agreement_id, user_id, session, svc)
    rows = await svc.payments.list_for_agreement(agreement_id, status=status_filter)
    return [PaymentApplicationResponse.model_validate(r) for r in rows]


@router.post(
    "/payment-applications/",
    response_model=PaymentApplicationResponse,
    status_code=201,
)
async def submit_payment_application(
    data: PaymentApplicationCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("subcontractors.create")),
) -> PaymentApplicationResponse:
    """Submit a new payment application (computes retention)."""
    svc = SubcontractorService(session)
    await _verify_agreement_project(data.agreement_id, user_id, session, svc)
    entity = await svc.submit_payment_application(data, user_id=user_id)
    return PaymentApplicationResponse.model_validate(entity)


@router.patch(
    "/payment-applications/{payment_id}",
    response_model=PaymentApplicationResponse,
)
async def update_payment_application(
    payment_id: uuid.UUID,
    data: PaymentApplicationUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> PaymentApplicationResponse:
    """Edit a still-`submitted` payment application."""
    svc = SubcontractorService(session)
    await _verify_payment_application_project(payment_id, user_id, session, svc)
    entity = await svc.update_payment_application(payment_id, data)
    return PaymentApplicationResponse.model_validate(entity)


@router.post(
    "/payment-applications/{payment_id}/approve-foreman",
    response_model=PaymentApplicationResponse,
)
async def approve_payment_foreman(
    payment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("subcontractors.approve_payment_foreman")),
) -> PaymentApplicationResponse:
    """Foreman-level approval of a payment application."""
    svc = SubcontractorService(session)
    await _verify_payment_application_project(payment_id, user_id, session, svc)
    entity = await svc.approve_payment_application_foreman(payment_id, user_id=user_id)
    return PaymentApplicationResponse.model_validate(entity)


@router.post(
    "/payment-applications/{payment_id}/approve-finance",
    response_model=PaymentApplicationResponse,
)
async def approve_payment_finance(
    payment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("subcontractors.approve_payment_finance")),
) -> PaymentApplicationResponse:
    """Finance-level approval of a payment application."""
    svc = SubcontractorService(session)
    await _verify_payment_application_project(payment_id, user_id, session, svc)
    entity = await svc.approve_payment_application_finance(payment_id, user_id=user_id)
    return PaymentApplicationResponse.model_validate(entity)


@router.post(
    "/payment-applications/{payment_id}/mark-paid",
    response_model=PaymentApplicationResponse,
)
async def mark_payment_paid(
    payment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.approve_payment_finance")),
) -> PaymentApplicationResponse:
    """Mark a finance-approved payment application as paid."""
    svc = SubcontractorService(session)
    await _verify_payment_application_project(payment_id, user_id, session, svc)
    entity = await svc.mark_paid(payment_id)
    return PaymentApplicationResponse.model_validate(entity)


@router.post(
    "/payment-applications/{payment_id}/reject",
    response_model=PaymentApplicationResponse,
)
async def reject_payment_application(
    payment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    reason: str = Query(..., min_length=1, max_length=255),
    _perm: None = Depends(RequirePermission("subcontractors.approve_payment_foreman")),
) -> PaymentApplicationResponse:
    """Reject a payment application."""
    svc = SubcontractorService(session)
    await _verify_payment_application_project(payment_id, user_id, session, svc)
    entity = await svc.reject_payment_application(payment_id, reason=reason)
    return PaymentApplicationResponse.model_validate(entity)


# ── Retention ──────────────────────────────────────────────────────────


@router.get("/retention/ledger", response_model=list[RetentionLedgerEntryResponse])
async def retention_ledger(
    session: SessionDep,
    user_id: CurrentUserId,
    agreement_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[RetentionLedgerEntryResponse]:
    """List retention ledger entries for an agreement."""
    svc = SubcontractorService(session)
    await _verify_agreement_project(agreement_id, user_id, session, svc)
    rows = await svc.retention.list_for_agreement(agreement_id)
    return [RetentionLedgerEntryResponse.model_validate(r) for r in rows]


@router.post(
    "/retention/release",
    response_model=RetentionLedgerEntryResponse,
    status_code=201,
)
async def release_retention(
    payload: RetentionReleasePayload,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.release_retention")),
) -> RetentionLedgerEntryResponse:
    """Release retention for an agreement."""
    svc = SubcontractorService(session)
    await _verify_agreement_project(payload.agreement_id, user_id, session, svc)
    entry = await svc.release_retention(
        agreement_id=payload.agreement_id,
        amount=payload.amount,
        reason=payload.reason,
    )
    return RetentionLedgerEntryResponse.model_validate(entry)


# ── Ratings ────────────────────────────────────────────────────────────


@router.get("/ratings/", response_model=list[RatingResponse])
async def list_ratings(
    session: SessionDep,
    _user: CurrentUserId,
    subcontractor_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[RatingResponse]:
    """List monthly rating roll-ups for a subcontractor."""
    svc = SubcontractorService(session)
    rows = await svc.ratings.list_for_subcontractor(subcontractor_id)
    return [RatingResponse.model_validate(r) for r in rows]


@router.post("/ratings/", response_model=RatingResponse, status_code=201)
async def update_rating(
    data: RatingCreate,
    session: SessionDep,
    _user: CurrentUserId,
    events: dict[str, Any] | None = Body(default=None),
    _perm: None = Depends(RequirePermission("subcontractors.rate")),
) -> RatingResponse:
    """Upsert a subcontractor rating for a period.

    R5: this endpoint is gated by the dedicated ``subcontractors.rate``
    permission (MANAGER-only) — previously any EDITOR could write a
    bogus rating and tamper with the subcontractor's roll-up score.
    """
    if events is not None and len(events) > 50:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail="events payload too large (max 50 keys)",
        )
    svc = SubcontractorService(session)
    entity = await svc.update_rating(data, events=events)
    return RatingResponse.model_validate(entity)


# ── Schedule of Values ─────────────────────────────────────────────────


@router.get(
    "/agreements/{agreement_id}/sov",
    response_model=SOVSummaryResponse,
)
async def get_sov_summary(
    agreement_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> SOVSummaryResponse:
    """Schedule-of-Values rollup per work package for this agreement.

    For each work package: planned value, completion %, and rollups of
    claimed / certified / approved amounts across every payment app to
    date, plus ``remaining = planned − approved``. The grand totals row
    is returned in ``totals``.
    """
    svc = SubcontractorService(session)
    await _verify_agreement_project(agreement_id, user_id, session, svc)
    return await svc.sov_summary(agreement_id)


# ── Tax-ID / VAT validation ────────────────────────────────────────────


@router.post(
    "/tax-id/validate",
    response_model=TaxIdValidationResponse,
)
async def validate_tax_id_endpoint(
    body: TaxIdValidationRequest,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> TaxIdValidationResponse:
    """Validate a tax-ID / VAT number against the country's published format.

    Format-only — no live registry lookup. Returns the canonical (uppercase,
    de-punctuated) form of the value plus a pass/fail flag and the name of
    the standard the value was matched against.
    """
    return validate_tax_id(body.country, body.tax_id)


# ── Wave 4 / T12 — BuildingConnected-style prequal + insurance + block ──


@router.post(
    "/subcontractors/{sub_id}/prequal",
    response_model=SubcontractorResponse,
)
async def submit_prequal(
    sub_id: uuid.UUID,
    body: PrequalRequest,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> SubcontractorResponse:
    """Submit a prequalification questionnaire + score.

    The questionnaire payload is stored verbatim on the subcontractor;
    the (optional) caller-supplied score wins over the auto-computed
    value when present. Stamps ``prequal_completed_at`` to now.
    """
    svc = SubcontractorService(session)
    entity = await svc.submit_prequal(
        sub_id,
        questionnaire_data=body.questionnaire,
        score=body.score,
    )
    return SubcontractorResponse.model_validate(entity)


@router.post(
    "/subcontractors/check-insurance-expiry",
    response_model=list[InsuranceExpiryEntry],
)
async def check_insurance_expiry(
    session: SessionDep,
    _user: CurrentUserId,
    days_ahead: int = Query(default=30, ge=0, le=365),
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[InsuranceExpiryEntry]:
    """Surface subcontractors whose insurance expires within ``days_ahead``.

    Already-past expiries are also surfaced so dispatcher sees both
    "renew soon" and "renew now". Emits a
    ``subcontractors.insurance.expiring`` event per flagged sub for the
    notification pipeline.
    """
    from datetime import date as _date  # local import to keep module load light

    svc = SubcontractorService(session)
    today = _date.today()
    rows = await svc.flag_expiring_insurance(days_ahead=days_ahead, today=today)
    return [
        InsuranceExpiryEntry(
            id=r.id,
            legal_name=r.legal_name,
            insurance_expiry_date=r.insurance_expiry_date,
            days_until_expiry=((r.insurance_expiry_date - today).days if r.insurance_expiry_date else 0),
            is_blocked=bool(r.is_blocked),
        )
        for r in rows
    ]


@router.post(
    "/subcontractors/{sub_id}/block",
    response_model=SubcontractorResponse,
)
async def block_subcontractor_endpoint(
    sub_id: uuid.UUID,
    body: BlockRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("subcontractors.block")),
) -> SubcontractorResponse:
    """Hard-block a subcontractor from bidding / payment with a reason.

    R5: gated by the dedicated ``subcontractors.block`` permission
    (MANAGER-only). Previously the generic ``update`` gate let any
    EDITOR exclude a competing firm from all future bids.
    """
    svc = SubcontractorService(session)
    entity = await svc.block_subcontractor(sub_id, reason=body.reason, by_user_id=user_id)
    return SubcontractorResponse.model_validate(entity)


@router.post(
    "/subcontractors/{sub_id}/unblock",
    response_model=SubcontractorResponse,
)
async def unblock_subcontractor_endpoint(
    sub_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("subcontractors.block")),
) -> SubcontractorResponse:
    """Clear the block flag + reason on a subcontractor."""
    svc = SubcontractorService(session)
    entity = await svc.unblock_subcontractor(sub_id, by_user_id=user_id)
    return SubcontractorResponse.model_validate(entity)


# ── Lien waivers / tax forms ───────────────────────────────────────────


def _serialize_lien_waiver(entity: LienWaiver) -> LienWaiverResponse:
    """Hand-roll the response so the ``metadata`` alias resolves."""
    return LienWaiverResponse.model_validate(entity, from_attributes=True)


@router.get(
    "/subcontractors/{sub_id}/lien-waivers",
    response_model=list[LienWaiverResponse],
)
async def list_lien_waivers(
    sub_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.read")),
) -> list[LienWaiverResponse]:
    """List every lien waiver / W-9 / W-8 filed against a subcontractor.

    Newest first so the most recent waiver wins on the dashboard. Returns
    an empty list when no waivers exist — the UI shows an empty state.
    """
    svc = SubcontractorService(session)
    rows = await svc.lien_waivers.list_for_subcontractor(sub_id)
    return [_serialize_lien_waiver(r) for r in rows]


@router.post(
    "/subcontractors/{sub_id}/lien-waivers/upload",
    response_model=LienWaiverResponse,
    status_code=201,
)
async def upload_lien_waiver(
    sub_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    waiver_type: str = Form(...),
    file: UploadFile = File(...),
    payment_application_id: uuid.UUID | None = Form(default=None),
    signed_date: str | None = Form(default=None),
    amount: str | None = Form(default=None),
    currency: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    _perm: None = Depends(RequirePermission("subcontractors.update")),
) -> LienWaiverResponse:
    """Upload a lien waiver / W-9 / W-8 PDF or image.

    Magic-byte gated against :data:`ALLOWED_DOCUMENT_TYPES` (pdf, png,
    jpeg, gif, webp, zip, ole, xml). The Content-Type header is
    attacker-controlled, so we sniff the first
    :data:`SIGNATURE_BYTES_REQUIRED` bytes and reject anything outside
    the allow-list with HTTP 415. The stored MIME is derived from the
    detected signature, not the request header.

    422 when the form fields fail validation (bad waiver_type, bad
    currency, negative amount). 404 when the linked subcontractor does
    not exist (IDOR-safe — generic message, no enumeration leak).
    """
    # Cap the read at the configured ceiling. UploadFile streams in
    # chunks; we collect into memory here because a lien waiver is
    # tiny relative to a CAD file and we need the bytes for both the
    # magic-byte sniff and the disk write.
    raw = await file.read(LIEN_WAIVER_MAX_BYTES + 1)
    if len(raw) > LIEN_WAIVER_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file exceeds maximum size of {LIEN_WAIVER_MAX_BYTES} bytes",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="file body is empty",
        )

    # Magic-byte gate. Returns the detected signature token (e.g. "pdf")
    # or raises FileSignatureMismatch — which we convert to 415 so the
    # frontend can show a "Format not supported" toast.
    try:
        detected = require_signature(
            raw[:SIGNATURE_BYTES_REQUIRED],
            ALLOWED_DOCUMENT_TYPES,
            filename=file.filename,
        )
    except FileSignatureMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        )
    safe_mime = mime_for_signature(detected)

    # Validate the structured form fields via Pydantic so the same
    # checks apply that we'd use on a JSON-only endpoint. Convert raw
    # form strings into typed values up-front so a bad ``amount``
    # produces a 422 with a useful Pydantic-style detail.
    try:
        parsed_amount = Decimal(amount) if amount not in (None, "") else Decimal("0")
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"amount is not a valid decimal: {amount!r}",
        )
    try:
        from datetime import date as _date

        parsed_signed = _date.fromisoformat(signed_date) if signed_date else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"signed_date is not a valid ISO date: {signed_date!r}",
        )
    try:
        form_payload = LienWaiverFormFields(
            waiver_type=waiver_type,
            payment_application_id=payment_application_id,
            signed_date=parsed_signed,
            amount=parsed_amount,
            currency=currency or "",
            notes=notes,
        )
    except Exception as exc:  # pydantic.ValidationError
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # IDOR-safe: 404 if the subcontractor doesn't exist BEFORE we touch
    # the disk — avoids leaving orphan files when the URL was guessed.
    svc = SubcontractorService(session)
    parent = await svc.subs.get_by_id(sub_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subcontractor not found",
        )
    # If a payment_application_id was provided, also verify ownership
    # via the agreement → project chain. None means "free-standing W-9".
    if form_payload.payment_application_id is not None:
        await _verify_payment_application_project(
            form_payload.payment_application_id,
            user_id,
            session,
            svc,
        )

    # Disk write — per-subcontractor folder so listings stay cheap.
    target_dir = LIEN_WAIVERS_DIR / str(sub_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "waiver.pdf").suffix or ".pdf"
    safe_filename = f"{form_payload.waiver_type}_{uuid.uuid4().hex[:10]}{ext}"
    on_disk = target_dir / safe_filename
    try:
        on_disk.write_bytes(raw)
    except OSError:
        logger.exception("Failed to persist lien waiver for sub %s", sub_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="storage error",
        )

    # Relative path keeps storage URLs portable when moving between
    # local disk and MinIO/S3 backends.
    rel_path = f"subcontractors/lien_waivers/{sub_id}/{safe_filename}"

    entity = LienWaiver(
        subcontractor_id=sub_id,
        payment_application_id=form_payload.payment_application_id,
        waiver_type=form_payload.waiver_type,
        document_url=rel_path,
        mime_type=safe_mime,
        file_size=len(raw),
        signed_date=form_payload.signed_date,
        amount=form_payload.amount,
        currency=form_payload.currency,
        notes=form_payload.notes,
        uploaded_by=user_id,
    )
    await svc.lien_waivers.create(entity)
    await session.commit()
    await session.refresh(entity)
    return _serialize_lien_waiver(entity)


@router.delete(
    "/subcontractors/{sub_id}/lien-waivers/{waiver_id}",
    status_code=204,
)
async def delete_lien_waiver(
    sub_id: uuid.UUID,
    waiver_id: uuid.UUID,
    session: SessionDep,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("subcontractors.delete")),
) -> None:
    """Delete a lien waiver record (file remains on disk for audit).

    IDOR-safe: 404 when the waiver doesn't exist OR belongs to a
    different subcontractor. Returning a generic 404 in both cases
    prevents an attacker enumerating waiver UUIDs across the tenant.
    """
    svc = SubcontractorService(session)
    entity = await svc.lien_waivers.get_by_id(waiver_id)
    if entity is None or entity.subcontractor_id != sub_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lien waiver not found",
        )
    await svc.lien_waivers.delete(waiver_id)
    await session.commit()
