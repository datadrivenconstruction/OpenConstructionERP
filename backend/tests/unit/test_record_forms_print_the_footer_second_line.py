# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The footer's second line on record forms.

The purchase order, goods receipt, invoice and payment honour the print stamp
and the registration line, in the form's own language, without touching the
main footer line or the 18 mm bottom margin.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pypdf
import pytest

from app.core import pdf_branding
from app.core.company_profile import DEFAULT_COMPANY_PROFILE
from app.core.pdf_appearance import write_appearance, write_override
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


# -- Record forms --------------------------------------------------------------------


@pytest.mark.parametrize("doc_type", RECORD_TYPES)
def test_a_record_form_prints_the_stamp_and_the_registration_line(data_dir: Path, doc_type: str) -> None:
    write_override(doc_type, {"print_stamp": "datetime", "footer_show_registration": True}, data_dir)
    text = _text(_render(doc_type, "de"))
    assert re.search(r"Erstellt \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", text)
    assert "HRB 12345 VAT DE123456789" in text
    assert "Seite 1 von 1" in text


@pytest.mark.parametrize("doc_type", RECORD_TYPES)
def test_the_default_stamp_keeps_the_generated_time_on_the_main_line(data_dir: Path, doc_type: str) -> None:
    text = _text(_render(doc_type))
    assert re.search(r"[|]\s+Generated", text)
    assert "HRB 12345" not in text


@pytest.mark.parametrize("doc_type", RECORD_TYPES)
def test_a_saved_stamp_moves_the_time_off_the_main_line(data_dir: Path, doc_type: str) -> None:
    write_override(doc_type, {"print_stamp": "date"}, data_dir)
    text = _text(_render(doc_type))
    assert len(re.findall(r"Generated \d{4}-\d{2}-\d{2}", text)) == 1
    assert not re.search(r"[|]\s+Generated", text)


def test_the_second_line_stays_inside_the_bottom_margin_and_clear_of_the_main_line(data_dir: Path) -> None:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar, LTTextContainer

    write_appearance({"print_stamp": "datetime", "footer_show_registration": True}, data_dir)
    low: list[tuple[float, float]] = []
    for page in extract_pages(io.BytesIO(_render("invoice"))):
        for box in page:
            if not isinstance(box, LTTextContainer) or box.y0 > 18 * 72 / 25.4:
                continue
            for line in box:
                chars = [c for c in line if isinstance(c, LTChar)]
                if chars:
                    low.append((min(c.y0 for c in chars), max(c.y1 for c in chars)))
    # The left and right texts of one line share a band; merge them.
    bands: list[tuple[float, float]] = []
    for bottom, top in sorted(low, key=lambda band: band[1], reverse=True):
        if bands and abs(bands[-1][1] - top) < 2.0:
            continue
        bands.append((bottom, top))
    assert len(bands) == 2
    assert bands[1][1] < bands[0][0]  # the second line clears the descenders of the main one
    assert bands[1][0] > 0  # and stays on the sheet, inside the 18 mm bottom margin
