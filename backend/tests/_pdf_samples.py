"""Hand-built PDF drawings for the PDF reader tests and the parity harness.

Each sample is written operator by operator, so a test knows exactly which
content stream a reader saw: an ``re`` rectangle and the same rectangle drawn
with four ``l`` operators are different inputs and decode differently.
"""

from __future__ import annotations

import zlib


def build_pdf(
    pages: list[dict],
    *,
    forms: dict[str, tuple[str, tuple[float, float, float, float], str]] | None = None,
) -> bytes:
    """Write a minimal PDF.

    Args:
        pages: One dict per page with ``content`` (the content stream text) and
            optional ``mediabox``, ``cropbox`` (4-tuples), ``rotate`` (int) and
            ``xobjects`` (names of entries in ``forms`` the page uses).
        forms: Form XObjects by name: ``(content, bbox, matrix)`` where
            ``matrix`` is the six numbers of ``/Matrix`` as text (may be empty)
            and ``content`` may itself use other forms by name.

    Returns:
        The PDF file as bytes.
    """
    forms = forms or {}
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    def stream(dict_extra: str, data: str) -> bytes:
        raw = zlib.compress(data.encode("latin-1"))
        return f"<< {dict_extra} /Length {len(raw)} /Filter /FlateDecode >>\nstream\n".encode() + raw + b"\nendstream"

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    form_ids: dict[str, int] = {}
    # Forms may reference earlier forms only, so define them in insertion order.
    for name, (content, bbox, matrix) in forms.items():
        used = [n for n in form_ids if f"/{n} Do" in content]
        xo = " ".join(f"/{n} {form_ids[n]} 0 R" for n in used)
        res = f"/Resources << /Font << /F1 {font_id} 0 R >> /XObject << {xo} >> >>"
        mtx = f"/Matrix [{matrix}]" if matrix else ""
        bb = " ".join(str(v) for v in bbox)
        form_ids[name] = add(stream(f"/Type /XObject /Subtype /Form /BBox [{bb}] {mtx} {res}", content))

    pages_id_placeholder = len(objs) + 1
    add(b"")  # Pages, filled below
    kids: list[int] = []
    for page in pages:
        content_id = add(stream("", page["content"]))
        xo = " ".join(f"/{n} {form_ids[n]} 0 R" for n in page.get("xobjects", ()))
        mb = " ".join(str(v) for v in page.get("mediabox", (0, 0, 612, 792)))
        extra = ""
        if "cropbox" in page:
            extra += " /CropBox [" + " ".join(str(v) for v in page["cropbox"]) + "]"
        if page.get("rotate"):
            extra += f" /Rotate {page['rotate']}"
        body = (
            f"<< /Type /Page /Parent {pages_id_placeholder} 0 R /MediaBox [{mb}]{extra} "
            f"/Resources << /Font << /F1 {font_id} 0 R >> /XObject << {xo} >> >> /Contents {content_id} 0 R >>"
        )
        kids.append(add(body.encode()))
    objs[pages_id_placeholder - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    )
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id_placeholder} 0 R >>".encode())

    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# A drawing that exercises every path shape the recognizer reads.
DRAWING = "\n".join(
    [
        # re operator, stroked: PyMuPDF reports it as one 're' item.
        "0 0 1 RG 2 w 50 600 200 120 re S",
        # Same rectangle drawn with three lines and h.
        "1 0 0 RG 1 w 300 600 m 500 600 l 500 720 l 300 720 l h S",
        # Four lines that return to the start, then h: a 'qu' item.
        "0 0 0 RG 0.5 w 50 400 m 250 400 l 250 550 l 50 550 l 50 400 l h S",
        # Open polyline with a bezier.
        "0 g 0 G 1.5 w 300 400 m 400 450 l 450 380 480 520 560 430 c S",
        # Filled and stroked triangle with even-odd fill.
        "0.2 0.6 0.2 rg 0 0 0 RG 300 200 m 400 300 l 500 200 l h B*",
        # Dashed long line.
        "[6 3] 0 d 0.25 0.25 0.25 RG 50 100 m 560 100 l S [] 0 d",
        # Fill then stroke of the same rectangle as two operators.
        "0.9 0.9 0.1 rg 60 200 80 80 re f 0 0 0 RG 60 200 80 80 re S",
        # A small symbol repeated under a translation: three copies.
        "q 1 0 0 1 100 300 cm 0 0 0 RG 0 0 m 8 0 l 8 8 l 0 8 l h S Q",
        "q 1 0 0 1 130 300 cm 0 0 0 RG 0 0 m 8 0 l 8 8 l 0 8 l h S Q",
        "q 1 0 0 1 160 300 cm 0 0 0 RG 0 0 m 8 0 l 8 8 l 0 8 l h S Q",
        # Scaled and rotated block.
        "q 0.866 0.5 -0.5 0.866 420 60 cm 2 0 0 2 0 0 cm 0 0 1 RG 0 0 20 10 re S Q",
        # Four lines back to the start without h: a 'qu' item when stroked.
        "0 0 0 RG 1 w 470 560 m 520 560 l 520 590 l 470 590 l 470 560 l S",
        # The same outline filled only: fills never collapse to 'qu'.
        "0.5 g 470 520 m 520 520 l 520 550 l 470 550 l 470 520 l h f",
        # CMYK colours and the v / y curve shorthands.
        "0.1 0.7 0.2 0.05 K 0.6 0.1 0 0 k 2 w 60 40 m 120 90 160 40 v 200 10 240 60 y S",
        # Degenerate segments: a repeated point and a zero-length curve.
        "0 G 1 w 300 40 m 340 40 l 340 40 l 380 60 l 380 60 380 60 380 60 c S",
        # Two subpaths in one path, one closed.
        "0 G 250 20 m 280 20 l 280 35 l h 290 20 m 295 35 l S",
        # Text, so text extraction has something to read.
        "BT /F1 12 Tf 50 760 Td (Ground floor plan) Tj ET",
        "BT /F1 9 Tf 300 740 Td (Room 1.01 Kitchen 12.5 m2) Tj ET",
    ]
)

FORM_INNER = "0 0 0 RG 1 w 0 0 m 30 0 l 30 20 l 0 20 l h S 0 0 m 30 20 l S"
FORM_OUTER = "q 1 0 0 1 10 10 cm /Inner Do Q q 2 0 0 2 60 10 cm /Inner Do Q 0 0 1 RG 0 0 120 80 re S"
FORMS = {
    "Inner": (FORM_INNER, (0, 0, 40, 30), ""),
    "Outer": (FORM_OUTER, (0, 0, 200, 120), "1 0 0 1 5 5"),
}
FORM_PAGE = "q 1 0 0 1 100 500 cm /Outer Do Q q 0.5 0 0 0.5 300 200 cm /Outer Do Q"


def sample_pages() -> list[tuple[str, bytes]]:
    """Every generated case as ``(name, pdf_bytes)``."""
    out = [("drawing", build_pdf([{"content": DRAWING}]))]
    for rot in (90, 180, 270):
        out.append((f"rotate_{rot}", build_pdf([{"content": DRAWING, "rotate": rot}])))
    out.append(("cropbox", build_pdf([{"content": DRAWING, "cropbox": (30, 50, 590, 780)}])))
    out.append(
        (
            "cropbox_rotate_90",
            build_pdf([{"content": DRAWING, "cropbox": (30, 50, 590, 780), "rotate": 90}]),
        )
    )
    out.append(("cropbox_frac", build_pdf([{"content": DRAWING, "cropbox": (30.4, 50.6, 590.3, 780.7)}])))
    out.append(("mediabox_offset", build_pdf([{"content": DRAWING, "mediabox": (-20, -40, 600, 800)}])))
    out.append(("forms", build_pdf([{"content": FORM_PAGE, "xobjects": ["Outer"]}], forms=FORMS)))
    out.append(
        ("forms_rotate_270", build_pdf([{"content": FORM_PAGE, "xobjects": ["Outer"], "rotate": 270}], forms=FORMS))
    )
    out.append(("empty", build_pdf([{"content": "BT /F1 12 Tf 72 720 Td (Scanned sheet) Tj ET"}])))
    out.append(
        (
            "multipage",
            build_pdf(
                [{"content": DRAWING}, {"content": FORM_PAGE, "xobjects": ["Outer"]}, {"content": ""}], forms=FORMS
            ),
        )
    )
    return out
