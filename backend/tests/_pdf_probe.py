# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Page-object probes for rendered test PDFs, read through pypdfium2.

``app.core.pdf_reader`` answers what a reader sees (text, words, vectors).
Some tests ask what was *drawn*: which face a run was set in, whether a
character reached the page as glyph zero, where an image landed. Those come
from the page objects, in top-left page points like ``pdf_reader``.
"""

from __future__ import annotations

import ctypes
import re
from typing import Any, NamedTuple

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from app.core import pdf_reader

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


class Run(NamedTuple):
    """One text object: a run of glyphs drawn with one face and size."""

    page: int
    font: str
    size: float
    text: str
    boxes: int  # characters drawn as glyph zero (the empty box), spaces excluded
    x0: float
    x1: float
    top: float  # distance from the top edge of the sheet to the top of the run
    bottom_gap: float  # distance from the bottom of the run to the bottom edge
    page_width: float


class Box(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float


def _page_sizes(pdf: bytes) -> list[tuple[float, float]]:
    with pdf_reader.open_pdf(pdf) as doc:
        return [(page.rect.width, page.rect.height) for page in doc]


def text_runs(pdf: bytes) -> list[Run]:
    """Every text object of the document, in drawing order."""
    out: list[Run] = []
    document = pdfium.PdfDocument(pdf)
    try:
        sizes = _page_sizes(pdf)
        for number, page in enumerate(document, start=1):
            width, height = sizes[number - 1]
            textpage = page.get_textpage()
            try:
                for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_TEXT]):
                    font = pdfium_c.FPDFTextObj_GetFont(obj.raw)
                    n = pdfium_c.FPDFFont_GetBaseFontName(font, None, 0)
                    name = ctypes.create_string_buffer(n)
                    pdfium_c.FPDFFont_GetBaseFontName(font, name, n)
                    size = ctypes.c_float()
                    pdfium_c.FPDFTextObj_GetFontSize(obj.raw, size)
                    count = pdfium_c.FPDFTextObj_GetText(obj.raw, textpage.raw, None, 0)
                    units = (ctypes.c_ushort * count)()
                    pdfium_c.FPDFTextObj_GetText(obj.raw, textpage.raw, units, count)
                    raw_text = bytes(units).decode("utf-16-le").rstrip("\x00")
                    left, bottom, right, top = obj.get_bounds()
                    out.append(
                        Run(
                            page=number,
                            font=_SUBSET_PREFIX.sub("", name.value.decode("latin-1")),
                            size=float(size.value),
                            text=raw_text.replace("\x00", ""),
                            boxes=sum(1 for ch in raw_text if ch == "\x00"),
                            x0=left,
                            x1=right,
                            top=height - top,
                            bottom_gap=bottom,
                            page_width=width,
                        )
                    )
            finally:
                textpage.close()
    finally:
        document.close()
    return out


def image_boxes(pdf: bytes, page: int = 0) -> list[Box]:
    """Boxes (top-left origin, points) of the images painted on a page."""
    document = pdfium.PdfDocument(pdf)
    try:
        height = _page_sizes(pdf)[page][1]
        boxes = []
        for obj in document[page].get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]):
            left, bottom, right, top = obj.get_bounds()
            boxes.append(Box(left, height - top, right, height - bottom))
        return boxes
    finally:
        document.close()


_BFCHAR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_BFRANGE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")


def _to_unicode(font: Any) -> tuple[dict[bytes, str], int]:
    """``(code -> text, code width in bytes)`` from a font's ToUnicode CMap; Latin-1 when it has none."""
    stream = font.get("/ToUnicode")
    if stream is None:
        return {}, 1
    data = stream.get_object().get_data()
    mapping: dict[bytes, str] = {}
    width = 1
    for part in data.split(b"beginbfrange")[1:]:
        for lo, hi, dst in _BFRANGE.findall(part.split(b"endbfrange")[0]):
            width = len(lo) // 2
            for offset in range(int(hi, 16) - int(lo, 16) + 1):
                code = (int(lo, 16) + offset).to_bytes(width, "big")
                mapping[code] = chr(int(dst, 16) + offset)
    for part in data.split(b"beginbfchar")[1:]:
        for src, dst in _BFCHAR.findall(part.split(b"endbfchar")[0]):
            width = len(src) // 2
            mapping[bytes.fromhex(src.decode())] = bytes.fromhex(dst.decode()).decode("utf-16-be")
    return mapping, width


def _raw(operand: Any) -> bytes:
    """The bytes of a string operand as they stand in the file."""
    original = getattr(operand, "original_bytes", None)
    return bytes(original) if original is not None else bytes(operand)


def _decode(raw: bytes, maps: tuple[dict[bytes, str], int]) -> str:
    mapping, width = maps
    return "".join(
        mapping.get(raw[i : i + width], raw[i : i + width].decode("latin-1")) for i in range(0, len(raw), width)
    )


def _apply(ctm: tuple[float, ...], x: float, y: float) -> tuple[float, float]:
    return ctm[0] * x + ctm[2] * y + ctm[4], ctm[1] * x + ctm[3] * y + ctm[5]


def drawn_strings(pdf: bytes) -> list[tuple[int, float, float, str]]:
    """Every string a page shows, as ``(page, x, baseline_y, text)`` in content-stream order.

    The text is the font's own ToUnicode reading of the bytes that were drawn,
    so joined Arabic forms stay joined and a right-to-left run stays in the
    order it was drawn - which text extractors reorder or normalise. Positions
    are in PDF space (bottom-left origin); read ``y`` only to group a row.
    Tracks ``q``/``Q``/``cm`` and ``Tm``, ``Td``, ``TD``, ``T*`` and ``TL``,
    which is what reportlab writes.
    """
    import io

    import pypdf
    from pypdf.generic import ContentStream

    out: list[tuple[int, float, float, str]] = []
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    for number, page in enumerate(reader.pages):
        fonts = (page.get("/Resources") or {}).get("/Font") or {}
        contents = page.get_contents()
        if contents is None:
            continue
        x = y = line_x = line_y = leading = 0.0
        maps: tuple[dict[bytes, str], int] = ({}, 1)
        ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        saved: list[tuple[float, ...]] = []

        for operands, operator in ContentStream(contents, reader).operations:
            if operator == b"q":
                saved.append(ctm)
            elif operator == b"Q":
                ctm = saved.pop() if saved else ctm
            elif operator == b"cm":
                a, b, c, d, e, f = (float(v) for v in operands)
                m = ctm
                ctm = (
                    a * m[0] + b * m[2],
                    a * m[1] + b * m[3],
                    c * m[0] + d * m[2],
                    c * m[1] + d * m[3],
                    e * m[0] + f * m[2] + m[4],
                    e * m[1] + f * m[3] + m[5],
                )
            elif operator == b"Tf":
                maps = _to_unicode(fonts[operands[0]].get_object())
            elif operator == b"Tm":
                line_x, line_y = float(operands[4]), float(operands[5])
                x, y = line_x, line_y
            elif operator in (b"Td", b"TD"):
                line_x, line_y = line_x + float(operands[0]), line_y + float(operands[1])
                x, y = line_x, line_y
                if operator == b"TD":
                    leading = -float(operands[1])
            elif operator == b"TL":
                leading = float(operands[0])
            elif operator == b"T*":
                line_y -= leading
                x, y = line_x, line_y
            elif operator == b"BT":
                x = y = line_x = line_y = 0.0
            elif operator == b"Tj":
                out.append((number, *_apply(ctm, x, y), _decode(_raw(operands[0]), maps)))
            elif operator == b"TJ":
                joined = b"".join(_raw(item) for item in operands[0] if isinstance(item, (bytes, str)))
                out.append((number, *_apply(ctm, x, y), _decode(joined, maps)))
    return out


def embedded_fonts(pdf: bytes) -> list[tuple[str, str]]:
    """``(base font name, file kind)`` of every font on every page; kind is ``ttf``, ``cff``, ``pfa`` or ``n/a``."""
    import io

    import pypdf

    out: list[tuple[str, str]] = []
    for page in pypdf.PdfReader(io.BytesIO(pdf)).pages:
        fonts = (page.get("/Resources") or {}).get("/Font") or {}
        for ref in fonts.values():
            font = ref.get_object()
            descendants = font.get("/DescendantFonts")
            face = descendants[0].get_object() if descendants else font
            descriptor = (face.get("/FontDescriptor") or {}).get_object() if "/FontDescriptor" in face else {}
            kind = "n/a"
            for key, ext in (("/FontFile2", "ttf"), ("/FontFile3", "cff"), ("/FontFile", "pfa")):
                if key in descriptor:
                    kind = ext
            out.append((str(font.get("/BaseFont", "")).lstrip("/"), kind))
    return out
