"""The RFQ editor's server side: header, scope lines and invitees can all be changed.

The editor offers three writes: the header, the scope lines (draft only) and the
list of contacts the RFQ goes to. Invitees stay editable after the RFQ is out so
a late invitation can be added; lines and the quoted basis do not.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.rfq_bidding.schemas import RFQLineCreate, RFQLineUpdate, RFQUpdate
from tests.modules.rfq_bidding.test_service_logic import _line, _rfq, _service


async def test_header_is_edited_on_a_draft() -> None:
    rfq = _rfq(status="draft")
    service = _service(rfq)
    out = await service.update_rfq(
        rfq.id, RFQUpdate(title="Mechanical fit-out, phase 2", description="New text", submission_deadline="2027-01-31")
    )
    assert out.title == "Mechanical fit-out, phase 2"
    assert out.description == "New text"
    assert out.submission_deadline == "2027-01-31"


async def test_invitees_are_picked_on_a_draft() -> None:
    rfq = _rfq(status="draft", issued_to_contacts=[])
    service = _service(rfq)
    out = await service.update_rfq(rfq.id, RFQUpdate(issued_to_contacts=["c-1", "c-2"]))
    assert out.issued_to_contacts == ["c-1", "c-2"]


async def test_invitees_can_still_be_added_after_the_rfq_is_out() -> None:
    rfq = _rfq(status="published", issued_to_contacts=["c-1"])
    service = _service(rfq)
    out = await service.update_rfq(rfq.id, RFQUpdate(issued_to_contacts=["c-1", "c-3"]))
    assert out.issued_to_contacts == ["c-1", "c-3"]


async def test_a_scope_line_is_added_edited_and_removed_on_a_draft() -> None:
    rfq = _rfq(status="draft")
    service = _service(rfq)

    added = await service.add_line(rfq.id, RFQLineCreate(description="Ductwork", unit="m2", quantity="10"))
    assert added.line_no == 1
    assert added.quantity == Decimal("10")

    edited = await service.update_line(rfq.id, added.id, RFQLineUpdate(description="Ductwork, L1", quantity="12.5"))
    assert edited.description == "Ductwork, L1"
    assert edited.quantity == Decimal("12.5")

    await service.delete_line(rfq.id, added.id)
    assert rfq.lines == []


async def test_a_line_of_another_rfq_is_not_reachable() -> None:
    rfq = _rfq(status="draft")
    other = _rfq(status="draft")
    line = _line(other)
    rfq.lines.append(line)
    service = _service(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.update_line(rfq.id, line.id, RFQLineUpdate(description="x"))
    assert exc.value.status_code == 404


@pytest.mark.parametrize("rfq_status", ["published", "bids_received", "awarded"])
async def test_lines_are_frozen_once_the_rfq_is_out(rfq_status: str) -> None:
    rfq = _rfq(status=rfq_status)
    line = _line(rfq)
    rfq.lines.append(line)
    service = _service(rfq)
    with pytest.raises(HTTPException) as exc:
        await service.update_line(rfq.id, line.id, RFQLineUpdate(description="x"))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await service.delete_line(rfq.id, line.id)
    assert exc.value.status_code == 409
