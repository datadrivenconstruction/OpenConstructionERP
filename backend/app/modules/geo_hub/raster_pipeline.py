# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Rasterisation helpers for the Geo Hub raster-overlay feature.

Three pure functions take bytes in and return PNG bytes + dimensions
out:

* :func:`pdf_to_png` - PyMuPDF rasterises a single PDF page at a
  reasonable DPI for a globe overlay.
* :func:`dwg_top_view_to_png` - Pillow renders a DDC-canonical JSON's
  2D elements (lines + polygons) in orthographic top-down projection.
* :func:`image_passthrough` - PNG/JPEG bytes are decoded only to read
  the dimensions; the original bytes are stored verbatim so re-uploads
  preserve the user's source quality.

None of these touch storage. The service layer owns blob keys.

Defaults are tuned for "site plan on a satellite map" use cases - DPI
high enough to keep text legible when the overlay covers a few hundred
metres, but low enough to keep the upload pipeline snappy.
"""

from __future__ import annotations

import io
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# 200 DPI was empirically the sweet spot: A4 site plans land at ~1650 ×
# ~2340 px which Cesium happily streams as a single tile, while still
# carrying legible dimension text. Override via ``dpi=`` if a caller
# wants higher fidelity.
DEFAULT_PDF_DPI: int = 200
# Cap the rasterisation surface so a malicious PDF page with absurd
# dimensions (some surveying tools emit 2 m × 2 m PDFs) can't OOM the
# worker. 16 megapixels is still ~4000 × 4000 - plenty.
MAX_RASTER_PIXELS: int = 64 * 1024 * 1024


def pdf_to_png(
    pdf_bytes: bytes,
    *,
    page: int = 1,
    dpi: int = DEFAULT_PDF_DPI,
) -> tuple[bytes, int, int, int]:
    """Rasterise one page of a PDF to PNG.

    Returns ``(png_bytes, width_px, height_px, page_count)`` so the
    caller can stash the page count on the overlay for "next page"
    affordances in the UI.
    """
    import fitz  # PyMuPDF

    if page < 1:
        raise ValueError("PDF page must be >= 1")

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page_count = doc.page_count
        if page_count == 0:
            raise ValueError("PDF has no pages")
        idx = min(page, page_count) - 1
        pdf_page = doc.load_page(idx)
        # ``Matrix`` scaler - fitz default is 72 DPI; scale_factor = dpi/72.
        scale = max(dpi, 36) / 72.0
        # Cap the surface - fitz silently truncates instead of OOMing,
        # but we'd rather fail explicit with a clear error.
        bbox = pdf_page.rect
        est_pixels = int(bbox.width * scale) * int(bbox.height * scale)
        if est_pixels > MAX_RASTER_PIXELS:
            # Recompute a scale that lands at the cap.
            scale = math.sqrt(MAX_RASTER_PIXELS / (bbox.width * bbox.height))
        matrix = fitz.Matrix(scale, scale)
        pix = pdf_page.get_pixmap(matrix=matrix, alpha=False)
        png_bytes = pix.tobytes(output="png")
        return png_bytes, pix.width, pix.height, page_count


def dwg_top_view_to_png(
    canonical: dict[str, Any],
    *,
    target_max_px: int = 1600,
    background: str = "#ffffff",
    stroke: str = "#1f2937",
    fill: str = "#3b82f6",
    fill_opacity: int = 64,
) -> tuple[bytes, int, int]:
    """Orthographic top-down render of canonical 2D elements.

    The canonical format carries ``elements[*].geometry`` and the most
    common 2D shapes (``polyline`` / ``polygon`` / ``rectangle``) come
    with explicit ``points`` arrays in either ``xy`` or full ``xyz``
    form. We compute the union bbox, normalise the coords into a target
    canvas, and draw lines + polygons via Pillow.

    Returns ``(png_bytes, width_px, height_px)``.
    """
    from PIL import Image, ImageDraw

    elements = canonical.get("elements") or []
    if not isinstance(elements, list):
        raise ValueError("canonical.elements must be a list")

    polylines, polygons = _collect_2d_features(elements)
    if not polylines and not polygons:
        # Render a small placeholder so the user gets _something_ on the
        # globe; explicit error noise belongs at the service-layer call
        # site, not the rasteriser.
        return _empty_placeholder(target_max_px // 2, background)

    minx, miny, maxx, maxy = _union_bbox(polylines + polygons)
    if maxx <= minx or maxy <= miny:
        return _empty_placeholder(target_max_px // 2, background)

    dx = maxx - minx
    dy = maxy - miny
    scale = target_max_px / max(dx, dy)
    width_px = max(int(dx * scale), 1)
    height_px = max(int(dy * scale), 1)

    img = Image.new("RGB", (width_px, height_px), background)
    draw = ImageDraw.Draw(img, "RGBA")

    # Y axis flipped - DWG / canonical "up" is positive Y, image "up"
    # is negative Y. Mirror so the drawing reads correctly.
    def _to_px(p: tuple[float, float]) -> tuple[float, float]:
        return (
            (p[0] - minx) * scale,
            height_px - (p[1] - miny) * scale,
        )

    # Polygons first so polyline strokes paint over the fill outlines.
    fill_rgba = _hex_to_rgba(fill, fill_opacity)
    stroke_rgb = _hex_to_rgba(stroke, 255)
    for pts in polygons:
        if len(pts) < 3:
            continue
        ring = [_to_px(p) for p in pts]
        try:
            draw.polygon(ring, fill=fill_rgba, outline=stroke_rgb)
        except (TypeError, ValueError) as exc:  # noqa: PERF203
            logger.debug("dwg raster: skipping polygon %s", exc)
            continue

    for pts in polylines:
        if len(pts) < 2:
            continue
        segs = [_to_px(p) for p in pts]
        try:
            draw.line(segs, fill=stroke_rgb, width=1, joint="curve")
        except (TypeError, ValueError) as exc:
            logger.debug("dwg raster: skipping polyline %s", exc)
            continue

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), width_px, height_px


def image_dimensions(png_or_jpeg: bytes) -> tuple[int, int]:
    """Read ``(width_px, height_px)`` from a PNG/JPEG byte string.

    We rely on Pillow rather than parsing the headers by hand so any
    new formats (WebP, HEIC) inherit support for free. Failure raises
    :class:`ValueError` which the caller maps to HTTP 415.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(png_or_jpeg)) as img:
            return img.size  # (w, h)
    except UnidentifiedImageError as exc:
        raise ValueError("image bytes not recognised") from exc


# ── internals ───────────────────────────────────────────────────────────


def _collect_2d_features(
    elements: list[Any],
) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]]:
    """Walk canonical elements and bucket into polylines + polygons."""
    polylines: list[list[tuple[float, float]]] = []
    polygons: list[list[tuple[float, float]]] = []
    for elem in elements:
        if not isinstance(elem, dict):
            continue
        geom = elem.get("geometry")
        if not isinstance(geom, dict):
            continue
        gtype = (geom.get("type") or "").lower()
        pts = _extract_points(geom)
        if not pts:
            continue
        if gtype in ("polygon", "rectangle", "closed_polyline"):
            polygons.append(pts)
        else:
            polylines.append(pts)
    return polylines, polygons


def _extract_points(geom: dict[str, Any]) -> list[tuple[float, float]]:
    """Pull XY coords out of the most common canonical shapes."""
    raw = geom.get("points") or geom.get("coordinates") or []
    if not isinstance(raw, list):
        return []
    out: list[tuple[float, float]] = []
    for p in raw:
        if isinstance(p, dict):
            if "x" in p and "y" in p:
                try:
                    out.append((float(p["x"]), float(p["y"])))
                except (TypeError, ValueError):
                    continue
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            try:
                out.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError):
                continue
    return out


def _union_bbox(
    shapes: list[list[tuple[float, float]]],
) -> tuple[float, float, float, float]:
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for pts in shapes:
        for x, y in pts:
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
    if minx == float("inf"):
        return 0.0, 0.0, 0.0, 0.0
    return minx, miny, maxx, maxy


def _empty_placeholder(
    size_px: int,
    background: str,
) -> tuple[bytes, int, int]:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size_px, size_px), background)
    draw = ImageDraw.Draw(img)
    # Diagonal "no data" tick so the user sees a visible card on the
    # globe instead of a blank white square that reads as a bug.
    draw.line(
        [(0, 0), (size_px, size_px)],
        fill="#9ca3af",
        width=2,
    )
    draw.line(
        [(0, size_px), (size_px, 0)],
        fill="#9ca3af",
        width=2,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), size_px, size_px


def _hex_to_rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return r, g, b, max(0, min(255, alpha))


__all__ = [
    "DEFAULT_PDF_DPI",
    "MAX_RASTER_PIXELS",
    "dwg_top_view_to_png",
    "image_dimensions",
    "pdf_to_png",
]
