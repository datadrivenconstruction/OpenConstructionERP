# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The generic page furniture in every language.

``pdf_footer`` exists in every locale file with the placeholders English has,
and the page number, the stamp and the generated date reach the page in every
script the PDF layer can draw.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.core import i18n, pdf_branding
from app.core.company_profile import DEFAULT_COMPANY_PROFILE
from app.core.i18n import LOCALES_DIR, SUPPORTED_LOCALES
from app.core.pdf_appearance import write_appearance
from app.core.pdf_fonts import register_pdf_fonts
from tests.unit import _record_pdf_samples as samples

RECORD_TYPES = ("purchase_order", "goods_receipt", "invoice", "payment")
KEYS = ("page_of", "page", "printed", "generated")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        pdf_branding,
        "_read_company_profile",
        lambda *_a, **_k: {**DEFAULT_COMPANY_PROFILE, "registration_line": "HRB 12345 VAT DE123456789"},
    )
    return tmp_path


def _text(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(data)).pages)


def _render(doc_type: str, locale: str = "en") -> bytes:
    from app.core.pdf_appearance import resolve_sections
    from app.modules.finance.pdf_export import build_invoice_pdf, build_payment_pdf
    from app.modules.procurement.pdf_export import build_goods_receipt_pdf, build_purchase_order_pdf

    sections = resolve_sections(doc_type)
    context: dict[str, Any] = {
        "project": samples.PROJECT,
        "people": samples.PEOPLE,
        "sections": sections,
        "locale": locale,
    }
    if doc_type == "purchase_order":
        return build_purchase_order_pdf(samples.purchase_order(), **context)
    if doc_type == "goods_receipt":
        return build_goods_receipt_pdf(samples.goods_receipt(), po=samples.purchase_order(), **context)
    if doc_type == "invoice":
        return build_invoice_pdf(samples.invoice(), **context)
    return build_payment_pdf(samples.payment(), invoice=samples.invoice(), **context)


@pytest.mark.parametrize("code", SUPPORTED_LOCALES)
def test_every_locale_file_translates_the_footer_with_english_placeholders(code: str) -> None:
    english = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))["pdf_footer"]
    own = json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))["pdf_footer"]
    assert set(own) == set(KEYS)
    for key in KEYS:
        assert set(re.findall(r"\{(\w+)\}", own[key])) == set(re.findall(r"\{(\w+)\}", english[key])), (code, key)
    if code != "en":
        assert own["page_of"] != english["page_of"]


def test_english_stays_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    i18n.set_locale("en")
    assert pdf_branding.page_number_text("page_of", page=3, total=7) == "Page 3 of 7"
    assert pdf_branding.page_number_text("page_of", page=3, total=0) == "Page 3"
    assert pdf_branding.page_number_text("page", page=3, total=7) == "Page 3"
    assert pdf_branding._print_stamp_text("date").startswith("Printed: ")


@pytest.mark.parametrize("fmt", ["short", "number"])
def test_short_and_number_formats_are_language_neutral(fmt: str) -> None:
    i18n.set_locale("ja")
    try:
        assert pdf_branding.page_number_text(fmt, page=3, total=7) == ("3 / 7" if fmt == "short" else "3")
    finally:
        i18n.set_locale("en")


def test_a_language_the_pdf_layer_cannot_print_gets_english() -> None:
    i18n.set_locale("bn")
    try:
        assert pdf_branding.page_number_text("page_of", page=1, total=2) == "Page 1 of 2"
    finally:
        i18n.set_locale("en")


PRINTABLE = ("en", "de", "fr", "ru", "zh", "ja", "ko", "th", "hi", "ar", "fa", "he", "hu", "tr", "pl", "vi")


@pytest.mark.parametrize("code", PRINTABLE)
def test_the_branded_footer_prints_the_translated_page_number(data_dir: Path, code: str) -> None:
    register_pdf_fonts()
    write_appearance({"print_stamp": "datetime"}, data_dir)
    i18n.set_locale(code)
    try:
        buffer = io.BytesIO()
        canvas = Canvas(buffer, pagesize=A4)
        doc = SimpleNamespace(
            pagesize=A4, leftMargin=56, rightMargin=56, topMargin=56, bottomMargin=56, page=3, page_count=7
        )
        pdf_branding.branded_header_footer(canvas, doc)
        canvas.showPage()
        canvas.save()
    finally:
        i18n.set_locale("en")
    text = _text(buffer.getvalue())
    assert "3" in text and "7" in text
    assert "2026" in text or re.search(r"\d{4}-\d{2}-\d{2}", text)
    if code == "de":
        assert "Seite 3 von 7" in text
        assert "Gedruckt:" in text
