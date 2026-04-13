"""Parse DDC DwgExporter Excel output into drawable entities.

DDC DwgExporter produces an Excel file with AutoCAD database records.
Geometry entities (AcDbLine, AcDbPolyline+AcDbVertex, AcDbArc, AcDbCircle,
AcDbBlockReference) have coordinate fields that we extract and convert
into the same JSON format used by the ezdxf-based DXF parser, so the
frontend DxfViewer can render them identically.

Coordinate formats in DDC output:
  - Lines: "295.144, 812.512, 0" (comma-separated)
  - Vertices: "[0.5 0.5]" or "[0.5 0.5 0.0]" (space-separated in brackets)
  - Arcs/Circles: same as lines for Center
"""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ACI (AutoCAD Color Index) → hex color
_ACI_COLORS: dict[int, str] = {
    0: "#000000", 1: "#ff0000", 2: "#ffff00", 3: "#00ff00",
    4: "#00ffff", 5: "#0000ff", 6: "#ff00ff", 7: "#ffffff",
    8: "#808080", 9: "#c0c0c0", 10: "#ff5555", 11: "#ffff55",
    12: "#55ff55", 13: "#55ffff", 14: "#5555ff", 15: "#ff55ff",
    16: "#555555", 40: "#cc8800", 160: "#00cc88", 256: "#cccccc",
}


def _aci_to_hex(aci_str: str | int | None) -> str:
    """Convert ACI color string/int to hex."""
    if aci_str is None:
        return "#cccccc"
    s = str(aci_str).strip()
    # "ACI 40" → 40
    m = re.search(r"(\d+)", s)
    if m:
        idx = int(m.group(1))
        return _ACI_COLORS.get(idx, f"#{min(idx * 37 % 256, 255):02x}{min(idx * 73 % 256, 255):02x}{min(idx * 113 % 256, 255):02x}")
    return "#cccccc"


def _parse_coord_csv(s: str | None) -> tuple[float, float] | None:
    """Parse '295.144, 812.512, 0' → (295.144, 812.512)."""
    if not s or not isinstance(s, str):
        return None
    parts = [p.strip() for p in s.split(",")]
    if len(parts) >= 2:
        try:
            return (float(parts[0]), float(parts[1]))
        except ValueError:
            return None
    return None


def _parse_coord_bracket(s: str | None) -> tuple[float, float] | None:
    """Parse '[0.5 0.5]' or '[0.5 0.5 0.0]' → (0.5, 0.5)."""
    if not s or not isinstance(s, str):
        return None
    nums = re.findall(r"[-\d.]+(?:[eE][+-]?\d+)?", s)
    if len(nums) >= 2:
        try:
            return (float(nums[0]), float(nums[1]))
        except ValueError:
            return None
    return None


def _parse_coord(s: str | None) -> tuple[float, float] | None:
    """Parse coordinate from either format."""
    if not s:
        return None
    s = str(s).strip()
    if s.startswith("["):
        return _parse_coord_bracket(s)
    return _parse_coord_csv(s)


def _parse_angle(s: str | None) -> float:
    """Parse angle in radians from string."""
    if not s:
        return 0.0
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return 0.0


def parse_ddc_dwg_excel(excel_path: str | Path) -> dict[str, Any]:
    """Parse DDC DwgExporter Excel into layers + drawable entities.

    Returns dict compatible with dxf_processor.parse_dxf() output:
    {
        "layers": [...],
        "entities": [...],
        "extents": {"min_x", "min_y", "max_x", "max_y"},
        "units": "unitless",
        "entity_count": N,
    }
    """
    import openpyxl

    wb = openpyxl.load_workbook(str(excel_path), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        return _empty()

    all_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if len(all_rows) < 2:
        return _empty()

    headers = [str(h or "").strip() for h in all_rows[0]]
    h_idx = {h: i for i, h in enumerate(headers)}

    def get(row: tuple, key: str) -> Any:
        i = h_idx.get(key)
        if i is None or i >= len(row):
            return None
        return row[i]

    # ── Pass 1: collect layers ─────────────────────────────────────────
    layers_map: dict[str, dict] = {}
    layer_colors: dict[str, str] = {}

    for row in all_rows[1:]:
        desc = str(get(row, "Description") or "")
        if desc == "<AcDbLayerTableRecord>":
            name = str(get(row, "Name") or "0")
            color = _aci_to_hex(get(row, "Color"))
            on = get(row, "On")
            frozen = get(row, "Frozen")
            visible = (on is not False) and (frozen is not True)
            layers_map[name] = {
                "name": name,
                "color": color,
                "visible": visible,
                "entity_count": 0,
            }
            layer_colors[name] = color

    # ── Pass 2: collect polyline parents ───────────────────────────────
    polyline_meta: dict[str, dict] = {}  # ID → {layer, color, closed, ...}
    for row in all_rows[1:]:
        desc = str(get(row, "Description") or "")
        if desc == "<AcDbPolyline>":
            eid = str(get(row, "ID") or "")
            layer = str(get(row, "Layer") or "0")
            ci = get(row, "Color Index")
            closed = str(get(row, "Closed") or "").lower() == "true"
            polyline_meta[eid] = {
                "layer": layer,
                "color_index": ci,
                "closed": closed,
            }

    # ── Pass 3: collect vertices grouped by ParentID ──────────────────
    polyline_vertices: dict[str, list[tuple[float, float]]] = {}
    for row in all_rows[1:]:
        desc = str(get(row, "Description") or "")
        if desc != "<AcDbVertex>":
            continue
        parent_id = str(get(row, "ParentID") or "")
        if not parent_id:
            continue
        # Try Start Point (bracket format), then EndPoint
        sp = _parse_coord(get(row, "Start Point"))
        ep = _parse_coord(get(row, "End Point"))
        pt = _parse_coord(get(row, "Point"))
        coord = sp or pt or ep
        if coord:
            polyline_vertices.setdefault(parent_id, []).append(coord)
        # Also add end point if different
        if ep and ep != coord:
            polyline_vertices.setdefault(parent_id, []).append(ep)

    # ── Pass 4: build entities ─────────────────────────────────────────
    entities: list[dict[str, Any]] = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    def expand(x: float, y: float) -> None:
        nonlocal min_x, min_y, max_x, max_y
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x)
        max_y = max(max_y, y)

    for row in all_rows[1:]:
        desc = str(get(row, "Description") or "")
        layer = str(get(row, "Layer") or "0")
        ci = get(row, "Color Index")
        # Resolve color: entity CI, or layer color
        if ci is not None and str(ci) != "256":
            color = _aci_to_hex(ci)
        else:
            color = layer_colors.get(layer, "#cccccc")

        if desc == "<AcDbLine>":
            sp = _parse_coord(get(row, "StartPoint") or get(row, "Start Point"))
            ep = _parse_coord(get(row, "EndPoint") or get(row, "End Point"))
            if sp and ep:
                entities.append({
                    "entity_type": "LINE",
                    "layer": layer,
                    "color": color,
                    "geometry_data": {
                        "start": {"x": sp[0], "y": sp[1]},
                        "end": {"x": ep[0], "y": ep[1]},
                    },
                })
                expand(sp[0], sp[1])
                expand(ep[0], ep[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbPolyline>":
            eid = str(get(row, "ID") or "")
            verts = polyline_vertices.get(eid, [])
            meta = polyline_meta.get(eid, {})
            closed = meta.get("closed", False)

            if verts:
                # Deduplicate consecutive identical points
                deduped = [verts[0]]
                for v in verts[1:]:
                    if v != deduped[-1]:
                        deduped.append(v)

                points = [{"x": v[0], "y": v[1]} for v in deduped]
                entities.append({
                    "entity_type": "LWPOLYLINE",
                    "layer": layer,
                    "color": color,
                    "geometry_data": {
                        "points": points,
                        "closed": closed,
                    },
                })
                for v in deduped:
                    expand(v[0], v[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbArc>":
            center = _parse_coord(get(row, "Center"))
            radius = None
            r_raw = get(row, "Radius")
            if r_raw is not None:
                try:
                    radius = float(r_raw)
                except (ValueError, TypeError):
                    pass
            sa = _parse_angle(get(row, "Start Angle") or get(row, "StartAngle"))
            ea = _parse_angle(get(row, "End Angle") or get(row, "EndAngle"))
            if center and radius:
                entities.append({
                    "entity_type": "ARC",
                    "layer": layer,
                    "color": color,
                    "geometry_data": {
                        "center": {"x": center[0], "y": center[1]},
                        "radius": radius,
                        "start_angle": sa,
                        "end_angle": ea,
                    },
                })
                expand(center[0] - radius, center[1] - radius)
                expand(center[0] + radius, center[1] + radius)
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbCircle>":
            center = _parse_coord(get(row, "Center"))
            r_raw = get(row, "Radius")
            radius = None
            if r_raw is not None:
                try:
                    radius = float(r_raw)
                except (ValueError, TypeError):
                    pass
            if center and radius:
                entities.append({
                    "entity_type": "CIRCLE",
                    "layer": layer,
                    "color": color,
                    "geometry_data": {
                        "center": {"x": center[0], "y": center[1]},
                        "radius": radius,
                    },
                })
                expand(center[0] - radius, center[1] - radius)
                expand(center[0] + radius, center[1] + radius)
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbBlockReference>":
            pos = _parse_coord(get(row, "Position"))
            if pos:
                entities.append({
                    "entity_type": "INSERT",
                    "layer": layer,
                    "color": color,
                    "geometry_data": {
                        "insertion_point": {"x": pos[0], "y": pos[1]},
                        "block_name": str(get(row, "Name") or "block"),
                    },
                })
                expand(pos[0], pos[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbRotatedDimension>":
            p1 = _parse_coord(get(row, "Extension Line 1 Point"))
            p2 = _parse_coord(get(row, "Extension Line 2 Point"))
            if p1 and p2:
                entities.append({
                    "entity_type": "LINE",
                    "layer": layer,
                    "color": color,
                    "geometry_data": {
                        "start": {"x": p1[0], "y": p1[1]},
                        "end": {"x": p2[0], "y": p2[1]},
                    },
                })
                expand(p1[0], p1[1])
                expand(p2[0], p2[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

    # Fallback extents
    if min_x == float("inf"):
        min_x = min_y = 0.0
        max_x = max_y = 1000.0

    layers = sorted(layers_map.values(), key=lambda l: l["name"])
    logger.info(
        "DDC DWG parsed: %d entities, %d layers, extents %.1f,%.1f → %.1f,%.1f",
        len(entities), len(layers), min_x, min_y, max_x, max_y,
    )

    return {
        "layers": layers,
        "entities": entities,
        "extents": {
            "min_x": float(min_x),
            "min_y": float(min_y),
            "max_x": float(max_x),
            "max_y": float(max_y),
        },
        "units": "unitless",
        "entity_count": len(entities),
    }


def _empty() -> dict[str, Any]:
    return {
        "layers": [],
        "entities": [],
        "extents": {"min_x": 0, "min_y": 0, "max_x": 0, "max_y": 0},
        "units": "unitless",
        "entity_count": 0,
    }
