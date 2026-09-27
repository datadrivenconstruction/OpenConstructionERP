# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The country VAT fills an unrated invoice line only when it matches the stated tax.

An invoice saved with a tax of 0 and lines without a rate had those lines
filled with the country's standard rate, so the header said 0 and the lines
said 25%. The default now applies only when it reproduces the header tax.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.finance.schemas import InvoiceLineItemCreate
from app.modules.finance.service import _default_vat_matching_tax


def _line(amount: str, vat_rate: str | None = None) -> InvoiceLineItemCreate:
    return InvoiceLineItemCreate(description="Works", amount=amount, vat_rate=vat_rate)


def test_default_applies_when_it_reproduces_the_tax() -> None:
    lines = [_line("600.00"), _line("400.00")]
    assert _default_vat_matching_tax(lines, "250.00", Decimal("25")) == Decimal("25")


def test_default_is_withheld_when_the_invoice_states_no_vat() -> None:
    assert _default_vat_matching_tax([_line("1000.00")], "0.00", Decimal("25")) is None


def test_default_is_withheld_when_the_tax_was_charged_at_another_rate() -> None:
    lines = [_line("100.00", "13"), _line("200.00")]
    # 13.00 on the rated line plus 26.00 at 13% on the rest: not 25%.
    assert _default_vat_matching_tax(lines, "39.00", Decimal("25")) is None
    assert _default_vat_matching_tax(lines, "63.00", Decimal("25")) == Decimal("25")


def test_an_unstated_tax_takes_the_default() -> None:
    assert _default_vat_matching_tax([_line("100.00")], None, Decimal("19")) == Decimal("19")
