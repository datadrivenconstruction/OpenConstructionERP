# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Issue #514 tails: the procurement and finance PDFs.

Their strings used to sit in Python dictionaries with English, German and
Russian only, so every other language printed English. They now come from the
backend locale files, so a language joins the moment its file translates the
form, with English for any key it has not translated yet. The header also
prints the counterparty's tax id and address when the contact carries them.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import document_forms_i18n
from app.core.document_forms_i18n import document_form_catalogue, load_document_forms
from app.core.party_names import PartyDetails, format_party_address, party_detail_pairs
from app.core.register_export import record_text_lines
from app.modules.finance.pdf_export import invoice_record, payment_record
from app.modules.procurement.pdf_export import goods_receipt_record, purchase_order_record
from tests.unit import _record_pdf_samples as samples

FORMS = ("procurement", "finance")


# ── The catalogue comes from the locale files ────────────────────────────


@pytest.mark.parametrize("form", FORMS)
def test_english_german_and_russian_still_print_from_the_locale_files(form: str) -> None:
    catalogue = document_form_catalogue(form)
    assert {"en", "de", "ru"} <= set(catalogue.supported)
    title = "invoice_title" if form == "finance" else "po_title"
    assert catalogue.tr("en", title) != catalogue.tr("de", title) != catalogue.tr("ru", title)


@pytest.mark.parametrize("form", FORMS)
def test_every_english_string_is_in_en_json(form: str) -> None:
    strings = load_document_forms("en")[form]["strings"]
    assert "counterparty_tax_id" in strings
    assert "counterparty_address" in strings
    assert all(isinstance(value, str) and value.strip() for value in strings.values())


@pytest.fixture
def french_partly_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    """A French file that translates two finance strings, one label and one furniture caption."""
    real = load_document_forms

    def fake(code: str) -> dict[str, Any]:
        if code == "fr":
            return {
                "furniture": {"signature": "Signature (fr)", "date_format": "%d/%m/%Y"},
                "finance": {
                    "strings": {"invoice_title": "Facture", "supplier": "Fournisseur"},
                    "labels": {"direction": {"payable": "Facture fournisseur"}},
                },
            }
        return real(code)

    monkeypatch.setattr(document_forms_i18n, "load_document_forms", fake)


@pytest.mark.usefixtures("french_partly_translated")
def test_a_language_joins_once_its_file_translates_the_form() -> None:
    catalogue = document_form_catalogue("finance")
    assert "fr" in catalogue.supported
    assert catalogue.normalize("fr-FR") == "fr"
    assert catalogue.tr("fr", "invoice_title") == "Facture"
    assert catalogue.tr("fr", "supplier") == "Fournisseur"
    # Not translated yet: English, never the raw key.
    assert catalogue.tr("fr", "due_date") == catalogue.tr("en", "due_date")
    assert catalogue.label("direction", "payable", "fr") == "Facture fournisseur"
    assert catalogue.label("direction", "receivable", "fr") == catalogue.label("direction", "receivable", "en")
    assert catalogue.tr("fr", "signature") == "Signature (fr)"
    assert catalogue.tr("fr", "footer_page", page=1, total=2) == "Page 1 of 2"
    # A date pattern is not translated text: the file cannot change it.
    assert catalogue.tr("fr", "date_format") == catalogue.tr("en", "date_format")


@pytest.mark.usefixtures("french_partly_translated")
def test_a_form_the_file_does_not_translate_stays_english() -> None:
    catalogue = document_form_catalogue("procurement")
    assert "fr" not in catalogue.supported
    assert catalogue.normalize("fr") == "en"


@pytest.mark.parametrize("form", FORMS)
def test_an_untranslated_language_prints_english_and_says_so(form: str) -> None:
    catalogue = document_form_catalogue(form)
    untranslated = [code for code in ("es", "it", "pl", "ja") if not load_document_forms(code).get(form)]
    for code in untranslated:
        assert catalogue.normalize(code) == "en"


# ── The counterparty's tax id and address ────────────────────────────────

DETAILS = {samples.VENDOR_ID: PartyDetails(tax_id="DE123456789", address="Hafenstr. 1, 20457 Hamburg, DE")}


def _record(doc_type: str, *, parties: Any, locale: str = "en") -> Any:
    context = {"project": samples.PROJECT, "people": samples.PEOPLE, "parties": parties, "locale": locale}
    if doc_type == "purchase_order":
        return purchase_order_record(samples.purchase_order(), **context)
    if doc_type == "goods_receipt":
        return goods_receipt_record(samples.goods_receipt(), po=samples.purchase_order(), **context)
    if doc_type == "invoice":
        return invoice_record(samples.invoice(), **context)
    return payment_record(samples.payment(), invoice=samples.invoice(), **context)


@pytest.mark.parametrize("doc_type", ["purchase_order", "goods_receipt", "invoice", "payment"])
def test_the_header_names_the_counterpartys_tax_id_and_address(doc_type: str) -> None:
    lines = record_text_lines(_record(doc_type, parties=DETAILS))
    assert "Tax ID" in lines
    assert "DE123456789" in lines
    assert "Address" in lines
    assert "Hafenstr. 1, 20457 Hamburg, DE" in lines


@pytest.mark.parametrize("doc_type", ["purchase_order", "invoice"])
def test_the_captions_follow_the_document_language(doc_type: str) -> None:
    lines = record_text_lines(_record(doc_type, parties=DETAILS, locale="de"))
    assert "Anschrift" in lines
    assert "DE123456789" in lines


@pytest.mark.parametrize("doc_type", ["purchase_order", "invoice"])
def test_no_details_no_rows(doc_type: str) -> None:
    lines = record_text_lines(_record(doc_type, parties=None))
    assert "Tax ID" not in lines
    assert "Address" not in lines


def test_only_the_parts_that_exist_print() -> None:
    only_tax = {samples.VENDOR_ID: PartyDetails(tax_id="DE1", address="")}
    assert party_detail_pairs(samples.VENDOR_ID, only_tax, "Tax", "Addr") == [("Tax", "DE1")]
    assert party_detail_pairs(None, only_tax, "Tax", "Addr") == []
    assert party_detail_pairs("someone-else", only_tax, "Tax", "Addr") == []


@pytest.mark.parametrize(
    ("address", "country", "expected"),
    [
        ({"street": "Hafenstr. 1", "postcode": "20457", "city": "Hamburg"}, "de", "Hafenstr. 1, 20457 Hamburg, DE"),
        ({"line1": "1 Main St", "zip": "10001", "city": "New York"}, None, "1 Main St, 10001 New York"),
        ({"text": "Somewhere 5"}, "", "Somewhere 5"),
        (None, "FR", ""),
        ("not a dict", None, ""),
    ],
)
def test_format_party_address(address: Any, country: str | None, expected: str) -> None:
    assert format_party_address(address, country) == expected
