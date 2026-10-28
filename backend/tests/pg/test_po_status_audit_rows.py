"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Purchase-order FSM transitions must leave an ActivityLog row (PG lane only).

The same defect the invoice tests next door cover, in two more places and with a
worse failure mode. ``approve_po`` and ``issue_po`` read ``po.po_number`` for
the audit metadata AFTER ``PORepository.update``, which ends in
``session.expire_all()``. Reading an expired attribute on the async session
re-issues a sync SELECT and raises ``MissingGreenlet``. The audit call is
wrapped in a ``try/except`` so the status change survives, and the except arm
logged at DEBUG, which is below the production root level of INFO. Every PO
approved and every PO issued therefore lost its compliance row leaving nothing
at all behind, not even a warning.

The linter cannot help here: ``F841`` (local assigned but never used) is in this
repository's ruff ignore list, so a snapshot taken and then not used is silent.
The invoice fix was itself half-applied for exactly that reason - the local was
added, the read below it was left alone, and both ruff and a reviewer signed it
off. A test that asserts on the persisted row is the only thing that notices.

These assert on the row rather than on log output, so they cannot pass because
somebody reworded a message and cannot keep passing if the row is written with
the wrong contents.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _seed_po(pg_session, *, status: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Insert an owner, a project and one purchase order in *status*.

    The PO carries a vendor, a coded line item and arithmetically consistent
    totals, because ``approve_po`` runs the ``procurement`` rule set first and
    an ERROR finding raises 422 before the code under test is ever reached.

    Returns:
        ``(owner_id, po_id, po_number)``.
    """
    from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"pg-po-{uuid.uuid4().hex[:8]}@procurement-audit.io",
        hashed_password="x",
        full_name="PG PO Owner",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()

    project = Project(
        id=uuid.uuid4(),
        name="PG PO Audit",
        owner_id=owner.id,
        currency="EUR",
    )
    pg_session.add(project)
    await pg_session.flush()

    po_number = f"PO-R-{uuid.uuid4().hex[:6].upper()}"
    po = PurchaseOrder(
        id=uuid.uuid4(),
        project_id=project.id,
        vendor_contact_id=str(uuid.uuid4()),
        po_number=po_number,
        po_type="standard",
        issue_date="2026-07-27",
        delivery_date="2026-08-31",
        currency_code="EUR",
        amount_subtotal="1000.00",
        tax_amount="0.00",
        amount_total="1000.00",
        status=status,
    )
    pg_session.add(po)
    await pg_session.flush()

    pg_session.add(
        PurchaseOrderItem(
            id=uuid.uuid4(),
            po_id=po.id,
            description="Ready-mix concrete C30/37",
            quantity="10",
            unit="m3",
            unit_rate="100.00",
            amount="1000.00",
        )
    )
    await pg_session.flush()
    return owner.id, po.id, po_number


async def _audit_rows(pg_session, po_id: uuid.UUID) -> list:
    """Read the activity-log rows for one PO with a real SELECT.

    ``session.get()`` answers from the identity map without touching SQL, which
    would let a row that was never written look present. Expire first, then go
    to the database.
    """
    from sqlalchemy import select

    from app.core.audit_log import ActivityLog

    pg_session.expire_all()
    result = await pg_session.execute(
        select(ActivityLog)
        .where(ActivityLog.entity_type == "purchase_order")
        .where(ActivityLog.entity_id == str(po_id))
        .order_by(ActivityLog.created_at)
    )
    return list(result.scalars().all())


# ── approve_po ──────────────────────────────────────────────────────────────


async def test_approve_po_writes_its_audit_row(pg_session) -> None:
    """draft -> approved leaves one status_changed row carrying the PO number."""
    from app.modules.procurement.service import ProcurementService

    _owner_id, po_id, po_number = await _seed_po(pg_session, status="draft")

    service = ProcurementService(pg_session)
    updated = await service.approve_po(po_id)
    assert updated.status == "approved"

    rows = await _audit_rows(pg_session, po_id)
    assert len(rows) == 1, "approve_po must leave exactly one audit row"
    row = rows[0]
    assert row.action == "status_changed"
    assert row.from_status == "draft"
    assert row.to_status == "approved"
    # The metadata read is the part that broke: the only place in the method
    # that touches the expired instance.
    assert row.metadata_["po_number"] == po_number


# ── issue_po ────────────────────────────────────────────────────────────────


async def test_issue_po_writes_its_audit_row(pg_session) -> None:
    """approved -> issued leaves one status_changed row carrying the PO number.

    Seeded straight at ``approved`` rather than approved first, so a regression
    in ``approve_po`` cannot fail this test for somebody else's reason.
    """
    from app.modules.procurement.service import ProcurementService

    _owner_id, po_id, po_number = await _seed_po(pg_session, status="approved")

    service = ProcurementService(pg_session)
    updated = await service.issue_po(po_id)
    assert updated.status == "issued"

    rows = await _audit_rows(pg_session, po_id)
    assert len(rows) == 1, "issue_po must leave exactly one audit row"
    row = rows[0]
    assert row.action == "status_changed"
    assert row.from_status == "approved"
    assert row.to_status == "issued"
    assert row.metadata_["po_number"] == po_number
