"""Invoice FSM transitions must leave an ActivityLog row (PG lane only).

``approve_invoice`` and ``pay_invoice`` write their audit row through
``log_activity`` inside a ``try/except`` that downgrades any failure to a
warning, so a broken audit call does not roll the status change back. That
guard also means a broken audit call is invisible to any test that only
checks the returned invoice: the status flips, the caller sees success, and
the compliance trail silently loses a row.

The specific way it broke: ``InvoiceRepository.update`` ends in
``session.expire_all()``, so every instance in the session - including the
``invoice`` the method is holding - is expired. Reading ``invoice.invoice_number``
for the audit metadata is then a lazy load, and a lazy load in async code with
no greenlet around it raises ``MissingGreenlet``. Everything else in those two
methods that touches ``invoice`` runs after a re-``get`` which reloads the row,
so the audit call was the only casualty.

These tests assert on the persisted row rather than on log output. Grepping the
warning would pass for the wrong reason the day someone rewords the message, and
would keep passing if the row were written with the wrong contents.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _seed_invoice(pg_session, *, status: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Insert an owner, a project and one invoice in *status*.

    Args:
        pg_session: The savepoint-isolated session fixture.
        status: Starting invoice status, so each test can enter the FSM at the
            node it is exercising instead of chaining through the one before it.

    Returns:
        ``(actor_id, invoice_id, invoice_number)``.
    """
    from app.modules.finance.models import Invoice
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"pg-audit-{uuid.uuid4().hex[:8]}@finance-audit.io",
        hashed_password="x",
        full_name="PG Audit Owner",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()

    project = Project(
        id=uuid.uuid4(),
        name="PG Invoice Audit",
        owner_id=owner.id,
        currency="EUR",
    )
    pg_session.add(project)
    await pg_session.flush()

    invoice_number = f"INV-R-{uuid.uuid4().hex[:6].upper()}"
    invoice = Invoice(
        id=uuid.uuid4(),
        project_id=project.id,
        invoice_direction="receivable",
        invoice_number=invoice_number,
        invoice_date="2026-07-27",
        currency_code="EUR",
        amount_subtotal=Decimal("1000.00"),
        amount_total=Decimal("1000.00"),
        status=status,
    )
    pg_session.add(invoice)
    await pg_session.flush()
    return owner.id, invoice.id, invoice_number


async def _audit_rows(pg_session, invoice_id: uuid.UUID) -> list:
    """Read the activity-log rows for one invoice with a real SELECT.

    ``session.get()`` answers from the identity map without touching SQL, which
    would let a row that was never written look present (or a row that was
    written look absent). Expire first, then go to the database.
    """
    from sqlalchemy import select

    from app.core.audit_log import ActivityLog

    pg_session.expire_all()
    result = await pg_session.execute(
        select(ActivityLog)
        .where(ActivityLog.entity_type == "invoice")
        .where(ActivityLog.entity_id == str(invoice_id))
        .order_by(ActivityLog.created_at)
    )
    return list(result.scalars().all())


# ── approve_invoice ─────────────────────────────────────────────────────────


async def test_approve_invoice_writes_its_audit_row(pg_session) -> None:
    """draft -> approved leaves one status_changed row carrying the invoice number."""
    from app.modules.finance.service import FinanceService

    actor_id, invoice_id, invoice_number = await _seed_invoice(pg_session, status="draft")

    service = FinanceService(pg_session)
    updated = await service.approve_invoice(
        invoice_id,
        actor_id=str(actor_id),
        reason="approved by the audit-row test",
    )
    assert updated.status == "approved"

    rows = await _audit_rows(pg_session, invoice_id)
    assert len(rows) == 1, "approve_invoice must leave exactly one audit row"
    row = rows[0]
    assert row.action == "status_changed"
    assert row.from_status == "draft"
    assert row.to_status == "approved"
    assert row.reason == "approved by the audit-row test"
    assert row.actor_id == actor_id
    # The metadata read is the part that broke: it is the only place in the
    # method that touches the expired instance before the re-``get``.
    assert row.metadata_["invoice_number"] == invoice_number


# ── pay_invoice ─────────────────────────────────────────────────────────────


async def test_pay_invoice_writes_its_audit_row(pg_session, no_detached_subscribers) -> None:
    """sent -> paid leaves one status_changed row carrying the invoice number.

    Seeded straight at ``sent`` rather than approved first, so a regression in
    ``approve_invoice`` cannot make this test fail for somebody else's reason.

    ``no_detached_subscribers`` is not decoration. Paying an invoice
    redistributes actuals across the cost spine, which publishes
    ``costmodel.budget_line.actual_posted``, and the overrun-alert subscriber
    on that event opens a session from ``app.database.async_session_factory``.
    This lane does not bind that factory, so the handler fails and its
    half-opened connection takes the rest of the suite down with it. The
    fixture removes the fan-out for the duration; what is under test here is
    the audit row, not the alerting.
    """
    from app.modules.finance.service import FinanceService

    actor_id, invoice_id, invoice_number = await _seed_invoice(pg_session, status="sent")

    service = FinanceService(pg_session)
    updated = await service.pay_invoice(
        invoice_id,
        actor_id=str(actor_id),
        reason="paid by the audit-row test",
    )
    assert updated.status == "paid"

    rows = await _audit_rows(pg_session, invoice_id)
    assert len(rows) == 1, "pay_invoice must leave exactly one audit row"
    row = rows[0]
    assert row.action == "status_changed"
    assert row.from_status == "sent"
    assert row.to_status == "paid"
    assert row.reason == "paid by the audit-row test"
    assert row.actor_id == actor_id
    assert row.metadata_["invoice_number"] == invoice_number
