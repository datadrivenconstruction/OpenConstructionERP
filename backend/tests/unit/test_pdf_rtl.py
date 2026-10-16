# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Arabic, Persian, Urdu and Hebrew print joined and in reading order.

Two instruments. The first half asks the helper directly, with expected
strings written out codepoint by codepoint, so a regression in either library
shows up as a different string rather than as a vague mismatch. The second half
renders real PDFs and reads them back with PyMuPDF, glyph by glyph in the order
they sit on the page from left to right. Text extraction alone is not enough
for that: MuPDF runs its own bidi pass when it extracts, so a backwards line
and a correct one can extract identically.
"""

from __future__ import annotations

import io
import unicodedata

import pymupdf
import pytest

from app.core import pdf_fonts
from app.core.pdf_rtl import (
    VisualText,
    _levels,
    _load,
    has_rtl,
    is_rtl_locale,
    rtl_support_available,
    shape_rtl,
    text_direction,
    visual_text,
)

# شركة: sheen initial, reh final, kaf initial, teh marbuta final. Reh does not
# join to the letter after it, so kaf starts a new joined group.
SHARIKA = "شركة"
SHARIKA_VISUAL = "ﺔﻛﺮﺷ"

AR_COUNTERPARTY = "شركة الأمل للمقاولات"


def _arabic_run(line: str) -> str:
    """The Arabic presentation-form and space run of a visual line, trimmed."""
    keep = "".join(ch if (0xFB50 <= ord(ch) <= 0xFEFF or ch == " ") else "|" for ch in line)
    return max(keep.split("|"), key=len).strip()


def _read_right_to_left(visual: str) -> str:
    """Undo the visual order the way a reader does, and fold the forms back to letters."""
    return unicodedata.normalize("NFKC", visual[::-1])


# -- The helper ----------------------------------------------------------------


def test_both_libraries_are_installed() -> None:
    """Without them every hook below silently stays off, so fail loudly here."""
    assert rtl_support_available() is True


def test_a_known_arabic_word_is_joined_and_reversed() -> None:
    assert visual_text(SHARIKA) == SHARIKA_VISUAL


def test_lam_alef_becomes_the_mandatory_ligature() -> None:
    # لا: lam followed by alef is always drawn as one glyph.
    assert visual_text("لا") == "ﻻ"


def test_shaping_alone_keeps_logical_order() -> None:
    assert shape_rtl(SHARIKA) == SHARIKA_VISUAL[::-1]


def test_numbers_inside_arabic_keep_their_own_order() -> None:
    """``فاتورة رقم 123``: the line reads right to left, the number left to right."""
    visual = visual_text("فاتورة رقم 123")
    assert visual.startswith("123 "), visual
    assert "321" not in visual
    assert _read_right_to_left(visual[4:]) == "فاتورة رقم"


def test_a_latin_name_inside_arabic_stays_readable() -> None:
    visual = visual_text("شركة ABC Ltd للمقاولات")
    assert "ABC Ltd" in visual
    assert visual.endswith(SHARIKA_VISUAL), "the first logical word must be drawn rightmost"


def test_brackets_on_a_right_to_left_level_are_mirrored() -> None:
    """``شركة (ذ.م.م)``: drawn left to right, the bracket on the left must open."""
    visual = visual_text("شركة (ذ.م.م)")
    assert visual[0] == "(" and visual.index(")") < visual.index(SHARIKA_VISUAL)


def test_hebrew_is_reversed_without_shaping() -> None:
    assert visual_text("שלום 2026") == "2026 םולש"


def test_hebrew_with_a_latin_company_and_a_number() -> None:
    assert visual_text("חשבונית 17 של ABC Ltd") == "ABC Ltd לש 17 תינובשח"


def test_a_left_to_right_paragraph_keeps_its_latin_order() -> None:
    visual = visual_text("Invoice for شركة")
    assert visual == "Invoice for " + SHARIKA_VISUAL


def test_the_paragraph_direction_can_be_fixed() -> None:
    assert visual_text("Invoice for شركة", direction="rtl") == SHARIKA_VISUAL + " Invoice for"


def test_each_line_is_reordered_on_its_own() -> None:
    assert visual_text("שלום\nעולם") == "םולש\nםלוע"


def test_diacritics_follow_their_letter() -> None:
    """reportlab draws a zero-width mark over the glyph drawn before it, so each
    letter's marks must come right after that letter in the visual string."""
    word = "مُحَمَّد"
    clusters: list[str] = []
    for ch in shape_rtl(word):
        if unicodedata.combining(ch) and clusters:
            clusters[-1] += ch
        else:
            clusters.append(ch)
    assert visual_text(word) == "".join(reversed(clusters))


@pytest.mark.parametrize("text", ["Straßenbau 12,5 m3", "Строительные работы", "工程量清单", "ก่อสร้าง", "", "2026"])
def test_text_without_right_to_left_letters_is_returned_as_the_same_object(text: str) -> None:
    assert visual_text(text) is text


def test_a_second_pass_is_a_no_op() -> None:
    """Running bidi twice would reverse the line back."""
    once = visual_text(AR_COUNTERPARTY)
    assert isinstance(once, VisualText)
    assert visual_text(once) is once


@pytest.mark.parametrize(
    ("text", "expected"),
    [("شركة", "rtl"), ("עברית", "rtl"), ("123 شركة", "rtl"), ("ABC شركة", "ltr"), ("123", None)],
)
def test_direction_comes_from_the_first_strong_character(text: str, expected: str | None) -> None:
    assert text_direction(text) == expected


@pytest.mark.parametrize(
    ("locale", "rtl"), [("ar", True), ("fa-IR", True), ("he_IL", True), ("ur", True), ("de", False)]
)
def test_right_to_left_locales(locale: str, rtl: bool) -> None:
    assert is_rtl_locale(locale) is rtl


def test_has_rtl() -> None:
    assert has_rtl("Supplier: شركة") and has_rtl("עברית") and not has_rtl("Größe") and not has_rtl(None)


def test_bracket_mirroring_still_reads_the_levels_from_python_bidi() -> None:
    """Mirroring depends on python-bidi's debug output. Pinned so an upgrade that
    changes it fails here instead of quietly printing brackets backwards."""
    libs = _load()
    assert libs is not None
    text = "شركة (ABC)"
    levels = _levels(text, 1, libs[1])
    assert levels is not None and len(levels) == len(text)
    assert levels[0] == 1 and levels[text.index("A")] == 2


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("Arabic", "شركة المقاولات العربية للإنشاءات"),
        ("Persian", "شرکت ساختمانی پارس گچ ژاله"),
        ("Urdu", "تعمیراتی کمپنی ٹھیکیدار بڑا ہے"),
        ("Hebrew", "חברת הבנייה בע״מ"),
    ],
)
def test_every_shaped_glyph_is_one_the_chosen_face_can_draw(label: str, text: str) -> None:
    """The face is chosen on the stored letters and the glyphs drawn are the
    shaped forms, so both have to be in the face. DejaVu covers Arabic, Persian
    and Hebrew; Urdu needs heh goal and yeh barree and goes to Noto Naskh."""
    face = pdf_fonts.pdf_font_for_text(text, base="Helvetica")
    visual = visual_text(text, face=face)
    missing = [hex(ord(ch)) for ch in visual if not ch.isspace() and not pdf_fonts.font_can_draw(face, ch)]
    assert missing == [], f"{label}: {face} cannot draw {missing}"
    if label == "Urdu":
        assert face == pdf_fonts.ARABIC_FONT
    else:
        assert face == pdf_fonts.BODY_FONT, f"{label} should stay in the bundled Unicode face"


# -- Real documents ------------------------------------------------------------


def _visual_lines(pdf: bytes) -> list[str]:
    """Every baseline of every page, its glyphs in left-to-right page order."""
    rows: dict[tuple[int, int], list[tuple[float, str]]] = {}
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        for page_number, page in enumerate(document):
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        for char in span["chars"]:
                            key = (page_number, round(char["origin"][1]))
                            rows.setdefault(key, []).append((char["origin"][0], char["c"]))
    return ["".join(ch for _, ch in sorted(chars)) for _, chars in sorted(rows.items())]


def _embedded_fonts(pdf: bytes) -> list[tuple[str, str]]:
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        return [(font[3], font[1]) for page in document for font in page.get_fonts()]


def test_a_canvas_line_prints_joined_and_right_to_left() -> None:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont(pdf_fonts.pdf_font_for_text(SHARIKA, base="Helvetica"), 12)
    pdf.drawString(72, 720, SHARIKA)
    pdf.save()

    assert SHARIKA_VISUAL in _visual_lines(buffer.getvalue())


def test_a_wrapped_arabic_paragraph_starts_at_the_right_and_reads_down() -> None:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    words = [f"البند {n}" for n in range(1, 31)]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    style = ParagraphStyle("body", fontName=pdf_fonts.BODY_FONT, fontSize=11, leading=14)
    doc.build([Paragraph(" ".join(words), style)])

    lines = [line for line in _visual_lines(buffer.getvalue()) if has_rtl(unicodedata.normalize("NFKC", line))]
    assert len(lines) > 1, "the paragraph should wrap"
    first = _read_right_to_left(lines[0])
    assert first.startswith("البند 1 البند 2"), first
    last = _read_right_to_left(lines[-1])
    assert last.rstrip().endswith("البند 03"), last  # the digits read left to right, so 30 reverses to 03

    with pymupdf.open(stream=buffer.getvalue(), filetype="pdf") as document:
        spans = [s for b in document[0].get_text("dict")["blocks"] for ln in b.get("lines", []) for s in ln["spans"]]
    right_edges = {round(span["bbox"][2]) for span in spans}
    assert max(right_edges) - min(right_edges) <= 2, f"the lines are not right-aligned: {sorted(right_edges)}"


def test_a_bare_table_cell_is_reordered_and_right_aligned() -> None:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    rows = [["Supplier", AR_COUNTERPARTY]]
    commands = pdf_fonts.pdf_table_font_commands(rows, base="Helvetica")
    assert ("ALIGN", (1, 0), (1, 0), "RIGHT") in commands
    assert not any(c[0] == "ALIGN" and c[1] == (0, 0) for c in commands), "a Latin cell keeps the table's alignment"

    buffer = io.BytesIO()
    table = Table(rows, colWidths=[100, 300])
    table.setStyle(TableStyle(commands))
    SimpleDocTemplate(buffer).build([table])

    line = next(line for line in _visual_lines(buffer.getvalue()) if "Supplier" in line)
    assert _read_right_to_left(_arabic_run(line)) == AR_COUNTERPARTY


def test_an_invoice_prints_an_arabic_counterparty_joined_and_in_order() -> None:
    """The form a client receives, rendered through the real invoice builder."""
    from app.core.pdf_appearance import resolve_sections
    from app.modules.finance.pdf_export import build_invoice_pdf
    from tests.unit import _record_pdf_samples as samples

    people = {**samples.PEOPLE, samples.VENDOR_ID: AR_COUNTERPARTY}
    pdf = build_invoice_pdf(
        samples.invoice(), project=samples.PROJECT, people=people, sections=resolve_sections("invoice")
    )

    lines = [line for line in _visual_lines(pdf) if any(0xFE70 <= ord(ch) <= 0xFEFF for ch in line)]
    assert lines, "the counterparty name is not on the page in joined forms"
    run = _arabic_run(lines[0])
    assert _read_right_to_left(run) == AR_COUNTERPARTY
    assert not any(0x0600 <= ord(ch) <= 0x06FF for ch in run), "a letter was left in its unjoined form"
    assert run.endswith(SHARIKA_VISUAL), "the first word of the name must be drawn rightmost"

    fonts = _embedded_fonts(pdf)
    assert any("DejaVuSans" in name and ext == "ttf" for name, ext in fonts), f"Arabic face not embedded: {fonts}"
