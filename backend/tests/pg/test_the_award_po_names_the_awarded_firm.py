# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the purchase order drafted from a tender award names the awarded firm.

The order had no vendor, although the bidder was invited from the directory
and the contract drafted from the same award names the firm.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.contacts.models import Contact
from app.modules.procurement import events as proc_events
from app.modules.procurement.models import PurchaseOrder
from app.modules.subcontractors.models import Subcontractor
from app.modules.tendering.service import TenderingService
from tests.pg.tender_award_fixtures import _bid, _bill, _NonCommittingSession, _package, _project

pytestmark = pytest.mark.asyncio


async def test_the_award_po_names_the_directory_firm(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, [("wall", "01", "Wall", "m3", None)])
    contact = Contact(contact_type="subcontractor", company_name="Rheinbeton GmbH")
    pg_session.add(contact)
    await pg_session.flush()
    sub = Subcontractor(legal_name="Rheinbeton GmbH", contact_id=contact.id)
    pg_session.add(sub)
    await pg_session.flush()
    package = await _package(
        pg_session,
        project,
        boq,
        metadata={"recipients": [{"email": "Bids@Rheinbeton.test", "subcontractor_id": str(sub.id)}]},
    )
    bid = await _bid(
        pg_session, package, "Rheinbeton", "700", [{"position_id": str(pos["wall"].id), "unit_rate": "70"}]
    )
    await TenderingService(pg_session).apply_winner(package.id, bid.id)

    monkeypatch.setattr(proc_events, "async_session_factory", lambda: _NonCommittingSession(pg_session))
    await proc_events._create_po_from_award(
        proc_events.Event(
            name="tendering.package.awarded",
            data={"package_id": str(package.id), "bid_id": str(bid.id)},
            source_module="oe_tendering",
        )
    )

    [po] = (await pg_session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id))).scalars()
    assert po.vendor_contact_id == str(contact.id)
