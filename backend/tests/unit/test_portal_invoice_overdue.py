# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A client sees which of their invoices are overdue, and only those they owe.

``Invoice.due_date`` is text. The finance dashboard learned that a blank due
date compares lexically below any date and showed phantom overdues; the
portal must not repeat that. Nor may it call an invoice overdue that owes
nothing: paid, cancelled, reversed by a credit note, or not yet sent.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.portal.router import _days_overdue

TODAY = date(2026, 10, 5)


@pytest.mark.parametrize(
    ("due", "status", "expected"),
    [
        ("2026-09-25", "sent", 10),
        ("2026-10-04T00:00:00", "approved", 1),
        ("2026-10-05", "sent", None),
        ("2026-10-20", "sent", None),
        ("2026-09-01", "paid", None),
        ("2026-09-01", "cancelled", None),
        ("2026-09-01", "credit_note_issued", None),
        ("2026-09-01", "pending", None),
        ("2026-09-01", None, None),
        ("", "sent", None),
        (None, "sent", None),
        ("next week", "sent", None),
    ],
)
def test_only_an_owed_invoice_can_be_overdue(due, status, expected):
    assert _days_overdue(due, status, TODAY) == expected
