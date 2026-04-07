"""Finance API routes.

Endpoints:
    GET    /                    — List invoices with filters
    POST   /                    — Create invoice (auth required)
    GET    /{id}                — Get single invoice
    PATCH  /{id}                — Update invoice (auth required)
    POST   /{id}/approve        — Approve invoice (auth required)
    POST   /{id}/pay            — Mark invoice as paid (auth required)
    GET    /payments             — List payments
    POST   /payments             — Create payment (auth required)
    GET    /budgets              — List budgets
    POST   /budgets              — Create budget (auth required)
    PATCH  /budgets/{id}         — Update budget (auth required)
    GET    /evm                  — List EVM snapshots
    POST   /evm/snapshot         — Create EVM snapshot (auth required)
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.finance.schemas import (
    BudgetCreate,
    BudgetListResponse,
    BudgetResponse,
    BudgetUpdate,
    EVMListResponse,
    EVMSnapshotCreate,
    EVMSnapshotResponse,
    InvoiceCreate,
    InvoiceListResponse,
    InvoiceResponse,
    InvoiceUpdate,
    PaymentCreate,
    PaymentListResponse,
    PaymentResponse,
)
from app.modules.finance.service import FinanceService

router = APIRouter()


def _get_service(session: SessionDep) -> FinanceService:
    return FinanceService(session)


# ── Invoices ─────────────────────────────────────────────────────────────────


@router.get("/", response_model=InvoiceListResponse)
async def list_invoices(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    direction: str | None = Query(default=None),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: FinanceService = Depends(_get_service),
) -> InvoiceListResponse:
    """List invoices with optional filters."""
    items, total = await service.list_invoices(
        project_id=project_id,
        direction=direction,
        invoice_status=status,
        offset=offset,
        limit=limit,
    )
    return InvoiceListResponse(
        items=[InvoiceResponse.model_validate(i) for i in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    data: InvoiceCreate,
    user_id: CurrentUserId,
    service: FinanceService = Depends(_get_service),
) -> InvoiceResponse:
    """Create a new invoice."""
    invoice = await service.create_invoice(data, user_id=user_id)
    return InvoiceResponse.model_validate(invoice)


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: FinanceService = Depends(_get_service),
) -> InvoiceResponse:
    """Get a single invoice by ID."""
    invoice = await service.get_invoice(invoice_id)
    return InvoiceResponse.model_validate(invoice)


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: uuid.UUID,
    data: InvoiceUpdate,
    user_id: CurrentUserId,
    service: FinanceService = Depends(_get_service),
) -> InvoiceResponse:
    """Update an invoice."""
    invoice = await service.update_invoice(invoice_id, data)
    return InvoiceResponse.model_validate(invoice)


@router.post("/{invoice_id}/approve", response_model=InvoiceResponse)
async def approve_invoice(
    invoice_id: uuid.UUID,
    user_id: CurrentUserId,
    service: FinanceService = Depends(_get_service),
) -> InvoiceResponse:
    """Approve an invoice."""
    invoice = await service.approve_invoice(invoice_id)
    return InvoiceResponse.model_validate(invoice)


@router.post("/{invoice_id}/pay", response_model=InvoiceResponse)
async def pay_invoice(
    invoice_id: uuid.UUID,
    user_id: CurrentUserId,
    service: FinanceService = Depends(_get_service),
) -> InvoiceResponse:
    """Mark invoice as paid."""
    invoice = await service.pay_invoice(invoice_id)
    return InvoiceResponse.model_validate(invoice)


# ── Payments ─────────────────────────────────────────────────────────────────


@router.get("/payments", response_model=PaymentListResponse)
async def list_payments(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    invoice_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: FinanceService = Depends(_get_service),
) -> PaymentListResponse:
    """List payments with optional invoice filter."""
    items, total = await service.list_payments(
        invoice_id=invoice_id, limit=limit, offset=offset
    )
    return PaymentListResponse(
        items=[PaymentResponse.model_validate(p) for p in items],
        total=total,
    )


@router.post("/payments", response_model=PaymentResponse, status_code=201)
async def create_payment(
    data: PaymentCreate,
    user_id: CurrentUserId,
    service: FinanceService = Depends(_get_service),
) -> PaymentResponse:
    """Record a payment against an invoice."""
    payment = await service.create_payment(data)
    return PaymentResponse.model_validate(payment)


# ── Budgets ──────────────────────────────────────────────────────────────────


@router.get("/budgets", response_model=BudgetListResponse)
async def list_budgets(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    category: str | None = Query(default=None),
    service: FinanceService = Depends(_get_service),
) -> BudgetListResponse:
    """List project budgets."""
    items, total = await service.list_budgets(project_id=project_id, category=category)
    return BudgetListResponse(
        items=[BudgetResponse.model_validate(b) for b in items],
        total=total,
    )


@router.post("/budgets", response_model=BudgetResponse, status_code=201)
async def create_budget(
    data: BudgetCreate,
    user_id: CurrentUserId,
    service: FinanceService = Depends(_get_service),
) -> BudgetResponse:
    """Create a project budget line."""
    budget = await service.create_budget(data)
    return BudgetResponse.model_validate(budget)


@router.patch("/budgets/{budget_id}", response_model=BudgetResponse)
async def update_budget(
    budget_id: uuid.UUID,
    data: BudgetUpdate,
    user_id: CurrentUserId,
    service: FinanceService = Depends(_get_service),
) -> BudgetResponse:
    """Update a budget line."""
    budget = await service.update_budget(budget_id, data)
    return BudgetResponse.model_validate(budget)


# ── EVM ──────────────────────────────────────────────────────────────────────


@router.get("/evm", response_model=EVMListResponse)
async def list_evm_snapshots(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    service: FinanceService = Depends(_get_service),
) -> EVMListResponse:
    """List EVM snapshots for a project."""
    items, total = await service.list_evm_snapshots(project_id=project_id)
    return EVMListResponse(
        items=[EVMSnapshotResponse.model_validate(s) for s in items],
        total=total,
    )


@router.post("/evm/snapshot", response_model=EVMSnapshotResponse, status_code=201)
async def create_evm_snapshot(
    data: EVMSnapshotCreate,
    user_id: CurrentUserId,
    service: FinanceService = Depends(_get_service),
) -> EVMSnapshotResponse:
    """Create an EVM snapshot."""
    snapshot = await service.create_evm_snapshot(data)
    return EVMSnapshotResponse.model_validate(snapshot)
