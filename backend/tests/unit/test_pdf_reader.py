# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The PDF reader adapter: pages, text, rendering and the vector layer.

Every case reads a PDF written operator by operator in
``tests/_pdf_samples.py``, so the expected geometry is known exactly. The
coordinates are points, top-left origin of the crop box, y down, on the
unrotated page, which is the space takeoff measurements are stored in.
"""

from __future__ import annotations

import pytest

from app.core import pdf_reader
from app.modules.takeoff import recognize
from tests._pdf_samples import DRAWING, FORM_PAGE, FORMS, build_pdf


def _page_drawings(pdf: bytes, index: int = 0) -> list[dict]:
    with pdf_reader.open_pdf(pdf) as doc:
        return doc[index].drawings()


def _items(drawings: list[dict]) -> list[tuple]:
    return [it for path in drawings for it in path["items"]]


def _rects(drawings: list[dict]) -> list[tuple[float, float, float, float]]:
    return [tuple(round(v, 3) for v in it[1]) for it in _items(drawings) if it[0] == "re"]


def test_open_count_and_reject_garbage(tmp_path):
    pdf = build_pdf([{"content": DRAWING}, {"content": ""}])
    assert pdf_reader.page_count(pdf) == 2
    path = tmp_path / "two.pdf"
    path.write_bytes(pdf)
    assert pdf_reader.page_count(path) == 2
    assert pdf_reader.page_count(str(path)) == 2
    with pytest.raises(pdf_reader.PdfReaderError):
        pdf_reader.open_pdf(b"not a pdf at all")
    with pdf_reader.open_pdf(pdf) as doc, pytest.raises(IndexError):
        doc[2]


def test_re_operator_and_h_closed_lines_become_rectangles():
    rects = _rects(_page_drawings(build_pdf([{"content": DRAWING}])))
    # 50 600 200 120 re -> top-left y = 792 - 720 = 72.
    assert (50.0, 72.0, 250.0, 192.0) in rects
    # m l l l h tracing a rectangle is the same rectangle.
    assert (300.0, 72.0, 500.0, 192.0) in rects
    # The three translated 8 x 8 symbols.
    for x in (100.0, 130.0, 160.0):
        assert (x, 484.0, x + 8.0, 492.0) in rects


def test_four_stroked_lines_back_to_start_are_a_quad_and_fills_are_not():
    drawings = _page_drawings(build_pdf([{"content": DRAWING}]))
    quads = [it for it in _items(drawings) if it[0] == "qu"]
    assert len(quads) == 1
    corners = sorted((round(p.x), round(p.y)) for p in quads[0][1])
    assert corners == [(470, 202), (470, 232), (520, 202), (520, 232)]
    fill_only = [p for p in drawings if p["type"] == "f" and p["fill"] == pytest.approx((0.5, 0.5, 0.5), abs=0.01)]
    assert len(fill_only) == 1
    assert "qu" not in [it[0] for it in fill_only[0]["items"]]


def test_fill_then_stroke_merge_and_style_keys():
    drawings = _page_drawings(build_pdf([{"content": DRAWING}]))
    triangle = next(p for p in drawings if p["type"] == "fs" and p["even_odd"])
    assert [it[0] for it in triangle["items"]] == ["l", "l", "l"]
    # h added the closing line explicitly.
    assert tuple(triangle["items"][-1][2]) == (300.0, 592.0)
    assert triangle["fill"] == pytest.approx((0.2, 0.6, 0.2), abs=0.01)
    assert triangle["color"] == pytest.approx((0.0, 0.0, 0.0))
    merged = next(p for p in drawings if p["type"] == "fs" and not p["even_odd"])
    assert merged["items"][0][0] == "re"
    assert merged["fill"] == pytest.approx((0.9, 0.9, 0.1), abs=0.01)
    dashed = next(p for p in drawings if p.get("dashes") not in (None, "[] 0"))
    assert dashed["dashes"] == "[ 6 3 ] 0"
    for path in drawings:
        assert {"items", "type", "rect", "color", "fill", "width", "even_odd", "closePath", "seqno"} <= set(path)


def test_stroke_width_follows_the_transform():
    drawings = _page_drawings(build_pdf([{"content": DRAWING}]))
    # The rotated block is drawn under a 2x scale with a 1.5 pt pen.
    rotated = next(p for p in drawings if p["color"] == pytest.approx((0, 0, 1)) and p["width"] > 2.5)
    assert rotated["width"] == pytest.approx(3.0, abs=1e-3)
    # Rotated rectangles are lines, not 're' items.
    assert [it[0] for it in rotated["items"]] == ["l", "l", "l", "l"]


def test_curves_and_degenerate_segments():
    drawings = _page_drawings(build_pdf([{"content": DRAWING}]))
    curves = [it for it in _items(drawings) if it[0] == "c"]
    assert len(curves) == 3  # one c, one v, one y
    degenerate = next(p for p in drawings if p["rect"][0] == pytest.approx(300.0) and p["rect"][3] > 740)
    # The repeated point and the zero-length curve add nothing.
    assert [it[0] for it in degenerate["items"]] == ["l", "l"]


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotation_keeps_unrotated_coordinates_and_swaps_the_page_size(rotation):
    plain = _page_drawings(build_pdf([{"content": DRAWING}]))
    rotated_pdf = build_pdf([{"content": DRAWING, "rotate": rotation}])
    rotated = _page_drawings(rotated_pdf)
    assert _items(rotated) == _items(plain)
    with pdf_reader.open_pdf(rotated_pdf) as doc:
        page = doc[0]
        assert page.rotation == rotation
        expected = (612.0, 792.0) if rotation == 180 else (792.0, 612.0)
        assert (page.rect.width, page.rect.height) == expected
        rendered = page.render(dpi=72)
        assert (rendered.width, rendered.height) == expected


def test_cropbox_offset_moves_the_origin():
    plain = _rects(_page_drawings(build_pdf([{"content": DRAWING}])))
    cropped_pdf = build_pdf([{"content": DRAWING, "cropbox": (30, 50, 590, 780)}])
    cropped = _rects(_page_drawings(cropped_pdf))
    # x shifts by the crop box's left edge, y by the gap above its top edge.
    assert cropped == [(x0 - 30, y0 - 12, x1 - 30, y1 - 12) for x0, y0, x1, y1 in plain]
    with pdf_reader.open_pdf(cropped_pdf) as doc:
        assert tuple(doc[0].rect) == (0.0, 0.0, 560.0, 730.0)


def test_nested_form_xobjects_compose_their_matrices():
    drawings = _page_drawings(build_pdf([{"content": FORM_PAGE, "xobjects": ["Outer"]}], forms=FORMS))
    rects = _rects(drawings)
    # Inner (30 x 20) at page cm (100, 500) + Outer /Matrix (5, 5) + cm (10, 10).
    assert (115.0, 257.0, 145.0, 277.0) in rects
    # The second Inner is drawn at 2x.
    assert (165.0, 237.0, 225.0, 277.0) in rects
    # The half-size copy of Outer.
    assert (302.5, 549.5, 362.5, 589.5) in rects
    assert len(rects) == 6


def test_text_and_words():
    with pdf_reader.open_pdf(build_pdf([{"content": DRAWING}])) as doc:
        page = doc[0]
        text = page.text()
        assert "Ground floor plan" in text
        assert "Room 1.01 Kitchen 12.5 m2" in text
        words = {w[4]: w[:4] for w in page.words()}
    x0, y0, x1, y1 = words["Ground"]
    # Drawn at baseline y = 760 with 12 pt type: the box sits near the top.
    assert 49 <= x0 <= 51
    assert 18 <= y0 < y1 <= 36


def test_render_png_and_clip():
    with pdf_reader.open_pdf(build_pdf([{"content": DRAWING}])) as doc:
        page = doc[0]
        full = page.render(dpi=144)
        assert (full.width, full.height) == (1224, 1584)
        assert len(full.samples) == full.width * full.height * 3
        assert full.png().startswith(b"\x89PNG")
        part = page.render(zoom=2, clip=(50, 72, 250, 192))
        assert (part.width, part.height) == (400, 240)
        # The clip is the blue rectangle's box, so its outline is in the corner.
        img = part.pil()
        r, g, b = img.getpixel((1, 120))
        assert b > 200 and r < 80


def test_recognizers_read_the_adapter_output():
    drawings = _page_drawings(build_pdf([{"content": DRAWING}]))
    candidates = recognize.recognize_candidates(drawings, 10.0)
    kinds = {c["type"] for c in candidates}
    assert "area" in kinds
    result = recognize.find_similar_symbols(drawings, 104.0, 488.0)
    assert result["seed_found"]
    assert len(result["hits"]) == 3


def test_empty_and_textless_pages():
    with pdf_reader.open_pdf(build_pdf([{"content": ""}])) as doc:
        page = doc[0]
        assert page.drawings() == []
        assert page.text().strip() == ""
        assert page.words() == []
