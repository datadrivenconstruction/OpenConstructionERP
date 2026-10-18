# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release API routes, mounted at ``/api/v1/payment-release/``.

    GET   /projects/{project_id}/ledger/             - invoice ledger of the project, per contract
    GET   /projects/{project_id}/retention/          - retention register of the project
    GET   /projects/{project_id}/findings/           - rules V11 to V18 on the project's supplier billing
    GET   /contracts/{contract_id}/terms/            - a contract's payment terms (defaults when none set)
    PUT   /contracts/{contract_id}/terms/            - store them
    POST  /contracts/{contract_id}/retention-postings/ - pay back held retention
    POST  /retention-postings/{posting_id}/void/     - take a posting back
    PATCH /invoices/{invoice_id}/                    - kind, contract and deductions of an open invoice
    POST  /invoices/{invoice_id}/release/            - confirm the release (frozen from then on)
    POST  /invoices/{invoice_id}/reopen/             - unfreeze it again

Every route checks the caller's access to the project the record belongs to.
Reading needs ``payment_release.read``; terms and invoice details
``payment_release.write``; confirming, reopening and retention postings, the
acts that commit money, ``payment_release.release``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.payment_release.schemas import (
    InvoiceReleaseState,
    InvoiceReleaseUpdate,
    PaymentTermsBody,
    PaymentTermsResponse,
    ProjectLedger,
    ReleaseFindings,
    RetentionPostingCreate,
    RetentionPostingResponse,
    RetentionRegister,
)
from app.modules.payment_release.service import PaymentReleaseService

router = APIRouter()


def _locale() -> str:
    from app.core.i18n import get_locale

    return get_locale()


def _state(row: Any) -> dict[str, Any]:
    return {
        "invoice_id": str(row.invoice_id),
        "contract_id": str(row.contract_id) if row.contract_id else None,
        "kind": row.kind,
        "status": row.status,
        "release_amount": str(row.release_amount) if row.release_amount is not None else None,
        "payable_amount": str(row.payable_amount) if row.payable_amount is not None else None,
    }


@router.get(
    "/projects/{project_id}/ledger/",
    response_model=ProjectLedger,
    dependencies=[Depends(RequirePermission("payment_release.read"))],
)
async def project_ledger(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The invoice ledger: every supplier contract with its invoices and each release step."""
    await verify_project_access(project_id, user_id, session)
    return await PaymentReleaseService(session).ledger(project_id)


@router.get(
    "/projects/{project_id}/retention/",
    response_model=RetentionRegister,
    dependencies=[Depends(RequirePermission("payment_release.read"))],
)
async def retention_register(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Retention withheld, paid back and still held, per supplier contract."""
    await verify_project_access(project_id, user_id, session)
    return await PaymentReleaseService(session).retention_register(project_id)


@router.get(
    "/projects/{project_id}/findings/",
    response_model=ReleaseFindings,
    dependencies=[Depends(RequirePermission("payment_release.read"))],
)
async def findings(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Rules V11 to V18 on the project's supplier billing, in the caller's language."""
    await verify_project_access(project_id, user_id, session)
    found = await PaymentReleaseService(session).findings(project_id, locale=_locale())
    return {
        "project_id": str(project_id),
        "findings": found,
        "errors": sum(1 for f in found if f["severity"] == "error"),
        "warnings": sum(1 for f in found if f["severity"] == "warning"),
    }


@router.get(
    "/contracts/{contract_id}/terms/",
    response_model=PaymentTermsResponse,
    dependencies=[Depends(RequirePermission("payment_release.read"))],
)
async def get_terms(contract_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    service = PaymentReleaseService(session)
    contract = await service.supplier_contract(contract_id)
    await verify_project_access(contract.project_id, user_id, session)
    return await service.terms(contract)


@router.put(
    "/contracts/{contract_id}/terms/",
    response_model=PaymentTermsResponse,
    dependencies=[Depends(RequirePermission("payment_release.write"))],
)
async def put_terms(
    contract_id: uuid.UUID, body: PaymentTermsBody, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    service = PaymentReleaseService(session)
    contract = await service.supplier_contract(contract_id)
    await verify_project_access(contract.project_id, user_id, session)
    out = await service.put_terms(contract, body, str(user_id) if user_id else None)
    return out


@router.post(
    "/contracts/{contract_id}/retention-postings/",
    response_model=RetentionPostingResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("payment_release.release"))],
)
async def post_retention(
    contract_id: uuid.UUID, body: RetentionPostingCreate, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    service = PaymentReleaseService(session)
    contract = await service.supplier_contract(contract_id)
    await verify_project_access(contract.project_id, user_id, session)
    row = await service.post_retention(contract, body, str(user_id) if user_id else None)
    return service.posting_out(row)


@router.post(
    "/retention-postings/{posting_id}/void/",
    response_model=RetentionPostingResponse,
    dependencies=[Depends(RequirePermission("payment_release.release"))],
)
async def void_posting(posting_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    service = PaymentReleaseService(session)
    row = await service.posting(posting_id)
    await verify_project_access(row.project_id, user_id, session)
    row = await service.void_posting(row, str(user_id) if user_id else None)
    return service.posting_out(row)


@router.patch(
    "/invoices/{invoice_id}/",
    response_model=InvoiceReleaseState,
    dependencies=[Depends(RequirePermission("payment_release.write"))],
)
async def update_invoice(
    invoice_id: uuid.UUID, body: InvoiceReleaseUpdate, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    service = PaymentReleaseService(session)
    invoice = await service.invoice(invoice_id)
    await verify_project_access(invoice.project_id, user_id, session)
    row = await service.update_invoice(invoice, body, str(user_id) if user_id else None)
    return _state(row)


@router.post(
    "/invoices/{invoice_id}/release/",
    response_model=InvoiceReleaseState,
    dependencies=[Depends(RequirePermission("payment_release.release"))],
)
async def release_invoice(invoice_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    service = PaymentReleaseService(session)
    invoice = await service.invoice(invoice_id)
    await verify_project_access(invoice.project_id, user_id, session)
    row = await service.release_invoice(invoice, str(user_id) if user_id else None, locale=_locale())
    return _state(row)


@router.post(
    "/invoices/{invoice_id}/reopen/",
    response_model=InvoiceReleaseState,
    dependencies=[Depends(RequirePermission("payment_release.release"))],
)
async def reopen_invoice(invoice_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    service = PaymentReleaseService(session)
    invoice = await service.invoice(invoice_id)
    await verify_project_access(invoice.project_id, user_id, session)
    row = await service.reopen_invoice(invoice, str(user_id) if user_id else None)
    return _state(row)
