# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The supplier card says whether the supplier is still qualified to buy from.

Performance alone (on time, in full) does not tell a buyer the supplier's
prequalification ran out last month. The card now carries the contact's
prequalification and its end date, the same compliance reasons the order gate
already reads from the linked subcontractor, and how many issued orders still
wait for the supplier's confirmation. Nothing here is a second rating: the
reasons come from the one gate the order write path uses.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.asyncio


async def _seed(pg_session, *, qualified_until: str | None, status: str | None):
    from app.modules.contacts.models import Contact
    from app.modules.procurement.models import PurchaseOrder
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"kyc-{uuid.uuid4().hex[:8]}@site.example",
        hashed_password="x",
        full_name="Buyer",
    )
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(id=uuid.uuid4(), name="Supplier card", owner_id=owner.id, currency="EUR")
    contact = Contact(
        id=uuid.uuid4(),
        contact_type="supplier",
        company_name="Ready Mix Ltd",
        prequalification_status=status,
        qualified_until=qualified_until,
    )
    pg_session.add_all([project, contact])
    await pg_session.flush()
    for n, (po_status, acknowledged) in enumerate(
        [("issued", None), ("issued", "2026-10-01T09:00:00+00:00"), ("partially_received", None), ("draft", None)]
    ):
        pg_session.add(
            PurchaseOrder(
                id=uuid.uuid4(),
                project_id=project.id,
                vendor_contact_id=str(contact.id),
                po_number=f"PO-K-{n}-{uuid.uuid4().hex[:4]}",
                currency_code="EUR",
                amount_subtotal="100.00",
                amount_total="100.00",
                status=po_status,
                supplier_acknowledged_at=acknowledged,
            )
        )
    await pg_session.flush()
    return project.id, str(contact.id)


async def test_a_lapsed_qualification_is_named_with_its_date(pg_session) -> None:
    from app.modules.procurement.service import ProcurementService

    lapsed = (date.today() - timedelta(days=3)).isoformat()
    project_id, contact_id = await _seed(pg_session, qualified_until=lapsed, status="approved")

    card = await ProcurementService(pg_session).supplier_compliance(contact_id, project_id=project_id)

    assert card["prequalification_status"] == "approved"
    assert card["qualified_until"] == lapsed
    assert card["qualification_state"] == "expired"
    assert card["unconfirmed_po_count"] == 2, "issued and partially received, not yet confirmed; drafts never left"


async def test_a_qualification_ending_within_thirty_days_is_flagged_early(pg_session) -> None:
    from app.modules.procurement.service import ProcurementService

    soon = (date.today() + timedelta(days=10)).isoformat()
    project_id, contact_id = await _seed(pg_session, qualified_until=soon, status="approved")

    card = await ProcurementService(pg_session).supplier_compliance(contact_id, project_id=project_id)

    assert card["qualification_state"] == "expiring"


async def test_no_date_means_not_stated_rather_than_valid(pg_session) -> None:
    from app.modules.procurement.service import ProcurementService

    project_id, contact_id = await _seed(pg_session, qualified_until=None, status=None)

    card = await ProcurementService(pg_session).supplier_compliance(contact_id, project_id=project_id)

    assert card["qualification_state"] == "not_stated"
    assert card["compliance_reasons"] == [], "no linked subcontractor: the order gate has nothing to say either"


async def test_an_unknown_supplier_answers_empty_not_500(pg_session) -> None:
    from app.modules.procurement.service import ProcurementService

    card = await ProcurementService(pg_session).supplier_compliance("not-a-uuid", project_id=None)

    assert card["qualification_state"] == "not_stated"
    assert card["unconfirmed_po_count"] == 0
