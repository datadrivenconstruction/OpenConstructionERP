# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The invoice and the payment record print exactly what they printed before the block engine.

The digests in ``golden_finance_forms.json`` were taken from the hand-written record
forms before they moved onto document layouts; every case now renders through the
engine's standard template. Regenerate only on an intended change of the printed form:
``python -m tests.modules.doc_templates.test_layout_golden_finance``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.party_names import PartyDetails
from tests.modules.doc_templates._golden import digest, regenerate
from tests.unit import _record_pdf_samples as samples

GOLDEN = Path(__file__).with_name("golden_finance_forms.json")
_GENERATED = "2026-11-18 09:30 UTC"
_PARTIES = {samples.VENDOR_ID: PartyDetails(tax_id="DE811111111", address="Hafenweg 3\n20457 Hamburg")}
_INVOICE_SECTIONS = ("line_items", "totals", "payments", "notes", "signatures")
_PAYMENT_SECTIONS = ("invoice", "withholding", "signatures")
_LOCALES = ("en", "de", "ru", "ar", "fr", "tr", "zh", "es")


def _cases() -> Iterator[tuple[str, Callable[[], Any]]]:
    from app.modules.finance.pdf_export import invoice_record, payment_record

    def inv(locale: str = "en", sections: Any = None, parties: Any = None, po: Any = None, **over: Any) -> Any:
        return lambda: invoice_record(
            samples.invoice(**over),
            project=samples.PROJECT,
            people=samples.PEOPLE,
            parties=parties,
            purchase_order_number=po,
            sections=sections,
            locale=locale,
            generated=_GENERATED,
        )

    def pay(locale: str = "en", sections: Any = None, parties: Any = None, inv_over: Any = None, **over: Any) -> Any:
        return lambda: payment_record(
            samples.payment(**over),
            invoice=samples.invoice(**(inv_over or {})),
            project=samples.PROJECT,
            people=samples.PEOPLE,
            parties=parties,
            sections=sections,
            locale=locale,
            generated=_GENERATED,
        )

    for locale in _LOCALES:
        yield f"inv-{locale}", inv(locale)
        yield f"inv-{locale}-parties", inv(locale, parties=_PARTIES, po="PO-0042")
        yield f"inv-{locale}-receivable", inv(locale, invoice_direction="receivable")
        yield f"pay-{locale}", pay(locale)
        yield f"pay-{locale}-parties", pay(locale, parties=_PARTIES)
    for section in _INVOICE_SECTIONS:
        yield f"inv-hide-{section}", inv(sections={s: s != section for s in _INVOICE_SECTIONS})
    for section in _PAYMENT_SECTIONS:
        yield f"pay-hide-{section}", pay(sections={s: s != section for s in _PAYMENT_SECTIONS})
    no_vat = SimpleNamespace(**{**vars(samples.invoice().line_items[0]), "vat_rate": None})
    yield "inv-no-vat-column", inv(line_items=[no_vat])
    yield "inv-no-items", inv(line_items=[])
    yield "inv-no-retention", inv(retention_amount=Decimal("0"))
    yield "inv-retention-none", inv(retention_amount=None)
    yield "inv-retention-no-total", inv(amount_total=None)
    yield "inv-no-payments", inv(payments=[])
    yield "inv-refund-payment", inv(payments=[samples.payment(is_refund=True, reference="")])
    yield "inv-no-notes", inv(notes="")
    yield "inv-no-terms", inv(payment_terms_days=None)
    yield "inv-no-currency", inv(currency_code=None)
    yield "inv-unknown-contact", inv(contact_id=None, created_by=None)
    yield "inv-draft-status", inv(status=None)
    yield "pay-refund", pay(is_refund=True)
    yield "pay-no-withholding", pay(withholding_amount=Decimal("0"))
    yield "pay-withholding-none", pay(withholding_amount=None, amount=None)
    yield "pay-fx-rate", pay(exchange_rate_snapshot=Decimal("1.0823"), currency_code="USD")
    yield "pay-no-reference", pay(reference="")
    yield "pay-unknown-contact", pay(inv_over={"contact_id": None, "invoice_number": ""})


def test_every_golden_case_is_still_generated() -> None:
    stored = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(stored) == {name for name, _ in _cases()}


@pytest.mark.parametrize(("name", "build"), list(_cases()), ids=[name for name, _ in _cases()])
def test_the_standard_template_prints_the_form_it_printed_before(name: str, build: Callable[[], Any]) -> None:
    stored = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert digest(build()) == stored[name], f"{name}: the printed form changed"


if __name__ == "__main__":  # pragma: no cover - regeneration helper
    regenerate(GOLDEN, _cases())
