# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Small SVG thumbnails of a changed DWG/DXF region.

Drawn server-side from the stored entity records, so the change list and the
report show the region without the browser loading the whole drawing:
unchanged context grey, the old revision red, the new one blue (the same
colours as the sheet overlay).
"""

from __future__ import annotations

import base64
import math
from collections.abc import Sequence
from typing import Any
from xml.sax.saxutils import escape

from app.modules.drawing_compare.geometry import Rect, points_of, rect_from_points

OLD_COLOUR = "#dc2626"
NEW_COLOUR = "#2563eb"
CONTEXT_COLOUR = "#9ca3af"
_SIZE = 160
_MAX_CONTEXT = 400


def _polyline(rec: dict[str, Any]) -> list[tuple[float, float]]:
    geometry = rec.get("geometry_data") if isinstance(rec.get("geometry_data"), dict) else {}
    assert isinstance(geometry, dict)  # noqa: S101 - narrowed above
    etype = str(rec.get("entity_type") or "").upper()
    if etype in ("CIRCLE", "ARC") and isinstance(geometry.get("center"), dict):
        cx = float(geometry["center"].get("x", 0.0))
        cy = float(geometry["center"].get("y", 0.0))
        r = abs(float(geometry.get("radius") or 0.0))
        start = float(geometry.get("start_angle", 0.0)) if etype == "ARC" else 0.0
        end = float(geometry.get("end_angle", math.tau)) if etype == "ARC" else math.tau
        if end < start:
            end += math.tau
        steps = 24
        return [
            (cx + r * math.cos(start + (end - start) * k / steps), cy + r * math.sin(start + (end - start) * k / steps))
            for k in range(steps + 1)
        ]
    pts = points_of(geometry)
    if geometry.get("closed") and len(pts) > 2:
        pts.append(pts[0])
    return pts


def _path(points: Sequence[tuple[float, float]], view: Rect, scale: float) -> str:
    if not points:
        return ""
    coords = [((px - view.x) * scale, (view.y2 - py) * scale) for px, py in points]
    if len(coords) == 1:
        x, y = coords[0]
        return f"M{x - 2:.1f} {y:.1f}h4M{x:.1f} {y - 2:.1f}v4"
    head = f"M{coords[0][0]:.1f} {coords[0][1]:.1f}"
    return head + "".join(f"L{x:.1f} {y:.1f}" for x, y in coords[1:])


def region_svg(
    region: Rect,
    *,
    context: Sequence[dict[str, Any]],
    old: Sequence[dict[str, Any]],
    new: Sequence[dict[str, Any]],
) -> str:
    """SVG data URL of ``region`` (drawing units, y up) with a 10% margin."""
    pad = max(region.w, region.h) * 0.1 or 1.0
    view = region.expanded(pad)
    scale = _SIZE / max(view.w, view.h)
    layers: list[str] = []
    for colour, records, width in (
        (CONTEXT_COLOUR, context[:_MAX_CONTEXT], 0.6),
        (OLD_COLOUR, old, 1.4),
        (NEW_COLOUR, new, 1.4),
    ):
        d = "".join(_path(_polyline(rec), view, scale) for rec in records)
        if d:
            layers.append(
                f'<path d="{escape(d)}" fill="none" stroke="{colour}" stroke-width="{width}" '
                'stroke-linecap="round" stroke-linejoin="round"/>'
            )
    w, h = view.w * scale, view.h * scale
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
        f'viewBox="0 0 {w:.1f} {h:.1f}"><rect width="100%" height="100%" fill="#ffffff"/>' + "".join(layers) + "</svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def records_in(records: Sequence[Any], region: Rect) -> list[dict[str, Any]]:
    """Entity records whose box touches ``region``."""
    out: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get("geometry_data"), dict):
            continue
        box = rect_from_points(points_of(rec["geometry_data"]))
        if box is not None and box.intersects(region):
            out.append(rec)
    return out
