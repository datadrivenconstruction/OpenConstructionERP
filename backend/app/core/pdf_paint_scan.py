"""Read from the content stream what PDFium's page objects leave out.

Two facts about a painted path do not survive PDFium's object model, and the
vector layer of :mod:`app.core.pdf_reader` depends on both:

* Whether a fill or a stroke uses a pattern or a shading. PDFium reports it
  as a plain colour (grey for a coloured tiling pattern, white for a shading,
  the underlying colour for an uncoloured pattern). The vector layer leaves
  such paints out, because a hatch or a gradient is not drawn geometry.
* How a subpath was closed. ``re``, ``m l l l h`` and ``m l l l l h`` all
  come out of PDFium as the same five points; the vector layer reports the
  first two as a rectangle (or three lines and a closing line) and the last
  as four lines, which a stroke turns into a quadrilateral.

This module reads the content streams with pypdf and records, for every
operator that becomes a PDFium path object, the pattern flags and the
closing style of each subpath that closes with a line. It does the same for
every Form XObject drawn, so the tracer can line the plan up with PDFium's
objects one to one; where they do not line up, the tracer ignores the plan.
"""

from __future__ import annotations

import logging
import re
import struct
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_MAX_DEPTH = 32
CLOSE_IMPLICIT, CLOSE_EXPLICIT, CLOSE_RECT = 0, 1, 2
# Inline images, literal strings (two levels of nesting), hex strings and
# comments carry no operators; they are blanked before splitting on spaces.
_INLINE_IMAGE = re.compile(rb"(?<![^\s])BI\s.*?\sID\s.*?\sEI(?![^\s])", re.DOTALL)
_OPAQUE = re.compile(
    rb"\((?:[^()\\]++|\\.|\((?:[^()\\]++|\\.)*+\))*+\)|<[0-9A-Fa-f\s]*>|%[^\r\n]*",
    re.DOTALL,
)
_DELIMS = re.compile(rb"(<<|>>|[\[\]{}]|/)")
_NAME_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")
_F32 = struct.Struct("<f")

# Operator kinds.
_MOVE, _LINE, _CURVE, _RECT, _CLOSE = 1, 2, 3, 4, 5
_PAINT_FILL, _PAINT_STROKE, _PAINT_BOTH, _PAINT_CLOSE_STROKE, _PAINT_CLOSE_BOTH, _PAINT_NONE = range(6, 12)
_Q_PUSH, _Q_POP, _CS_FILL, _CS_STROKE, _DEV_FILL, _DEV_STROKE, _DO = range(12, 19)
_OPS = {
    b"m": _MOVE,
    b"l": _LINE,
    b"c": _CURVE,
    b"v": _CURVE,
    b"y": _CURVE,
    b"re": _RECT,
    b"h": _CLOSE,
    b"f": _PAINT_FILL,
    b"F": _PAINT_FILL,
    b"f*": _PAINT_FILL,
    b"S": _PAINT_STROKE,
    b"B": _PAINT_BOTH,
    b"B*": _PAINT_BOTH,
    b"s": _PAINT_CLOSE_STROKE,
    b"b": _PAINT_CLOSE_BOTH,
    b"b*": _PAINT_CLOSE_BOTH,
    b"n": _PAINT_NONE,
    b"q": _Q_PUSH,
    b"Q": _Q_POP,
    b"cs": _CS_FILL,
    b"CS": _CS_STROKE,
    b"g": _DEV_FILL,
    b"rg": _DEV_FILL,
    b"k": _DEV_FILL,
    b"G": _DEV_STROKE,
    b"RG": _DEV_STROKE,
    b"K": _DEV_STROKE,
    b"Do": _DO,
}


@dataclass
class PaintPlan:
    """What one content stream paints, in PDFium object order.

    Attributes:
        paints: For each operator that becomes a path object: whether the
            fill uses a pattern, whether the stroke does, and for each
            subpath closed by a line back to its start, in order, where
            that line came from: :data:`CLOSE_IMPLICIT` (added by ``h``),
            :data:`CLOSE_EXPLICIT` (drawn before ``h``) or
            :data:`CLOSE_RECT` (an ``re``).
        forms: The plan of each Form XObject drawn, in order; ``None`` where
            the form could not be read.
    """

    paints: list[tuple[bool, bool, tuple[int, ...]]] = field(default_factory=list)
    forms: list[PaintPlan | None] = field(default_factory=list)


def page_plan(reader: Any, index: int) -> PaintPlan:
    """The paint plan of one page of a pypdf ``PdfReader``."""
    page = reader.pages[index]
    resources = _resolve(page.get("/Resources")) or {}
    contents = page.get_contents()
    data = contents.get_data() if contents is not None else b""
    return _Scanner().scan(data, resources, (False, False), 0)


def _resolve(obj: Any) -> Any:
    return obj.get_object() if hasattr(obj, "get_object") else obj


def _name(token: bytes) -> str:
    raw = token[1:] if token[:1] == b"/" else token
    if b"#" in raw:
        raw = _NAME_ESCAPE.sub(lambda m: bytes((int(m.group(1), 16),)), raw)
    return "/" + raw.decode("latin-1")


def _f32(text: bytes) -> float:
    """A number as PDFium holds it (single precision)."""
    try:
        return _F32.unpack(_F32.pack(float(text)))[0]
    except (ValueError, OverflowError):
        return 0.0


def _tokens(data: bytes) -> list[bytes]:
    if b"BI" in data:
        data = _INLINE_IMAGE.sub(b" ", data)
    data = _OPAQUE.sub(b" ", data)
    return _DELIMS.sub(rb" \1 ", data).split()


class _Scanner:
    def __init__(self) -> None:
        self._cache: dict[tuple[Any, ...], PaintPlan | None] = {}

    @staticmethod
    def _is_pattern_space(name: str, resources: Any) -> bool:
        if name == "/Pattern":
            return True
        spaces = _resolve(resources.get("/ColorSpace")) or {}
        space = _resolve(spaces.get(name))
        if space == "/Pattern":
            return True
        return isinstance(space, list) and len(space) > 0 and _resolve(space[0]) == "/Pattern"

    def _form(self, ref: Any, resources: Any, state: tuple[bool, bool], depth: int) -> PaintPlan | None:
        key = (getattr(ref, "idnum", None) or id(ref), state, id(resources))
        if key in self._cache:
            return self._cache[key]
        plan: PaintPlan | None = None
        try:
            xobj = _resolve(ref)
            inner = _resolve(xobj.get("/Resources")) or resources
            plan = self.scan(xobj.get_data(), inner, state, depth + 1)
        except Exception:  # noqa: BLE001 - an unreadable form only loses the plan
            logger.debug("pdf_paint_scan: form unreadable", exc_info=True)
        self._cache[key] = plan
        return plan

    def scan(self, data: bytes, resources: Any, state: tuple[bool, bool], depth: int) -> PaintPlan:  # noqa: C901
        plan = PaintPlan()
        paints = plan.paints
        fill_pat, stroke_pat = state
        stack: list[tuple[bool, bool]] = []
        # Path state, mirroring how PDFium builds its point list. Points are
        # kept as their operand text and compared as numbers only when needed.
        points = 0
        after_move = False
        start: tuple[bytes, bytes] | None = None
        current: tuple[bytes, bytes] | None = None
        last = 0
        closes: list[int] = []
        xobjects: Any = None
        ops = _OPS
        toks = _tokens(data)
        for i, tok in enumerate(toks):
            kind = ops.get(tok)
            if kind is None:
                continue
            if kind == _LINE:
                points += 1
                after_move = False
                current = (toks[i - 2], toks[i - 1])
                last = _LINE
            elif kind == _MOVE:
                if not (after_move and points):
                    points += 1
                after_move = True
                start = current = (toks[i - 2], toks[i - 1])
                last = _MOVE
            elif kind == _CURVE:
                points += 3
                after_move = False
                current = (toks[i - 2], toks[i - 1])
                last = _CURVE
            elif kind == _RECT:
                points += 4 if after_move else 5
                after_move = False
                start = current = (toks[i - 4], toks[i - 3])
                closes.append(CLOSE_RECT)
                last = _RECT
            elif kind in (_CLOSE, _PAINT_CLOSE_STROKE, _PAINT_CLOSE_BOTH):
                if points:
                    if not _same_point(start, current):
                        closes.append(CLOSE_IMPLICIT)
                        current = start
                    elif last == _LINE:
                        closes.append(CLOSE_EXPLICIT)
                    last = _CLOSE
                if kind != _CLOSE:
                    if points >= 2:
                        paints.append((fill_pat and kind == _PAINT_CLOSE_BOTH, stroke_pat, tuple(closes)))
                    points, after_move, closes, last = 0, False, [], 0
            elif _PAINT_FILL <= kind <= _PAINT_NONE:
                if kind != _PAINT_NONE and points >= 2:
                    fills = kind in (_PAINT_FILL, _PAINT_BOTH)
                    strokes = kind in (_PAINT_STROKE, _PAINT_BOTH)
                    paints.append((fill_pat and fills, stroke_pat and strokes, tuple(closes)))
                points, after_move, closes, last = 0, False, [], 0
            elif kind == _Q_PUSH:
                stack.append((fill_pat, stroke_pat))
            elif kind == _Q_POP:
                if stack:
                    fill_pat, stroke_pat = stack.pop()
            elif kind == _CS_FILL:
                fill_pat = self._is_pattern_space(_name(toks[i - 1]), resources)
            elif kind == _CS_STROKE:
                stroke_pat = self._is_pattern_space(_name(toks[i - 1]), resources)
            elif kind == _DEV_FILL:
                fill_pat = False
            elif kind == _DEV_STROKE:
                stroke_pat = False
            elif kind == _DO:
                if xobjects is None:
                    xobjects = _resolve(resources.get("/XObject")) or {}
                ref = xobjects.get(_name(toks[i - 1]))
                xobj = _resolve(ref) if ref is not None else None
                if xobj is not None and xobj.get("/Subtype") == "/Form":
                    child = self._form(ref, resources, (fill_pat, stroke_pat), depth) if depth < _MAX_DEPTH else None
                    plan.forms.append(child)
        return plan


def _same_point(a: tuple[bytes, bytes] | None, b: tuple[bytes, bytes] | None) -> bool:
    if a == b:
        return True
    if a is None or b is None:
        return False
    return _f32(a[0]) == _f32(b[0]) and _f32(a[1]) == _f32(b[1])
