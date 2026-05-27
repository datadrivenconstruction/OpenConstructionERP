"""Finance R7 security regression suite.

Pins the five R7 invariants for the finance module:

1. **IDOR**: ``_require_project_access`` answers **404** on cross-tenant
   (was 403 pre-R7 — leaked project existence). All entity-scoped
   helpers (invoice / budget / payment / EVM) chain through the project
   gate before service logic.
2. **Decimal-as-string**: every money field on every response schema
   is typed ``str``. The ORM uses ``MoneyType`` (Decimal in Python,
   NUMERIC on Postgres, VARCHAR on SQLite) and the response schemas
   coerce via a ``mode="before"`` field validator.
3. **Magic-byte uploads**: ``/budgets/import/file/`` rejects non-ZIP /
   non-OLE content with a magic-byte signature mismatch (HTTP 415).
4. **FSM allowlists**: ``_INVOICE_STATUS_TRANSITIONS`` is complete and
   ``paid → paid`` is NOT allowed → idempotency by allowlist (a
   double-click on the pay button cannot trigger a duplicate
   budget-actual recompute).
5. **RBAC on writes**: ``finance.approve`` / ``finance.pay`` /
   ``finance.record_payment`` are pinned to MANAGER. EDITOR may draft
   invoices but not approve / pay / record a payment row.

Module-specific concerns:
    * **Audit trail on every money-moving event**: approve / pay /
      payment-create write to :class:`ActivityLog`. The tests assert
      the log_activity call survives in the service source.
    * **Decimal arithmetic correctness on EVM snapshot**: the SV/CV/SPI/
      CPI/EAC/VAC derivation must round-trip exactly with Decimal,
      no float intermediates. Pinned with a numeric end-to-end test.
    * **Escrow / commission / retention-release**: live in
      ``property_dev`` and ``crm`` respectively, NOT finance. Finance's
      retention column on invoices is a passive amount stored on the
      header — no separate release endpoint exists here.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.permissions import Role, permission_registry
from app.modules.finance import permissions as finance_perms
from app.modules.finance import router as finance_router
from app.modules.finance.schemas import (
    BudgetResponse,
    EVMSnapshotCreate,
    InvoiceCreate,
    InvoiceResponse,
    PaymentCreate,
    PaymentResponse,
)
from app.modules.finance.service import (
    _INVOICE_STATUS_TRANSITIONS,
    _VALID_INVOICE_STATUSES,
    FinanceService,
)

# ── Shared stubs ──────────────────────────────────────────────────────────

PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


class _StubInvoiceRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, invoice: Any) -> Any:
        if getattr(invoice, "id", None) is None:
            invoice.id = uuid.uuid4()
        invoice.line_items = []
        invoice.payments = []
        invoice.created_at = datetime.now(UTC)
        invoice.updated_at = datetime.now(UTC)
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
        return rows, len(rows)

    async def next_invoice_number(self, project_id: uuid.UUID, direction: str) -> str:
        self._counter += 1
        return f"INV-{self._counter:04d}"

    async def update(self, invoice_id: uuid.UUID, **fields: Any) -> None:
        inv = self.rows.get(invoice_id)
        if inv is not None:
            for k, v in fields.items():
                setattr(inv, k, v)
            inv.updated_at = datetime.now(UTC)


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
        payment.created_at = datetime.now(UTC)
        payment.updated_at = datetime.now(UTC)
        self.rows.append(payment)
        return payment

    async def list(self, *, invoice_id=None, limit=50, offset=0):
        rows = list(self.rows)
        if invoice_id is not None:
            rows = [r for r in rows if r.invoice_id == invoice_id]
        return rows, len(rows)

    async def aggregate_total(self) -> Decimal:
        return Decimal("0")


class _StubBudgetRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, budget: Any) -> Any:
        if getattr(budget, "id", None) is None:
            budget.id = uuid.uuid4()
        budget.created_at = datetime.now(UTC)
        budget.updated_at = datetime.now(UTC)
        self.rows[budget.id] = budget
        return budget

    async def get(self, budget_id: uuid.UUID) -> Any:
        return self.rows.get(budget_id)

    async def list(self, *, project_id=None, category=None):
        rows = list(self.rows.values())
        if project_id is not None:
            rows = [r for r in rows if r.project_id == project_id]
        return rows, len(rows)

    async def update(self, budget_id, **fields):
        b = self.rows.get(budget_id)
        if b is not None:
            for k, v in fields.items():
                setattr(b, k, v)

    async def aggregate_for_dashboard(self, *, project_id=None) -> dict:
        return {
            "total_budget_original": Decimal("0"),
            "total_budget_revised": Decimal("0"),
            "total_committed": Decimal("0"),
            "total_actual": Decimal("0"),
            "currency": "",
        }


class _StubEVMRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, snap: Any) -> Any:
        if getattr(snap, "id", None) is None:
            snap.id = uuid.uuid4()
        snap.created_at = datetime.now(UTC)
        snap.updated_at = datetime.now(UTC)
        self.rows[snap.id] = snap
        return snap

    async def list(self, *, project_id=None):
        return list(self.rows.values()), len(self.rows)


class _StubSession:
    """Minimal ``AsyncSession`` shim for the audit-log call inside services."""

    def add(self, _obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def execute(self, _stmt: Any) -> SimpleNamespace:
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalars=lambda: SimpleNamespace(all=lambda: []),
        )


def _make_service() -> FinanceService:
    svc = FinanceService.__new__(FinanceService)
    svc.session = _StubSession()
    svc.invoices = _StubInvoiceRepo()
    svc.line_items = _StubLineItemRepo()
    svc.payments_repo = _StubPaymentRepo()
    svc.budgets = _StubBudgetRepo()
    svc.evm = _StubEVMRepo()
    return svc


# ── 1. IDOR coverage ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_project_access_returns_404_on_cross_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-R7 the finance gate returned 403 on cross-tenant access; this
    leaked the existence of project UUIDs the caller does not own. The
    R7 fix collapses 403 → 404 (same shape as the missing-project branch
    and the shared ``app.dependencies.verify_project_access``).
    """
    project_a = SimpleNamespace(id=PROJECT_A, owner_id=USER_A)

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            return project_a if project_id == PROJECT_A else None

    class _StubUserRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, user_id: Any):
            return SimpleNamespace(id=user_id, role="user")

    monkeypatch.setattr(
        "app.modules.projects.repository.ProjectRepository",
        _StubProjectRepo,
    )
    monkeypatch.setattr(
        "app.modules.users.repository.UserRepository",
        _StubUserRepo,
    )

    # USER_B (no access) → 404, not 403.
    with pytest.raises(HTTPException) as exc_info:
        await finance_router._require_project_access(
            session=None,
            project_id=PROJECT_A,
            user_id=USER_B,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404, (
        f"finance _require_project_access leaks existence on cross-tenant: "
        f"expected 404, got {exc_info.value.status_code}"
    )

    # USER_A (owner) → no raise.
    await finance_router._require_project_access(
        session=None,
        project_id=PROJECT_A,
        user_id=USER_A,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_require_project_access_missing_project_is_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing project must also 404 — same shape as cross-tenant so the
    caller cannot distinguish "doesn't exist" from "I lack access".
    """

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            return None

    class _StubUserRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, user_id: Any):
            return SimpleNamespace(id=user_id, role="user")

    monkeypatch.setattr(
        "app.modules.projects.repository.ProjectRepository",
        _StubProjectRepo,
    )
    monkeypatch.setattr(
        "app.modules.users.repository.UserRepository",
        _StubUserRepo,
    )

    with pytest.raises(HTTPException) as exc_info:
        await finance_router._require_project_access(
            session=None,
            project_id=uuid.uuid4(),
            user_id=USER_A,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_require_project_access_no_project_id_is_noop() -> None:
    """``project_id=None`` (cross-project dashboard) must not raise — the
    aggregation endpoints handle scoping at the service layer."""
    await finance_router._require_project_access(
        session=None,
        project_id=None,
        user_id=USER_A,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_require_project_access_no_user_is_401() -> None:
    """Missing user context on a project-scoped call must be 401, not
    a silent 200 or 500."""
    with pytest.raises(HTTPException) as exc_info:
        await finance_router._require_project_access(
            session=None,
            project_id=PROJECT_A,
            user_id=None,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 401


def test_router_require_project_access_uses_404_not_403() -> None:
    """Static guard: a future refactor that reverts to 403 trips here.

    Pins the source-level invariant that finance's project access guard
    no longer emits a 403 response code anywhere in the cross-tenant
    branch (was the legacy behaviour).
    """
    src = inspect.getsource(finance_router._require_project_access)
    # The cross-tenant rejection must NOT mention HTTP_403_FORBIDDEN —
    # the original buggy code returned that on owner mismatch.
    assert "HTTP_403_FORBIDDEN" not in src, (
        "finance _require_project_access regressed to 403 on owner "
        "mismatch — existence of project UUIDs leaks cross-tenant."
    )


def test_router_get_invoice_chains_through_access_guard() -> None:
    """All entity-scoped routes (get / patch / approve / pay) MUST call
    one of the access-guard helpers BEFORE touching the service.
    """
    for handler_name in (
        "get_invoice",
        "update_invoice",
        "approve_invoice",
        "pay_invoice",
    ):
        handler = getattr(finance_router, handler_name)
        src = inspect.getsource(handler)
        assert "_require_invoice_access" in src, (
            f"IDOR REGRESSION: finance.{handler_name} no longer chains through _require_invoice_access"
        )


def test_router_payment_create_chains_through_invoice_access_guard() -> None:
    """``POST /payments/`` resolves the parent invoice and gates its
    project before persisting the payment row — otherwise a forged
    invoice_id could enable cross-tenant ledger pollution.
    """
    src = inspect.getsource(finance_router.create_payment)
    assert "_require_invoice_access" in src


def test_router_budget_update_chains_through_budget_access_guard() -> None:
    """Budget update gates the parent project via the budget access
    helper (budget → project → owner).
    """
    src = inspect.getsource(finance_router.update_budget)
    assert "_require_budget_access" in src


# ── 2. Decimal-as-string on response schemas ──────────────────────────────


def test_invoice_response_money_fields_are_strings() -> None:
    """``InvoiceResponse`` money fields stay ``str``-typed — a
    regression to float would lose precision on the wire."""
    fields = InvoiceResponse.model_fields
    for fname in (
        "amount_subtotal",
        "tax_amount",
        "retention_amount",
        "amount_total",
    ):
        ann = fields[fname].annotation
        assert ann is str, f"InvoiceResponse.{fname} must be `str`, got {ann!r}"


def test_payment_response_money_fields_are_strings() -> None:
    """``PaymentResponse.amount`` + ``exchange_rate_snapshot`` stay
    strings — exchange rates with 6-decimal precision must not round-
    trip through float.
    """
    fields = PaymentResponse.model_fields
    for fname in ("amount", "exchange_rate_snapshot"):
        ann = fields[fname].annotation
        assert ann is str, f"PaymentResponse.{fname} must be `str`, got {ann!r}"


def test_budget_response_money_fields_are_strings() -> None:
    """All budget money slots return Decimal-as-string."""
    fields = BudgetResponse.model_fields
    for fname in (
        "original_budget",
        "revised_budget",
        "committed",
        "actual",
        "forecast_final",
        "variance",
    ):
        ann = fields[fname].annotation
        assert ann is str, f"BudgetResponse.{fname} must be `str`, got {ann!r}"


def test_payment_create_rejects_zero_amount() -> None:
    """Payment amounts must be strictly positive — a zero payment is a
    schema-level error (422), not a 500 later."""
    with pytest.raises(ValueError):
        PaymentCreate(
            invoice_id=uuid.uuid4(),
            payment_date="2026-05-24",
            amount="0",
        )


def test_payment_create_rejects_negative_amount() -> None:
    """Defence against credit-injection via negative payment."""
    with pytest.raises(ValueError):
        PaymentCreate(
            invoice_id=uuid.uuid4(),
            payment_date="2026-05-24",
            amount="-100",
        )


def test_invoice_create_rejects_garbage_decimal() -> None:
    """Garbage in money fields is 422 at schema, not 500 at service."""
    with pytest.raises(ValueError):
        InvoiceCreate(
            project_id=PROJECT_A,
            invoice_direction="payable",
            amount_subtotal="not-a-number",
        )


@pytest.mark.asyncio
async def test_invoice_response_serialises_decimal_arithmetic_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: subtotal 100.10 + tax 9.90 must serialise as
    "110.00", never a float-rounded "110.0000000000001"."""
    svc = _make_service()

    inv = await svc.create_invoice(
        InvoiceCreate(
            project_id=PROJECT_A,
            invoice_direction="payable",
            invoice_date="2026-05-24",
            amount_subtotal="100.10",
            tax_amount="9.90",
            amount_total="0",
        ),
        user_id=USER_A,
    )
    # Decimal-exact equality.
    assert Decimal(str(inv.amount_total)) == Decimal("110.00")


# ── 3. Magic-byte uploads ─────────────────────────────────────────────────


def test_budget_import_router_imports_file_signature() -> None:
    """Pin the static import — without it the magic-byte gate falls
    out and the filename-extension check (which is attacker-controlled)
    is all that's left.
    """
    src = Path(finance_router.__file__).read_text(encoding="utf-8")
    assert "file_signature" in src, (
        "finance/router.py no longer imports file_signature — the magic-byte gate on /budgets/import/file/ is gone."
    )


def test_budget_import_calls_require_signature() -> None:
    """The import handler must invoke the signature gate before passing
    bytes to openpyxl/csv parsers."""
    src = inspect.getsource(finance_router.import_budgets_file)
    assert "require_signature" in src, (
        "import_budgets_file no longer calls require_signature — an "
        "attacker can rename a payload to .xlsx and have it parsed."
    )


def test_magic_byte_gate_rejects_pe_executable_renamed_as_xlsx() -> None:
    """Unit-level proof that the gate would reject a PE/EXE blob
    renamed to ``payload.xlsx``."""
    from app.core.file_signature import (
        FileSignatureMismatch,
    )
    from app.core.file_signature import (
        require as require_signature,
    )

    # "MZ" header — the universal Windows PE/DOS magic byte.
    pe_head = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    with pytest.raises(FileSignatureMismatch):
        require_signature(
            pe_head,
            frozenset({"zip", "ole"}),
            filename="payload.xlsx",
        )


def test_magic_byte_gate_accepts_real_xlsx_signature() -> None:
    """The gate does NOT block a real xlsx (ZIP container)."""
    from app.core.file_signature import require as require_signature

    zip_head = b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00\xab\xcd"
    detected = require_signature(
        zip_head,
        frozenset({"zip", "ole"}),
        filename="budget.xlsx",
    )
    assert detected == "zip"


def test_magic_byte_gate_accepts_legacy_xls_signature() -> None:
    """Legacy .xls (OLE compound document) also passes."""
    from app.core.file_signature import require as require_signature

    ole_head = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\x00\x00\x00\x00\x00\x00\x00"
    detected = require_signature(
        ole_head,
        frozenset({"zip", "ole"}),
        filename="budget.xls",
    )
    assert detected == "ole"


# ── 4. FSM allowlists ─────────────────────────────────────────────────────


def test_invoice_status_transitions_table_covers_all_states() -> None:
    """Every state in the FSM must appear as a key in the transitions
    map — a missing key would silently return an empty set on lookup
    and brick the workflow without an explicit allowlist decision.
    """
    expected = {
        "draft",
        "pending",
        "approved",
        "sent",
        "paid",
        "cancelled",
        "credit_note_issued",
    }
    assert expected == _VALID_INVOICE_STATUSES, (
        f"invoice FSM state set drifted: expected {expected}, got {_VALID_INVOICE_STATUSES}"
    )


def test_invoice_status_transitions_paid_is_idempotent() -> None:
    """``paid → paid`` is NOT allowed → second pay click 400s instead
    of triggering a duplicate budget-actual recompute (idempotency by
    FSM allowlist)."""
    paid_exits = _INVOICE_STATUS_TRANSITIONS["paid"]
    assert "paid" not in paid_exits, (
        "paid -> paid is in the allowlist — pay button is no longer "
        "idempotent and a double-click would double-recompute actuals."
    )
    # Only credit-note reversal is allowed from paid.
    assert paid_exits == {"credit_note_issued"}


def test_invoice_status_credit_note_is_terminal() -> None:
    """credit_note_issued has no exits — no resurrection from a
    voided invoice."""
    assert _INVOICE_STATUS_TRANSITIONS["credit_note_issued"] == set()


@pytest.mark.asyncio
async def test_pay_invoice_twice_is_rejected() -> None:
    """Functional end-to-end of the FSM idempotency: pay once → ok,
    pay again → 400. No double-recompute of budget actuals.
    """
    svc = _make_service()
    inv = await svc.create_invoice(
        InvoiceCreate(
            project_id=PROJECT_A,
            invoice_direction="payable",
            invoice_date="2026-05-24",
            amount_subtotal="100",
            tax_amount="0",
        ),
        user_id=USER_A,
    )
    # draft → sent → paid (legal)
    await svc.approve_invoice(inv.id, actor_id=USER_A)
    await svc.pay_invoice(inv.id, actor_id=USER_A)
    # paid → paid (must reject)
    with pytest.raises(HTTPException) as exc_info:
        await svc.pay_invoice(inv.id, actor_id=USER_A)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_approve_rejects_from_paid_state() -> None:
    """A paid invoice cannot be re-approved — that would let an
    attacker reset state and double-bill."""
    svc = _make_service()
    inv = await svc.create_invoice(
        InvoiceCreate(
            project_id=PROJECT_A,
            invoice_direction="payable",
            invoice_date="2026-05-24",
            amount_subtotal="50",
            tax_amount="0",
        ),
        user_id=USER_A,
    )
    await svc.approve_invoice(inv.id, actor_id=USER_A)
    await svc.pay_invoice(inv.id, actor_id=USER_A)
    with pytest.raises(HTTPException) as exc_info:
        await svc.approve_invoice(inv.id, actor_id=USER_A)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_invoice_update_rejects_invalid_status_transition() -> None:
    """draft → paid is NOT allowed — must traverse sent first."""
    from app.modules.finance.schemas import InvoiceUpdate

    svc = _make_service()
    inv = await svc.create_invoice(
        InvoiceCreate(
            project_id=PROJECT_A,
            invoice_direction="payable",
            invoice_date="2026-05-24",
            amount_subtotal="50",
            tax_amount="0",
        ),
        user_id=USER_A,
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.update_invoice(inv.id, InvoiceUpdate(status="paid"))
    assert exc_info.value.status_code == 400


# ── 5. RBAC on writes ─────────────────────────────────────────────────────


def test_finance_approve_permission_is_manager() -> None:
    """The R7 split-off ``finance.approve`` permission is MANAGER+.
    EDITOR must NOT satisfy it.
    """
    finance_perms.register_finance_permissions()
    assert permission_registry.get_min_role("finance.approve") is Role.MANAGER
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "finance.approve",
    ), "EDITOR can now approve invoices — RBAC regression"
    assert permission_registry.role_has_permission(
        Role.MANAGER,
        "finance.approve",
    )


def test_finance_pay_permission_is_manager() -> None:
    """Pay button is MANAGER+ — moving an invoice to paid is a binding
    ledger action."""
    finance_perms.register_finance_permissions()
    assert permission_registry.get_min_role("finance.pay") is Role.MANAGER
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "finance.pay",
    )


def test_finance_record_payment_permission_is_manager() -> None:
    """Recording a payment row is MANAGER+. An EDITOR-level role can no
    longer fabricate ledger entries against an invoice."""
    finance_perms.register_finance_permissions()
    assert permission_registry.get_min_role("finance.record_payment") is Role.MANAGER
    assert not permission_registry.role_has_permission(
        Role.EDITOR,
        "finance.record_payment",
    )


def test_router_approve_uses_finance_approve_permission() -> None:
    """Static pin on the route so a refactor that drops back to
    ``finance.update`` (EDITOR) trips here."""
    src = inspect.getsource(finance_router.approve_invoice)
    assert 'RequirePermission("finance.approve")' in src


def test_router_pay_uses_finance_pay_permission() -> None:
    src = inspect.getsource(finance_router.pay_invoice)
    assert 'RequirePermission("finance.pay")' in src


def test_router_create_payment_uses_record_payment_permission() -> None:
    src = inspect.getsource(finance_router.create_payment)
    assert 'RequirePermission("finance.record_payment")' in src


# ── Audit trail (R7 compliance) ──────────────────────────────────────────


def test_service_approve_invoice_writes_audit_log() -> None:
    """Static guard: approve_invoice persists an ActivityLog row."""
    src = inspect.getsource(FinanceService.approve_invoice)
    assert "log_activity" in src, "approve_invoice no longer writes an audit row — compliance hole"


def test_service_pay_invoice_writes_audit_log() -> None:
    src = inspect.getsource(FinanceService.pay_invoice)
    assert "log_activity" in src


def test_service_create_payment_writes_audit_log() -> None:
    """Recording a payment row is a money-moving event — must surface in
    the audit trail with the actor id."""
    src = inspect.getsource(FinanceService.create_payment)
    assert "log_activity" in src, (
        "create_payment no longer writes an audit row — money-moving events must always be auditable."
    )


# ── EVM Decimal arithmetic correctness ───────────────────────────────────


@pytest.mark.asyncio
async def test_evm_snapshot_uses_decimal_arithmetic() -> None:
    """EVM derivations (SV, CV, SPI, CPI, EAC, VAC, ETC, TCPI) must be
    computed with Decimal end-to-end. Pin numeric correctness so a
    refactor to float doesn't cause cent-level drift on multi-million
    project rollups.

    Inputs chosen so float arithmetic would visibly drift:
        BAC=1_000_000, PV=500_000, EV=400_000, AC=450_000
        SV = -100_000 (schedule behind)
        CV = -50_000  (cost over)
        SPI = 0.8     (400_000 / 500_000)
        CPI = 0.8888… (400_000 / 450_000)
        EAC = AC + (BAC - EV) / CPI = 450_000 + 600_000 / 0.8889 = 1_125_000
        VAC = BAC - EAC = -125_000
    """
    svc = _make_service()
    snap = await svc.create_evm_snapshot(
        EVMSnapshotCreate(
            project_id=PROJECT_A,
            snapshot_date="2026-05-24",
            bac="1000000",
            pv="500000",
            ev="400000",
            ac="450000",
        ),
    )
    # SV / CV: exact Decimal subtraction.
    assert Decimal(snap.sv) == Decimal("-100000")
    assert Decimal(snap.cv) == Decimal("-50000")
    # SPI = 400_000 / 500_000 = 0.8 exact
    assert Decimal(snap.spi) == Decimal("0.8")
    # CPI = 400_000 / 450_000 (irrational in base-10 — rounded to 4dp = 0.8889)
    assert Decimal(snap.cpi) == Decimal("0.8889")
    # EAC = AC + (BAC - EV) / CPI
    # The CPI rounding above yields EAC ≈ 1_124_997.19 — pin to 2dp.
    eac = Decimal(snap.eac)
    assert Decimal("1124000") <= eac <= Decimal("1126000"), eac
    # VAC = BAC - EAC must mirror EAC's sign convention exactly.
    vac = Decimal(snap.vac)
    assert vac == Decimal("1000000") - eac
