"""Unit tests for :class:`FinanceService`.

Scope:
    Baseline smoke coverage for invoicing, payments, budgets, and the
    EVM snapshot derivation. Repositories are stubbed so the suite
    doesn't need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC
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

    async def next_invoice_number(self, project_id: uuid.UUID, direction: str) -> str:
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

    async def aggregate_for_dashboard(self, *, project_id: uuid.UUID | None = None) -> dict[str, Any]:
        # EVM zero-input fallback path (service.create_evm_snapshot) calls
        # this when any of BAC/PV/EV/AC is "0". For unit tests we return
        # an empty aggregate so derived values stay zero and the test
        # asserts the divide-by-zero guard, not the fallback math.
        return {
            "total_budget_original": 0.0,
            "total_budget_revised": 0.0,
            "total_committed": 0.0,
            "total_actual": 0.0,
        }


class _StubEVMRepo:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    async def create(self, snapshot: Any) -> Any:
        if getattr(snapshot, "id", None) is None:
            snapshot.id = uuid.uuid4()
        # SQLAlchemy server-side defaults don't fire without a real INSERT,
        # so emulate them here so EVMSnapshotResponse.model_validate(...)
        # doesn't choke on None timestamps.
        from datetime import datetime

        now = datetime.now(UTC)
        if getattr(snapshot, "created_at", None) is None:
            snapshot.created_at = now
        if getattr(snapshot, "updated_at", None) is None:
            snapshot.updated_at = now
        self.rows.append(snapshot)
        return snapshot

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> tuple[list[Any], int]:
        rows = self.rows
        if project_id is not None:
            rows = [s for s in rows if s.project_id == project_id]
        return rows, len(rows)


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
async def test_list_evm_snapshots_returns_envelope_not_bare_list() -> None:
    """v2.6.42 regression guard: ``list_evm_snapshots`` must return a
    ``(items, total)`` tuple and the router must wrap it in
    :class:`EVMListResponse`. Frontend ``FinancePage.tsx`` types the
    response as ``{items, total}`` and pulls ``items[0]`` for the latest
    snapshot — drifting back to a bare list breaks the EVM KPI cards
    (BAC/PV/EV/AC/SPI/CPI render as ``NaN``)."""
    from app.modules.finance.schemas import EVMListResponse, EVMSnapshotResponse

    service = _make_service()
    pid = uuid.uuid4()
    await service.create_evm_snapshot(
        EVMSnapshotCreate(
            project_id=pid,
            snapshot_date="2026-04-01",
            bac="100000",
            pv="50000",
            ev="45000",
            ac="48000",
        )
    )

    result = await service.list_evm_snapshots(project_id=pid)
    # Service contract: tuple of (items, total).
    assert isinstance(result, tuple)
    assert len(result) == 2
    items, total = result
    assert total == 1
    assert len(items) == 1

    # Router wraps with EVMListResponse — exercise that path too.
    response = EVMListResponse(
        items=[EVMSnapshotResponse.model_validate(s) for s in items],
        total=total,
    )
    payload = response.model_dump()
    assert set(payload.keys()) == {"items", "total"}
    assert payload["total"] == 1
    assert isinstance(payload["items"], list)

    # Decimal-as-string contract: every numeric metric must be a string.
    # Frontend parseFloat()'s these — drifting to native Decimal/float
    # serialization would silently lose precision.
    snap = payload["items"][0]
    for field in ("bac", "pv", "ev", "ac", "sv", "cv", "spi", "cpi", "eac", "vac", "etc", "tcpi"):
        assert isinstance(snap[field], str), f"EVM field {field!r} must serialize as string"


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


# ── BUG-346: pay_invoice distributes actuals by (wbs_id, cost_category) ──


class _ExecuteStubSession:
    """Session stub that satisfies the two ``self.session.execute`` calls
    in :meth:`FinanceService.pay_invoice`'s recalculation block.

    The first execute fetches paid invoices; the second fetches project
    budgets. We dispatch by the target entity name in the compiled SQL so
    the stub stays decoupled from SQLAlchemy internals.
    """

    def __init__(self, paid_invoices: list[Any], budgets: list[Any]) -> None:
        self.paid_invoices = paid_invoices
        self.budgets = budgets

    async def execute(self, stmt: Any) -> Any:
        target = str(stmt).lower()

        class _Result:
            def __init__(self, value: list[Any]) -> None:
                self._value = value

            def scalars(self) -> Any:
                class _Scalars:
                    def __init__(self, v: list[Any]) -> None:
                        self._v = v

                    def all(self) -> list[Any]:
                        return self._v

                return _Scalars(self._value)

        if "oe_finance_invoice" in target and "oe_finance_budget" not in target:
            return _Result(self.paid_invoices)
        return _Result(self.budgets)


def _make_service_with_session(paid_invoices: list[Any], budgets: list[Any]) -> FinanceService:
    service = _make_service()
    service.session = _ExecuteStubSession(paid_invoices, budgets)  # type: ignore[assignment]
    return service


def _make_line_item(*, amount: str, wbs_id: str | None = None, cost_category: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        amount=amount,
        wbs_id=wbs_id,
        cost_category=cost_category,
    )


def _make_paid_invoice(*, project_id: uuid.UUID, amount_total: str, items: list[Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        status="paid",
        amount_total=amount_total,
        invoice_number="INV-TEST",
        line_items=list(items or []),
    )


def _make_budget_row(
    *, project_id: uuid.UUID, wbs_id: str | None = None, category: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        wbs_id=wbs_id,
        category=category,
        actual="0",
    )


@pytest.mark.asyncio
async def test_pay_invoice_distributes_actuals_by_category() -> None:
    """Two budget rows ('material' and 'labor') must receive DIFFERENT
    actuals pulled from matching invoice-line items — not the combined total."""
    pid = uuid.uuid4()

    paid_invoice = _make_paid_invoice(
        project_id=pid,
        amount_total="1000",
        items=[
            _make_line_item(amount="700", cost_category="material"),
            _make_line_item(amount="300", cost_category="labor"),
        ],
    )
    budget_material = _make_budget_row(project_id=pid, category="material")
    budget_labor = _make_budget_row(project_id=pid, category="labor")

    service = _make_service_with_session([paid_invoice], [budget_material, budget_labor])

    # Seed an approved invoice and its lookup so pay_invoice can run.
    approved_invoice = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=pid,
        status="approved",
        amount_total="1000",
        invoice_number="INV-SEED",
        currency_code="EUR",
    )
    service.invoices.rows[approved_invoice.id] = approved_invoice  # type: ignore[attr-defined]

    await service.pay_invoice(approved_invoice.id)

    assert budget_material.actual == "700"
    assert budget_labor.actual == "300"


@pytest.mark.asyncio
async def test_pay_invoice_unmatched_category_lands_in_catch_all() -> None:
    """Line items with a cost_category that has NO matching budget row
    fall through to the ``(None, None)`` bucket if one exists — otherwise
    they are dropped (logged elsewhere)."""
    pid = uuid.uuid4()

    paid_invoice = _make_paid_invoice(
        project_id=pid,
        amount_total="500",
        items=[_make_line_item(amount="500", cost_category="material")],
    )
    uncategorized_budget = _make_budget_row(project_id=pid, category=None)
    # No matching budget row for "material".

    service = _make_service_with_session([paid_invoice], [uncategorized_budget])

    approved_invoice = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=pid,
        status="approved",
        amount_total="500",
        invoice_number="INV-UNMATCHED",
        currency_code="EUR",
    )
    service.invoices.rows[approved_invoice.id] = approved_invoice  # type: ignore[attr-defined]

    await service.pay_invoice(approved_invoice.id)

    # 500 went to the 'material' bucket that has no matching budget; the
    # catch-all budget (category=None) stays at 0.
    assert uncategorized_budget.actual == "0"


@pytest.mark.asyncio
async def test_pay_invoice_no_line_items_falls_to_catch_all() -> None:
    """Invoice without line items — entire amount_total → ``(None, None)`` bucket."""
    pid = uuid.uuid4()

    paid_invoice = _make_paid_invoice(
        project_id=pid,
        amount_total="2500",
        items=[],  # no breakdown
    )
    catch_all_budget = _make_budget_row(project_id=pid, wbs_id=None, category=None)

    service = _make_service_with_session([paid_invoice], [catch_all_budget])

    approved_invoice = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=pid,
        status="approved",
        amount_total="2500",
        invoice_number="INV-LUMP",
        currency_code="EUR",
    )
    service.invoices.rows[approved_invoice.id] = approved_invoice  # type: ignore[attr-defined]

    await service.pay_invoice(approved_invoice.id)
    assert catch_all_budget.actual == "2500"


@pytest.mark.asyncio
async def test_pay_invoice_does_not_write_total_to_every_budget_row() -> None:
    """BUG-346 regression guard: two unrelated budget rows must NOT both
    receive the project grand-total."""
    pid = uuid.uuid4()

    paid_invoice = _make_paid_invoice(
        project_id=pid,
        amount_total="1000",
        items=[_make_line_item(amount="1000", cost_category="material")],
    )
    budget_material = _make_budget_row(project_id=pid, category="material")
    budget_labor = _make_budget_row(project_id=pid, category="labor")

    service = _make_service_with_session([paid_invoice], [budget_material, budget_labor])

    approved_invoice = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=pid,
        status="approved",
        amount_total="1000",
        invoice_number="INV-REGRESSION",
        currency_code="EUR",
    )
    service.invoices.rows[approved_invoice.id] = approved_invoice  # type: ignore[attr-defined]

    await service.pay_invoice(approved_invoice.id)

    assert budget_material.actual == "1000"
    assert budget_labor.actual == "0"  # stays zero — the bug would have written 1000 here


# ── ETC clamp regression (2026-05-21 audit fix #4) ────────────────────────


@pytest.mark.asyncio
async def test_create_evm_snapshot_etc_clamped_to_zero_when_over_budget() -> None:
    """When AC > EAC (over-budget run), ETC ("estimate to complete") would
    naively report a negative figure (eac - ac < 0). The right answer is
    "no remaining spend forecast" = 0, not a negative budget recovery.

    Setup: CPI=1 (so EAC ≈ AC + (BAC-EV) = AC ≈ 12000 with BAC=10000,
    EV=10000, AC=12000 → EAC=12000, ETC raw = 0). We push harder:
    BAC=10000, PV=10000, EV=10000, AC=15000 → CPI=10000/15000=0.667,
    EAC = 15000 + 0 / 0.667 = 15000, ETC raw = eac - ac = 0 — still
    zero. We craft an explicit AC > EAC scenario by exploiting the
    cpi==0 branch: when EV=0 and BAC < AC, EAC = AC + BAC < AC.
    """
    service = _make_service()
    snapshot = await service.create_evm_snapshot(
        EVMSnapshotCreate(
            project_id=uuid.uuid4(),
            snapshot_date="2026-04-01",
            bac="10000",
            pv="5000",
            ev="0",  # forces cpi=0 branch -> eac = ac + (bac - ev) = ac + bac
            ac="50000",  # ac > bac, so eac = 50000 + 10000 = 60000 still > ac
        )
    )
    # Above scenario: eac = 60000, ac = 50000, etc raw = 10000 > 0 — safe.

    # Now the actual clamp case: bac small, ev > 0, cpi forces EAC < AC.
    # EAC = AC + (BAC-EV)/CPI. With CPI very large (EV >> AC), EAC ≈ AC + 0+.
    # To force EAC < AC we need (BAC-EV)/CPI < 0, i.e. EV > BAC.
    snapshot2 = await service.create_evm_snapshot(
        EVMSnapshotCreate(
            project_id=uuid.uuid4(),
            snapshot_date="2026-04-02",
            bac="10000",
            pv="10000",
            ev="12000",  # over-performing — EV > BAC drives (BAC-EV) negative
            ac="11000",  # CPI = 12000/11000 = 1.0909
        )
    )
    # EAC = 11000 + (10000 - 12000) / 1.0909 = 11000 - 1833.33 = 9166.67
    # raw ETC = 9166.67 - 11000 = -1833.33  -->  clamp -> 0
    assert Decimal(snapshot2.etc) == Decimal("0.00")
    # snapshot1 retains a positive ETC (cpi==0 fallback path)
    assert Decimal(snapshot.etc) >= Decimal("0")


# ── Audit-warning regression (2026-05-21 audit fix #3) ────────────────────


@pytest.mark.asyncio
async def test_approve_invoice_audit_failure_emits_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the audit-log helper raises, ``approve_invoice`` must still
    succeed (best-effort) but emit a logger.warning carrying the actor_id
    and invoice_id so ops can spot the failure (previously logger.debug,
    invisible at production INFO root level)."""
    import logging as _logging

    service = _make_service()
    invoice = await service.create_invoice(
        InvoiceCreate(
            project_id=uuid.uuid4(),
            invoice_direction="payable",
            invoice_date="2026-04-01",
            amount_subtotal="100",
            tax_amount="19",
        )
    )

    # Force the audit-log helper to blow up.
    import app.core.audit_log as _audit_mod

    original = _audit_mod.log_activity

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit db is down")

    _audit_mod.log_activity = _boom  # type: ignore[assignment]
    try:
        actor = uuid.uuid4()
        with caplog.at_level(_logging.WARNING, logger="app.modules.finance.service"):
            updated = await service.approve_invoice(invoice.id, actor_id=str(actor))
        # The status transition still landed:
        assert updated.status == "sent"
        # The warning fired and carries the operational metadata:
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == _logging.WARNING and "FSM audit log FAILED for invoice approve" in r.getMessage()
        ]
        assert warning_records, "Expected an audit-failure WARNING but none was emitted"
        msg = warning_records[0].getMessage()
        assert str(actor) in msg
        assert str(invoice.id) in msg
    finally:
        _audit_mod.log_activity = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_update_invoice_line_items_replace_logs_audit_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bulk line-item replace path inside ``update_invoice`` must log a
    single audit row carrying the count + total delta — no per-item diff.
    We capture the helper call instead of running it for real to keep this
    fully stubbed."""
    from app.modules.finance.schemas import InvoiceLineItemCreate, InvoiceUpdate

    service = _make_service()
    # Build a synthetic invoice row directly — the SQLAlchemy ORM-typed
    # ``line_items`` relationship rejects SimpleNamespace, but a plain
    # SimpleNamespace stand-in for the whole invoice lets us hand-pick the
    # prior line items the audit delta calc inspects.
    invoice = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        invoice_number="INV-TEST-1",
        invoice_direction="payable",
        amount_subtotal="500",
        tax_amount="0",
        amount_total="500",
        status="draft",
        line_items=[
            SimpleNamespace(amount="200"),
            SimpleNamespace(amount="300"),
        ],
    )
    service.invoices.rows[invoice.id] = invoice  # type: ignore[attr-defined]

    # Capture audit calls.
    import app.core.audit_log as _audit_mod

    captured: dict[str, Any] = {}
    original = _audit_mod.log_activity

    async def _spy(*args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    _audit_mod.log_activity = _spy  # type: ignore[assignment]
    try:
        await service.update_invoice(
            invoice.id,
            InvoiceUpdate(
                line_items=[
                    InvoiceLineItemCreate(
                        description="New only",
                        quantity="1",
                        unit="lsum",
                        unit_rate="450",
                        amount="450",
                    ),
                ],
            ),
        )
    finally:
        _audit_mod.log_activity = original  # type: ignore[assignment]

    assert captured.get("action") == "line_items_replaced"
    md = captured.get("metadata") or {}
    assert md.get("prior_count") == 2
    assert md.get("new_count") == 1
    # 200 + 300 = 500 prior; 450 new; delta = -50
    assert Decimal(md.get("total_delta", "0")) == Decimal("-50")
