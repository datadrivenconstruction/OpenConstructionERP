# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Right-to-left text for generated PDFs: Arabic, Persian, Urdu and Hebrew.

reportlab draws glyphs left to right in the order it is handed them and does
no contextual shaping of its own unless the optional ``rlbidi`` package is
present, which this project does not ship. Handed Arabic as it is stored, in
logical order, it printed every letter in its isolated form and the line read
backwards. Hebrew needs no shaping but came out backwards just the same. This
module turns logical text into what reportlab can draw verbatim:

* ``arabic_reshaper`` replaces each Arabic letter with the presentation form
  for its position in the word (isolated, initial, medial, final) and applies
  the mandatory lam-alef ligature;
* ``python-bidi`` resolves the Unicode Bidirectional Algorithm levels, so a
  line mixing Arabic or Hebrew with Latin names and numbers keeps each run in
  its own direction;
* the line is then reordered into visual order and the characters that sit on
  a right-to-left level are mirrored, so ``(ABC)`` inside an Arabic name keeps
  its brackets the right way round.

Only strings that contain a strong right-to-left character are touched. Every
other string comes back as the same object, so Latin, Cyrillic, CJK, Thai and
Devanagari output does not move by a byte.

One helper, applied in one place. :func:`install_reportlab_rtl` wraps the
three canvas string calls (which is also how reportlab draws a bare table
cell) and the paragraph line breaker and painter, so every PDF renderer in the
product gets the same treatment without each one remembering to call it. A
paragraph is shaped before its lines are broken, so widths are measured on
the joined forms, and reordered one line at a time when it is drawn, so a
wrapped Arabic paragraph reads top to bottom rather than from its last line.
A paragraph whose first strong character is right-to-left is drawn
right-aligned when its style asked for left alignment, which is the same rule
a browser applies to ``dir="auto"``.

The transform is idempotent by type: its result is a :class:`VisualText`, and a
second pass returns that object unchanged. Applying bidi twice would reverse
the line back, so callers that already prepared a string can pass it through
the hooked canvas safely.

Both libraries are small and have no dependencies of their own. If either is
missing the hooks are not installed and PDFs print as before, with a single
warning in the log, rather than failing.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from functools import lru_cache
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "RTL_LOCALES",
    "VisualText",
    "has_rtl",
    "install_reportlab_rtl",
    "is_rtl_locale",
    "rtl_support_available",
    "shape_rtl",
    "text_direction",
    "visual_text",
]

#: Languages written right to left among those the product ships.
RTL_LOCALES: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})

_STRONG_RTL = frozenset({"R", "AL"})
_STRONG_LTR = "L"

#: Explicit directional formatting characters. They steer the algorithm and are
#: never drawn; a face that lacks them would print a box in their place.
_BIDI_CONTROLS = frozenset("؜‎‏‪‫‬‭‮⁦⁧⁨⁩")

#: Whitespace that rule L1 returns to the paragraph level at the end of a line.
_L1_WHITESPACE = frozenset({"WS", "S", "B", "BN", "LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"})

_LEVEL_RE = re.compile(r"Level\(\s*(\d+)\s*,?\s*\)")


class VisualText(str):
    """Text already in visual order. Passing it through again is a no-op."""

    __slots__ = ()


def is_rtl_locale(locale: str | None) -> bool:
    """Whether ``locale`` (``"ar"``, ``"fa-IR"``, ``"he_IL"``) is written right to left."""
    language = (locale or "").strip().lower().replace("_", "-").split("-", 1)[0]
    return language in RTL_LOCALES


def has_rtl(text: str | None) -> bool:
    """Whether ``text`` contains a strong right-to-left character."""
    if not text or text.isascii():
        return False
    return any(unicodedata.bidirectional(ch) in _STRONG_RTL for ch in text)


def text_direction(text: str | None) -> str | None:
    """``"rtl"`` or ``"ltr"`` from the first strong character (UAX #9 P2), else ``None``."""
    for ch in text or "":
        kind = unicodedata.bidirectional(ch)
        if kind in _STRONG_RTL:
            return "rtl"
        if kind == _STRONG_LTR:
            return "ltr"
    return None


# -- The two libraries ---------------------------------------------------------

_libs_lock = Lock()
_libs: tuple[Any, Any, dict[str, str], dict[str, str]] | None = None
_libs_failed = False


def _load() -> tuple[Any, Any, dict[str, str], dict[str, str]] | None:
    """Import both libraries once: (reshaper, get_display, mirror map, form -> letter)."""
    global _libs, _libs_failed
    if _libs is not None or _libs_failed:
        return _libs
    with _libs_lock:
        if _libs is not None or _libs_failed:
            return _libs
        try:
            from arabic_reshaper import ArabicReshaper
            from arabic_reshaper.letters import LETTERS_ARABIC
            from bidi import get_display
            from bidi.mirror import MIRRORED

            reshaper = ArabicReshaper(
                configuration={
                    # Diacritics are data. Dropping them would print a name the
                    # record does not hold.
                    "delete_harakat": False,
                    # Word ligatures map onto single presentation glyphs that
                    # the bundled face does not carry; the letters print joined
                    # without them. Lam-alef stays on, it is mandatory.
                    "ARABIC LIGATURE ALLAH": False,
                }
            )
            base_of_form: dict[str, str] = {}
            for letter, forms in LETTERS_ARABIC.items():
                for form in forms:
                    if form:
                        base_of_form.setdefault(form, letter)
            _libs = (reshaper, get_display, dict(MIRRORED), base_of_form)
        except Exception as exc:  # noqa: BLE001 - degrade to the old output, never break a PDF
            _libs_failed = True
            logger.warning(
                "PDF RTL: arabic-reshaper or python-bidi is unavailable (%s); "
                "Arabic, Persian, Urdu and Hebrew print unjoined and in logical order",
                exc,
            )
        return _libs


def rtl_support_available() -> bool:
    """Whether shaping and reordering can run in this process."""
    return _load() is not None


# -- Shaping -------------------------------------------------------------------

#: Asked whether a face has a glyph, as ``probe(face, char)``. Installed by
#: :func:`install_reportlab_rtl`; without it every presentation form is assumed
#: drawable.
_glyph_probe: Callable[[str, str], bool] | None = None


@lru_cache(maxsize=8192)
def _shape_cached(text: str, face: str | None) -> str:
    libs = _load()
    if libs is None:
        return text
    reshaper, _get_display, _mirrored, base_of_form = libs
    shaped = reshaper.reshape(text)
    probe = _glyph_probe
    if face is None or probe is None:
        return shaped
    # A face can carry the letter and still lack one of its positional forms.
    # DejaVu has every form Arabic and Persian need and is missing two of
    # Urdu's (initial heh goal, final yeh barree). The base letter prints as an
    # unjoined but correct glyph; the missing form would print as a box.
    out = []
    for ch in shaped:
        base = base_of_form.get(ch)
        if base is not None and not probe(face, ch) and probe(face, base):
            out.append(base)
        else:
            out.append(ch)
    return "".join(out)


def shape_rtl(text: str, *, face: str | None = None) -> str:
    """Contextual Arabic forms for ``text``, still in logical order.

    Idempotent: presentation forms are not letters the reshaper knows, so a
    second pass leaves them alone. Text without Arabic comes back unchanged.

    Args:
        text: Logical-order text.
        face: The registered font the text will be drawn in. When given, a
            positional form that face cannot draw is replaced by its base
            letter instead of printing as a box.
    """
    if not has_rtl(text) or isinstance(text, VisualText):
        return text
    return _shape_cached(str(text), face)


# -- Reordering ----------------------------------------------------------------


def _levels(text: str, base: int, get_display: Any) -> list[int] | None:
    """The resolved embedding level of every character of one line.

    python-bidi exposes levels only through the debug form of its result, one
    level per UTF-8 byte. The answer is checked against the byte length and
    ``None`` comes back on any mismatch, so a change in that format costs the
    mirroring of brackets and nothing else; a test pins it.
    """
    try:
        dump = get_display(text, base_dir="R" if base else "L", debug=True)
    except Exception:  # noqa: BLE001 - see the docstring
        return None
    # The text itself is printed first and may contain the word, so take the
    # last occurrence: the fields after ``levels`` never hold user text.
    _head, _, tail = str(dump).rpartition("levels:")
    if not tail:
        return None
    body = tail.split("]", 1)[0]
    per_byte = [int(level) for level in _LEVEL_RE.findall(body)]
    encoded = text.encode("utf-8")
    if len(per_byte) != len(encoded):
        return None
    levels: list[int] = []
    offset = 0
    for ch in text:
        levels.append(per_byte[offset])
        offset += len(ch.encode("utf-8"))
    return levels


def _reorder(text: str, levels: list[int], base: int, mirrored: dict[str, str]) -> str:
    """Rules L1 to L4 of UAX #9 for one line, with combining marks kept after their base."""
    levels = list(levels)
    # L1: trailing whitespace and isolate or embedding controls return to the
    # paragraph level, so a space typed at the end of an Arabic cell does not
    # jump to its left edge.
    index = len(text) - 1
    while index >= 0 and unicodedata.bidirectional(text[index]) in _L1_WHITESPACE:
        levels[index] = base
        index -= 1
    for position, ch in enumerate(text):
        if unicodedata.bidirectional(ch) in ("S", "B"):
            levels[position] = base
            back = position - 1
            while back >= 0 and unicodedata.bidirectional(text[back]) in _L1_WHITESPACE:
                levels[back] = base
                back -= 1
    # L2: from the highest level down to the lowest odd one, reverse every run
    # at that level or above.
    order = list(range(len(text)))
    highest = max(levels, default=0)
    lowest_odd = min((level for level in levels if level % 2), default=highest + 1)
    for level in range(highest, lowest_odd - 1, -1):
        start = None
        for position in range(len(order) + 1):
            inside = position < len(order) and levels[order[position]] >= level
            if inside and start is None:
                start = position
            elif not inside and start is not None:
                order[start:position] = order[start:position][::-1]
                start = None
    # L3: a reversed run now has each combining mark in front of its base.
    # reportlab draws marks with no advance over the glyph drawn before them,
    # so put them back after the letter they belong to.
    visual: list[str] = []
    pending: list[str] = []
    for logical in order:
        ch = text[logical]
        if ch in _BIDI_CONTROLS:
            continue
        if levels[logical] % 2:
            # L4: a mirrored character on a right-to-left level is drawn with
            # its mirror glyph.
            ch = mirrored.get(ch, ch)
            if unicodedata.combining(ch):
                pending.append(ch)
                continue
            visual.append(ch)
            if pending:
                visual.extend(reversed(pending))
                pending = []
        else:
            visual.extend(pending)
            pending = []
            visual.append(ch)
    visual.extend(pending)
    return "".join(visual)


@lru_cache(maxsize=8192)
def _visual_line(line: str, direction: str | None, face: str | None) -> str:
    libs = _load()
    if libs is None:
        return line
    _reshaper, get_display, mirrored, _forms = libs
    shaped = _shape_cached(line, face)
    if direction == "rtl":
        base = 1
    elif direction == "ltr":
        base = 0
    else:
        base = 1 if text_direction(shaped) == "rtl" else 0
    levels = _levels(shaped, base, get_display)
    if levels is None:
        display = get_display(shaped, base_dir="R" if base else "L")
        return "".join(ch for ch in display if ch not in _BIDI_CONTROLS)
    return _reorder(shaped, levels, base, mirrored)


def visual_text(text: Any, *, direction: str | None = None, face: str | None = None) -> Any:
    """``text`` shaped and in visual order, ready for reportlab to draw left to right.

    Each line is reordered on its own, so a multi-line cell keeps its line
    order. Anything that is not a string, or has no right-to-left character,
    or already went through here, is returned as the same object.

    Args:
        text: Logical-order text.
        direction: ``"rtl"`` or ``"ltr"`` to fix the paragraph direction, as a
            right-to-left document fixes it for every line; ``None`` takes it
            from the first strong character of each line.
        face: The registered font the text will be drawn in, see
            :func:`shape_rtl`.

    Returns:
        A :class:`VisualText`, or ``text`` itself when nothing needed doing.
    """
    if not isinstance(text, str) or isinstance(text, VisualText) or not has_rtl(text):
        return text
    if _load() is None:
        return text
    lines = str(text).split("\n")
    return VisualText("\n".join(_visual_line(line, direction, face) if has_rtl(line) else line for line in lines))


# -- reportlab hooks -----------------------------------------------------------

_install_lock = Lock()
_installed: bool | None = None


def _direction_of_paragraph(paragraph: Any) -> str | None:
    style = getattr(paragraph, "style", None)
    if str(getattr(style, "wordWrap", "") or "").upper() == "RTL":
        return "rtl"
    for frag in getattr(paragraph, "frags", None) or ():
        found = text_direction(getattr(frag, "text", None) or "")
        if found is not None:
            return found
    return None


def _paragraph_has_rtl(paragraph: Any) -> bool:
    cached = paragraph.__dict__.get("_oe_rtl")
    if cached is None:
        frags = getattr(paragraph, "frags", None) or ()
        cached = any(has_rtl(getattr(frag, "text", None)) for frag in frags) or any(
            has_rtl(word) for frag in frags for word in (getattr(frag, "words", None) or ()) if isinstance(word, str)
        )
        paragraph.__dict__["_oe_rtl"] = cached
    return cached


def _visual_blpara(paragraph: Any, bl_para: Any, direction: str | None) -> Any:
    """A copy of a broken paragraph with every line in visual order."""
    font = getattr(bl_para, "fontName", None) or getattr(getattr(paragraph, "style", None), "fontName", None)
    lines = []
    if getattr(bl_para, "kind", 0) == 0:
        for line in bl_para.lines:
            words = list(line[1])
            joined = " ".join(str(word) for word in words)
            if has_rtl(joined):
                words = visual_text(joined, direction=direction, face=font).split(" ")
            rebuilt = list(line)
            rebuilt[1] = words
            lines.append(tuple(rebuilt) if isinstance(line, tuple) else rebuilt)
    else:
        # A styled line is a list of fragments, one per run of a single style.
        # Each fragment is reordered on its own and, on a right-to-left line,
        # the fragments themselves are reversed. reportlab already reverses
        # them when the style says ``wordWrap='RTL'``, so it is left to do so.
        reverse_frags = (
            direction == "rtl"
            and str(getattr(getattr(paragraph, "style", None), "wordWrap", "") or "").upper() != "RTL"
        )
        for line in bl_para.lines:
            words = []
            for frag in line.words:
                text = getattr(frag, "text", None)
                if isinstance(text, str) and has_rtl(text):
                    frag = frag.clone(text=visual_text(text, direction=direction, face=getattr(frag, "fontName", font)))
                words.append(frag)
            if reverse_frags:
                words.reverse()
            lines.append(line.clone(words=words))
    return bl_para.clone(lines=lines)


def install_reportlab_rtl(glyph_probe: Callable[[str, str], bool] | None = None) -> bool:
    """Teach reportlab to draw right-to-left text. Idempotent; never raises.

    Wraps ``Canvas.drawString``, ``drawRightString`` and ``drawCentredString``
    (a bare table cell is drawn through these), and ``Paragraph.breakLines``
    and ``Paragraph.drawPara``. Each wrapper returns straight to reportlab when
    the text has no right-to-left character, so other output is unchanged.

    Args:
        glyph_probe: ``probe(face, char)``, whether a registered face has a
            glyph; used to fall back from a positional form the face lacks.

    Returns:
        ``True`` when the hooks are in place, ``False`` when a library is
        missing and nothing was changed.
    """
    global _installed, _glyph_probe
    if glyph_probe is not None:
        _glyph_probe = glyph_probe
        _shape_cached.cache_clear()
        _visual_line.cache_clear()
    if _installed is not None:
        return _installed
    with _install_lock:
        if _installed is not None:
            return _installed
        if _load() is None:
            _installed = False
            return False
        try:
            from reportlab.lib.enums import TA_LEFT, TA_RIGHT
            from reportlab.pdfgen.canvas import Canvas
            from reportlab.platypus.paragraph import Paragraph

            def _wrap_canvas(name: str) -> None:
                original = getattr(Canvas, name)
                if getattr(original, "_oe_rtl", False):
                    return

                def draw(self: Any, x: float, y: float, text: Any, *args: Any, **kwargs: Any) -> Any:
                    if isinstance(text, str) and has_rtl(text):
                        text = visual_text(text, face=getattr(self, "_fontname", None))
                    return original(self, x, y, text, *args, **kwargs)

                draw._oe_rtl = True  # type: ignore[attr-defined]
                draw.__wrapped__ = original  # type: ignore[attr-defined]
                draw.__name__ = original.__name__
                draw.__doc__ = original.__doc__
                setattr(Canvas, name, draw)

            for name in ("drawString", "drawRightString", "drawCentredString"):
                _wrap_canvas(name)

            original_break = Paragraph.breakLines
            original_draw = Paragraph.drawPara

            if not getattr(original_break, "_oe_rtl", False):

                def break_lines(self: Any, width: Any) -> Any:
                    if _paragraph_has_rtl(self):
                        for frag in getattr(self, "frags", None) or ():
                            text = getattr(frag, "text", None)
                            if isinstance(text, str) and has_rtl(text):
                                frag.text = shape_rtl(text, face=getattr(frag, "fontName", None))
                    return original_break(self, width)

                break_lines._oe_rtl = True  # type: ignore[attr-defined]
                break_lines.__wrapped__ = original_break  # type: ignore[attr-defined]
                Paragraph.breakLines = break_lines

            if not getattr(original_draw, "_oe_rtl", False):

                def draw_para(self: Any, *args: Any, **kwargs: Any) -> Any:
                    bl_para = getattr(self, "blPara", None)
                    if bl_para is None or not _paragraph_has_rtl(self):
                        return original_draw(self, *args, **kwargs)
                    direction = _direction_of_paragraph(self)
                    style = self.style
                    try:
                        visual = _visual_blpara(self, bl_para, direction)
                    except Exception as exc:  # noqa: BLE001 - print the old way rather than fail
                        logger.warning("PDF RTL: could not reorder a paragraph (%s); it prints in logical order", exc)
                        return original_draw(self, *args, **kwargs)
                    self.blPara = visual
                    if direction == "rtl" and getattr(style, "alignment", TA_LEFT) == TA_LEFT:
                        self.style = style.clone(f"{getattr(style, 'name', 'Style')}-rtl", alignment=TA_RIGHT)
                    try:
                        return original_draw(self, *args, **kwargs)
                    finally:
                        self.blPara = bl_para
                        self.style = style

                draw_para._oe_rtl = True  # type: ignore[attr-defined]
                draw_para.__wrapped__ = original_draw  # type: ignore[attr-defined]
                Paragraph.drawPara = draw_para

            _installed = True
            logger.debug("PDF RTL: reportlab hooks installed")
        except Exception as exc:  # noqa: BLE001 - degrade, never break PDF output
            _installed = False
            logger.warning("PDF RTL: could not install the reportlab hooks (%s)", exc)
        return _installed
