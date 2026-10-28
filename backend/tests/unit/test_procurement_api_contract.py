# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Wave 5 (API contract) regressions for the procurement schemas.

Pure-schema tests (no Postgres, no FastAPI app) covering the wire contract
tightened in this wave:

* ``POInvoiceCreatedResponse`` keeps ``amount_total`` a Decimal-as-string and
  serialises ids as strings (the endpoint previously returned an untyped dict
  that leaked the ORM ``Decimal`` as a JSON number).
* ``GRListResponse`` / ``PORetainageReleaseListResponse`` echo the
  ``offset`` / ``limit`` pagination window like ``POListResponse`` does, while
  staying backward-compatible when those fields are omitted.
* The 3-way-match status fields accept exactly the closed tag set the service
  emits and reject anything outside it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.procurement.schemas import (
    GRListResponse,
    POInvoiceCreatedResponse,
    POLineMatchStatus,
    POMatchStatusResponse,
    PORetainageReleaseListResponse,
)

# ── POInvoiceCreatedResponse: money stays a string, ids serialise as strings ──


def test_invoice_created_response_coerces_decimal_amount_to_string() -> None:
    """A ``Decimal`` amount_total (straight off the ORM) must render as a string."""
    resp = POInvoiceCreatedResponse(
        invoice_id=uuid.uuid4(),
        invoice_number="INV-PO-0001",
        po_id=uuid.uuid4(),
        po_number="PO-0001",
        amount_total=Decimal("12000.00"),
    )
    assert resp.amount_total == "12000.00"
    assert isinstance(resp.amount_total, str)


def test_invoice_created_response_json_emits_string_money_and_ids() -> None:
    """The JSON wire shape: amount_total is a string, ids are strings (not numbers)."""
    inv_id = uuid.uuid4()
    po_id = uuid.uuid4()
    resp = POInvoiceCreatedResponse(
        invoice_id=inv_id,
        invoice_number="INV-PO-0001",
        po_id=po_id,
        po_number="PO-0001",
        amount_total=Decimal("999.99"),
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["amount_total"] == "999.99"
    assert isinstance(dumped["amount_total"], str)
    # UUIDs serialise to strings on the wire - same shape the old dict produced
    # via str(invoice.id) / str(po_id), so existing consumers are unaffected.
    assert dumped["invoice_id"] == str(inv_id)
    assert dumped["po_id"] == str(po_id)


def test_invoice_created_response_none_amount_defaults_to_zero_string() -> None:
    resp = POInvoiceCreatedResponse(
        invoice_id=uuid.uuid4(),
        invoice_number="INV-X",
        po_id=uuid.uuid4(),
        po_number="PO-X",
        amount_total=None,  # type: ignore[arg-type]
    )
    assert resp.amount_total == "0"


# ── Pagination envelope parity (offset / limit) ──────────────────────────────


def test_gr_list_response_echoes_offset_and_limit() -> None:
    resp = GRListResponse(items=[], total=7, offset=10, limit=25)
    assert resp.offset == 10
    assert resp.limit == 25
    assert resp.total == 7


def test_gr_list_response_offset_limit_are_backward_compatible() -> None:
    """Constructing with only items/total (the old shape) still validates."""
    resp = GRListResponse(items=[], total=0)
    assert resp.offset == 0
    assert resp.limit == 50


def test_retainage_release_list_echoes_offset_and_limit() -> None:
    resp = PORetainageReleaseListResponse(items=[], total=3, offset=5, limit=200)
    assert resp.offset == 5
    assert resp.limit == 200


def test_retainage_release_list_offset_limit_backward_compatible() -> None:
    resp = PORetainageReleaseListResponse(items=[], total=0)
    assert resp.offset == 0
    assert resp.limit == 100


# ── 3-way match status: closed tag set ───────────────────────────────────────


@pytest.mark.parametrize(
    "tag",
    ["ok", "partial", "unmatched", "over_received", "over_invoiced"],
)
def test_line_match_status_accepts_every_valid_tag(tag: str) -> None:
    line = POLineMatchStatus(
        line_id=uuid.uuid4(),
        description="Cement",
        match_status=tag,  # type: ignore[arg-type]
    )
    assert line.match_status == tag


def test_line_match_status_rejects_unknown_tag() -> None:
    with pytest.raises(ValidationError):
        POLineMatchStatus(
            line_id=uuid.uuid4(),
            description="Cement",
            match_status="bogus",  # type: ignore[arg-type]
        )


def test_match_status_envelope_rejects_unknown_overall_status() -> None:
    with pytest.raises(ValidationError):
        POMatchStatusResponse(
            po_id=uuid.uuid4(),
            po_number="PO-0001",
            overall_status="weird",  # type: ignore[arg-type]
        )


def test_match_status_envelope_defaults_to_unmatched() -> None:
    env = POMatchStatusResponse(po_id=uuid.uuid4(), po_number="PO-0001")
    assert env.overall_status == "unmatched"
    assert env.lines == []


# ── Sanity: the constructed match envelope round-trips to JSON ───────────────


def test_match_status_envelope_round_trips() -> None:
    line = POLineMatchStatus(
        line_id=uuid.uuid4(),
        description="Rebar",
        ordered_qty="100",
        received_qty="100",
        invoiced_qty="100",
        match_status="ok",
    )
    env = POMatchStatusResponse(
        po_id=uuid.uuid4(),
        po_number="PO-0002",
        overall_status="ok",
        lines=[line],
    )
    dumped = env.model_dump(mode="json")
    assert dumped["overall_status"] == "ok"
    assert dumped["lines"][0]["match_status"] == "ok"
    # Quantities stay strings on the wire.
    assert dumped["lines"][0]["ordered_qty"] == "100"
