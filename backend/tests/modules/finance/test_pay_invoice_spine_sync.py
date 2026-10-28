"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Gap B integration tests: paying an invoice posts into the costmodel spine.

Exercises ``FinanceService.pay_invoice`` end to end against a real PostgreSQL
session (the only dialect the app runs on), wrapped in a per-test transaction
that is rolled back on teardown via the canonical ``transactional_session``
helper. After a pay, both budget tables are asserted:

* legacy ``finance.ProjectBudget.actual`` (backward compat, BUG-346 bucketing)
* the cost spine ``costmodel.BudgetLine.actual_amount`` (new in Gap B)

Money is asserted with exact ``Decimal`` values.

Covers TEST MATRIX cases 11-18 (integration):
    11 two line items → two spine BudgetLine rows
    12 headerless invoice → one uncategorised row (category="")
    13 paying twice is idempotent (no double count)
    14 line.cost_line_id is honoured on the spine row
    15 USD invoice, EUR base → converted to EUR via fx_rates
    16 JPY invoice, no rate → kept in its own units (never zeroed)
    17 a spine failure leaves the invoice paid (non-fatal)
    18 both ProjectBudget AND BudgetLine are updated
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine, ControlAccount, CostLine
from app.modules.finance.models import ProjectBudget
from app.modules.finance.schemas import InvoiceCreate, InvoiceLineItemCreate
from app.modules.finance.service import FinanceService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session per test (rolled back on teardown)."""
    async with transactional_session() as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _seed_project(
    session: AsyncSession,
    *,
    currency: str = "EUR",
    fx_rates: list | None = None,
) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"payspine-{uuid.uuid4().hex[:10]}@cost-spine.io",
        hashed_password="x",
        full_name="Pay Spine Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Pay Spine project",
        owner_id=owner.id,
        currency=currency,
        fx_rates=fx_rates or [],
    )
    session.add(project)
    await session.flush()
    return project.id


async def _budget_lines(session: AsyncSession, project_id: uuid.UUID) -> list[BudgetLine]:
    rows = await session.execute(select(BudgetLine).where(BudgetLine.project_id == project_id))
    return list(rows.scalars().all())


async def _make_and_pay_invoice(
    svc: FinanceService,
    project_id: uuid.UUID,
    *,
    currency: str = "EUR",
    items: list[InvoiceLineItemCreate] | None = None,
    subtotal: str = "0",
) -> uuid.UUID:
    """Create → approve → pay an invoice; return its id."""
    create = InvoiceCreate(
        project_id=project_id,
        invoice_direction="payable",
        currency_code=currency,
        amount_subtotal=subtotal,
        tax_amount="0",
        line_items=items or [],
    )
    invoice = await svc.create_invoice(create)
    await svc.approve_invoice(invoice.id)
    await svc.pay_invoice(invoice.id)
    return invoice.id


# ── Case 11: two line items → two spine rows ──────────────────────────────────


async def test_pay_invoice_posts_to_budget_line_per_item(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = FinanceService(session)

    items = [
        InvoiceLineItemCreate(description="Concrete", amount="1000.00", cost_category="material"),
        InvoiceLineItemCreate(description="Crew", amount="400.00", cost_category="labor"),
    ]
    await _make_and_pay_invoice(svc, project_id, items=items, subtotal="1400.00")

    lines = await _budget_lines(session, project_id)
    by_cat = {bl.category: Decimal(bl.actual_amount) for bl in lines}
    assert by_cat.get("material") == Decimal("1000.00")
    assert by_cat.get("labor") == Decimal("400.00")
    assert len(lines) == 2


# ── Case 12: headerless invoice → one uncategorised row ───────────────────────


async def test_pay_invoice_posts_full_if_no_items(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = FinanceService(session)

    await _make_and_pay_invoice(svc, project_id, items=[], subtotal="2500.00")

    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    assert lines[0].category == ""  # uncategorised sentinel
    assert lines[0].cost_line_id is None
    assert Decimal(lines[0].actual_amount) == Decimal("2500.00")


# ── Case 13: paying twice is idempotent ───────────────────────────────────────


async def test_pay_invoice_idempotent_if_paid_twice(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = FinanceService(session)

    items = [InvoiceLineItemCreate(description="Concrete", amount="1000.00", cost_category="material")]
    invoice_id = await _make_and_pay_invoice(svc, project_id, items=items, subtotal="1000.00")

    # Re-run the spine sweep directly (simulating a replay / second trigger).
    await svc._post_paid_invoices_to_spine(project_id)

    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    assert Decimal(lines[0].actual_amount) == Decimal("1000.00")  # not 2000
    assert len(lines[0].metadata_["postings"]) == 1


# ── Case 14: line cost_line_id honoured ───────────────────────────────────────


async def test_pay_invoice_respects_cost_line_id(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    account = ControlAccount(
        project_id=project_id,
        code="330",
        name="Baukonstruktion",
        classification_standard="din276",
    )
    session.add(account)
    await session.flush()
    cost_line = CostLine(
        project_id=project_id,
        control_account_id=account.id,
        code="CL-WALL-1",
        description="RC wall",
        unit="m3",
        source="manual",
        estimate_amount="5000.00",
        currency="EUR",
    )
    session.add(cost_line)
    await session.flush()

    svc = FinanceService(session)
    items = [
        InvoiceLineItemCreate(
            description="Concrete",
            amount="1000.00",
            cost_category="material",
            cost_line_id=cost_line.id,
        )
    ]
    await _make_and_pay_invoice(svc, project_id, items=items, subtotal="1000.00")

    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    assert lines[0].cost_line_id == cost_line.id
    assert lines[0].control_account_id == account.id
    assert Decimal(lines[0].actual_amount) == Decimal("1000.00")


# ── Case 15: multicurrency converted to base ──────────────────────────────────


async def test_pay_invoice_multicurrency_converted(session: AsyncSession) -> None:
    # 1 USD = 0.90 EUR (rate = base units per 1 unit of foreign).
    project_id = await _seed_project(
        session,
        currency="EUR",
        fx_rates=[{"code": "USD", "rate": "0.90", "label": "US Dollar"}],
    )
    svc = FinanceService(session)

    items = [InvoiceLineItemCreate(description="Imported steel", amount="1000.00", cost_category="material")]
    await _make_and_pay_invoice(svc, project_id, currency="USD", items=items, subtotal="1000.00")

    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    # 1000 USD * 0.90 = 900 EUR.
    assert Decimal(lines[0].actual_amount) == Decimal("900.00")
    assert lines[0].currency == "EUR"
    # Original currency recorded for audit in the posting trail.
    assert lines[0].metadata_["postings"][0]["currency"] == "USD"


# ── Case 16: missing FX rate is NOT zeroed ────────────────────────────────────


async def test_pay_invoice_missing_fx_rate_not_zeroed(session: AsyncSession) -> None:
    # Base EUR, no JPY rate configured.
    project_id = await _seed_project(session, currency="EUR", fx_rates=[])
    svc = FinanceService(session)

    items = [InvoiceLineItemCreate(description="Tooling", amount="100000.00", cost_category="equipment")]
    await _make_and_pay_invoice(svc, project_id, currency="JPY", items=items, subtotal="100000.00")

    lines = await _budget_lines(session, project_id)
    assert len(lines) == 1
    # No rate → value kept in its own units (NEVER zeroed), so the bad figure
    # surfaces visibly instead of silently dropping money.
    assert Decimal(lines[0].actual_amount) == Decimal("100000.00")


# ── Case 17: spine failure is non-fatal ───────────────────────────────────────


async def test_pay_invoice_spine_failure_nonfatal(session: AsyncSession, monkeypatch) -> None:
    project_id = await _seed_project(session)
    svc = FinanceService(session)

    async def _boom(self, project_id) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("spine exploded")

    monkeypatch.setattr(FinanceService, "_post_paid_invoices_to_spine", _boom)

    items = [InvoiceLineItemCreate(description="Concrete", amount="1000.00", cost_category="material")]
    create = InvoiceCreate(
        project_id=project_id,
        invoice_direction="payable",
        currency_code="EUR",
        amount_subtotal="1000.00",
        tax_amount="0",
        line_items=items,
    )
    invoice = await svc.create_invoice(create)
    await svc.approve_invoice(invoice.id)
    paid = await svc.pay_invoice(invoice.id)

    # Payment still succeeded despite the spine blowing up.
    assert paid.status == "paid"
    # And no spine rows were written (the failure was swallowed).
    assert await _budget_lines(session, project_id) == []


# ── Case 18: both budget tables updated ───────────────────────────────────────


async def test_pay_invoice_both_tables_updated(session: AsyncSession) -> None:
    project_id = await _seed_project(session)
    svc = FinanceService(session)

    # Seed a legacy ProjectBudget row so the BUG-346 bucketing has a target.
    budget = ProjectBudget(
        project_id=project_id,
        wbs_id=None,
        category="material",
        currency_code="EUR",
        original_budget=Decimal("5000"),
        revised_budget=Decimal("5000"),
    )
    session.add(budget)
    await session.flush()
    budget_id = budget.id

    items = [InvoiceLineItemCreate(description="Concrete", amount="1000.00", cost_category="material")]
    await _make_and_pay_invoice(svc, project_id, items=items, subtotal="1000.00")

    # Legacy ProjectBudget.actual got the bucketed amount.
    refreshed = await session.get(ProjectBudget, budget_id)
    assert refreshed is not None
    assert Decimal(str(refreshed.actual)) == Decimal("1000.00")

    # New BudgetLine spine row also carries the actual.
    lines = await _budget_lines(session, project_id)
    by_cat = {bl.category: Decimal(bl.actual_amount) for bl in lines}
    assert by_cat.get("material") == Decimal("1000.00")
