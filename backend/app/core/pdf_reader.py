"""The one PDF reader the backend uses, built on pypdfium2.

pypdfium2 (Apache-2.0 / BSD-3-Clause) binds PDFium and already ships in every
install under pdfplumber. Everything that opens, counts, reads, renders or
walks the vector layer of a PDF goes through this module, so the engine can
be reasoned about (and licensed) in one place.

Coordinates follow the convention our takeoff data was stored in: points,
origin at the top left of the page's crop box, y growing downwards, on the
UNROTATED page. :meth:`PdfPage.drawings` returns the same dictionaries and
item tuples as the reader this module replaced (``'l'``, ``'c'``, ``'re'``,
``'qu'`` items, ``rect``, ``color``, ``fill``, ``width``, ``type`` ...), so
the recognizers that consume them did not change. Two things PDFium's object
model does not keep (pattern paints, and how a subpath was closed) are read
from the content stream by :mod:`app.core.pdf_paint_scan`.

PDFium is not thread safe and ctypes releases the GIL, so every call into it
is serialised through one process-wide lock.
"""

from __future__ import annotations

import ctypes
import io
import logging
import math
import struct
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from app.core import pdf_paint_scan
from app.core.pdf_paint_scan import CLOSE_EXPLICIT, CLOSE_RECT

__all__ = [
    "PdfDocument",
    "PdfPage",
    "PdfReaderError",
    "Point",
    "Quad",
    "Rect",
    "RenderedPage",
    "open_pdf",
    "page_count",
]

_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


class PdfReaderError(Exception):
    """The document could not be opened or a page could not be read."""


class Point(NamedTuple):
    """A point in page space (top-left origin, y down)."""

    x: float
    y: float


class Rect(NamedTuple):
    """An axis-aligned rectangle in page space."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class Quad(NamedTuple):
    """Four corners of a closed four-sided outline."""

    ul: Point
    ur: Point
    ll: Point
    lr: Point


class RenderedPage(NamedTuple):
    """An RGB raster of one page."""

    width: int
    height: int
    samples: bytes  # packed RGB, row major, ``width * 3`` bytes per row

    @property
    def n(self) -> int:
        return 3

    def pil(self) -> Any:
        from PIL import Image  # noqa: PLC0415 - Pillow arrives with pdfplumber and reportlab

        return Image.frombytes("RGB", (self.width, self.height), self.samples)

    def png(self) -> bytes:
        buf = io.BytesIO()
        self.pil().save(buf, format="PNG")
        return buf.getvalue()


def open_pdf(source: str | Path | bytes | bytearray, password: str | None = None) -> PdfDocument:
    """Open a PDF from a path or from bytes."""
    return PdfDocument(source, password=password)


def page_count(source: str | Path | bytes | bytearray) -> int:
    """Number of pages, raising :class:`PdfReaderError` when unreadable."""
    with open_pdf(source) as doc:
        return doc.page_count


class PdfDocument:
    """An open PDF. Use as a context manager or call :meth:`close`."""

    def __init__(self, source: str | Path | bytes | bytearray, password: str | None = None) -> None:
        if isinstance(source, bytearray):
            source = bytes(source)
        elif isinstance(source, Path):
            source = str(source)
        with _LOCK:
            try:
                self._doc = pdfium.PdfDocument(source, password=password)
            except pdfium.PdfiumError as exc:
                raise PdfReaderError(str(exc)) from exc
        self._pages: list[PdfPage] = []
        self._source = source
        self._password = password
        self._scan_reader: Any = None
        self._scan_checked = False

    def _paint_plan(self, index: int) -> pdf_paint_scan.PaintPlan | None:
        """The content-stream plan of one page; ``None`` when it cannot be read."""
        if not self._scan_checked:
            self._scan_checked = True
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(self._source) if isinstance(self._source, bytes) else self._source)
                if reader.is_encrypted:
                    reader.decrypt(self._password or "")
                self._scan_reader = reader
            except Exception:  # noqa: BLE001 - without the plan the tracer keeps its defaults
                logger.debug("pdf_reader: content scan unavailable", exc_info=True)
        if self._scan_reader is None:
            return None
        try:
            return pdf_paint_scan.page_plan(self._scan_reader, index)
        except Exception:  # noqa: BLE001
            logger.debug("pdf_reader: content scan failed on page %d", index, exc_info=True)
            return None

    @property
    def page_count(self) -> int:
        with _LOCK:
            return len(self._doc)

    def __len__(self) -> int:
        return self.page_count

    def __getitem__(self, index: int) -> PdfPage:
        count = self.page_count
        if index < 0:
            index += count
        if not 0 <= index < count:
            raise IndexError(f"page {index} out of range (document has {count} pages)")
        with _LOCK:
            try:
                page = PdfPage(self._doc[index], index, self._paint_plan)
            except pdfium.PdfiumError as exc:
                raise PdfReaderError(str(exc)) from exc
        self._pages.append(page)
        return page

    def __iter__(self) -> Iterator[PdfPage]:
        for i in range(self.page_count):
            page = self[i]
            try:
                yield page
            finally:
                page.close()

    def close(self) -> None:
        with _LOCK:
            for page in self._pages:
                page.close()
            self._pages.clear()
            self._doc.close()
        self._scan_reader = None

    def __enter__(self) -> PdfDocument:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class PdfPage:
    """One page of an open :class:`PdfDocument`."""

    def __init__(
        self,
        page: pdfium.PdfPage,
        index: int,
        paint_plan: Callable[[int], pdf_paint_scan.PaintPlan | None] | None = None,
    ) -> None:
        self._page = page
        self.index = index
        self._paint_plan = paint_plan
        self._closed = False
        self.rotation = page.get_rotation() % 360
        media = _norm_box(page.get_mediabox())
        crop = _norm_box(page.get_cropbox())
        # The visible box is the crop box clipped to the media box.
        box = (max(crop[0], media[0]), max(crop[1], media[1]), min(crop[2], media[2]), min(crop[3], media[3]))
        if box[2] <= box[0] or box[3] <= box[1]:
            box = media
        self.mediabox = media
        self.cropbox = box

    def close(self) -> None:
        if not self._closed:
            with _LOCK:
                self._page.close()
            self._closed = True

    # ── geometry ────────────────────────────────────────────────────────
    @property
    def rect(self) -> Rect:
        """Page size as displayed, so width and height swap on 90 and 270."""
        w = self.cropbox[2] - self.cropbox[0]
        h = self.cropbox[3] - self.cropbox[1]
        if self.rotation in (90, 270):
            w, h = h, w
        return Rect(0.0, 0.0, w, h)

    @property
    def width(self) -> float:
        return self.rect.width

    @property
    def height(self) -> float:
        return self.rect.height

    def _to_top_left(self) -> tuple[float, float, float, float, float, float]:
        """PDF user space -> unrotated top-left page space."""
        return (1.0, 0.0, 0.0, -1.0, -self.cropbox[0], self.cropbox[3])

    # ── text ────────────────────────────────────────────────────────────
    def text(self) -> str:
        """Plain text of the page in reading order, lines joined by ``\\n``."""
        with _LOCK:
            textpage = self._page.get_textpage()
            try:
                # An explicit count: pypdfium2 4.x reroutes the default call.
                raw = textpage.get_text_range(0, textpage.count_chars())
            finally:
                textpage.close()
        return raw.replace("\r\n", "\n").replace("\r", "\n")

    def words(self) -> list[tuple[float, float, float, float, str]]:
        """Words with their boxes ``(x0, y0, x1, y1, word)`` in page space."""
        e, f = self._to_top_left()[4:]
        out: list[tuple[float, float, float, float, str]] = []
        with _LOCK:
            textpage = self._page.get_textpage()
            try:
                n = pdfium_c.FPDFText_CountChars(textpage.raw)
                cur: list[str] = []
                box = [math.inf, math.inf, -math.inf, -math.inf]
                left, right, bottom, top = (ctypes.c_double() for _ in range(4))

                def flush() -> None:
                    if cur:
                        out.append((box[0] + e, f - box[3], box[2] + e, f - box[1], "".join(cur)))
                    cur.clear()
                    box[:] = [math.inf, math.inf, -math.inf, -math.inf]

                for i in range(n):
                    ch = chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, i))
                    if ch.isspace() or ch in "\x00￾":
                        flush()
                        continue
                    pdfium_c.FPDFText_GetCharBox(textpage.raw, i, left, right, bottom, top)
                    cur.append(ch)
                    box[0] = min(box[0], left.value)
                    box[1] = min(box[1], bottom.value)
                    box[2] = max(box[2], right.value)
                    box[3] = max(box[3], top.value)
                flush()
            finally:
                textpage.close()
        return out

    # ── raster ──────────────────────────────────────────────────────────
    def render(
        self,
        *,
        dpi: float | None = None,
        zoom: float | None = None,
        clip: tuple[float, float, float, float] | None = None,
    ) -> RenderedPage:
        """Rasterise the page (rotation applied) to RGB on white.

        Args:
            dpi: Resolution; ``zoom = dpi / 72``.
            zoom: Scale factor, used when ``dpi`` is not given (default 1).
            clip: Optional ``(x0, y0, x1, y1)`` in displayed page space
                (``self.rect``) to render only that part.
        """
        scale = (dpi / 72.0) if dpi else (zoom or 1.0)
        crop = (0.0, 0.0, 0.0, 0.0)
        if clip is not None:
            r = self.rect
            x0, y0 = max(0.0, clip[0]), max(0.0, clip[1])
            x1, y1 = min(r.x1, clip[2]), min(r.y1, clip[3])
            crop = (x0, r.y1 - y1, r.x1 - x1, y0)  # left, bottom, right, top margins
        with _LOCK:
            bitmap = self._page.render(scale=scale, crop=crop, rev_byteorder=True, may_draw_forms=True)
            try:
                img = bitmap.to_pil()
                if img.mode != "RGB":
                    img = img.convert("RGB")
                rendered = RenderedPage(img.width, img.height, img.tobytes())
            finally:
                bitmap.close()
        return rendered

    # ── vector layer ────────────────────────────────────────────────────
    def drawings(self) -> list[dict[str, Any]]:
        """Vector paths of the page, one dict per painted path.

        Each dict carries ``items`` (``('l', p1, p2)``, ``('c', p1, c1, c2,
        p2)``, ``('re', Rect, orientation)``, ``('qu', Quad)``), ``type``
        (``'f'``, ``'s'`` or ``'fs'``), ``rect``, ``color``, ``fill``,
        ``width``, ``even_odd``, ``closePath``, ``dashes``, ``lineCap``,
        ``lineJoin``, ``fill_opacity``, ``stroke_opacity``, ``seqno`` and
        ``layer``. A fill immediately followed by a stroke of the same path
        is merged into one ``'fs'`` entry. Fills and strokes painted with a
        pattern or a shading are left out, as hatching and gradients are not
        drawn geometry.
        """
        plan = self._paint_plan(self.index) if self._paint_plan else None
        with _LOCK:
            return _Tracer(self._to_top_left()).run(self._page.raw, plan)


def _norm_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = (float(v) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


Matrix = tuple[float, float, float, float, float, float]


def _concat(m: Matrix, n: Matrix) -> Matrix:
    """``m`` then ``n`` (row-vector convention, as in PDF ``cm``)."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)


_SEG_LINE = pdfium_c.FPDF_SEGMENT_LINETO
_SEG_BEZIER = pdfium_c.FPDF_SEGMENT_BEZIERTO
_SEG_MOVE = pdfium_c.FPDF_SEGMENT_MOVETO
_COUNT_SEGMENTS = pdfium_c.FPDFPath_CountSegments
_SEG_CALLS = (
    pdfium_c.FPDFPath_GetPathSegment,
    pdfium_c.FPDFPathSegment_GetPoint,
    pdfium_c.FPDFPathSegment_GetType,
    pdfium_c.FPDFPathSegment_GetClose,
)
_OBJ_PATH = pdfium_c.FPDF_PAGEOBJ_PATH
_OBJ_FORM = pdfium_c.FPDF_PAGEOBJ_FORM
_MAX_FORM_DEPTH = 32
_ALL_KEYS = (
    "closePath",
    "fill",
    "color",
    "width",
    "lineCap",
    "lineJoin",
    "dashes",
    "stroke_opacity",
    "fill_opacity",
    "even_odd",
)


class _Tracer:
    """Turns PDFium path objects into line-art dictionaries.

    The item rules mirror the tracing device of the previous reader: three
    lines closed by ``h`` that form an axis-aligned rectangle (which is also
    how an ``re`` operator decomposes) become one ``'re'`` item; four stroked
    lines that return to their start become a ``'qu'`` item; ``h`` adds the
    closing line explicitly.
    """

    def __init__(self, page_ctm: Matrix) -> None:
        self.page_ctm = page_ctm
        self.out: list[dict[str, Any]] = []
        self.seqno = 0
        self._x = ctypes.c_float()
        self._y = ctypes.c_float()
        self._m = pdfium_c.FS_MATRIX()
        self._fm = ctypes.c_int()
        self._st = ctypes.c_int()
        self._rgba = [ctypes.c_uint() for _ in range(4)]
        self._w = ctypes.c_float()

    def run(self, page: Any, plan: pdf_paint_scan.PaintPlan | None = None) -> list[dict[str, Any]]:
        n = pdfium_c.FPDFPage_CountObjects(page)
        self._walk([pdfium_c.FPDFPage_GetObject(page, i) for i in range(n)], self.page_ctm, 0, plan)
        for path in self.out:
            for k in _ALL_KEYS:
                path.setdefault(k, None)
        return self.out

    def _matrix(self, obj: Any) -> Matrix:
        m = self._m
        if not pdfium_c.FPDFPageObj_GetMatrix(obj, m):
            return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        return (m.a, m.b, m.c, m.d, m.e, m.f)

    def _walk(self, objs: list[Any], parent: Matrix, depth: int, plan: pdf_paint_scan.PaintPlan | None) -> None:
        kinds = [pdfium_c.FPDFPageObj_GetType(obj) for obj in objs]
        # The plan is trusted only when it lines up with PDFium's objects exactly.
        if plan is not None and (
            kinds.count(_OBJ_PATH) != len(plan.paints) or kinds.count(_OBJ_FORM) != len(plan.forms)
        ):
            logger.debug("pdf_reader: content plan does not line up with the page objects")
            plan = None
        paths = forms = 0
        for obj, kind in zip(objs, kinds, strict=True):
            if kind == _OBJ_PATH:
                paint = plan.paints[paths] if plan is not None else None
                paths += 1
                self._path(obj, _concat(self._matrix(obj), parent), paint)
            elif kind == _OBJ_FORM:
                child = plan.forms[forms] if plan is not None else None
                forms += 1
                if depth < _MAX_FORM_DEPTH:
                    ctm = _concat(self._matrix(obj), parent)
                    n = pdfium_c.FPDFFormObj_CountObjects(obj)
                    self._walk([pdfium_c.FPDFFormObj_GetObject(obj, i) for i in range(n)], ctm, depth + 1, child)
                else:
                    self.seqno += 1
            else:
                self.seqno += 1

    def _color(self, getter: Any, obj: Any) -> tuple[tuple[float, float, float] | None, float]:
        r, g, b, a = self._rgba
        if not getter(obj, r, g, b, a):
            return None, 1.0
        return (r.value / 255.0, g.value / 255.0, b.value / 255.0), a.value / 255.0

    def _segments(self, obj: Any) -> list[tuple[int, float, float, bool]]:
        x, y = self._x, self._y
        get_seg, get_point, get_type, get_close = _SEG_CALLS
        segs = []
        append = segs.append
        for i in range(_COUNT_SEGMENTS(obj)):
            seg = get_seg(obj, i)
            get_point(seg, x, y)
            append((get_type(seg), x.value, y.value, get_close(seg) != 0))
        return segs

    def _path(self, obj: Any, ctm: Matrix, paint: tuple[bool, bool, tuple[int, ...]] | None = None) -> None:
        fm, st = self._fm, self._st
        if not pdfium_c.FPDFPath_GetDrawMode(obj, fm, st):
            return
        fill_mode, stroke = fm.value, bool(st.value)
        closes: tuple[int, ...] = ()
        if paint is not None:
            if paint[0]:
                fill_mode = 0
            if paint[1]:
                stroke = False
            closes = paint[2]
        if not fill_mode and not stroke:
            return
        segs = self._segments(obj)
        if not segs:
            return
        if fill_mode:
            fill, alpha = self._color(pdfium_c.FPDFPageObj_GetFillColor, obj)
            items, rect, _ = _trace(segs, ctm, stroke_path=False, closes=closes)
            if items:
                pathdict: dict[str, Any] = {
                    "items": items,
                    "type": "f",
                    "even_odd": fill_mode == pdfium_c.FPDF_FILLMODE_ALTERNATE,
                    "fill_opacity": alpha,
                    "fill": fill if fill is not None else (),
                    "rect": rect,
                    "seqno": self.seqno,
                    "layer": "",
                }
                self._append(pathdict)
            self.seqno += 1
        if stroke:
            color, alpha = self._color(pdfium_c.FPDFPageObj_GetStrokeColor, obj)
            items, rect, close_path = _trace(segs, ctm, stroke_path=True, closes=closes)
            if items:
                factor = math.sqrt(abs(ctm[0] * ctm[3] - ctm[1] * ctm[2]))
                width = self._w.value if pdfium_c.FPDFPageObj_GetStrokeWidth(obj, self._w) else 1.0
                cap = pdfium_c.FPDFPageObj_GetLineCap(obj)
                pathdict = {
                    "items": items,
                    "type": "s",
                    "stroke_opacity": alpha,
                    "color": color if color is not None else (),
                    "width": factor * width,
                    "lineCap": (cap, cap, cap),
                    "lineJoin": float(pdfium_c.FPDFPageObj_GetLineJoin(obj)),
                    "closePath": close_path,
                    "dashes": self._dashes(obj, factor),
                    "rect": rect,
                    "layer": "",
                    "seqno": self.seqno,
                }
                self._append(pathdict)
            self.seqno += 1

    def _dashes(self, obj: Any, factor: float) -> str:
        n = pdfium_c.FPDFPageObj_GetDashCount(obj)
        if n <= 0:
            return "[] 0"
        arr = (ctypes.c_float * n)()
        if not pdfium_c.FPDFPageObj_GetDashArray(obj, arr, n):
            return "[] 0"
        phase = ctypes.c_float()
        pdfium_c.FPDFPageObj_GetDashPhase(obj, phase)
        return "[ " + "".join(f"{factor * v:g} " for v in arr) + f"] {factor * phase.value:g}"

    def _append(self, pathdict: dict[str, Any]) -> None:
        out = self.out
        if (
            out
            and pathdict["type"] == "s"
            and out[-1]["type"] == "f"
            and _same_items(out[-1]["items"], pathdict["items"])
        ):
            prev = out[-1]
            for k, v in pathdict.items():
                if k not in prev:
                    prev[k] = v
            prev["type"] = "fs"
            return
        out.append(pathdict)


def _trace(  # noqa: C901
    segs: list[tuple[int, float, float, bool]],
    ctm: Matrix,
    *,
    stroke_path: bool,
    closes: tuple[int, ...] = (),
) -> tuple[list[tuple], Rect, bool | None]:
    """Replay one PDFium path as path-walker calls and collect items.

    ``closes`` says, for each subpath closed by a line back to its start,
    whether it came from ``h``, from a line drawn before ``h`` or from
    ``re``; PDFium stores all three as the same points.
    """
    a, b, c, d, e, f = ctm
    # Every point transformed once; the walk below works on indices.
    pts = [Point(x * a + y * c + e, x * b + y * d + f) for _, x, y, _ in segs]
    items: list[tuple] = []
    used: list[Point] = []
    last = Point(0.0, 0.0)
    first = last
    have_move = False
    linecount = 0
    close_path: bool | None = None
    # User-space bookkeeping for the degenerate-segment rules.
    cur_u: tuple[float, float] | None = None
    start_u: tuple[float, float] | None = None
    last_cmd = ""
    rect_op = False

    def lineto(k: int) -> None:
        nonlocal last, linecount, cur_u, last_cmd
        u = (segs[k][1], segs[k][2])
        if last_cmd != "m" and cur_u == u and not rect_op:
            return
        p = pts[k]
        used.append(p)
        items.append(("l", last, p))
        last = p
        cur_u = u
        last_cmd = "l"
        linecount += 1
        if linecount == 4 and stroke_path:
            _check_quad(items)
            if items[-1][0] == "qu":
                linecount = 0

    def closepath() -> None:
        nonlocal linecount, last, have_move, close_path, cur_u, last_cmd
        if last_cmd in ("", "h"):
            return
        cur_u = start_u
        last_cmd = "h"
        if linecount == 3 and _check_rect(items):
            linecount = 0
            return
        linecount = 0
        if have_move:
            if last != first:
                items.append(("l", last, first))
                last = first
            close_path = False
        else:
            close_path = True
        have_move = False

    n_closes = len(closes)
    close_at = 0
    i = 0
    n = len(segs)
    pending_move = -1
    while i < n:
        kind, x, y, close = segs[i]
        if kind == _SEG_MOVE:
            pending_move = i
            i += 1
            continue
        if pending_move >= 0:
            # Consecutive moves collapse into the last one.
            p = pts[pending_move]
            if not used:
                used.append(p)
            last = first = p
            have_move = True
            linecount = 0
            cur_u = start_u = (segs[pending_move][1], segs[pending_move][2])
            last_cmd = "m"
            pending_move = -1
            # An ``re`` keeps its sides even when they have no length.
            rect_op = (
                close_at < n_closes
                and closes[close_at] == CLOSE_RECT
                and i + 3 < n
                and segs[i][0] == segs[i + 1][0] == segs[i + 2][0] == segs[i + 3][0] == _SEG_LINE
                and segs[i + 3][3]
            )
        if kind == _SEG_LINE:
            if close and (x, y) == start_u:
                explicit = close_at < n_closes and closes[close_at] == CLOSE_EXPLICIT
                close_at += 1
                rect_op = False
                if explicit:
                    lineto(i)
                # ``h`` (or ``re``) closing back to the start: the close adds the line.
                closepath()
            else:
                lineto(i)
                if close:
                    closepath()
            i += 1
        elif kind == _SEG_BEZIER and i + 2 < n:
            _, x1, y1, _ = segs[i]
            _, x2, y2, _ = segs[i + 1]
            _, x3, y3, close = segs[i + 2]
            x0, y0 = cur_u if cur_u is not None else (x1, y1)
            straight = (
                (x0 == x1 and y0 == y1 and x2 == x3 and y2 == y3)
                or (x0 == x1 == x2 and y0 == y1 == y2)
                or (x1 == x2 == x3 and y1 == y2 == y3)
            )
            if straight:
                if not (x0 == x1 == x2 == x3 and y0 == y1 == y2 == y3 and last_cmd != "m"):
                    lineto(i + 2)
            else:
                p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2]
                used.append(p1)
                used.append(p2)
                used.append(p3)
                items.append(("c", last, p1, p2, p3))
                last = p3
                cur_u = (x3, y3)
                last_cmd = "c"
                linecount = 0
            if close:
                closepath()
            i += 3
        else:
            i += 1
    if not used:
        return items, Rect(0.0, 0.0, 0.0, 0.0), close_path
    xs = [p.x for p in used]
    ys = [p.y for p in used]
    return items, Rect(min(xs), min(ys), max(xs), max(ys)), close_path


_F32 = struct.Struct("<f")


def _f32(v: float) -> float:
    return _F32.unpack(_F32.pack(v))[0]


def _same_items(a: list[tuple], b: list[tuple]) -> bool:
    """Equal items, allowing for the float noise of two separately placed objects.

    The previous reader compared single-precision points, so a fill and a
    stroke of one path drawn as two objects are equal when they agree in
    single precision.
    """
    if a == b:
        return True
    if len(a) != len(b):
        return False
    for ia, ib in zip(a, b, strict=True):
        if ia[0] != ib[0] or len(ia) != len(ib):
            return False
        for va, vb in zip(ia[1:], ib[1:], strict=True):
            if isinstance(va, int):
                if va != vb:
                    return False
                continue
            fa = va if isinstance(va, Rect) else (va.ul + va.ur + va.ll + va.lr if isinstance(va, Quad) else va)
            fb = vb if isinstance(vb, Rect) else (vb.ul + vb.ur + vb.ll + vb.lr if isinstance(vb, Quad) else vb)
            if any(x != y and _f32(x) != _f32(y) for x, y in zip(fa, fb, strict=True)):
                return False
    return True


def _check_quad(items: list[tuple]) -> None:
    """Four consecutive lines returning to their start become one ``'qu'``."""
    lines = items[-4:]
    if lines[3][2] != lines[0][1]:
        return
    p0, p1, p2, p3 = (ln[1] for ln in lines)
    items[-4:] = [("qu", Quad(p0, p3, p1, p2))]


def _check_rect(items: list[tuple]) -> bool:
    """Three lines tracing an axis-aligned rectangle become one ``'re'``."""
    if len(items) < 3:
        return False
    line0, line2 = items[-3], items[-1]
    ll, lr = line0[1], line0[2]
    ur, ul = line2[1], line2[2]
    if ll.y != lr.y or ll.x != ul.x or ur.y != ul.y or ur.x != lr.x:
        return False
    if ul.y < lr.y:
        rect, orientation = Rect(ul.x, ul.y, lr.x, lr.y), 1
    else:
        rect, orientation = Rect(ll.x, ll.y, ur.x, ur.y), -1
    x0, x1 = sorted((rect.x0, rect.x1))
    y0, y1 = sorted((rect.y0, rect.y1))
    items[-3:] = [("re", Rect(x0, y0, x1, y1), orientation)]
    return True
