# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unicode font registration for every reportlab-generated PDF.

OpenEstimate principle #2 is *i18n EVERYWHERE*. reportlab's built-in Type-1
fonts (Helvetica / Times / Courier) are Latin-1 only, so any PDF that renders
Cyrillic (ru, bg, uk, sr), Greek, or the many accented Latin scripts with the
default font shows empty boxes ("tofu") instead of text. A construction ERP
that ships 29 locales but prints unreadable invoices and contracts in half of
them is broken.

This module bundles **DejaVu Sans** (regular + bold) and registers it with
reportlab once per process. DejaVu covers Latin, Latin-Extended, Cyrillic and
Greek - i.e. every locale this product ships *except* the complex scripts
(Arabic, Hebrew, CJK, Thai, Devanagari), which need much larger Noto fonts and
proper bidi/shaping. For the covered scripts the fix is complete: glyphs
render, not boxes.

Chinese and Korean are handled separately and without bundling anything,
because reportlab ships CID font *metrics* for the Adobe Asian font packs and
can reference them by name. ``pdf_font_for_text`` returns the CID face for text
that needs it and the DejaVu face for everything else, so a Chinese document
does not change the face a German one prints in.

The two CID rungs overlap and their order is load bearing. Han encodes in
EUC-KR, so the Korean rung would answer for Chinese text if it were asked
first; measured against the shipped Chinese locale, 73 of 385 strings would
change face, including most of the commonest words in the UI. Chinese is asked
first, and :func:`_face_ladder` says so where the order is set.

Thai and Devanagari are bundled as embedded Noto faces. Neither has a CID pack,
so unlike Korean they could not be added for free: each needs a real face in the
repository, 73 KB and 276 KB, under the SIL Open Font License 1.1.

Those two scripts also need more than a face. A face alone fixes the boxes and
leaves the text wrong, which is the worse of the two failures because it looks
like output. Thai stacks a tone mark above an upper vowel, and the mark that
belongs above the vowel is a different glyph from the one that belongs above the
consonant; without shaping the font draws the consonant-height glyph and the two
marks collide. Devanagari stores the i-matra after its consonant and draws it
before, so without shaping the vowel appears on the wrong side of the letter.
Both are fixed by ``uharfbuzz``, which reportlab uses when it is installed, and
:func:`pdf_shaping_for_text` says which strings need it.

Shaping reaches the page through Paragraph, not through ``canvas.drawString``.
reportlab routes ``drawString(shaping=True)`` through ``bidiShapedText``, which
has two definitions, and the one selected when ``rlbidi`` is absent discards the
argument and returns the string unshaped. It does not warn. So a caller drawing
complex script straight onto the canvas gets silence and a wrong page; use
:func:`pdf_style_for_text` and a Paragraph, which calls the shaper directly and
is unaffected.

A bare string in a table is that caller without looking like one. reportlab
draws a cell that is not a flowable through ``canvas.drawString``, so the
warning above covers every such cell, and the generator that built the row
never typed the word canvas. ``TableStyle`` does carry a ``SHAPING`` op and
cells do honour ``cellstyle.shaping``, which makes this harder to catch rather
than easier: reaching for the obvious control routes into the same no-op and
reports nothing. Measured on the page, a Thai tone mark in a bare cell draws
the consonant-height glyph where the shaper calls for the raised one, and a
Devanagari i-matra draws after its consonant instead of before.

The condition to watch, which is more useful than the decision it would change:
``rlbidi`` is not priced in while the canvas route carries only table cells. If
a generator ever routes body text through the canvas directly, that route stops
being avoidable and ``rlbidi`` is worth pricing then.

**The CID face is referenced, not embedded.** A PDF using it carries the text
and the metrics but not the outlines, so it renders wherever the reader can
supply an Adobe Simplified Chinese face - which every mainstream desktop and
browser viewer does, and an offline or minimal viewer may not. That is the
trade for not carrying a 16 MB font in the repository, and it is a real
limitation rather than a footnote: a document that must render identically
everywhere needs an embedded font, which is a separate decision with a size
cost attached.

Usage in a generator::

    from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, register_pdf_fonts

    register_pdf_fonts()            # idempotent; call once at the top
    canvas.setFont(BODY_FONT, 10)   # instead of "Helvetica"
    canvas.setFont(BOLD_FONT, 12)   # instead of "Helvetica-Bold"

A generator that can be handed Chinese - which in this product means any
generator that prints project names, item descriptions or party names, because
that is where Chinese arrives - asks for the face per string instead::

    from app.core.pdf_fonts import pdf_font_for_text, pdf_style_for_text, pdf_table_font_commands

    canvas.setFont(pdf_font_for_text(title, bold=True), 12)
    Paragraph(html.escape(desc), pdf_style_for_text(styles["cell"], desc))
    table.setStyle(TableStyle([*base_commands, *pdf_table_font_commands(rows)]))

Per string rather than per document on purpose. The faces cover different
scripts and none covers all of them, so a document mixing a Chinese supplier
name into German text renders correctly only if the choice is made at the string
that is being drawn.

The choice is made by asking the font, not by testing the codepoint against a
range. ``font_can_draw`` reads the TrueType character map, or a Type-1 built-in's
own encoding vector, and reports whether that face has a glyph. A string is then
given the lowest face on a ladder - the generator's existing face, then the
bundled Unicode face, then the Chinese pack - that can draw every character in
it. Two things follow, and both matter more than the tidiness. A string the old
face could already draw never leaves the first rung, so wiring a generator up
does not move a single byte of its existing Latin output. And a string the old
face could not draw escalates whatever the reason: Cyrillic and Greek get the
same treatment as Han, which a range test named for one script would never have
given them.

Right-to-left scripts. Arabic, Persian, Urdu and Hebrew escalate to the
bundled Unicode face like any other script the base face cannot draw, and that
face has their glyphs, including the Arabic presentation forms, except two
Urdu letters (heh goal and yeh barree); an Urdu string escalates one rung
further, to the bundled Noto Naskh Arabic, which has all of them. Shaping and
order are handled by :mod:`app.core.pdf_rtl`, which this module installs into
reportlab at import: letters are joined into their positional forms, each line
is put into visual order by the Unicode Bidirectional Algorithm, and an
Arabic or Hebrew paragraph is drawn right-aligned. The text layer then carries
the presentation forms in visual order, which is what a reader extracts.

``register_pdf_fonts()`` is safe to call from many generators and many times;
it registers at most once and never raises if the bundled TTFs are missing
(it falls back to Helvetica and logs a warning, so PDF generation degrades
rather than crashing).
"""

from __future__ import annotations

import html
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.pdf_rtl import install_reportlab_rtl, text_direction

logger = logging.getLogger(__name__)

_FONT_DIR = Path(__file__).resolve().parent / "fonts"

#: Registered font names. When registration succeeds these are the DejaVu
#: faces; if the bundled TTFs are somehow unavailable they fall back to the
#: reportlab built-ins so callers never crash (only lose non-Latin glyphs).
BODY_FONT = "DejaVuSans"
BOLD_FONT = "DejaVuSans-Bold"

_FALLBACK_BODY = "Helvetica"
_FALLBACK_BOLD = "Helvetica-Bold"

# Map the reportlab built-in names every legacy generator hard-codes to the
# Unicode faces, so wiring an existing generator is a one-line swap via
# pdf_font("Helvetica") rather than touching every setFont call by hand.
_HELVETICA_MAP = {
    "Helvetica": BODY_FONT,
    "Helvetica-Bold": BOLD_FONT,
    "Helvetica-Oblique": BODY_FONT,
    "Helvetica-BoldOblique": BOLD_FONT,
}

_lock = Lock()
_registered: bool | None = None  # None = not attempted, True/False = outcome


def register_pdf_fonts() -> bool:
    """Register the bundled DejaVu faces with reportlab. Idempotent.

    Returns ``True`` when the Unicode faces are available (either just
    registered or registered earlier in this process), ``False`` when the
    bundled TTFs could not be loaded and callers should expect the
    Helvetica fallback. Never raises.
    """
    global _registered, BODY_FONT, BOLD_FONT
    if _registered is not None:
        return _registered

    with _lock:
        if _registered is not None:
            return _registered

        try:
            from reportlab.lib.fonts import addMapping
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            regular = _FONT_DIR / "DejaVuSans.ttf"
            bold = _FONT_DIR / "DejaVuSans-Bold.ttf"
            if not regular.is_file() or not bold.is_file():
                raise FileNotFoundError(f"bundled DejaVu TTFs missing in {_FONT_DIR}")

            # The _registered gate guarantees this body runs at most once per
            # process, so a plain registerFont is enough (no need to probe the
            # registry first).
            pdfmetrics.registerFont(TTFont("DejaVuSans", str(regular)))
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(bold)))

            # Let Paragraph markup (<b>, <i>) resolve to the right face. We only
            # bundle regular + bold, so italic maps onto the upright faces.
            pdfmetrics.registerFontFamily(
                "DejaVuSans",
                normal="DejaVuSans",
                bold="DejaVuSans-Bold",
                italic="DejaVuSans",
                boldItalic="DejaVuSans-Bold",
            )
            addMapping("DejaVuSans", 0, 0, "DejaVuSans")
            addMapping("DejaVuSans", 1, 0, "DejaVuSans-Bold")
            addMapping("DejaVuSans", 0, 1, "DejaVuSans")
            addMapping("DejaVuSans", 1, 1, "DejaVuSans-Bold")

            _registered = True
            logger.debug("PDF fonts: registered DejaVu Sans (regular + bold)")
        except Exception as exc:  # noqa: BLE001 - degrade, never break PDF output
            BODY_FONT = _FALLBACK_BODY
            BOLD_FONT = _FALLBACK_BOLD
            _registered = False
            logger.warning(
                "PDF fonts: could not register DejaVu (%s); falling back to Helvetica - non-Latin text may not render",
                exc,
            )
        return _registered


def pdf_font(name: str, *, bold: bool = False) -> str:
    """Resolve a font name to its Unicode-capable equivalent.

    Accepts a reportlab built-in name (``"Helvetica"`` / ``"Helvetica-Bold"``)
    and returns the registered DejaVu face, or honours an explicit ``bold``
    flag. Registers fonts on first use so callers need not remember to.

    When DejaVu registration failed (bundled TTFs missing) it returns the
    matching reportlab built-in instead, so the caller always gets a name
    reportlab can actually resolve.
    """
    ok = register_pdf_fonts()
    if not ok:
        want_bold = bold or name in ("Helvetica-Bold", "Helvetica-BoldOblique")
        return _FALLBACK_BOLD if want_bold else _FALLBACK_BODY
    if name in _HELVETICA_MAP:
        return _HELVETICA_MAP[name]
    if bold:
        return BOLD_FONT
    return name or BODY_FONT


# -- Chinese ------------------------------------------------------------------

#: The Adobe CID face for Simplified Chinese. reportlab knows its metrics and
#: references it by name, so nothing is bundled and nothing is embedded.
CJK_FONT = "STSong-Light"

_cjk_lock = Lock()
_cjk_registered: bool | None = None

#: Ideographic codepoint ranges, for :func:`has_cjk` only. This is a statement
#: about scripts, not about any font, and nothing on the face-selection path
#: reads it: see :func:`font_can_draw`, which asks the face.
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3000, 0x303F),  # CJK symbols and punctuation
    (0x3400, 0x4DBF),  # unified ideographs extension A
    (0x4E00, 0x9FFF),  # unified ideographs
    (0xF900, 0xFAFF),  # compatibility ideographs
    (0xFF00, 0xFFEF),  # halfwidth and fullwidth forms
    (0x20000, 0x3FFFF),  # the supplementary ideographic plane
)


def has_cjk(text: str | None) -> bool:
    """Whether ``text`` contains a character inside the CID pack's declared ranges.

    Kept for callers that want to ask about scripts rather than about faces.
    It is **not** the face-selection predicate: a range test cannot tell you
    whether a given face has a given glyph, and it answers ``False`` for plenty
    of characters Helvetica cannot draw (Cyrillic, Greek, several accented Latin
    forms). Selection goes through :func:`font_can_draw`, which asks the font.
    """
    return any(any(low <= ord(ch) <= high for low, high in _CJK_RANGES) for ch in text or "")


def register_cjk_font() -> bool:
    """Register the Simplified Chinese CID face with reportlab. Idempotent.

    Separate from :func:`register_pdf_fonts` and lazy on purpose. It costs
    nothing to skip in a process that never prints Chinese, and it must never
    become the process-wide body face: :data:`BODY_FONT` and :data:`BOLD_FONT`
    are module globals that generators bind at import, so reassigning them for
    one document would change the face of every later German and Russian one in
    the same worker.

    Returns ``True`` when the face is usable, ``False`` when this reportlab
    build cannot provide it. Never raises.
    """
    global _cjk_registered
    if _cjk_registered is not None:
        return _cjk_registered

    with _cjk_lock:
        if _cjk_registered is not None:
            return _cjk_registered
        try:
            from reportlab.lib.fonts import addMapping
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont

            pdfmetrics.registerFont(UnicodeCIDFont(CJK_FONT))
            # The pack carries one weight. Bold Paragraph markup resolves to
            # the same face rather than to a synthesised one, so a heading is
            # legible and simply not heavier. Mapping it to a Latin bold would
            # be worse: the run would render as boxes.
            pdfmetrics.registerFontFamily(
                CJK_FONT,
                normal=CJK_FONT,
                bold=CJK_FONT,
                italic=CJK_FONT,
                boldItalic=CJK_FONT,
            )
            for bold_flag in (0, 1):
                for italic_flag in (0, 1):
                    addMapping(CJK_FONT, bold_flag, italic_flag, CJK_FONT)
            _cjk_registered = True
            logger.debug("PDF fonts: registered CID face %s (referenced, not embedded)", CJK_FONT)
        except Exception as exc:  # noqa: BLE001 - degrade, never break PDF output
            _cjk_registered = False
            logger.warning(
                "PDF fonts: could not register the CID face %s (%s); Chinese text will not render",
                CJK_FONT,
                exc,
            )
        return _cjk_registered


# -- Korean -------------------------------------------------------------------

#: The Adobe CID face for Korean. Like the Chinese one it is referenced by name
#: from metrics reportlab already ships, so this rung costs no bytes in the
#: repository and adds no dependency. Gothic rather than MyeongJo because the
#: body face is a sans and a document should not change class halfway down.
KOREAN_FONT = "HYGothic-Medium"

_korean_lock = Lock()
_korean_registered: bool | None = None


def register_korean_font() -> bool:
    """Register the Korean CID face with reportlab. Idempotent.

    The same shape as :func:`register_cjk_font` and for the same reasons: lazy,
    because a process that never prints Korean should not pay for it, and never
    process-wide, because :data:`BODY_FONT` is bound at import by generators and
    reassigning it for one document would re-face every later one in the worker.

    Returns ``True`` when the face is usable, ``False`` when this reportlab
    build cannot provide it. Never raises.
    """
    global _korean_registered
    if _korean_registered is not None:
        return _korean_registered

    with _korean_lock:
        if _korean_registered is not None:
            return _korean_registered
        try:
            from reportlab.lib.fonts import addMapping
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont

            pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_FONT))
            # One weight, mapped the way the Chinese pack is: a bold heading
            # comes back in the same face rather than a synthesised or Latin
            # bold, because either of those would render the run as boxes.
            pdfmetrics.registerFontFamily(
                KOREAN_FONT,
                normal=KOREAN_FONT,
                bold=KOREAN_FONT,
                italic=KOREAN_FONT,
                boldItalic=KOREAN_FONT,
            )
            for bold_flag in (0, 1):
                for italic_flag in (0, 1):
                    addMapping(KOREAN_FONT, bold_flag, italic_flag, KOREAN_FONT)
            _korean_registered = True
            logger.debug("PDF fonts: registered CID face %s (referenced, not embedded)", KOREAN_FONT)
        except Exception as exc:  # noqa: BLE001 - degrade, never break PDF output
            _korean_registered = False
            logger.warning(
                "PDF fonts: could not register the CID face %s (%s); Korean text will not render",
                KOREAN_FONT,
                exc,
            )
        return _korean_registered


# -- Coverage: ask the font, do not assume from a range -----------------------

#: Answers to "can this face draw this character", keyed by face name and
#: codepoint. The alphabet a document draws is small and fixed in practice - a
#: few hundred distinct characters across a whole run - so this saturates almost
#: immediately and every later question is a dict hit. Never holds an entry for
#: an unregistered face: see :func:`font_can_draw`.
_coverage: dict[tuple[str, int], bool] = {}
_coverage_lock = Lock()

#: reportlab's single-byte encodings, and the Python codec that decides what
#: fits in them. A Type-1 built-in can only draw what its encoding can address.
_ENCODING_CODECS = {
    "WinAnsiEncoding": "cp1252",
    "MacRomanEncoding": "mac_roman",
    "PDFDocEncoding": "cp1252",
}

#: Faces that are already bold, so escalating from one keeps the weight.
_BOLD_FACES = frozenset({"Helvetica-Bold", "Helvetica-BoldOblique", "Times-Bold", "Courier-Bold", BOLD_FONT})


def _encodable(char: str, codec: str) -> bool:
    try:
        char.encode(codec)
    except UnicodeEncodeError:
        return False
    return True


def _cid_pack_covers(char: str) -> bool:
    """Whether the Adobe Simplified Chinese pack carries ``char``.

    This is the one face in the module that cannot be asked directly: reportlab
    holds no CMap and no glyph widths for the Adobe packs, because it names a
    standard CMap and leaves the mapping to the reader. So the question is put
    to the pack's *repertoire* instead, via the two encodings that define it.

    GBK is the character set the Simplified Chinese pack is built around, and
    Python ships the table. It is a far better answer than a hand-written range
    list, which is what stood here before and got two things wrong that matter:
    it missed the squared and cubed metre signs and the degree sign, which are
    ordinary units in a bill of quantities, and it claimed kana were absent when
    the repertoire has carried them since GB 2312.

    The Windows Latin set is unioned in because the pack carries proportional
    roman alongside the ideographs. Without it a mixed string - "规费 (Statutory
    charges)", or a German street next to a Chinese company name - would fail
    every rung and lose its ideographs in order to keep its ASCII.

    Neither encoding reaches Hangul, Thai, Arabic, Hebrew or Devanagari, which
    is correct: this pack does not draw them, and answering ``True`` would swap
    one set of boxes for another while looking like a fix.
    """
    return _encodable(char, "gbk") or _encodable(char, "cp1252")


def _korean_pack_covers(char: str) -> bool:
    """Whether the Adobe Korean pack carries ``char``.

    The Chinese predicate's problem restated for a different pack, and answered
    the same way: reportlab holds no CMap for the Adobe packs, so the question
    goes to the repertoire via the encoding that defines it. EUC-KR is that
    encoding. Python's codec implements the UHC superset, so it reaches all
    11172 modern Hangul syllables rather than the 2350 of the original standard;
    ``cp949`` was measured against it over the whole block and answers
    identically, so neither is more correct and swapping them buys nothing.

    Windows Latin is unioned in for the reason it is unioned into the Chinese
    one: the pack carries proportional roman, and without it a mixed string
    would fail this rung and lose its Hangul in order to keep its ASCII.

    **This predicate overlaps the Chinese one and must stay below it.** Han
    encodes in EUC-KR, so asked in isolation this returns ``True`` for Chinese
    text. What keeps that from re-facing Chinese documents is ladder order in
    :func:`_face_ladder`, not anything here, and the ordering has a test.
    """
    return _encodable(char, "euc_kr") or _encodable(char, "cp1252")


def _single_byte_encoding_covers(font: Any, char: str) -> bool:
    """Whether a Type-1 built-in's encoding can address ``char``, per its own vector."""
    codec = _ENCODING_CODECS.get(getattr(font, "encName", "") or "")
    if codec is None:
        # An encoding we have no codec for. Claim only ASCII, which every
        # reportlab built-in encoding agrees on.
        return ord(char) < 128
    try:
        code = char.encode(codec)
    except UnicodeEncodeError:
        return False
    vector = getattr(getattr(font, "encoding", None), "vector", None)
    if not vector:
        return True
    index = code[0]
    if index >= len(vector):
        return False
    glyph = vector[index]
    return bool(glyph) and glyph != ".notdef"


def font_can_draw(font_name: str, char: str) -> bool:
    """Whether ``font_name`` has a glyph for ``char``, asked of the font itself.

    Three kinds of face answer three different ways, which is why this exists
    rather than a codepoint range:

    * A TrueType face (DejaVu) carries ``charToGlyph``. A missing character is
      absent from it, or maps to glyph 0, which is ``.notdef`` - the box.
    * A Type-1 built-in (Helvetica) carries a single-byte encoding. It can draw
      exactly what that encoding can address, so the question is whether the
      character encodes and whether the vector slot holds a real glyph name.
    * A CID face (STSong-Light) carries neither in this reportlab build, so it
      answers from :data:`_CJK_RANGES`. That one is a declaration, not a
      measurement, and is documented as such where the table is defined.

    A face reportlab cannot resolve answers ``False`` and the answer is **not**
    cached, because the usual reason is that registration has not run yet and
    caching it would make the miss permanent for the life of the process.
    """
    key = (font_name, ord(char))
    cached = _coverage.get(key)
    if cached is not None:
        return cached

    if font_name == CJK_FONT:
        answer = _cid_pack_covers(char)
    elif font_name == KOREAN_FONT:
        answer = _korean_pack_covers(char)
    else:
        try:
            from reportlab.pdfbase import pdfmetrics

            font = pdfmetrics.getFont(font_name)
        except Exception:  # noqa: BLE001 - an unresolvable face draws nothing
            return False
        char_to_glyph = getattr(getattr(font, "face", None), "charToGlyph", None)
        if char_to_glyph is not None:
            answer = bool(char_to_glyph.get(ord(char)))
        else:
            answer = _single_byte_encoding_covers(font, char)

    with _coverage_lock:
        _coverage[key] = answer
    return answer


def font_can_draw_all(font_name: str, text: str | None) -> bool:
    """Whether ``font_name`` can draw every character in ``text``."""
    return all(font_can_draw(font_name, ch) for ch in text or "")


# -- Thai and Devanagari ------------------------------------------------------

#: The bundled Noto faces, embedded rather than referenced. Unlike the Chinese
#: and Korean packs these are real outlines in the repository, because neither
#: script has a CID pack for reportlab to reference.
THAI_FONT = "NotoSansThai"
DEVANAGARI_FONT = "NotoSansDevanagari"

#: Face name -> the file under ``fonts/`` that provides it.
#:
#: These are the faces as their authors published them, and they must stay that
#: way. Subsetting at embed time is ordinary use and reportlab already does it,
#: so the PDF carries only the glyphs a document needs and nothing here makes
#: the output bigger. Subsetting the file *in the repository* is a different
#: act: it produces a modified face, and the OFL binds "in part or in whole", so
#: the cut-down file would still have to travel with its licence and copyright.
#: The practical reason is plainer. A face cut to the glyphs some sample needed
#: silently fails to draw anything outside that set, and the failure looks
#: exactly like the box-glyph bug these faces were added to fix. Leave them
#: whole.
#: They live in a subdirectory of their own, with their licence texts beside
#: them, and that is load bearing rather than tidy. The guard that checks every
#: shipped font has resolvable licence text picks between several licences in
#: one directory by longest shared filename prefix, and ``LICENSE_DEJAVU``
#: shares no prefix with ``DejaVuSans``. It resolved only because it was the
#: sole candidate in that directory. Dropping two more licence files beside it
#: made all three score nothing and left every font in the folder unattributable,
#: DejaVu included. One directory per vendor keeps each family's licence the
#: unambiguous answer for its own fonts and leaves DejaVu exactly as it was.
_BUNDLED_COMPLEX: dict[str, str] = {
    THAI_FONT: "noto/NotoSansThai-Regular.ttf",
    DEVANAGARI_FONT: "noto/NotoSansDevanagari-Regular.ttf",
}

#: The bundled Arabic-script face, for what the Unicode face cannot draw.
#: DejaVu carries every letter and positional form Arabic and Persian need, so
#: those stay in it; it lacks two of Urdu's commonest letters, heh goal and yeh
#: barree, and an Urdu string reaches this rung for them. Noto Naskh Arabic
#: carries the full presentation-form blocks, which matters because
#: :mod:`app.core.pdf_rtl` shapes by substituting those codepoints. Unhinted,
#: 159 KB, SIL Open Font License 1.1.
ARABIC_FONT = "NotoNaskhArabic"

#: The bold weight of the same release (2.021, unhinted, 158 KB, same licence).
#: Without it bold markup on text that only this face can draw printed in the
#: regular weight, so an Urdu heading or total looked like body text.
ARABIC_BOLD_FONT = "NotoNaskhArabic-Bold"

_BUNDLED_RTL: dict[str, str] = {
    ARABIC_FONT: "noto/NotoNaskhArabic-Regular.ttf",
}

#: Bold weights bundled for a complex face, by the face they embolden. A face
#: listed here registers its bold as the bold member of its family; a face that
#: is not keeps mapping bold onto itself.
_BUNDLED_BOLD: dict[str, tuple[str, str]] = {
    ARABIC_FONT: (ARABIC_BOLD_FONT, "noto/NotoNaskhArabic-Bold.ttf"),
}

#: Every bundled face :func:`register_complex_font` can register.
_BUNDLED_FACES: dict[str, str] = {**_BUNDLED_COMPLEX, **_BUNDLED_RTL}

#: Faces whose scripts are wrong without shaping rather than merely unkerned.
#: Read by :func:`pdf_shaping_for_text` and by :func:`pdf_style_for_text`.
#: The Arabic face is deliberately not one of them: its text arrives already
#: shaped and in visual order from :mod:`app.core.pdf_rtl`, and running
#: HarfBuzz over that again would reverse it a second time.
_SHAPED_FACES = frozenset(_BUNDLED_COMPLEX)

_complex_lock = Lock()
_complex_registered: dict[str, bool] = {}
#: Complex face -> its registered bold weight, filled by :func:`_register_bold`.
_complex_bold: dict[str, str] = {}


def register_complex_font(face: str) -> bool:
    """Register one bundled complex-script face with reportlab. Idempotent.

    Lazy and per face, for the same reason :func:`register_cjk_font` is: a
    process that never prints Thai should not pay for parsing a Thai font, and
    neither face may ever become the process-wide body face.

    Returns ``True`` when the face is usable, ``False`` when its file is missing
    or unreadable. Never raises: a missing face costs those scripts their glyphs
    and leaves every other document untouched.
    """
    known = _complex_registered.get(face)
    if known is not None:
        return known

    with _complex_lock:
        known = _complex_registered.get(face)
        if known is not None:
            return known
        try:
            from reportlab.lib.fonts import addMapping
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont

            path = _FONT_DIR / _BUNDLED_FACES[face]
            if not path.is_file():
                raise FileNotFoundError(f"bundled face missing: {path}")
            pdfmetrics.registerFont(TTFont(face, str(path)))
            # Bold resolves to the bundled bold weight when there is one, and to
            # the same face otherwise. Mapping bold onto a Latin bold would print
            # the run as boxes, which is the trade the Chinese pack makes here too.
            bold = _register_bold(face)
            pdfmetrics.registerFontFamily(face, normal=face, bold=bold, italic=face, boldItalic=bold)
            for bold_flag in (0, 1):
                for italic_flag in (0, 1):
                    addMapping(face, bold_flag, italic_flag, bold if bold_flag else face)
            _complex_registered[face] = True
            logger.debug("PDF fonts: registered bundled face %s", face)
        except Exception as exc:  # noqa: BLE001 - degrade, never break PDF output
            _complex_registered[face] = False
            logger.warning(
                "PDF fonts: could not register the bundled face %s (%s); that script will not render",
                face,
                exc,
            )
        return _complex_registered[face]


def _register_bold(face: str) -> str:
    """Register the bundled bold weight of ``face``; the face to use for bold.

    Returns ``face`` itself when no bold is bundled or its file cannot be read,
    so a missing bold costs the weight, never the glyphs.
    """
    entry = _BUNDLED_BOLD.get(face)
    if entry is None:
        return face
    bold_face, relative = entry
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        path = _FONT_DIR / relative
        if not path.is_file():
            raise FileNotFoundError(f"bundled face missing: {path}")
        pdfmetrics.registerFont(TTFont(bold_face, str(path)))
    except Exception as exc:  # noqa: BLE001 - degrade to the regular weight
        logger.warning("PDF fonts: could not register %s (%s); bold prints in the regular weight", bold_face, exc)
        return face
    _complex_bold[face] = bold_face
    return bold_face


def font_needs_shaping(face: str) -> bool:
    """Whether ``face`` draws its script wrongly unless the shaper runs.

    Answers ``False`` when ``uharfbuzz`` is not installed, because then nothing
    can shape and saying otherwise would have callers ask for something they
    cannot get. It is a statement about what this process can actually do, not
    about what the script deserves.
    """
    if face not in _SHAPED_FACES:
        return False
    try:
        from reportlab.pdfbase import pdfmetrics

        return bool(pdfmetrics.getFont(face).shapable)
    except Exception:  # noqa: BLE001 - an unregistered or unshapable face simply does not shape
        return False


def _face_ladder(base: str | None, *, bold: bool) -> tuple[list[str], str]:
    """The faces to try in order, and the one to settle for if none of them fits.

    Lowest rung first, so a string keeps the face it would have had unless that
    face cannot draw it. This is what makes the choice free of side effects for
    existing documents: an ASCII string never leaves rung one, so its bytes do
    not move.

    The settle-for face is the bundled Unicode one rather than the first rung,
    because it is a superset: measured across the whole Windows Latin set it
    draws every character Helvetica draws bar the delete control, which no
    document contains. So a string nothing can fully draw still renders as much
    of itself as this product is able to render, instead of being pinned to the
    narrowest face on the ladder because of one character at the end of it.

    That rule has a sharp edge worth knowing, because it keeps the string whole
    at the cost of the script. Neither bundled Noto face carries the superscript
    digits or the micro sign, so a single ``m2`` written with a superscript two
    beside a Thai description drops the whole string to the Unicode face and the
    Thai renders as boxes, while the same text with a plain digit renders
    correctly. Devanagari behaves the same way. Degree, en dash, euro and the
    multiplication sign are present in both faces and are unaffected, and CJK is
    unaffected because the CID face covers those symbols itself. Fixing it means
    choosing a face per run rather than per string, which is a larger change
    than this function.
    """
    want_bold = bold or (base or "") in _BOLD_FACES
    widest = pdf_font(BOLD_FONT if want_bold else BODY_FONT, bold=want_bold)
    rungs: list[str] = []
    if base:
        rungs.append(base)
    if widest not in rungs:
        rungs.append(widest)
    if register_cjk_font():
        rungs.append(CJK_FONT)
    # Korean sits below Chinese and the order is load bearing rather than
    # stylistic. Han encodes in EUC-KR, so the Korean predicate answers True for
    # Chinese text; put this rung first and every Chinese document silently
    # changes face, renders plausibly, and is wrong. Chinese is asked first, so
    # no string that reaches the Chinese pack today can reach this one.
    if register_korean_font():
        rungs.append(KOREAN_FONT)
    # Thai and Devanagari go last, and unlike the Korean rung the reason is not
    # that they overlap with anything above them. They do not: neither script
    # shares a codepoint with Han or Hangul. The hazard is the opposite one.
    # Both faces carry a full Latin alphabet as well as their own script, so
    # each is a face that can draw "Total" or "2026" perfectly well, and a rung
    # that answers True for plain Latin would capture Latin strings if anything
    # above it ever stopped answering first. Nothing reaches here that an
    # earlier rung can draw, so the position is what keeps a German invoice out
    # of a Thai face.
    for face in _BUNDLED_COMPLEX:
        if register_complex_font(face):
            rungs.append(face)
    # The Arabic face goes last for the same reason. It carries digits and a
    # little punctuation, so nothing an earlier rung can draw should reach it;
    # an Urdu string mixed with Latin letters still settles for the widest face.
    for face in _BUNDLED_RTL:
        if register_complex_font(face):
            rungs.append(_complex_bold.get(face, face) if want_bold else face)
    return rungs, widest


# Characters the layout engine consumes and never draws, so they are not part of
# the coverage question. Leaving them in it is not a small inaccuracy: a string
# of plain Latin carrying a line break comes back drawn in the Chinese pack.
# The route there is worth stating exactly, because it is not the settle-for
# path. Neither the base face nor the bundled Unicode one reports a glyph for a
# line break, but the CID pack does, since it answers coverage from a codepage
# that encodes one, so it satisfies the loop and wins on its own merits while
# the two rungs below it fail. The widest face is never consulted. Listed one at
# a time rather than taken as a category, because a category wide enough to hold
# these also holds the zero-width marks, and those are real characters that a
# face either has or has not got.
_NEVER_DRAWN = "\n\r\t"


def pdf_font_for_text(text: str | None, *, bold: bool = False, base: str | None = None) -> str:
    """Pick the lowest face on the ladder that can draw every character in ``text``.

    Per call, never per process, and per string rather than per document: the
    unit of the decision is the string being drawn, so a Chinese supplier name
    inside a German invoice gets the face it needs without moving anything
    around it.

    ``base`` is where the ladder starts, and it is how a generator keeps its
    existing output byte for byte. Pass the face the generator draws in today
    (``"Helvetica"`` for the legacy ones) and any string that face can already
    draw comes straight back unchanged; only strings it cannot draw escalate.
    Pass the exact face including its weight (``"Helvetica-Bold"``), because the
    first rung is used verbatim; ``bold`` only decides which weight the
    escalation rungs use. Omitting ``base`` starts at the bundled Unicode face,
    which is the right default for a generator that has already been converted.

    ``bold`` is honoured for the Latin faces and ignored for Chinese, which has
    one weight. When no face on the ladder covers the whole string - Hangul and
    Thai are the live examples, since neither the bundled TTF nor the Chinese
    pack carries them - the widest face is returned rather than the narrowest.
    Those characters still will not render, but everything around them does, and
    the gap stays visible instead of being swapped for a different box.

    Line breaks, carriage returns and tabs leave the question before it is
    asked. They are instructions to the layout engine rather than glyphs, so a
    face not having them says nothing about whether it can draw the string, and
    asking anyway sent every string containing one to that widest face. A table
    heading written as ``"A\\nItem"`` is the shape that finds this.
    """
    ladder, widest = _face_ladder(base, bold=bold)
    drawn = "".join(ch for ch in text or "" if ch not in _NEVER_DRAWN)
    for face in ladder:
        if font_can_draw_all(face, drawn):
            return face
    return widest


def pdf_shaping_for_text(text: str | None, *, bold: bool = False, base: str | None = None) -> bool:
    """Whether ``text`` needs the shaper, given the face it will be drawn in.

    Takes the same arguments as :func:`pdf_font_for_text` and answers about the
    face that function would pick, so the two cannot disagree about one string.

    Useful to a caller drawing onto a canvas, and a bare table cell is such a
    caller without looking like one, because reportlab draws a cell that is not
    a flowable through canvas.drawString. Any such caller should read the
    warning that comes with it. ``canvas.drawString(..., shaping=True)``
    does nothing unless ``rlbidi`` is installed: reportlab defines its shaping
    entry point twice and the definition it uses without that package drops the
    argument and returns the text unchanged, with no warning and no error. The
    supported route for Thai and Devanagari is :func:`pdf_style_for_text` and a
    Paragraph, which reaches the shaper by a different path that does work.
    Anything drawn with ``drawString`` will have its glyphs and lack their
    arrangement, which for these two scripts means a page that is wrong rather
    than one that is plain.
    """
    return font_needs_shaping(pdf_font_for_text(text, bold=bold, base=base))


#: The smallest size a line of page furniture is set in before it is cut short.
#: Below six points a footer stops being readable on an office printer, so a
#: name longer than that allows loses its tail rather than its legibility.
MIN_FURNITURE_SIZE = 6.0


def pdf_fit_line(
    text: str,
    width: float,
    *,
    suffix: str = "",
    size: float = 7.0,
    bold: bool = False,
    base: str | None = None,
) -> tuple[str, str, float]:
    """Fit one line of page furniture into ``width`` points.

    A header band or a footer draws a single line of text beside something else
    on the same baseline, usually the page number, so it cannot wrap and cannot
    grow. The company name in it is the firm's own, up to
    :data:`app.core.company_profile.MAX_LEGAL_NAME` characters, which is twice
    the workspace name these lines were written for, and a Chinese name is
    about twice as wide per character as a Latin one.

    Three steps, in order: the line is set at ``size`` if it fits; else it is
    set smaller, down to :data:`MIN_FURNITURE_SIZE`; else ``text`` is cut and
    closed with an ellipsis at that size, keeping ``suffix`` whole, because the
    suffix is usually the generated date and a half-written date is worse than
    a shortened name.

    Every width is measured in the face the line will actually be drawn in, so
    CJK counts at its own width rather than at a Latin approximation.

    Args:
        text: The part that may be cut.
        width: The room available, in points.
        suffix: Text kept whole at the end of the line, cut only if nothing
            else is left.
        size: The size the line is drawn at when it fits.
        bold: Whether the escalation rungs use the bold weight.
        base: The face the caller draws in today, as
            :func:`pdf_font_for_text` means it. Pass it to keep an unchanged
            line byte for byte.

    Returns:
        ``(line, face, size)``: the whole line to draw, the face to draw it in
        and the size to draw it at.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    line = f"{text}{suffix}"
    face = pdf_font_for_text(line, bold=bold, base=base)
    natural = stringWidth(line, face, size)
    if natural <= width or natural <= 0:
        return line, face, size
    smallest = min(size, MIN_FURNITURE_SIZE)
    if natural * smallest / size <= width:
        return line, face, size * width / natural
    # Still too wide at the smallest size, so the name is what has to give.
    ellipsis = "…" if font_can_draw(face, "…") else "..."
    cut = text
    while cut and stringWidth(f"{cut.rstrip()}{ellipsis}{suffix}", face, smallest) > width:
        cut = cut[:-1]
    return f"{cut.rstrip()}{ellipsis}{suffix}", face, smallest


#: The clear space kept between the two ends of a header or footer band.
FURNITURE_GAP = 8.0


def pdf_room_beside(width: float, reserved: str | None, *, size: float = 7.0, gap: float = FURNITURE_GAP) -> float:
    """The width left for a line of furniture beside ``reserved`` on one baseline.

    ``reserved`` is what the renderer draws at the other end of the band, in
    practice the page number, measured in the body face because that is what
    every page number in the app is drawn in. Returns the whole ``width`` when
    nothing shares the baseline.
    """
    if not reserved:
        return width
    from reportlab.pdfbase.pdfmetrics import stringWidth

    return max(0.0, width - stringWidth(reserved, BODY_FONT, size) - gap)


def pdf_style_for_text(style: Any, text: str | None, *, base: str | None = None) -> Any:
    """Return ``style``, or a clone of it faced for a script its own face cannot draw.

    A ``ParagraphStyle`` carries its face in ``fontName``, so a generator that
    builds its styles once cannot serve a Chinese paragraph from them. Mutating
    the style in place would be the same process-wide trap as reassigning
    :data:`BODY_FONT`, one flowable earlier: the style object outlives the
    document. This returns a fresh clone instead and leaves the original alone,
    so the choice is per paragraph and the caller keeps one style table.

    The ladder starts at the style's own ``fontName`` unless ``base`` overrides
    it, so text that face can already draw gets the original object back -
    unchanged, not copied, and identical by identity, not merely by value.
    Nothing about an existing document changes by routing it through here.

    Args:
        style: A reportlab ``ParagraphStyle`` (or anything with ``clone``).
        text: The string this style is about to render.
        base: Start the ladder at this face instead of the style's own.

    Returns:
        The same style, or a clone of it faced for the string.
    """
    start = base or getattr(style, "fontName", None) or BODY_FONT
    face = pdf_font_for_text(text, base=start)
    shaping = font_needs_shaping(face)
    if face == start:
        # The style already names the right face. It still needs shaping turned
        # on if that face is a complex-script one, and it is cloned rather than
        # written to for the reason in the docstring above: this object outlives
        # the document. A style that already has shaping on is returned by
        # identity, so the common Latin path copies nothing.
        if not shaping or getattr(style, "shaping", 0):
            return style
        return style.clone(f"{getattr(style, 'name', 'Style')}-shaped", shaping=1)
    name = f"{getattr(style, 'name', 'Style')}-{face}"
    if shaping:
        return style.clone(name, fontName=face, shaping=1)
    return style.clone(name, fontName=face)


def pdf_fitted_style(style: Any, text: str | None, size: float, *, base: str | None = None) -> Any:
    """A style for one line of furniture already measured by :func:`pdf_fit_line`.

    A footer line that has to shrink is still drawn as a paragraph, because a
    paragraph is the only route through which reportlab's shaper acts, so the
    size the fit arrived at has to reach the style. A line that did not shrink
    gets :func:`pdf_style_for_text` unchanged, which returns the caller's own
    style object for Latin text and so leaves an existing document alone.
    """
    styled = pdf_style_for_text(style, text, base=base)
    if size >= float(getattr(style, "fontSize", size) or size):
        return styled
    # Only the size changes. The leading is left where the caller set it because
    # it cancels out: these footers place the paragraph by ``y = c - height``,
    # which pins the top of its box, and reportlab sets the first baseline a
    # font size below that top whatever the leading is. A fitted line never
    # wraps, so no second line is affected either. What the smaller size does
    # move is that baseline, by the difference between the two sizes - at most a
    # point, upward, away from the edge of the sheet.
    return styled.clone(f"{getattr(styled, 'name', 'Style')}-{size:g}", fontSize=size)


def pdf_table_font_commands(
    rows: Sequence[Sequence[Any]],
    *,
    base: str | None = None,
    header_rows: int = 0,
    header_base: str | None = None,
) -> list[tuple[str, tuple[int, int], tuple[int, int], str]]:
    """``FONTNAME`` commands for exactly the table cells their base face cannot draw.

    A bare string in a reportlab table is drawn with the face the ``TableStyle``
    names, so a per-paragraph choice never reaches it: this is where a
    half-wired generator keeps printing boxes while every other assertion
    passes. Append the returned commands after the table's own style and the
    later command wins for those cells only.

    ``base`` is the face those cells are drawn in today. A cell that face can
    already draw produces no command at all, so the table's Latin output is
    untouched and its column widths do not move. Pass what the table actually
    uses, and note that this is rarely one face: a table that names a
    ``FONTNAME`` for its header row and none for its body has a bold Unicode
    header sitting on top of a body that reportlab draws in **Helvetica**,
    because that is what a cell with no ``FONTNAME`` over it falls back to.
    Give the header rows with ``header_rows`` and ``header_base`` so they are
    measured against the face they really have. Getting that wrong is not
    harmless: a header already drawn in a bold Unicode face would otherwise be
    handed a command putting it back to the regular weight.

    Cells holding a flowable (a ``Paragraph``) are skipped, because a flowable
    draws itself with its own style and a ``FONTNAME`` command would not reach
    it anyway. Give those the treatment from :func:`pdf_style_for_text`.

    **These commands choose a face. They do not shape.** A bare cell is drawn
    through ``canvas.drawString``, where reportlab drops its shaping argument
    unless ``rlbidi`` is installed, so a cell holding Thai or Devanagari gets
    the right characters in the wrong arrangement: a page that is wrong rather
    than one that is plain. Nothing in the call signature hints at that, which
    is why it is repeated here instead of left in the module docstring. Text
    that needs shaping belongs in a ``Paragraph`` with
    :func:`pdf_style_for_text`. Korean, Chinese and Latin need no shaping, so
    for those a ``FONTNAME`` command on its own is the whole answer.

    Bold cells resolve to the same single-weight CJK face, so a Chinese heading
    is legible and simply not heavier. That is the same trade
    :func:`register_cjk_font` documents.

    A cell whose first strong character is right-to-left (an Arabic or Hebrew
    name) also gets an ``ALIGN RIGHT`` command, because a bare cell is placed
    by the table and the canvas hook in :mod:`app.core.pdf_rtl` can reorder its
    text but cannot move it. Cells that start in a left-to-right script keep
    the table's own alignment.

    Args:
        rows: The table's data, row-major, as handed to ``Table``.
        base: The face the table draws its body cells in today.
        header_rows: How many leading rows are drawn in a different face.
        header_base: The face those rows are drawn in; defaults to the bold
            Unicode face, which is what a header ``FONTNAME`` usually names.

    Returns:
        A possibly empty list of ``("FONTNAME", (col, row), (col, row), face)``
        and ``("ALIGN", (col, row), (col, row), "RIGHT")`` commands.
    """
    body_base = base or BODY_FONT
    head_base = header_base or BOLD_FONT
    commands: list[tuple[str, tuple[int, int], tuple[int, int], str]] = []
    for row_index, row in enumerate(rows):
        start = head_base if row_index < header_rows else body_base
        for col_index, cell in enumerate(row):
            if not isinstance(cell, str):
                continue
            face = pdf_font_for_text(cell, base=start)
            if face != start:
                commands.append(("FONTNAME", (col_index, row_index), (col_index, row_index), face))
            if text_direction(cell) == "rtl":
                commands.append(("ALIGN", (col_index, row_index), (col_index, row_index), "RIGHT"))
    return commands


# The shaper is asked at one size because its answer does not depend on size.
# Measured across 6, 7, 8, 9, 10, 12, 18 and 36 point on both bundled faces: one
# distinct result each. The generators draw these tables at 7, 8 and 9 point, so
# a size-dependent shaper would force this helper to know every table's
# ``FONTSIZE``, which is a far larger change than shaping once per string. There
# is a test named for this, so the assumption fails loudly rather than rotting.
_SHAPING_SIZE = 12


def _shape_cell(text: str, face: str) -> str:
    """``text`` shaped for ``face``, or ``text`` unchanged if the shaper cannot.

    ``shapeStr`` goes straight to reportlab and reads the face out of its own
    registry, so the face has to be registered before it is called. The build
    path registers lazily through :func:`pdf_font_for_text`, but a caller that
    shapes before anything has resolved that face gets a ``KeyError`` out of
    ``pdfmetrics.getTypeFace`` that reads like a broken install. So this asks
    for the registration itself instead of depending on the order it is called
    in. Registration is idempotent, so asking costs nothing.

    A failure returns the original text, which is the very behaviour this
    function exists to improve on rather than a safe default, and that is why it
    is logged at warning level: a document that prints is worth more than a
    document that raises, but nobody should have to guess why the marks are
    still wrong.
    """
    register_complex_font(face)
    try:
        from reportlab.pdfbase.ttfonts import shapeStr

        # Returned with reportlab's own type still on it rather than flattened
        # to a plain str. That type is what makes shaping safe to apply twice;
        # see the note on the marker helper below.
        return shapeStr(text, face, _SHAPING_SIZE)
    except Exception as exc:  # noqa: BLE001 - see the docstring, printing beats raising
        logger.warning("PDF fonts: could not shape a table cell in %s (%s); it prints unshaped", face, exc)
        return text


def _shaped_text_marker() -> Any:
    """The type reportlab tags already-shaped text with, for use with ``isinstance``.

    Shaping is not idempotent and fails destructively, which is why this exists.
    Shaping a Thai stack once substitutes the tone mark for its raised form at
    U+E000; shaping that result again turns it into U+FFFF, which no face can
    draw, so the cell prints as boxes. Nothing raises and nothing is logged. A
    caller who applies this helper twice, or a generator that gains a second
    call in a later edit, would get a worse page than the one this module set
    out to fix.

    ``ShapedStr`` subclasses ``str``, so text carrying it behaves as a string
    everywhere, and a cell holding one draws byte for byte what the plain string
    draws. Measured, not assumed.

    Returns the empty tuple on a reportlab with no such type, which makes every
    ``isinstance`` check against it False and leaves the previous behaviour.
    """
    try:
        from reportlab.pdfbase.ttfonts import ShapedStr
    except Exception:  # noqa: BLE001 - an older reportlab simply has no marker to read
        return ()
    return ShapedStr


def pdf_table_shaped_rows(
    rows: Sequence[Sequence[Any]],
    *,
    base: str | None = None,
    header_rows: int = 0,
    header_base: str | None = None,
) -> list[list[Any]]:
    """``rows`` with every bare cell that needs shaping already shaped.

    :func:`pdf_table_font_commands` gives a cell the right face and cannot give
    it the right shape, because a bare cell is drawn through
    ``canvas.drawString``, where reportlab discards its shaping argument unless
    ``rlbidi`` is installed. Thai and Devanagari in a plain cell therefore come
    out as the right characters in the wrong arrangement. Shaping the text
    before it reaches the table sidesteps that: the cell then holds the glyphs
    the shaper chose, and the draw call has nothing left to do. This needs no
    new dependency, because the shaper is :mod:`uharfbuzz`, which already ships.

    Call this before building the ``Table``, and give it the same ``base``,
    ``header_rows`` and ``header_base`` you give :func:`pdf_table_font_commands`.
    Both resolve the face the same way, so the same arguments are what keep them
    agreeing about which face each cell is in.

    Only cells whose face reports :func:`font_needs_shaping` are touched, and
    that is what keeps this away from the common case: Latin, Korean, Chinese
    and Arabic all answer ``False`` and come back untouched. The narrowness is
    the point rather than an optimisation. Handing Latin to the shaper applies
    its ligatures, so ``five`` becomes one glyph and the column width moves with
    it; a version of this that shaped every cell would quietly rewrite English
    documents while looking like it only touched Thai.

    Cells holding a flowable are left alone, because a ``Paragraph`` shapes
    itself through :func:`pdf_style_for_text` and never had this problem.

    Applying this twice is safe, and it needs to be, because shaping is not
    idempotent and fails destructively: shaping an already shaped Thai stack
    turns the substituted mark into U+FFFF, which no face draws, silently. Text
    this function has shaped carries reportlab's ``ShapedStr`` type and is
    skipped on any later pass, so a generator that gains a second call does not
    quietly start printing boxes.

    Args:
        rows: The table's data, row-major, as it would be handed to ``Table``.
        base: The face the table draws its body cells in today.
        header_rows: How many leading rows are drawn in a different face.
        header_base: The face those rows are drawn in.

    Returns:
        A new row structure, always, so the type a caller gets back does not
        depend on what happened to be in the table. Only the shaped cells are
        replaced: every other cell is the same object that was passed in, which
        is the guarantee that matters, because it is the cells rather than the
        lists around them that carry a document's text.
    """
    body_base = base or BODY_FONT
    head_base = header_base or BOLD_FONT
    already_shaped = _shaped_text_marker()
    shaped_rows = [list(row) for row in rows]
    for row_index, row in enumerate(shaped_rows):
        start = head_base if row_index < header_rows else body_base
        for col_index, cell in enumerate(row):
            if not isinstance(cell, str) or isinstance(cell, already_shaped):
                continue
            # This order is deliberate. ``font_needs_shaping`` answers from the
            # registered font object, and ``pdf_font_for_text`` is what causes a
            # bundled face to be registered at all, so asking the other way
            # round reports False for a face that does need shaping.
            face = pdf_font_for_text(cell, base=start)
            if not font_needs_shaping(face):
                continue
            shaped_rows[row_index][col_index] = _shape_cell(cell, face)
    return shaped_rows


_TABLE_CELL_PADDING = 12.0

#: A column narrower than this is on the page and still not readable: at the
#: eight point these tables draw at it leaves room for about seven characters
#: once the cell padding is taken off. It is a threshold for reporting, not a
#: constraint to enforce. Widening one column here means narrowing another, and
#: the caller has no more paper to give.
_MIN_LEGIBLE_COLUMN = 48.0


def _row_style(style: Any, header_style: Any | None, row_index: int, header_rows: int) -> Any:
    """The style a row's cells are measured and drawn with."""
    if header_style is not None and row_index < header_rows:
        return header_style
    return style


def pdf_table_available_width(doc: Any) -> float:
    """The width a table can actually occupy inside ``doc``'s frame.

    ``doc.width`` is the space between the margins, and that is not the space a
    flowable is given. ``SimpleDocTemplate`` lays its story out in a ``Frame``,
    and a Frame pads by six points on each side, so a table built to
    ``doc.width`` begins six points inside the left margin and ends six points
    past the right one. That is on the paper and off the frame, and at six
    points it reads as a rounding error when it is in fact a whole cell padding.
    A centred table hides it entirely by overflowing both sides equally and
    landing back on the margins, which is why this was worth a named function
    rather than a subtraction at each call site.

    The padding is read from a Frame rather than written down here, so it stays
    reportlab's number. If a future version renames the attribute this falls back
    to the documented default instead of failing in the middle of a report.

    Args:
        doc: A reportlab ``SimpleDocTemplate`` (anything with ``width``).

    Returns:
        The usable width in points.
    """
    from reportlab.platypus import Frame

    frame = Frame(0.0, 0.0, float(doc.width), 1.0)
    return float(doc.width) - getattr(frame, "_leftPadding", 6.0) - getattr(frame, "_rightPadding", 6.0)


def _natural_column_widths(
    rows: Sequence[Sequence[Any]],
    style: Any,
    *,
    header_style: Any | None = None,
    header_rows: int = 0,
    padding: float = _TABLE_CELL_PADDING,
) -> list[float]:
    """The width each column would take if nothing had to fit.

    Measuring is the expensive part of laying a table out - one
    ``stringWidth`` per cell - so it is done once and the arithmetic that
    follows works on the answer.

    Args:
        rows: The table's cells, as they will be handed to ``Table``.
        style: The paragraph style body cells are drawn with.
        header_style: The style for the first ``header_rows`` rows.
        header_rows: How many leading rows use ``header_style``.
        padding: Horizontal cell padding, both sides together, in points.

    Returns:
        One natural width per column, empty when there are no columns.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    columns = max((len(row) for row in rows), default=0)
    if not columns:
        return []
    natural = [0.0] * columns
    for row_index, row in enumerate(rows):
        row_style = _row_style(style, header_style, row_index, header_rows)
        for col_index, cell in enumerate(row):
            if not isinstance(cell, str):
                continue
            faced = pdf_style_for_text(row_style, cell)
            width = stringWidth(cell, faced.fontName, faced.fontSize) + padding
            natural[col_index] = max(natural[col_index], width)
    return natural


def _fit_to_width(natural: Sequence[float], available: float) -> list[float]:
    """Squeeze natural widths into ``available``, taking it from the wide.

    Every column narrower than an equal share keeps its natural width, and
    what remains is divided among the rest, repeatedly, until the division
    holds. A label column stays legible and the prose column beside it
    absorbs the loss.

    Args:
        natural: One natural width per column.
        available: The frame width to fit into.

    Returns:
        One width per column, summing to at most ``available``.
    """
    if sum(natural) <= available:
        return list(natural)
    fitted = list(natural)
    unsettled = list(range(len(natural)))
    room = available
    while unsettled:
        share = room / len(unsettled)
        settled = {index for index in unsettled if natural[index] <= share}
        if not settled:
            for index in unsettled:
                fitted[index] = share
            break
        for index in settled:
            fitted[index] = natural[index]
            room -= natural[index]
        unsettled = [index for index in unsettled if index not in settled]
    return fitted


def pdf_table_legible_columns(
    rows: Sequence[Sequence[Any]],
    available: float,
    style: Any,
    *,
    header_style: Any | None = None,
    header_rows: int = 0,
    padding: float = _TABLE_CELL_PADDING,
) -> int:
    """How many leading columns this table can print and still be read.

    :func:`pdf_table_column_widths` divides the frame between whatever
    columns it is given, and past a point there is nothing left to divide.
    Measured on a landscape A4 frame at the size a dashboard export draws
    at: thirty columns are narrow but drawn, forty make the header row
    taller than the frame and reportlab refuses the table, and eighty
    leave each column narrower than its own padding, at which point
    reportlab is handed a negative content width and raises. The caller
    that hits this is not a stress test - a KPI grouped by a free-text
    field becomes one column per group.

    So the count comes back here and the caller decides what to do with
    the columns beyond it, which has to be something a reader can see:
    dropping them quietly would be a worse defect than the crash.

    The answer is the widest leading run of columns that
    :func:`pdf_table_column_widths` would not squeeze below the legibility
    floor - not ``available`` divided by that floor. The difference
    matters: twenty short columns fit the frame at their own widths with
    room to spare, and a flat division would throw four of them away to
    fix a problem they do not have. Dropping a column only ever frees
    room, so the property is monotone in the count and the answer is found
    by halving rather than by trying every prefix.

    At least one column always comes back, even where the frame cannot
    hold one legibly, because a squeezed column beats a blank page.

    Args:
        rows: The table's cells, as they will be handed to ``Table``.
        available: The frame width to fit into, normally ``doc.width``.
        style: The paragraph style body cells are drawn with.
        header_style: The style for the first ``header_rows`` rows.
        header_rows: How many leading rows use ``header_style``.
        padding: Horizontal cell padding, both sides together, in points.

    Returns:
        How many of the leading columns to keep. ``0`` only when there are
        no columns at all.
    """
    natural = _natural_column_widths(
        rows,
        style,
        header_style=header_style,
        header_rows=header_rows,
        padding=padding,
    )
    if not natural:
        return 0

    def legible(count: int) -> bool:
        head = natural[:count]
        fitted = _fit_to_width(head, available)
        return all(w >= n or w >= _MIN_LEGIBLE_COLUMN for w, n in zip(fitted, head, strict=True))

    if legible(len(natural)):
        return len(natural)
    low, high, best = 1, len(natural), 1
    while low <= high:
        middle = (low + high) // 2
        if legible(middle):
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


def pdf_table_column_widths(
    rows: Sequence[Sequence[Any]],
    available: float,
    style: Any,
    *,
    header_style: Any | None = None,
    header_rows: int = 0,
    padding: float = _TABLE_CELL_PADDING,
    report: str = "table",
) -> list[float]:
    """Column widths that fit ``available``, leaving narrow columns alone.

    A table built without ``colWidths`` is sized by reportlab, and neither of
    the two answers it gives is the one a report wants. With bare string cells
    it sizes each column to its longest string and lets the table grow, so a
    wide export is drawn past the edge of the sheet; nothing raises, nothing is
    logged, and the file still extracts every column, which is exactly why that
    goes unnoticed. With flowable cells it does the opposite and spreads the
    columns across the whole frame, so a two column export that fits
    comfortably today would be stretched out to the margins. Passing widths is
    what avoids both.

    When the natural widths fit, they come back unchanged and the table is laid
    out as it is now. When they do not, the overflow is taken from the wide
    columns only: every column narrower than an equal share keeps its natural
    width, and what remains is divided among the rest, repeatedly, until the
    division holds. A label column stays legible and the prose column beside it
    absorbs the loss, which is not what a flat proportional scaling does to a
    table holding one long value.

    Complex scripts are measured before shaping, so a Thai or Devanagari column
    can come out slightly narrow and wrap once more than it needed to. The text
    is inside the frame either way, which is what this function promises.

    Args:
        rows: The table's cells, as they will be handed to ``Table``.
        available: The frame width to fit into, normally ``doc.width``.
        style: The paragraph style body cells are drawn with.
        header_style: The style for the first ``header_rows`` rows.
        header_rows: How many leading rows use ``header_style``.
        padding: Horizontal cell padding, both sides together, in points.
        report: Named in the log line when columns have to be compressed.

    Returns:
        One width per column, summing to at most ``available``.
    """
    natural = _natural_column_widths(
        rows,
        style,
        header_style=header_style,
        header_rows=header_rows,
        padding=padding,
    )
    if not natural:
        return []
    fitted = _fit_to_width(natural, available)
    squeezed = [w for w, n in zip(fitted, natural, strict=True) if w < n and w < _MIN_LEGIBLE_COLUMN]
    if squeezed:
        logger.warning(
            "%s: %d of %d columns were compressed below %.0fpt to fit the page, narrowest %.0fpt. "
            "The data is on the page, but those columns are hard to read",
            report,
            len(squeezed),
            len(natural),
            _MIN_LEGIBLE_COLUMN,
            min(squeezed),
        )
    return fitted


def pdf_table_paragraph_rows(
    rows: Sequence[Sequence[Any]],
    style: Any,
    *,
    header_style: Any | None = None,
    header_rows: int = 0,
    style_for: Callable[[int, int], Any | None] | None = None,
) -> list[list[Any]]:
    """Wrap bare string cells in Paragraphs, escaped and faced cell by cell.

    A bare cell cannot wrap. reportlab draws it with ``canvas.drawString`` at
    the column's left edge and lets it run on, so a value longer than its
    column is printed over the column beside it, and a table wider than its
    frame is printed off the paper. A Paragraph wraps, and it is also the path
    that shapes, so the same text a bare cell mis-arranges comes out correct
    here.

    Because a Paragraph shapes its own text, cells have to arrive raw. Handing
    the output of :func:`pdf_table_shaped_rows` to this function would shape a
    second time, and shaping twice is destructive rather than idempotent: a
    Thai stack that became a private use codepoint on the first pass becomes
    U+FFFF on the second, which no face draws and nothing downstream can
    recover. That is refused loudly here, because it is invisible on the page
    it produces.

    Cell text is escaped, since a Paragraph parses its argument as markup where
    a bare cell took it literally, and these cells carry whatever a query
    returned. Newlines become line breaks: a bare cell drew them as line
    breaks, and a Paragraph would otherwise collapse them into spaces.

    A ``TableStyle`` cannot reach these cells once they are Paragraphs.
    FONTNAME, FONTSIZE, TEXTCOLOR and ALIGN are read from the paragraph's own
    style, so a table that named a bold label column, a right aligned money
    column or a white header through table commands keeps saying so and stops
    being obeyed. Those commands become dead the moment a cell is wrapped, and
    dead quietly: the text is still on the page, in the wrong weight, the wrong
    alignment, or in black on a dark fill. ``style_for`` is where that intent
    moves to, and a table converted to this path should have its inert commands
    deleted rather than left behind to describe a layout that is no longer
    happening.

    Args:
        rows: The table's cells. Cells that are not strings are left alone.
        style: The paragraph style for body cells.
        header_style: The style for the first ``header_rows`` rows.
        header_rows: How many leading rows use ``header_style``.
        style_for: Called with ``(row_index, column_index)`` for every string
            cell. Return a style to draw that cell with, or ``None`` to keep
            the row's style. This is how per column and per row appearance
            survives the move off table commands.

    Returns:
        A fresh list of rows, with string cells replaced by Paragraphs.

    Raises:
        ValueError: If a cell has already been shaped.
    """
    from reportlab.platypus import Paragraph

    already_shaped = _shaped_text_marker()
    wrapped = [list(row) for row in rows]
    for row_index, row in enumerate(wrapped):
        row_style = _row_style(style, header_style, row_index, header_rows)
        for col_index, cell in enumerate(row):
            if not isinstance(cell, str):
                continue
            if isinstance(cell, already_shaped):
                raise ValueError(
                    "table cell has already been shaped, and a Paragraph shapes its own text. "
                    "Shaping twice destroys the codepoints, so pass raw cells here and drop the "
                    "pdf_table_shaped_rows call for this table."
                )
            cell_style = row_style
            if style_for is not None:
                chosen = style_for(row_index, col_index)
                if chosen is not None:
                    cell_style = chosen
            markup = html.escape(cell).replace(chr(10), "<br/>")
            wrapped[row_index][col_index] = Paragraph(markup, pdf_style_for_text(cell_style, cell))
    return wrapped


# Register eagerly, at import time. Generators capture the face names with
# ``from app.core.pdf_fonts import BODY_FONT, BOLD_FONT``, which snapshots the
# string values at the moment of import. If registration only ran later (inside
# a generator), the Helvetica fallback - implemented by reassigning these module
# globals on failure - would never reach the names those modules already bound,
# so an install with the bundled TTFs missing would hand reportlab the
# unregistered "DejaVuSans" and raise instead of degrading gracefully. Running
# it here finalises BODY_FONT / BOLD_FONT before any importer can read them, and
# the _registered gate keeps every later call a no-op.
register_pdf_fonts()

# Right-to-left shaping and reordering, installed once into reportlab and asked
# about glyph coverage through the same probe the face ladder uses.
install_reportlab_rtl(font_can_draw)


__all__ = [
    "ARABIC_BOLD_FONT",
    "ARABIC_FONT",
    "BODY_FONT",
    "BOLD_FONT",
    "CJK_FONT",
    "DEVANAGARI_FONT",
    "THAI_FONT",
    "font_can_draw",
    "font_can_draw_all",
    "font_needs_shaping",
    "has_cjk",
    "pdf_font",
    "pdf_font_for_text",
    "pdf_shaping_for_text",
    "pdf_style_for_text",
    "pdf_table_available_width",
    "pdf_table_column_widths",
    "pdf_table_font_commands",
    "pdf_table_legible_columns",
    "pdf_table_paragraph_rows",
    "pdf_table_shaped_rows",
    "register_cjk_font",
    "register_complex_font",
    "register_pdf_fonts",
]
