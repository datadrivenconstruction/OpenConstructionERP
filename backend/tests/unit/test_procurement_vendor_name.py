# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The vendor label on a purchase order, for a contact with only an email.

``Contact`` has no ``email`` column - the column is ``primary_email`` - and the
same display-name rule was written out by hand in several places, two of which
ended their fallback chain on ``c.email``. That branch is reached only when a
contact has neither a company name nor a person name, which is exactly the
shape a vendor imported from a supplier list or created from an inbound invoice
arrives in. The purchase order list endpoint therefore raised AttributeError,
as a 500 over the whole page rather than one unnamed row, for any project with
such a vendor on any of its orders.

The test drives the endpoint rather than the helper underneath it, because the
helper was never the thing that was wrong: the rule it applied was written out
by hand at the call site, and a test of the hand-written copy would have agreed
with it. What follows asserts the label a buyer actually sees.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.procurement import router as procurement_router
from app.modules.procurement.models import PurchaseOrder
from app.modules.procurement.service import ProcurementService
from app.modules.reporting.service import ReportingService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction."""
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _allow_project_access(monkeypatch) -> None:
    """Neutralise the cross-project access gate; it is not what is under test."""

    async def _noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(procurement_router, "verify_project_access", _noop)


async def _list_pos(session: AsyncSession, project_id: uuid.UUID):
    """Call the list endpoint the way FastAPI would, with the query defaults."""
    return await procurement_router.list_purchase_orders(
        user_id="buyer",
        session=session,
        project_id=project_id,
        status=None,
        vendor_contact_id=None,
        offset=0,
        limit=50,
        service=ProcurementService(session),
    )


@pytest.mark.asyncio
async def test_po_list_names_a_vendor_that_has_only_an_email(session: AsyncSession) -> None:
    """A vendor with no company and no person name reads as its email address."""
    vendor = Contact(
        contact_type="vendor",
        company_name=None,
        first_name=None,
        last_name=None,
        primary_email="rechnung@example.de",
    )
    session.add(vendor)
    await session.flush()

    project_id = uuid.uuid4()
    session.add(
        PurchaseOrder(
            project_id=project_id,
            po_number="PO-0001",
            vendor_contact_id=str(vendor.id),
            amount_total="1000.00",
        )
    )
    await session.flush()

    # Before the fix this raised AttributeError: 'Contact' object has no
    # attribute 'email', taking the whole page down rather than one label.
    resp = await _list_pos(session, project_id)

    assert resp.total == 1
    assert resp.items[0].vendor_name == "rechnung@example.de"


@pytest.mark.asyncio
async def test_po_list_prefers_the_company_name_over_the_email(session: AsyncSession) -> None:
    """The email is the last resort, not the label. Guards the fallback order.

    Without this, a fix that returned the email unconditionally would satisfy
    the test above while renaming every vendor in the system.
    """
    vendor = Contact(
        contact_type="vendor",
        company_name="Stadtwerke Kiel",
        first_name="Anna",
        last_name="Schmidt",
        primary_email="rechnung@example.de",
    )
    session.add(vendor)
    await session.flush()

    project_id = uuid.uuid4()
    session.add(
        PurchaseOrder(
            project_id=project_id,
            po_number="PO-0002",
            vendor_contact_id=str(vendor.id),
            amount_total="1000.00",
        )
    )
    await session.flush()

    resp = await _list_pos(session, project_id)

    assert resp.items[0].vendor_name == "Stadtwerke Kiel"


@pytest.mark.asyncio
async def test_po_list_falls_back_to_the_person_when_there_is_no_company(session: AsyncSession) -> None:
    """A sole trader reads as their name, not as their email address."""
    vendor = Contact(
        contact_type="vendor",
        company_name=None,
        first_name="Anna",
        last_name="Schmidt",
        primary_email="rechnung@example.de",
    )
    session.add(vendor)
    await session.flush()

    project_id = uuid.uuid4()
    session.add(
        PurchaseOrder(
            project_id=project_id,
            po_number="PO-0003",
            vendor_contact_id=str(vendor.id),
            amount_total="1000.00",
        )
    )
    await session.flush()

    resp = await _list_pos(session, project_id)

    assert resp.items[0].vendor_name == "Anna Schmidt"


@pytest.mark.asyncio
async def test_retainage_report_names_a_vendor_that_has_only_an_email(session: AsyncSession) -> None:
    """The retainage report resolves the same vendor through the same helper.

    This path already delegated correctly, so this test guards rather than
    fixes. It earns its place because the lookup sits inside a broad handler
    that logs at debug and moves on: if the rule there is ever rewritten by
    hand and breaks, the report does not fail, it silently drops every vendor
    name and reads as a page of blank counterparties. A swallow with no test
    over it is exactly how the other two copies rotted unnoticed.
    """
    vendor = Contact(
        contact_type="vendor",
        company_name=None,
        first_name=None,
        last_name=None,
        primary_email="rechnung@example.de",
    )
    session.add(vendor)
    await session.flush()

    project_id = uuid.uuid4()
    session.add(
        PurchaseOrder(
            project_id=project_id,
            po_number="PO-0004",
            vendor_contact_id=str(vendor.id),
            amount_total="1000.00",
            currency_code="EUR",
            retention_percent=Decimal("5.00"),
            issue_date="2026-03-15",
        )
    )
    await session.flush()

    report = await ReportingService(session).render_po_retainage_reconciliation(project_id, "2026-01-01", "2026-12-31")

    assert len(report["po_rows"]) == 1
    assert report["po_rows"][0]["vendor_name"] == "rechnung@example.de"


@pytest.mark.asyncio
async def test_a_failed_vendor_lookup_is_logged_where_somebody_sees_it(
    session: AsyncSession, monkeypatch, caplog
) -> None:
    """Losing every vendor name on a report must not be a debug-level event.

    The handler wraps the whole lookup, so a throw does not cost one name, it
    costs all of them and the report renders with a blank counterparty on every
    row. At debug that can happen on every run forever and nothing anywhere
    says so: the report looks sparse rather than broken, which is the failure
    nobody reports because it does not look like one.
    """
    from app.modules.finance import einvoice_parties

    def _boom(_contact):
        raise RuntimeError("display helper exploded")

    monkeypatch.setattr(einvoice_parties, "contact_display_name", _boom)

    vendor = Contact(contact_type="vendor", company_name="Stadtwerke Kiel")
    session.add(vendor)
    await session.flush()

    project_id = uuid.uuid4()
    session.add(
        PurchaseOrder(
            project_id=project_id,
            po_number="PO-0005",
            vendor_contact_id=str(vendor.id),
            amount_total="1000.00",
            currency_code="EUR",
            retention_percent=Decimal("5.00"),
            issue_date="2026-03-15",
        )
    )
    await session.flush()

    with caplog.at_level(logging.DEBUG, logger="app.modules.reporting.service"):
        report = await ReportingService(session).render_po_retainage_reconciliation(
            project_id, "2026-01-01", "2026-12-31"
        )

    # The report still renders: the guard is right that this must not 500.
    assert report["po_rows"][0]["vendor_name"] == ""

    complaints = [r for r in caplog.records if "Vendor-name lookup" in r.message]
    assert complaints, "the failure was not logged at all"
    assert complaints[0].levelno >= logging.WARNING, (
        f"logged at {complaints[0].levelname}; losing every vendor name is not a debug-level event"
    )
