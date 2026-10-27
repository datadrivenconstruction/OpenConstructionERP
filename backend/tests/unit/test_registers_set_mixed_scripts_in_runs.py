# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A string no single PDF face can draw is set in runs, one face per run.

Urdu is the case that forced it: its letters need the bundled Naskh face (the
Unicode face lacks heh goal and yeh barree) and Naskh has digits and Arabic
only, so "صفحہ 2 / 5 (UTC)" needs both faces. The tests below hold three things:

* :func:`app.core.pdf_fonts.pdf_font_runs` splits such a string where it has to
  and nowhere else, never inside an Arabic word and never inside a number;
* a Paragraph built from :func:`pdf_markup` and :func:`pdf_style_for_text`
  draws every glyph of it;
* a submittal register and an RFI log rendered in Urdu and in a regression set
  of other scripts carry no character in a face that has no glyph for it.
"""

from __future__ import annotations

import io
import re
from typing import Any

import pytest

from app.core.document_forms_i18n import REGISTER_UNRENDERABLE, register_form_catalogue
from app.core.pdf_fonts import (
    ARABIC_FONT,
    BODY_FONT,
    BOLD_FONT,
    CJK_FONT,
    KOREAN_FONT,
    THAI_FONT,
    font_can_draw,
    pdf_font_runs,
    pdf_markup,
    pdf_style_for_text,
    pdf_text_width,
    register_pdf_fonts,
)
from tests.unit import test_pilot_documents_render_in_turkish as pilot

URDU_FOOTER = "صفحہ 2 / 5 (UTC)"
REGRESSION_SET = ("ur", "ar", "fa", "he", "zh", "ja", "ko", "th", "hi", "ru", "de")


@pytest.fixture(autouse=True)
def _no_company_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.company_profile.read_company_profile", lambda: {})
    register_pdf_fonts()


# -- the split -----------------------------------------------------------------------


def test_a_string_one_face_draws_is_one_run() -> None:
    assert pdf_font_runs("Total (EUR) 12/5", base=BODY_FONT) == [(BODY_FONT, "Total (EUR) 12/5")]
    assert pdf_font_runs("", base=BODY_FONT) == []


def test_the_urdu_footer_splits_into_naskh_and_the_unicode_face() -> None:
    runs = pdf_font_runs(URDU_FOOTER, base=BODY_FONT)
    assert runs == [(ARABIC_FONT, "صفحہ "), (BODY_FONT, "2 / 5 (UTC)")]
    assert "".join(chunk for _face, chunk in runs) == URDU_FOOTER
    for face, chunk in runs:
        assert all(font_can_draw(face, ch) for ch in chunk), (face, chunk)


def test_an_arabic_word_is_never_split_between_faces() -> None:
    # The word has heh goal (Naskh only) and letters both faces carry.
    word = "صفحہ"
    for face, chunk in pdf_font_runs(f"abc {word} (x)", base=BODY_FONT):
        if any(ch in word for ch in chunk):
            assert chunk.strip() == word


def test_every_arabic_letter_of_a_string_shares_one_face() -> None:
    # "از" alone is drawn in the Unicode face; beside "صفحہ" it follows it into Naskh.
    runs = pdf_font_runs("از (x) صفحہ", base=BODY_FONT)
    assert {face for face, chunk in runs if re.search("[؀-ۿ]", chunk)} == {ARABIC_FONT}


def test_a_number_is_not_cut_between_faces() -> None:
    runs = pdf_font_runs("تیار کردہ 10.10.2026 09:00 UTC", base=BODY_FONT)
    assert [chunk for _face, chunk in runs if "2026" in chunk] == ["10.10.2026 09:00 UTC"]
    assert runs[0][0] == ARABIC_FONT


def test_thai_with_a_superscript_no_longer_drops_to_boxes() -> None:
    runs = pdf_font_runs("พื้นที่ 12 m²", base=BODY_FONT)
    faces = [face for face, _chunk in runs]
    assert THAI_FONT in faces and BODY_FONT in faces
    for face, chunk in runs:
        assert all(font_can_draw(face, ch) for ch in chunk), (face, chunk)


def test_chinese_beside_a_devanagari_name_gets_a_face_for_each() -> None:
    text = "供应商 रमेश कुमार"
    runs = pdf_font_runs(text, base=BODY_FONT)
    assert "".join(chunk for _face, chunk in runs) == text
    assert CJK_FONT in {face for face, _chunk in runs}
    for face, chunk in runs:
        assert all(font_can_draw(face, ch) for ch in chunk if ch != " "), (face, chunk)


def test_bold_runs_use_the_bold_weight_where_there_is_one() -> None:
    runs = pdf_font_runs(URDU_FOOTER, bold=True, base=BOLD_FONT)
    assert runs[-1][0] == BOLD_FONT
    assert all(font_can_draw(face, ch) for face, chunk in runs for ch in chunk)


def test_the_markup_tags_only_the_runs_outside_the_styles_face() -> None:
    style = _style()
    markup = pdf_markup('صفحہ 2 / <5> & "x"', style)
    assert markup.startswith(f'<font name="{ARABIC_FONT}">صفحہ</font>')
    assert "&lt;5&gt; &amp; &quot;x&quot;" in markup
    assert pdf_markup("a < b\nc", style, line_breaks=True) == "a &lt; b<br/>c"


def test_the_width_adds_up_run_by_run() -> None:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    whole = pdf_text_width(URDU_FOOTER, 7.0)
    naskh = stringWidth("صفحہ", ARABIC_FONT, 7.0)
    assert whole > naskh > 0
    assert pdf_text_width("Page 3", 7.0) == pytest.approx(stringWidth("Page 3", BODY_FONT, 7.0))


def _style() -> Any:
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle("t", fontName=BODY_FONT, fontSize=10, leading=12)


# -- glyph coverage of a drawn page ---------------------------------------------------


#: The BaseFont a CID face is written under, by the name reportlab registers it as.
_CID_ALIASES = {"STSongStd-Light": CJK_FONT, "HYSMyeongJo-Medium": KOREAN_FONT}


def _strip_subset(fontname: str) -> str:
    """The registered face name of an embedded font's PostScript name (``ABCDEF+NotoNaskhArabic-Regular``)."""
    name = re.sub(r"-Regular$", "", re.sub(r"^[A-Z]{6}\+", "", fontname))
    return _CID_ALIASES.get(name, name)


def _missing_glyphs(pdf: bytes) -> list[tuple[str, str]]:
    """Every ``(face, character)`` the page draws in a face that has no glyph for it."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar, LTTextContainer

    missing: list[tuple[str, str]] = []
    drawn = 0

    def walk(node: Any) -> None:
        nonlocal drawn
        if isinstance(node, LTChar):
            text = node.get_text()
            # U+FFFF and the private-use block are a shaper's contextual glyphs (a Thai tone mark moved over its vowel,
            # a Devanagari conjunct) with no Unicode of their own.
            if text.isspace() or text.startswith("(cid:") or text == "￿" or "" <= text <= "":
                return
            drawn += 1
            face = _strip_subset(node.fontname)
            if not font_can_draw(face, text):
                missing.append((face, text))
        elif hasattr(node, "__iter__") and isinstance(node, LTTextContainer | object):
            for child in node:
                walk(child)

    for page in extract_pages(io.BytesIO(pdf)):
        walk(page)
    assert drawn > 0
    return missing


def _render_case(name: str, locale: str) -> list[bytes]:
    case = next(c for c in pilot.CASES if c.name == name)
    return [pilot._render(document) for document in pilot._documents(case, locale)]


@pytest.mark.parametrize("locale", REGRESSION_SET)
@pytest.mark.parametrize("case", ["submittals", "rfi"])
def test_no_glyph_is_missing_in_a_register(case: str, locale: str) -> None:
    pdfs = _render_case(case, locale)
    assert pdfs
    for pdf in pdfs:
        assert pdf.startswith(b"%PDF")
        assert _missing_glyphs(pdf) == []


def test_urdu_is_offered_and_bengali_is_still_held_back() -> None:
    assert "ur" not in REGISTER_UNRENDERABLE
    assert "bn" in REGISTER_UNRENDERABLE
    assert "ur" in register_form_catalogue("submittals").supported
    assert "bn" not in register_form_catalogue("submittals").supported


def test_the_urdu_register_prints_its_own_title_and_a_mixed_footer() -> None:
    from pypdf import PdfReader

    catalogue = register_form_catalogue("submittals")
    assert catalogue.tr("ur", "register_title") != catalogue.tr("en", "register_title")
    pdf = _render_case("submittals", "ur")[0]
    text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "UTC" in text  # the Latin run beside the Urdu letters is on the page
    assert re.search(r"\d{2}\.\d{2}\.\d{4}", text)  # and so is a whole date


def test_a_word_is_not_split_across_a_shaping_face() -> None:
    # reportlab shapes a word as one unit in the face of its first fragment.
    runs = pdf_font_runs("พื้นที่ 12 m² (รวม)", base=BODY_FONT)
    assert [chunk for face, chunk in runs if face == THAI_FONT][-1].endswith("(รวม)")
    for _face, chunk in runs:
        assert "(" not in chunk or ")" in chunk  # the bracket pair travels with its word
    mixed = pdf_font_runs("रमेश (GmbH)", base=BODY_FONT)
    assert "(GmbH)" in [chunk for _face, chunk in mixed][-1]
    assert len({face for face, chunk in mixed if "GmbH" in chunk}) == 1


def test_a_string_that_needs_the_shaper_takes_the_shaping_face_as_its_style_face() -> None:
    style = _style()
    text = "พื้นที่ 12 m²"
    faced = pdf_style_for_text(style, text)
    assert faced.fontName == THAI_FONT and faced.shaping == 1
    assert style.fontName == BODY_FONT  # the caller's style is not written to
    markup = pdf_markup(text, style)
    assert markup.startswith("พื้นที่") and f'<font name="{BODY_FONT}">' in markup


def test_a_paragraph_of_mixed_scripts_draws_and_measures() -> None:
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Paragraph

    style = _style()
    canvas = Canvas(io.BytesIO())
    for text in (URDU_FOOTER, "พื้นที่ 12 m² (รวม)", "रमेश (GmbH) ²", "供应商 रमेश कुमार"):
        paragraph = Paragraph(pdf_markup(text, style), pdf_style_for_text(style, text))
        width, height = paragraph.wrapOn(canvas, 400, 100)
        assert 0 < width <= 400 and 0 < height <= 14
        paragraph.drawOn(canvas, 10, 10)


def test_the_space_between_two_runs_is_a_fragment_of_its_own() -> None:
    # Reordering a right-to-left run drops or misplaces a space at its edge.
    markup = pdf_markup("OCE | تیار کردہ 10.10.2026", _style())
    assert f'<font name="{ARABIC_FONT}">تیار کردہ</font>' in markup
    assert f'<font name="{BODY_FONT}"> </font><font name="{ARABIC_FONT}">' in markup
    assert f'</font><font name="{BODY_FONT}"> </font>10.10.2026' in markup


def test_an_arabic_word_keeps_the_urdu_face_beside_a_bracket() -> None:
    runs = pdf_font_runs("جی ہاں (3 دن)", base=BODY_FONT)
    assert [chunk for face, chunk in runs if face == ARABIC_FONT and "دن" in chunk] == ["دن"]
