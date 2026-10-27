# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document labels that need no register furniture are read from the locale files.

The bill-of-quantities PDF, the generated reports and the e-invoice page each kept
a table of their own in code. Their labels now sit under
``document_forms.<form>.strings`` (reports also ``labels``) of
``backend/locales/<code>.json``, the same files as every other backend string, and
a language joins once its file translates at least one of them. A key a language
has not translated reads English.

Pure: no database, no event bus.
"""

from __future__ import annotations

import json
import string
from decimal import Decimal

import pytest

from app.core.document_forms_i18n import document_form_locales, form_strings, load_document_forms
from app.core.i18n import LOCALES_DIR, SUPPORTED_LOCALES
from app.modules.boq import pdf_export


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(value) if name}


FORMS = ("boq_pdf", "einvoice_pdf", "report")


def _file_strings(code: str, form: str = "boq_pdf") -> dict[str, str]:
    data = json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
    return data.get("document_forms", {}).get(form, {}).get("strings", {})


def test_the_bill_reads_its_labels_from_the_catalogue_not_from_a_table_of_its_own() -> None:
    assert form_strings("boq_pdf") == pdf_export._PDF_LABELS
    source = (LOCALES_DIR.parent / "app" / "modules" / "boq" / "pdf_export.py").read_text(encoding="utf-8")
    assert '"cost_estimate": "' not in source


@pytest.mark.parametrize("form", FORMS)
def test_english_defines_every_label_and_every_other_language_is_a_subset(form: str) -> None:
    english = _file_strings("en", form)
    assert len(english) >= 20
    for code in SUPPORTED_LOCALES:
        assert set(_file_strings(code, form)) <= set(english), (form, code)


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("code", [c for c in SUPPORTED_LOCALES if c != "en"])
def test_a_translated_label_keeps_the_placeholders_of_the_english_text(code: str, form: str) -> None:
    english = _file_strings("en", form)
    for key, text in _file_strings(code, form).items():
        assert text != "", (code, key)
        assert _placeholders(text) == _placeholders(english[key]), (form, code, key)


def test_reports_and_invoice_pages_read_the_locale_files_and_keep_their_languages() -> None:
    from app.modules.einvoice import pdf_translations as einvoice
    from app.modules.reporting import report_translations as reporting

    assert form_strings("einvoice_pdf") == einvoice._STRINGS
    assert {"en", "de"} <= set(einvoice.SUPPORTED_PDF_LOCALES)
    assert einvoice.tr("de", "doc_title") == "RECHNUNG"
    assert einvoice.tr("ru", "doc_title") == "СЧЁТ"
    assert einvoice.fmt_money(Decimal("1240000"), "EUR", "ru") == "1 240 000,00"
    assert einvoice.fmt_date("2026-04-15", "ru") == "15.04.2026"
    assert form_strings("report") == reporting._STRINGS
    assert {"en", "de", "ru"} <= set(reporting.SUPPORTED_REPORT_LOCALES)
    assert reporting.section_title("Cash Flow", "ru") == "Движение денежных средств"
    assert reporting.field_label("open_rfis", "en") == "Open Rfis"
    for form in ("einvoice_pdf", "report"):
        assert form in document_form_locales()
    assert "bn" not in document_form_locales()["report"]


def test_the_languages_the_bill_had_are_still_there_with_their_own_words() -> None:
    labels = pdf_export._PDF_LABELS
    for code in ("de", "fr", "es", "ru", "uk", "hu", "pt", "tr"):
        assert labels[code]["cost_estimate"] != labels["en"]["cost_estimate"], code
        assert set(labels[code]) == set(labels["en"]), code
    assert labels["de"]["cost_estimate"] == "KOSTENSCHÄTZUNG"
    assert labels["tr"]["subject"] == "Keşif ve metraj"


def test_a_language_the_files_do_not_translate_prints_english() -> None:
    assert pdf_export._get_pdf_labels("ja") == pdf_export._PDF_LABELS["en"]
    assert pdf_export.pdf_language("ja") == "en"


def test_a_three_letter_language_is_not_cut_to_another_language() -> None:
    assert pdf_export._language_of("fil") == "fil"
    assert pdf_export._language_of("de_DE") == "de"
    assert pdf_export._language_of(None) == "en"


def test_the_server_lists_the_bill_languages_without_chinese() -> None:
    listed = document_form_locales()["boq_pdf"]
    assert "zh" not in listed
    assert {"en", "de", "fr", "es", "ru", "uk", "hu", "pt", "tr"} <= set(listed)
    assert "boq_pdf" in load_document_forms("en")
