"""Tests for ProcurementService._classify_line_match.

The frontend's per-row match badge and the per-line drilldown both rely
on this single helper to collapse three quantities (ordered / received /
invoiced) into a single status tag. Pin the eight regression cases so a
refactor of the precedence rules trips here.

These are pure-function tests — no DB / no fixtures required.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.procurement.service import ProcurementService

D = Decimal


@pytest.mark.parametrize(
    ("ordered", "received", "invoiced", "expected"),
    [
        # Nothing happened yet.
        (D("100"), D("0"), D("0"), "unmatched"),
        # Partial receipt, no invoice yet.
        (D("100"), D("40"), D("0"), "partial"),
        # Receipt complete, invoice complete — clean three-way.
        (D("100"), D("100"), D("100"), "ok"),
        # Over-received (warehouse logged more than ordered).
        (D("100"), D("120"), D("0"), "over_received"),
        # Over-invoiced beats over-received in precedence (most urgent).
        (D("100"), D("120"), D("130"), "over_invoiced"),
        # Invoice > received but received <= ordered → over_invoiced.
        (D("100"), D("50"), D("80"), "over_invoiced"),
        # Received in full but invoice partial → partial (still in flight).
        (D("100"), D("100"), D("40"), "partial"),
        # Edge: zero ordered with positive received — still classified as
        # partial (received > 0, so 'unmatched' is wrong).
        (D("0"), D("10"), D("0"), "partial"),
    ],
)
def test_classify_line_match(
    ordered: Decimal,
    received: Decimal,
    invoiced: Decimal,
    expected: str,
) -> None:
    """Pin the matrix of (ordered, received, invoiced) → status tag."""
    assert ProcurementService._classify_line_match(ordered, received, invoiced) == expected


def test_over_invoiced_outranks_over_received() -> None:
    """Precedence: an over-invoiced line is reported even if it is also
    over-received — overpaying is the more urgent finance concern."""
    tag = ProcurementService._classify_line_match(
        D("100"),
        D("200"),
        D("300"),
    )
    assert tag == "over_invoiced"


def test_zero_invoice_with_positive_receipt_is_partial() -> None:
    """A line that has been received in full but not yet invoiced is
    'partial', not 'ok' — the three-way match is not closed."""
    tag = ProcurementService._classify_line_match(
        D("50"),
        D("50"),
        D("0"),
    )
    assert tag == "partial"
