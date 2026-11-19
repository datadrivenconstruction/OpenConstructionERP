# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lines and outlines taken from a drawing already in the drawings module.

CAD files reach the platform through DDC cad2data (the drawings module converts
them and stores the entities); this module never opens a CAD file itself. It
reads the stored entities of one drawing and returns its lines and polylines per
layer, in drawing coordinates, which for a survey drawing are the project CRS.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DrawingLine:
    """One line or polyline of a drawing layer."""

    layer: str
    points: list[tuple[float, float]]
    closed: bool


def _xy(p: object) -> tuple[float, float] | None:
    if isinstance(p, dict) and "x" in p and "y" in p:
        return float(p["x"]), float(p["y"])
    if isinstance(p, list | tuple) and len(p) >= 2:
        return float(p[0]), float(p[1])
    return None


def lines_of(entities: list[dict], layers: set[str] | None = None) -> list[DrawingLine]:
    """LINE, LWPOLYLINE and POLYLINE entities of the given layers (all layers when ``layers`` is empty)."""
    out: list[DrawingLine] = []
    for e in entities:
        layer = str(e.get("layer") or "0")
        if layers and layer not in layers:
            continue
        kind = e.get("type")
        if kind == "LINE":
            a, b = _xy(e.get("start")), _xy(e.get("end"))
            if a and b:
                out.append(DrawingLine(layer, [a, b], False))
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            pts = [q for q in (_xy(v) for v in e.get("vertices") or []) if q is not None]
            if len(pts) >= 2:
                out.append(DrawingLine(layer, pts, bool(e.get("closed"))))
    return out


async def drawing_lines(
    session: AsyncSession, project_id: uuid.UUID, drawing_id: uuid.UUID, layers: set[str] | None = None
) -> list[DrawingLine]:
    """The lines of ``drawing_id``; 404 when the drawing is not in this project."""
    from app.modules.dwg_takeoff.models import DwgDrawing  # noqa: PLC0415
    from app.modules.dwg_takeoff.service import DwgTakeoffService  # noqa: PLC0415

    drawing = await session.get(DwgDrawing, drawing_id)
    if drawing is None or drawing.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawing not found")
    entities = await DwgTakeoffService(session).get_entities(drawing_id)
    return lines_of(entities, layers)


__all__ = ["DrawingLine", "drawing_lines", "lines_of"]
