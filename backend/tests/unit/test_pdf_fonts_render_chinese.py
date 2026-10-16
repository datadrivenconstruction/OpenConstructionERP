# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A generated PDF can print Chinese, and printing it changes nothing else.

The bundled DejaVu faces have no Han glyphs at all - not a thin subset, none -
so until now every Chinese string in every generated PDF came out as boxes.
The fix references an Adobe CID face that reportlab already carries metrics
for, which costs no dependency and no bundled megabytes.

Two properties matter and they pull against each other. The face has to be
reachable when the text needs it, and it must not become the face anything
else prints in: ``BODY_FONT`` and ``BOLD_FONT`` are module globals that every
generator binds at import time, so a per-document choice that wrote to them
would change every later German and Russian document in the same worker. The
selection is therefore per call, and the assertions below check both halves.
"""

from __future__ import annotations

import io

import pytest

from app.core import pdf_fonts
from app.core.pdf_fonts import (
    BODY_FONT,
    CJK_FONT,
    DEVANAGARI_FONT,
    KOREAN_FONT,
    THAI_FONT,
    font_needs_shaping,
    has_cjk,
    pdf_font_for_text,
    pdf_shaping_for_text,
    register_cjk_font,
    register_complex_font,
    register_korean_font,
)

CHINESE = "工程量清单计价"
GERMAN = "Straßenbauarbeiten, Größe"
RUSSIAN = "Строительные работы"


# ── Detection, in both directions ───────────────────────────────────────────


@pytest.mark.parametrize("text", [CHINESE, "综合单价", "措施项目费 (Preliminaries)", "面积：120㎡"])
def test_chinese_text_is_detected(text: str) -> None:
    assert has_cjk(text) is True


@pytest.mark.parametrize("text", [GERMAN, RUSSIAN, "", "Preliminaries 8.0%", "m3", None])
def test_latin_and_cyrillic_text_is_not_detected(text: str | None) -> None:
    """The negative control is the load-bearing half.

    A detector that answered yes to everything would satisfy every assertion
    above and would route every document in the product to a Chinese face.
    """
    assert has_cjk(text) is False


def test_a_mixed_string_is_detected_by_its_chinese_half() -> None:
    """Our own labels are mixed, so this is the realistic case rather than an
    edge one: the regional markup names read ``措施项目费 (Preliminaries)``."""
    assert has_cjk("规费 (Statutory charges)") is True


# ── Registration ────────────────────────────────────────────────────────────


def test_the_cid_face_is_available_from_reportlab_alone() -> None:
    """No bundled TTF, no new dependency, no download at runtime."""
    assert register_cjk_font() is True


def test_registration_is_idempotent() -> None:
    assert register_cjk_font() is True
    assert register_cjk_font() is True


# ── Selection is per call, and leaves the process alone ─────────────────────


def test_chinese_text_selects_the_cid_face() -> None:
    assert pdf_font_for_text(CHINESE) == CJK_FONT


@pytest.mark.parametrize("text", [GERMAN, RUSSIAN, "", None])
def test_other_text_keeps_the_latin_face(text: str | None) -> None:
    assert pdf_font_for_text(text) != CJK_FONT


def test_printing_chinese_does_not_change_the_face_anything_else_prints_in() -> None:
    """The regression this design exists to prevent, asserted as equality.

    ``BODY_FONT`` is read once, at import, by every generator in the product.
    If the Chinese path reassigned it - the way the Helvetica fallback path
    legitimately does - then one Chinese invoice would silently re-face every
    document produced afterwards by the same process.
    """
    body_before, bold_before = pdf_fonts.BODY_FONT, pdf_fonts.BOLD_FONT

    assert pdf_font_for_text(CHINESE) == CJK_FONT

    assert (body_before, bold_before) == (pdf_fonts.BODY_FONT, pdf_fonts.BOLD_FONT)
    assert pdf_font_for_text(GERMAN) == body_before


def test_bold_chinese_is_the_same_face_rather_than_a_latin_bold() -> None:
    """The pack carries one weight. A heading is legible and not heavier;
    falling back to a Latin bold would render the heading as boxes."""
    assert pdf_font_for_text(CHINESE, bold=True) == CJK_FONT


# ── The document itself ─────────────────────────────────────────────────────


def test_a_pdf_containing_chinese_is_produced_and_names_the_face() -> None:
    """The second instrument: the assertions above are about our own helpers,
    and this one is about a file reportlab actually wrote."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont(pdf_font_for_text(CHINESE), 14)
    pdf.drawString(72, 720, CHINESE)
    pdf.save()
    data = buffer.getvalue()

    assert data.startswith(b"%PDF")
    assert b"STSong" in data, "the document does not reference the CID face it was told to use"


def test_the_face_is_referenced_and_not_embedded() -> None:
    """Stated as a test so the caveat cannot quietly stop being true.

    A referenced face keeps the document small and depends on the reader
    supplying the outlines. If someone later embeds a Chinese font, this fails
    and the change gets noticed rather than discovered in a repository size.
    """
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont(pdf_font_for_text(CHINESE), 14)
    pdf.drawString(72, 720, CHINESE * 40)
    pdf.save()
    data = buffer.getvalue()

    assert b"/FontFile" not in data
    assert len(data) < 100_000, f"a referenced CID face should keep this tiny, got {len(data)} bytes"


def test_a_latin_document_is_unaffected_by_the_chinese_path() -> None:
    """Negative control on the document rather than on the helper."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont(pdf_font_for_text(GERMAN), 14)
    pdf.drawString(72, 720, GERMAN)
    pdf.save()
    data = buffer.getvalue()

    assert data.startswith(b"%PDF")
    assert b"STSong" not in data
    assert BODY_FONT.encode() in data or b"Helvetica" in data


# ── Right-to-left scripts ───────────────────────────────────────────────────
#
# Arabic and Hebrew escalate to the bundled Unicode face rather than being left
# to draw as boxes, and app.core.pdf_rtl shapes and reorders them on the way to
# the page. This file used to pin the unshaped, backwards output as a known bug
# so that the fix would have to replace it; the replacement is below, and the
# layout itself is covered in test_pdf_rtl.py.

AR_COMPANY = "شركة الإنشاءات المتحدة"
HE_COMPANY = "חברת הבנייה המאוחדת"


def _drawn(text: str) -> str:
    """What a reader recovers from a page that drew ``text`` once."""
    import pypdf
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from app.core.pdf_fonts import pdf_font_for_text

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont(pdf_font_for_text(text, base="Helvetica"), 12)
    pdf.drawString(50, 700, text)
    pdf.showPage()
    pdf.save()
    pages = pypdf.PdfReader(io.BytesIO(buffer.getvalue())).pages
    return "".join(page.extract_text() for page in pages).strip()


@pytest.mark.parametrize(("label", "text"), [("Arabic", AR_COMPANY), ("Hebrew", HE_COMPANY)])
def test_a_right_to_left_name_escalates_instead_of_boxing(label: str, text: str) -> None:
    """Boxes are unrecoverable: the codepoint is replaced by glyph zero and no
    reader can undo it. Escalating puts real glyphs in the content stream. The
    Arabic ones are presentation forms, which fold back to the stored letters."""
    import unicodedata

    assert not pdf_fonts.font_can_draw_all("Helvetica", text), f"{label} no longer needs to escalate"
    assert pdf_fonts.font_can_draw_all(BODY_FONT, text), f"the bundled face lost its {label} glyphs"
    drawn = _drawn(text)
    assert "\x00" not in drawn, f"{label} came out as boxes, which is the failure this avoids"
    assert sorted(unicodedata.normalize("NFKC", drawn)) == sorted(text), (
        f"{label} lost or gained characters on the way to the page"
    )


@pytest.mark.parametrize(("label", "text"), [("Arabic", AR_COMPANY), ("Hebrew", HE_COMPANY)])
def test_a_right_to_left_name_is_drawn_in_visual_order(label: str, text: str) -> None:
    """The replacement for the pinned bug. The glyphs on the page, read left to
    right by position, must be exactly what the helper produced. Extracted text
    is no instrument for this: both pypdf and MuPDF reorder right-to-left runs
    themselves when they extract, so a backwards line can extract correctly."""
    import pymupdf
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from app.core.pdf_rtl import visual_text

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont(pdf_font_for_text(text, base="Helvetica"), 12)
    pdf.drawString(50, 700, text)
    pdf.save()
    with pymupdf.open(stream=buffer.getvalue(), filetype="pdf") as document:
        chars = [
            (char["origin"][0], char["c"])
            for block in document[0].get_text("rawdict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
            for char in span["chars"]
        ]
    on_page = "".join(ch for _, ch in sorted(chars))
    assert on_page == visual_text(text), f"{label} is not drawn in visual order: {on_page!r}"
    assert on_page != text


# ── Characters the layout engine consumes and never draws ───────────────────
#
# The ladder settles for its widest face when no rung covers the string, which
# is right for a script nothing carries. A line break is not a script. No face
# reports a glyph for one, so leaving it in the coverage question failed every
# rung and sent plain Latin to the Chinese pack. These pin the boundary from
# both sides: whitespace leaves the question, unsupported scripts stay in it.

HANGUL = "서울건설"
THAI = "ก่อสร้าง"
DEVANAGARI = "निर्माण"

# The fall-off controls. Thai and Devanagari used to serve here and cannot any
# more: the ladder carries both, which is the point of the faces this file also
# tests. These two are picked because nothing on the ladder draws them, so the
# settle-for path is still exercised by a real script rather than by a made-up
# codepoint. If either is ever bundled, the assertion below says so by name
# rather than going quietly green.
KHMER = "សំណង់"
BENGALI = "নির্মাণ"


@pytest.mark.parametrize("whitespace", list(pdf_fonts._NEVER_DRAWN))
def test_a_never_drawn_character_does_not_escalate_latin(whitespace: str) -> None:
    """A table heading is the shape that finds this: "A\\nItem" is plain Latin."""
    text = f"A{whitespace}Item"
    assert pdf_fonts.pdf_font_for_text(text, base="Helvetica") == "Helvetica", (
        f"{whitespace!r} escalated a string of plain Latin"
    )
    assert pdf_fonts.pdf_font_for_text(text, base=BODY_FONT) == BODY_FONT


@pytest.mark.parametrize("whitespace", list(pdf_fonts._NEVER_DRAWN))
def test_a_string_of_nothing_but_whitespace_keeps_its_face(whitespace: str) -> None:
    """There is nothing to draw, so there is nothing to escalate for."""
    assert pdf_fonts.pdf_font_for_text(whitespace, base="Helvetica") == "Helvetica"


def test_every_never_drawn_character_is_covered_by_a_case() -> None:
    """A ratchet on the set itself, so widening it cannot skip its evidence.

    This is meant to fail if someone adds a member. Adding one is a claim that
    the layout engine consumes that character too, and the claim wants a case
    rather than a comment.
    """
    assert set(pdf_fonts._NEVER_DRAWN) == set("\n\r\t"), (
        "the never-drawn set changed; add the new character to the cases above"
    )


@pytest.mark.parametrize(("label", "text"), [("Khmer", KHMER), ("Bengali", BENGALI)])
def test_a_script_no_face_carries_still_escalates(label: str, text: str) -> None:
    """The load-bearing control, and the reason this is not just less escalation.

    Neither the bundled face nor the Chinese pack carries these, so the ladder
    runs out and settles for its widest face. That fall-off is the behaviour it
    was built for and it has to survive a change that makes the ladder escalate
    less often.
    """
    assert not pdf_fonts.font_can_draw_all(BODY_FONT, text), f"the ladder now carries {label}, so this control is dead"
    assert pdf_fonts.pdf_font_for_text(text, base="Helvetica") == BODY_FONT, (
        f"{label} stopped escalating off the base face"
    )


@pytest.mark.parametrize(("label", "text"), [("Khmer", KHMER), ("Bengali", BENGALI)])
def test_a_newline_does_not_hide_a_script_that_needs_escalating(label: str, text: str) -> None:
    """The discriminating pair. Same shape, same newline, one real difference.

    "A\\nItem" and "A\\n<script>" differ only in whether a character no face can
    draw is present. Removing the newline from the question must not remove the
    script with it, so the first keeps its base face and this one does not.
    """
    assert pdf_fonts.pdf_font_for_text(f"A\n{text}", base="Helvetica") == BODY_FONT, (
        f"{label} stopped escalating once a newline was in the string"
    )


# ── Korean, and the Chinese face surviving it ───────────────────────────────

KOREAN_COMPANY = "서울건설"
KOREAN_UNIT = "제곱미터"


def test_korean_text_selects_the_korean_cid_face() -> None:
    """The rung exists and the text reaches it.

    Asserted on the resolved face rather than on whether a PDF came out,
    because output is produced either way: before this rung Hangul came back
    faced in DejaVu, which draws it as boxes perfectly successfully.
    """
    assert pdf_font_for_text(KOREAN_COMPANY, base=BODY_FONT) == KOREAN_FONT
    assert pdf_fonts.font_can_draw_all(KOREAN_FONT, KOREAN_COMPANY)


def test_a_korean_string_carrying_latin_keeps_the_korean_face() -> None:
    """Mixed strings are the common case in a bill, not the exotic one.

    Windows Latin is unioned into the Korean predicate for exactly this, and
    without it the string would fail the rung and fall back to a face that
    keeps the parenthesis and loses the company name.
    """
    assert pdf_font_for_text("서울건설 (Seoul Construction)", base=BODY_FONT) == KOREAN_FONT


@pytest.mark.parametrize("text", [CHINESE, "综合单价", "上海建工", "措施项目费 (Preliminaries)", "A\n上海建工"])
def test_chinese_still_resolves_to_the_chinese_face_after_the_korean_rung(text: str) -> None:
    """The load-bearing test of this change, and the reason the rung is ordered.

    Han encodes in EUC-KR. So a Korean rung placed above the Chinese one would
    satisfy the ladder first and hand Chinese documents to the Korean face,
    which is the worst available failure: it renders, it looks plausible, and
    nothing in the product or its gates would report it. No box appears and
    nothing raises, so a test that only checked output was produced would pass
    on the broken arrangement. This asserts the resolved face by name.

    The cases are not equally discriminating and that is deliberate. Measured
    against the broken ordering, only ``上海建工`` and its newline twin actually
    change face; the other three survive by accident, because they contain
    simplified characters EUC-KR cannot encode. Across the shipped Chinese
    locale the capture rate is 73 of 385 strings, so a single sampled string
    finds this roughly one time in five. Keep the company name in the list, and
    do not trust sampling alone: the invariant is asserted directly in
    :func:`test_the_korean_rung_sits_below_the_chinese_one`.
    """
    assert pdf_font_for_text(text, base=BODY_FONT) == CJK_FONT


def test_the_korean_rung_sits_below_the_chinese_one() -> None:
    """The property the test above depends on, asserted directly.

    The test above samples strings; this one states the invariant those samples
    are evidence for, so a reordering is caught even by a string nobody thought
    to sample.
    """
    rungs, _widest = pdf_fonts._face_ladder(BODY_FONT, bold=False)
    assert CJK_FONT in rungs and KOREAN_FONT in rungs, "both CID rungs should be on the ladder"
    assert rungs.index(CJK_FONT) < rungs.index(KOREAN_FONT), (
        "the Korean rung moved above the Chinese one; Chinese documents will now "
        "render in the Korean face, plausibly and wrongly"
    )


def test_the_two_cid_predicates_overlap_and_that_is_why_order_matters() -> None:
    """Names the hazard as a measurement rather than leaving it in a comment.

    If this ever fails because the overlap is gone, the ordering above stops
    being load bearing and the comments saying it is should be corrected.
    """
    han = "上"
    assert pdf_fonts._korean_pack_covers(han), (
        "Han no longer encodes in the Korean pack's encoding, so the ordering "
        "hazard this file guards against may no longer exist"
    )
    assert not pdf_fonts._cid_pack_covers("서"), "Hangul should not be claimed by the Chinese pack"


def test_printing_korean_does_not_change_the_face_anything_else_prints_in() -> None:
    """The same global-mutation guard the Chinese path has, for the new rung."""
    before_body, before_bold = pdf_fonts.BODY_FONT, pdf_fonts.BOLD_FONT
    pdf_font_for_text(KOREAN_COMPANY, base=BODY_FONT)
    assert before_body == pdf_fonts.BODY_FONT
    assert before_bold == pdf_fonts.BOLD_FONT
    assert pdf_font_for_text(GERMAN, base=BODY_FONT) == BODY_FONT
    assert pdf_font_for_text(RUSSIAN, base=BODY_FONT) == BODY_FONT


def test_korean_registration_is_idempotent() -> None:
    assert register_korean_font() is True
    assert register_korean_font() is True


def test_an_ascii_string_never_reaches_either_cid_rung() -> None:
    """Existing documents do not move a byte, which is what makes this safe to
    add to a shipped product rather than something to schedule."""
    assert pdf_font_for_text("Concrete C25/30", base="Helvetica") == "Helvetica"


def test_chinese_still_escalates_with_a_newline_in_the_string() -> None:
    """The ordinary case, asserted with the newline present rather than without,
    because that combination is what the change touches."""
    assert pdf_fonts.pdf_font_for_text("A\n上海建工", base=BODY_FONT) == "STSong-Light"


# ── Thai and Devanagari, where a face alone is the wrong fix ────────────────
#
# These two differ from every rung above them. Chinese and Korean are correct as
# soon as the face is reachable: one codepoint, one glyph, drawn where it falls.
# Thai and Devanagari are not. A face alone gets the glyphs onto the page and
# arranges them wrongly, which is worse than boxes, because boxes read as
# missing and a wrong arrangement reads as a sentence.
#
# So the assertions below are about shaping, not about presence, and they are
# built to fail if shaping stops happening while the fonts stay installed. That
# is the regression worth guarding: the fonts are conspicuous and a dependency
# is not, so the way this breaks in future is somebody dropping uharfbuzz.

# Thai: consonant, upper vowel, tone mark. The tone belongs above the vowel and
# the glyph for that position is not the glyph used above a bare consonant, so
# the shaper has to substitute it. Unshaped, both marks are drawn at the same
# height and collide.
THAI_STACKS = (
    "ที่",
    "พื้",
    "นี่",
    "มื้",
    "สี่",
)

# The same five consonants and vowels with the tone mark removed. One mark above
# a base is the case that was always correct, so nothing needs substituting and
# the shaper leaves the characters alone. This is the control, and it is the
# half that makes the pair evidence: if the stacks and the controls both changed
# the test would only be proving that the shaper ran.
THAI_CONTROLS = (
    "ที",
    "พื",
    "นี",
    "มื",
    "สี",
)

# Devanagari ka + i-matra. Stored consonant first, drawn vowel first.
DEVANAGARI_REORDER = "कि"


def _shaped(text: str, face: str) -> str:
    """The characters reportlab will actually draw, after the shaper has run."""
    from reportlab.pdfbase.ttfonts import shapeStr

    return str(shapeStr(text, face, 10))


def test_uharfbuzz_is_installed_and_the_faces_report_themselves_shapable() -> None:
    """Asserted rather than skipped, on purpose.

    A skip here would be the quietest possible way to lose Thai and Devanagari:
    the fonts would still be in the tree, the ladder would still return them,
    every other assertion in this file would still pass, and the pages would be
    wrong. uharfbuzz is a declared dependency, so its absence is a broken
    install and should read as a failure rather than as a test that did not run.
    """
    import uharfbuzz  # noqa: F401 - imported for the assertion that it exists

    assert register_complex_font(THAI_FONT) is True
    assert register_complex_font(DEVANAGARI_FONT) is True
    assert font_needs_shaping(THAI_FONT), "the Thai face stopped reporting itself shapable"
    assert font_needs_shaping(DEVANAGARI_FONT), "the Devanagari face stopped reporting itself shapable"


@pytest.mark.parametrize("text", THAI_STACKS)
def test_a_thai_tone_over_a_vowel_is_substituted_by_the_shaper(text: str) -> None:
    """The defect, asserted directly: this string cannot be drawn as it is stored.

    The shaper replaces the tone mark with the glyph that belongs above a vowel.
    Without shaping the string goes to the page unchanged and the two marks land
    on top of each other. Comparing the shaped string with the input is what
    distinguishes those two states; a test that merely rendered the page would
    pass in both, because both produce a page.
    """
    assert _shaped(text, THAI_FONT) != text, (
        "the tone mark was not substituted, so it will be drawn at consonant height and collide with the vowel"
    )


@pytest.mark.parametrize("text", THAI_CONTROLS)
def test_a_thai_vowel_without_a_tone_is_left_alone(text: str) -> None:
    """The control, and the reason the pair above is evidence rather than noise.

    These have one mark above the base and nothing above the mark, which is the
    arrangement that was always right. The shaper substitutes nothing. If this
    ever fails alongside the stacks, the instrument is reporting that shaping
    happened rather than that shaping was needed, and the pair stops meaning
    anything.
    """
    assert _shaped(text, THAI_FONT) == text, "a vowel with no tone over it should need no substitution"


def test_the_stacks_and_the_controls_disagree_and_that_is_the_measurement() -> None:
    """Stated once as a set, so the discrimination is asserted and not inferred.

    Five and five, all five stacks changed, none of the controls changed. Either
    half alone is satisfiable by something uninteresting: a shaper that rewrote
    everything would pass the first, and a shaper that did nothing at all would
    pass the second.
    """
    changed = {t for t in THAI_STACKS if _shaped(t, THAI_FONT) != t}
    untouched = {t for t in THAI_CONTROLS if _shaped(t, THAI_FONT) == t}
    assert len(changed) == len(THAI_STACKS), f"only {len(changed)} of {len(THAI_STACKS)} stacks were shaped"
    assert len(untouched) == len(THAI_CONTROLS), (
        f"only {len(untouched)} of {len(THAI_CONTROLS)} controls survived untouched"
    )


def test_the_devanagari_vowel_moves_in_front_of_its_consonant() -> None:
    """The other script's defect, which is order rather than height.

    The i-matra is stored after the consonant it attaches to and drawn before
    it. Unshaped, the vowel appears on the wrong side of the letter, which reads
    as a different syllable rather than as a typo. The shaper moves it, so the
    first character drawn is no longer the consonant that is first in the input.
    """
    out = _shaped(DEVANAGARI_REORDER, DEVANAGARI_FONT)
    assert out != DEVANAGARI_REORDER, "the i-matra was not reordered"
    assert out[0] != DEVANAGARI_REORDER[0], (
        "the consonant is still being drawn first, so the vowel is on the wrong side"
    )


def test_shaping_reaches_the_page_and_not_only_the_shaper() -> None:
    """A shaped string is not a shaped document, so this asserts the bytes.

    ``shapeStr`` returning something different proves the shaper ran. It does
    not prove the result was emitted: reportlab gates that on a second condition
    at the point of drawing. This renders the same text twice through the same
    Paragraph machinery the generators use, once with shaping and once without,
    and compares the page content streams.
    """
    # Registered here rather than inherited from a sibling test. These faces are
    # process-global and lazily registered, so a test that leans on an earlier one
    # passes in a full-file run and fails under -k with a pdfmetrics KeyError that
    # reads like a broken install rather than a missing precondition.
    assert register_complex_font(THAI_FONT), "the Thai face did not register"

    import re

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    def content_stream(shaping: int) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        doc.pageCompression = 0
        style = ParagraphStyle("t", fontName=THAI_FONT, fontSize=24, leading=30, shaping=shaping)
        doc.build([Paragraph("".join(THAI_STACKS), style)])
        for match in re.finditer(rb"stream\r?\n(.*?)endstream", buffer.getvalue(), re.S):
            body = match.group(1)
            if b"BT" in body and b"ET" in body:
                return body
        raise AssertionError("no page content stream was produced")

    assert content_stream(0) != content_stream(1), (
        "the shaped and unshaped pages are byte identical, so shaping never reached the content stream"
    )


def test_a_thai_paragraph_style_comes_back_faced_and_shaped() -> None:
    """The wiring a generator actually touches, asserted end to end."""
    from reportlab.lib.styles import ParagraphStyle

    style = ParagraphStyle("body", fontName=BODY_FONT, fontSize=10)
    shaped = pdf_fonts.pdf_style_for_text(style, THAI)
    assert shaped.fontName == THAI_FONT
    assert getattr(shaped, "shaping", 0), "the style was refaced but never told to shape, which draws the marks wrongly"


def test_refacing_a_style_for_thai_leaves_the_original_style_alone() -> None:
    """The same global-mutation guard the other rungs have, for the style path.

    A ``ParagraphStyle`` outlives the document, so writing ``shaping`` onto the
    caller's own object would turn shaping on for every later paragraph in every
    later document that shares the style table.
    """
    from reportlab.lib.styles import ParagraphStyle

    style = ParagraphStyle("body", fontName=BODY_FONT, fontSize=10)
    pdf_fonts.pdf_style_for_text(style, THAI)
    assert style.fontName == BODY_FONT
    assert not getattr(style, "shaping", 0), "the caller's style was mutated"


def test_a_latin_string_gets_its_own_style_object_back_unchanged() -> None:
    """The identity guarantee, which is what makes this safe to route everything
    through: Latin text returns the same object, not an equal copy."""
    from reportlab.lib.styles import ParagraphStyle

    style = ParagraphStyle("body", fontName=BODY_FONT, fontSize=10)
    assert pdf_fonts.pdf_style_for_text(style, GERMAN) is style


@pytest.mark.parametrize(
    ("label", "text", "face"),
    [("Thai", THAI, THAI_FONT), ("Devanagari", DEVANAGARI, DEVANAGARI_FONT)],
)
def test_each_bundled_script_reaches_its_own_face(label: str, text: str, face: str) -> None:
    assert pdf_font_for_text(text, base="Helvetica") == face, f"{label} did not reach its bundled face"
    assert pdf_shaping_for_text(text, base="Helvetica") is True, f"{label} reached its face without asking for shaping"


@pytest.mark.parametrize(
    ("label", "text", "face"),
    [
        ("Latin", "Concrete C25/30", "Helvetica"),
        ("German", GERMAN, BODY_FONT),
        ("Russian", RUSSIAN, BODY_FONT),
        ("Chinese", CHINESE, CJK_FONT),
        ("Korean", KOREAN_COMPANY, KOREAN_FONT),
    ],
)
def test_the_new_rungs_capture_nothing_that_was_already_working(label: str, text: str, face: str) -> None:
    """The load-bearing control for the two faces added here.

    Both carry a complete Latin alphabet as well as their own script, so each is
    a face that can draw "Concrete C25/30" perfectly well. That is a real hazard
    and not a theoretical one: a rung answering True for plain Latin would
    capture Latin strings the moment it sat above something, and the pages would
    render, and nobody would notice. Asserted by face name rather than by
    rendering, because every one of these renders either way.
    """
    assert pdf_font_for_text(text, base="Helvetica" if label == "Latin" else BODY_FONT) == face, (
        f"{label} was captured by a face added for another script"
    )
    assert pdf_shaping_for_text(text, base="Helvetica" if label == "Latin" else BODY_FONT) is False, (
        f"{label} was told it needs shaping, which it does not"
    )


def test_the_bundled_faces_sit_below_every_rung_that_existed_before_them() -> None:
    """Position, asserted directly rather than through its consequences.

    The test above checks what the order currently produces. This checks the
    order, so a reordering is reported here rather than surfacing as a document
    that quietly changed face.
    """
    rungs, _widest = pdf_fonts._face_ladder(BODY_FONT, bold=False)
    for face in (THAI_FONT, DEVANAGARI_FONT):
        assert face in rungs, f"{face} is not on the ladder at all"
    newest = min(rungs.index(THAI_FONT), rungs.index(DEVANAGARI_FONT))
    for older in (BODY_FONT, CJK_FONT, KOREAN_FONT):
        assert rungs.index(older) < newest, f"{older} sank below a face bundled after it"


def test_drawstring_does_not_shape_and_this_pins_the_limitation() -> None:
    """The documented gap, asserted so it cannot rot into a comment nobody trusts.

    ``canvas.drawString(shaping=True)`` is a no-op without ``rlbidi``: reportlab
    defines its shaping entry point twice and the definition selected when that
    package is absent drops the argument and returns the text unchanged, with no
    warning. This is why the module routes complex scripts through Paragraph.

    If ``rlbidi`` is ever added this test fails, which is the right outcome: it
    means the canvas path started working and the warning in ``pdf_fonts`` about
    it is now wrong and should be removed.
    """
    # Self-registering, for the reason given in the Paragraph test above.
    assert register_complex_font(THAI_FONT), "the Thai face did not register"

    from reportlab.pdfgen import canvas as rl_canvas

    def content_stream(shaping: bool) -> bytes:
        import re

        buffer = io.BytesIO()
        pdf = rl_canvas.Canvas(buffer, pagesize=(400, 100))
        pdf.setPageCompression(0)
        pdf.setFont(THAI_FONT, 24)
        pdf.drawString(20, 40, "".join(THAI_STACKS), shaping=shaping)
        pdf.showPage()
        pdf.save()
        for match in re.finditer(rb"stream\r?\n(.*?)endstream", buffer.getvalue(), re.S):
            body = match.group(1)
            if b"BT" in body and b"ET" in body:
                return body
        raise AssertionError("no page content stream was produced")

    assert content_stream(False) == content_stream(True), (
        "drawString has started honouring shaping, so the canvas path is no longer a trap and pdf_fonts should say so"
    )
