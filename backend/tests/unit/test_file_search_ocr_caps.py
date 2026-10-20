# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""OOM guards for the file_search OCR rasteriser.

``_extract_ocr_text`` renders each PDF page to a pixmap before OCR. ``get_pixmap``
has no size ceiling, so a large-format sheet (an A0 drawing at 150 DPI is ~35 MP)
or a maliciously oversized page could allocate hundreds of MB and OOM a 3 GB
worker. These tests pin the pure render-scale clamp that bounds every page render
to ``MAX_OCR_PIXELS`` and confirm normal pages are rendered unchanged. Pure
functions - no PDF reader, no tesseract, no database.
"""

from __future__ import annotations

import pytest

from app.modules.file_search.extractors import (
    MAX_OCR_PAGES,
    MAX_OCR_PIXELS,
    OCR_RENDER_DPI,
    _clamp_render_scale,
)


def test_normal_page_keeps_the_target_scale() -> None:
    # A4 in PDF points (595 x 842). At 150 DPI this is ~2 MP, far under the cap,
    # so the render is unchanged - normal documents behave exactly as before.
    scale = _clamp_render_scale(595, 842, OCR_RENDER_DPI, MAX_OCR_PIXELS)
    assert scale == pytest.approx(OCR_RENDER_DPI / 72.0)


def test_huge_page_is_clamped_at_the_pixel_cap() -> None:
    # A 20000 x 20000 pt sheet at 150 DPI would be ~1.7 Gpx; the clamp must pull
    # the scale down so the pixmap lands at (or just under) the cap.
    scale = _clamp_render_scale(20000, 20000, OCR_RENDER_DPI, MAX_OCR_PIXELS)
    assert scale < OCR_RENDER_DPI / 72.0
    rendered_pixels = (20000 * scale) * (20000 * scale)
    assert rendered_pixels <= MAX_OCR_PIXELS * 1.001


def test_degenerate_dimensions_fall_back_to_the_base_scale() -> None:
    # A zero-width page must not divide by zero; it takes the unclamped scale.
    scale = _clamp_render_scale(0, 100, OCR_RENDER_DPI, MAX_OCR_PIXELS)
    assert scale == pytest.approx(OCR_RENDER_DPI / 72.0)


def test_caps_are_sane() -> None:
    assert MAX_OCR_PAGES > 0
    assert MAX_OCR_PIXELS > 0
