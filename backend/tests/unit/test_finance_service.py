"""Unit tests for :class:`FinanceService`.

Scope:
    Baseline smoke coverage for invoicing, payments, budgets, and the
    EVM snapshot derivation. Repositories are stubbed so the suite
    doesn't need a live database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.finance.schemas import (
    BudgetCreate,
    EVMSnapshotCreate,
    InvoiceCreate,
    PaymentCreate,
)
from app.modules.finance.service import FinanceService

# ── Helpers / stubs ───────────────────────────────────────────────────────


def _make_service() -> FinanceService:
    service = FinanceService.__new__(FinanceService)
    service.session = SimpleNamespace()
    service.invoices = _StubInvoiceRepo()
    service.line_items = _StubLineItemRepo()
    service.payments_repo = _StubPaymentRepo()
    service.budgets = _StubBudgetRepo()
    service.evm = _StubEVMRepo()
    return service


class _StubInvoiceRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, invoice: Any) -> Any:
        if getattr(invoice, "id", None) is None:
            invoice.id = uuid.uuid4()
        invoice.line_items = []
        invoice.payments = []
        self.rows[invoice.id] = invoice
        return invoice

    async def get(self, invoice_id: uuid.UUID) -> Any:
        return self.rows.get(invoice_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        direction: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if project_id is not None:
            rows = [r for r in rows if r.project_id == project_id]
        if direction is not None:
            rows = [r for r in rows if r.invoice_direction == direction]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows, len(rows)

    async def next_invoice_number(
        self, project_id: uuid.UUID, direction: str
    ) -> str:
        self._counter += 1
        prefix = "INV-P" if direction == "payable" else "INV-R"
        return f"{prefix}-{self._counter:03d}"

    async def update(self, invoice_id: uuid.UUID, **fields: Any) -> None:
        inv = self.rows.get(invoice_id)
        if inv is not None:
            for k, v in fields.items():
                setattr(inv, k, v)


class _StubLineItemRepo:
    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        return item

    async def delete_by_invoice(self, invoice_id: uuid.UUID) -> None:
        return None


class _StubPaymentRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, payment: Any) -> Any:
        if getattr(payment, "id", None) is None:
            payment.id = uuid.uuid4()
        self.rows.append(payment)
        return payment

    async def list(
        self,
        *,
        invoice_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        rows = self.rows
        if invoice_id is not None:
            rows = [p for p in rows if p.invoice_id == invoice_id]
        return rows, len(rows)


class _StubBudgetRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, budget: Any) -> Any:
        if getattr(budget, "id", None) is None:
            budget.id = uuid.uuid4()
        self.rows[budget.id] = budget
        return budget

    async def get(self, budget_id: uuid.UUID) -> Any:
        return self.rows.get(budget_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        category: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if project_id is not None:
            rows = [r for r in rows if r.project_id == project_id]
        if category is not None:
            rows = [r for r in rows if r.category == category]
        return rows, len(rows)


class _StubEVMRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, snapshot: Any) -> Any:
        if getattr(snapshot, "id", None) is None:
            snapshot.id = uuid.uuid4()
        self.rows.append(snapshot)
        return snapshot


# ── Invoices ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_invoice_and_list_roundtrip() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    data = InvoiceCreate(
        project_id=pid,
        invoice_direction="payable",
        invoice_date="2026-04-01",
        amount_subtotal="1000",
        tax_amount="190",
    )
    invoice = await service.create_invoice(data)

    assert invoice.id is not None
    assert invoice.amount_total == "1190"  # server-side computed
    assert invoice.invoice_number.startswith("INV-P-")

    rows, total = await service.list_invoices(project_id=pid)
    assert total == 1
    assert rows[0].id == invoice.id


@pytest.mark.asyncio
async def test_create_invoice_auto_totals_subtotal_plus_tax() -> None:
    service = _make_service()
    data = InvoiceCreate(
        project_id=uuid.uuid4(),
        invoice_direction="receivable",
        invoice_date="2026-04-01",
        amount_subtotal="50000.00",
        tax_amount="9500.00",
    )
    invoice = await service.create_invoice(data)
    assert Decimal(invoice.amount_total) == Decimal("59500.00")


# ── Payments ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_payment_persists_against_invoice() -> None:
    """``create_payment`` validates the invoice exists (404 otherwise) and
    records the payment row. We intentionally do NOT assert any
    ``invoice.amount_paid`` mutation — the production service does not
    currently touch that field, and the test must reflect reality."""
    service = _make_service()
    invoice = await service.create_invoice(
        InvoiceCreate(
            project_id=uuid.uuid4(),
            invoice_direction="payable",
            invoice_date="2026-04-01",
            amount_subtotal="2000",
            tax_amount="380",
        )
    )

    payment = await service.create_payment(
        PaymentCreate(
            invoice_id=invoice.id,
            payment_date="2026-04-05",
            amount="2380",
        )
    )

    assert payment.id is not None
    rows, _ = await service.list_payments(invoice_id=invoice.id)
    assert len(rows) == 1
    assert rows[0].amount == "2380"


@pytest.mark.asyncio
async def test_create_payment_missing_invoice_raises_404() -> None:
    from fastapi import HTTPException

    service = _make_service()
    with pytest.raises(HTTPException) as exc_info:
        await service.create_payment(
            PaymentCreate(
                invoice_id=uuid.uuid4(),
                payment_date="2026-04-05",
                amount="100",
            )
        )
    assert exc_info.value.status_code == 404


# ── Budgets ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_budget_and_list_roundtrip() -> None:
    service = _make_service()
    pid = uuid.uuid4()
    budget = await service.create_budget(
        BudgetCreate(
            project_id=pid,
            category="material",
            original_budget="100000",
            revised_budget="110000",
        )
    )

    assert budget.id is not None
    rows, total = await service.list_budgets(project_id=pid)
    assert total == 1
    assert rows[0].category == "material"


# ── EVM snapshot (derived metrics) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_evm_snapshot_computes_derived_metrics() -> None:
    service = _make_service()
    snapshot = await service.create_evm_snapshot(
        EVMSnapshotCreate(
            project_id=uuid.uuid4(),
            snapshot_date="2026-04-01",
            bac="1000000",
            pv="500000",
            ev="450000",
            ac="480000",
        )
    )

    # SPI = EV / PV = 0.9
    assert Decimal(snapshot.spi) == Decimal("0.9")
    # CPI = EV / AC = 450/480 = 0.9375
    assert Decimal(snapshot.cpi) == Decimal("0.9375")
    # SV = EV - PV = -50000
    assert Decimal(snapshot.sv) == Decimal("-50000")
    # CV = EV - AC = -30000
    assert Decimal(snapshot.cv) == Decimal("-30000")
    # EAC = AC + (BAC - EV) / CPI = 480000 + 550000/0.9375
    expected_eac = Decimal("480000") + (Decimal("1000000") - Decimal("450000")) / Decimal("0.9375")
    assert Decimal(snapshot.eac) == expected_eac.quantize(Decimal("0.01"))


@pytest.mark.asyncio
async def test_create_evm_snapshot_zero_pv_spi_is_zero() -> None:
    """Divide-by-zero guard: PV=0 should yield SPI=0, not crash."""
    service = _make_service()
    snapshot = await service.create_evm_snapshot(
        EVMSnapshotCreate(
            project_id=uuid.uuid4(),
            snapshot_date="2026-04-01",
            bac="100000",
            pv="0",
            ev="10000",
            ac="12000",
        )
    )
    assert Decimal(snapshot.spi) == Decimal("0")


# ── Dashboard ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_dashboard_returns_invoices_and_budgets() -> None:
    """Dashboard aggregates call into repo-level SQL helpers; we wire
    them up directly on the stub repo instances so the calculation
    logic is exercised without a real DB."""
    service = _make_service()

    async def _inv_agg(*, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        return {
            "total_payable": 10_000.0,
            "total_receivable": 25_000.0,
            "total_overdue": 2_000.0,
            "overdue_count": 1,
            "status_counts": {
                "draft": 1,
                "pending": 0,
                "approved": 2,
                "paid": 3,
            },
        }

    async def _budget_agg(*, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        return {
            "total_budget_original": 100_000.0,
            "total_budget_revised": 110_000.0,
            "total_committed": 40_000.0,
            "total_actual": 30_000.0,
        }

    async def _payments_total() -> float:
        return 15_000.0

    service.invoices.aggregate_for_dashboard = _inv_agg  # type: ignore[attr-defined]
    service.budgets.aggregate_for_dashboard = _budget_agg  # type: ignore[attr-defined]
    service.payments_repo.aggregate_total = _payments_total  # type: ignore[attr-defined]

    dashboard = await service.get_dashboard(project_id=uuid.uuid4())

    # Service returns ``.model_dump()`` of FinanceDashboardResponse.
    assert dashboard["total_payable"] == 10_000.0
    assert dashboard["total_receivable"] == 25_000.0
    assert dashboard["total_budget_revised"] == 110_000.0
    assert dashboard["invoices_paid"] == 3
    assert dashboard["budget_warning_level"] == "normal"  # 30/110 ~ 27%
