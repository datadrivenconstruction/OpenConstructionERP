# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A purchase order may allow its invoices a stated overrun before warning.

Freight, rounding on a weighed delivery, a price index clause: a supplier's
invoice often lands a little above the order, and a buyer who has agreed to
that does not want a warning on every invoice. The order carries the allowance
as a percentage, an amount, or both. Both set means the invoice must stay
within both, so the smaller band wins. Neither set means exactly the behaviour
every order had before: a one-cent rounding band and nothing more.

Pure-Python, no database.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.procurement import validators as po_checks
from app.modules.procurement.schemas import POCreate, POUpdate


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "po_number": "PO-0042",
        "currency_code": "EUR",
        "po_net": "10000.00",
        "invoiced_before_net": "0",
        "invoice_net": "10150.00",
        "invoice_ref": "R-77",
        "has_receipts": False,
        "received_net": "0",
        "lines": [],
    }
    payload.update(overrides)
    return payload


def test_without_an_allowance_a_small_overrun_still_warns() -> None:
    assert len(po_checks.check_invoice_within_order(_payload())) == 1


def test_a_percentage_allowance_absorbs_an_overrun_inside_it() -> None:
    assert po_checks.check_invoice_within_order(_payload(invoice_tolerance_pct="2")) == []


def test_an_overrun_past_the_percentage_warns_and_names_the_band() -> None:
    findings = po_checks.check_invoice_within_order(_payload(invoice_net="10250.00", invoice_tolerance_pct="2"))
    assert len(findings) == 1
    assert findings[0].details["tolerance_net"] == "200.00"


def test_an_amount_allowance_works_alone() -> None:
    assert po_checks.check_invoice_within_order(_payload(invoice_tolerance_abs="150")) == []
    assert len(po_checks.check_invoice_within_order(_payload(invoice_tolerance_abs="149.99"))) == 1


def test_with_both_set_the_smaller_band_wins() -> None:
    # 2% of 10 000 is 200, the amount cap is 100: an overrun of 150 is past it.
    findings = po_checks.check_invoice_within_order(_payload(invoice_tolerance_pct="2", invoice_tolerance_abs="100"))
    assert len(findings) == 1
    assert findings[0].details["tolerance_net"] == "100.00"


def test_the_value_received_check_measures_the_band_on_what_arrived() -> None:
    received = _payload(has_receipts=True, received_net="5000.00", invoice_net="5080.00", invoice_tolerance_pct="2")
    assert po_checks.check_invoice_value_received(received) == []
    assert len(po_checks.check_invoice_value_received({**received, "invoice_net": "5101.00"})) == 1


def test_an_unreadable_allowance_is_ignored_not_widened() -> None:
    assert len(po_checks.check_invoice_within_order(_payload(invoice_tolerance_pct="lots"))) == 1


@pytest.mark.parametrize("pct", ["-1", "100.01", "abc"])
def test_the_order_refuses_a_percentage_outside_0_to_100(pct: str) -> None:
    with pytest.raises(ValueError):
        POUpdate(invoice_tolerance_pct=pct)


def test_the_order_refuses_a_negative_amount() -> None:
    with pytest.raises(ValueError):
        POCreate(project_id="00000000-0000-4000-8000-000000000001", invoice_tolerance_abs="-5")
