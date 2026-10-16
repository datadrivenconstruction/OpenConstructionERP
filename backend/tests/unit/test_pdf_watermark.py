# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A saved watermark prints on every page of every document that offers it.

The watermark is one appearance field, ``watermark_text``, drawn by
:func:`app.core.pdf_branding.draw_watermark` from the same page callbacks that
draw the footer. These tests read the produced PDF back rather than a stub
canvas, because the mark is set as a rotated paragraph and a stub would answer
calls a real canvas refuses; the guard around the drawer would then swallow
the failure and every "it printed" assertion would have nothing behind it.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfReader

from app.core.pdf_appearance import (
    DEFAULT_APPEARANCE,
    DOCUMENT_TYPES,
    MAX_WATERMARK_TEXT,
    read_appearance,
    resolve_appearance,
    sanitise,
    sanitise_override,
    write_appearance,
    write_override,
)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every no-argument appearance and profile read at a throwaway directory."""
    from app.core import company_profile, pdf_appearance

    monkeypatch.setattr(pdf_appearance, "resolve_data_dir", lambda: tmp_path)
    monkeypatch.setattr(company_profile, "resolve_data_dir", lambda: tmp_path)
    return tmp_path


def _text_of(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)


def _draw_one_page(appearance: dict[str, Any]) -> tuple[bool, bytes]:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    from app.core.pdf_branding import draw_watermark

    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    drew = draw_watermark(canvas, appearance, page_w=A4[0], page_h=A4[1])
    canvas.showPage()
    canvas.save()
    return drew, buffer.getvalue()


def test_an_untouched_workspace_prints_no_watermark() -> None:
    assert DEFAULT_APPEARANCE["watermark_text"] == ""
    drew, pdf = _draw_one_page(dict(DEFAULT_APPEARANCE))
    assert drew is False
    assert "DRAFT" not in _text_of(pdf)


def test_the_sanitiser_collapses_whitespace_and_caps_the_length() -> None:
    assert sanitise({"watermark_text": "  NOT \n FOR\tCONSTRUCTION "})["watermark_text"] == "NOT FOR CONSTRUCTION"
    assert len(sanitise({"watermark_text": "X" * 200})["watermark_text"]) == MAX_WATERMARK_TEXT
    assert sanitise({"watermark_text": 12})["watermark_text"] == ""


def test_a_saved_watermark_is_drawn_faintly_onto_the_page() -> None:
    drew, pdf = _draw_one_page({"watermark_text": "DRAFT"})
    assert drew is True
    assert "DRAFT" in _text_of(pdf)
    # The low opacity is a graphics state, so the mark cannot print solid.
    assert b"/ca .14" in pdf


@pytest.mark.parametrize("word", ["ЧЕРНОВИК", "ENTWURF", "草稿"])
def test_a_non_latin_watermark_is_set_in_a_face_that_carries_it(word: str) -> None:
    from app.core.pdf_fonts import BOLD_FONT, font_can_draw_all, pdf_font_for_text

    face = pdf_font_for_text(word, bold=True, base=BOLD_FONT)
    assert font_can_draw_all(face, word)
    drew, pdf = _draw_one_page({"watermark_text": word})
    assert drew is True
    assert face.encode() in pdf
    assert word in _text_of(pdf)


def test_a_failing_canvas_loses_the_watermark_not_the_document() -> None:
    from app.core.pdf_branding import draw_watermark

    class Broken:
        def saveState(self) -> None:  # noqa: N802 - reportlab's spelling
            raise RuntimeError("canvas gone")

    assert draw_watermark(Broken(), {"watermark_text": "DRAFT"}, page_w=595.0, page_h=842.0) is False


def test_the_workspace_watermark_reaches_the_shared_page_furniture(data_dir: Path) -> None:
    from app.core.pdf_branding import render_sample_pdf

    assert "CONFIDENTIAL" not in _text_of(render_sample_pdf())
    write_appearance({**read_appearance(), "watermark_text": "CONFIDENTIAL"})
    assert "CONFIDENTIAL" in _text_of(render_sample_pdf())


def test_every_type_with_a_footer_offers_the_watermark_and_no_other() -> None:
    for kind in DOCUMENT_TYPES.values():
        assert ("watermark_text" in kind.fields) == ("footer_text" in kind.fields), kind.key


def test_a_type_can_clear_the_workspace_watermark(data_dir: Path) -> None:
    write_appearance({**read_appearance(), "watermark_text": "DRAFT"})
    assert sanitise_override("invoice", {"watermark_text": ""}) == {"watermark_text": ""}
    write_override("invoice", {"watermark_text": ""})
    assert resolve_appearance("invoice")["watermark_text"] == ""
    assert resolve_appearance("purchase_order")["watermark_text"] == "DRAFT"


@pytest.mark.parametrize("doc_type", ["rfi", "meeting_minutes", "daily_report", "invoice"])
def test_the_typed_sample_prints_the_types_watermark(data_dir: Path, doc_type: str) -> None:
    from app.core.pdf_branding import render_sample_pdf

    write_override(doc_type, {"watermark_text": "COPY"})
    assert "COPY" in _text_of(render_sample_pdf(doc_type))


def test_the_rfi_page_callback_draws_the_watermark() -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    from app.modules.rfi.pdf_export import _make_page_callback

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    on_page = _make_page_callback("2026-10-16", "en", appearance={"watermark_text": "VOID"})
    doc.build([Paragraph("body")], onFirstPage=on_page, onLaterPages=on_page)
    assert "VOID" in _text_of(buffer.getvalue())


def test_the_record_form_callback_draws_the_watermark(data_dir: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    from app.core.register_export import _footer_callback

    write_override("purchase_order", {"watermark_text": "UNAPPROVED"})
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    on_page = _footer_callback(
        page_label="Page {page} of {total}",
        generated_label="Generated {timestamp}",
        generated="2026-10-16",
        total_pages=1,
        page_width=A4[0],
        margin_side=56.0,
        doc_type="purchase_order",
        letterhead_on_first_page=False,
    )
    doc.build([Paragraph("body")], onFirstPage=on_page, onLaterPages=on_page)
    assert "UNAPPROVED" in _text_of(buffer.getvalue())
