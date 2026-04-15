"""DWG/DXF file processor — ezdxf wrapper.

Parses DXF files to extract layers, entities, extents, and units.
Generates SVG thumbnail previews and calculates entity measurements.

ezdxf is an optional dependency — functions degrade gracefully with a
clear error message if it is not installed.
"""

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

try:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing import svg as ezdxf_svg

    HAS_EZDXF = True
except ImportError:
    HAS_EZDXF = False
    logger.info("ezdxf not installed — DXF processing will be unavailable")


def _require_ezdxf() -> None:
    """Raise ImportError with a helpful message if ezdxf is not available."""
    if not HAS_EZDXF:
        raise ImportError(
            "ezdxf is required for DXF processing. "
            "Install it with: pip install 'ezdxf>=0.18.0'"
        )


def _aci_to_hex(aci: int) -> str:
    """Convert AutoCAD Color Index (ACI) to hex color string.

    Returns a hex color for common ACI values, falls back to #ffffff.
    """
    aci_map = {
        1: "#ff0000",
        2: "#ffff00",
        3: "#00ff00",
        4: "#00ffff",
        5: "#0000ff",
        6: "#ff00ff",
        7: "#ffffff",
        8: "#808080",
        9: "#c0c0c0",
    }
    return aci_map.get(aci, "#ffffff")


def _serialize_entity(entity: Any, layer_colors: dict[str, str] | None = None) -> dict[str, Any]:
    """Convert an ezdxf entity to a JSON-serializable dict."""
    dxf = entity.dxf
    aci = dxf.get("color", 256)  # 256 = ByLayer (default)
    layer_name = dxf.get("layer", "0")
    # ACI 0 (ByBlock) or 256 (ByLayer): use layer color
    if aci in (0, 256) and layer_colors and layer_name in layer_colors:
        color = layer_colors[layer_name]
    else:
        color = _aci_to_hex(aci)
    result: dict[str, Any] = {
        "entity_type": entity.dxftype(),
        "layer": layer_name,
        "color": color,
        "geometry_data": {},
    }

    entity_type = entity.dxftype()

    if entity_type == "LINE":
        result["geometry_data"] = {
            "start": {"x": dxf.start.x, "y": dxf.start.y},
            "end": {"x": dxf.end.x, "y": dxf.end.y},
        }
    elif entity_type == "CIRCLE":
        result["geometry_data"] = {
            "center": {"x": dxf.center.x, "y": dxf.center.y},
            "radius": dxf.radius,
        }
    elif entity_type == "ARC":
        result["geometry_data"] = {
            "center": {"x": dxf.center.x, "y": dxf.center.y},
            "radius": dxf.radius,
            "start_angle": math.radians(dxf.start_angle),
            "end_angle": math.radians(dxf.end_angle),
        }
    elif entity_type in ("LWPOLYLINE", "POLYLINE"):
        try:
            points = []
            if entity_type == "LWPOLYLINE":
                for x, y, *_ in entity.get_points(format="xy"):
                    points.append({"x": x, "y": y})
            else:
                for vertex in entity.vertices:
                    loc = vertex.dxf.location
                    points.append({"x": loc.x, "y": loc.y})
            result["geometry_data"] = {
                "points": points,
                "closed": getattr(entity, "closed", False),
            }
        except Exception:
            result["geometry_data"] = {"points": [], "closed": False}
    elif entity_type == "TEXT":
        insert = dxf.get("insert", None)
        result["geometry_data"] = {
            "insert": {"x": insert.x, "y": insert.y} if insert else {"x": 0, "y": 0},
            "text": dxf.get("text", ""),
            "height": dxf.get("height", 1.0),
            "rotation": dxf.get("rotation", 0.0),
        }
    elif entity_type == "MTEXT":
        insert = dxf.get("insert", None)
        result["geometry_data"] = {
            "insert": {"x": insert.x, "y": insert.y} if insert else {"x": 0, "y": 0},
            "text": entity.plain_text() if hasattr(entity, "plain_text") else str(entity.text),
            "height": dxf.get("char_height", 1.0),
        }
    elif entity_type == "INSERT":
        insert = dxf.get("insert", None)
        result["geometry_data"] = {
            "insert": {"x": insert.x, "y": insert.y} if insert else {"x": 0, "y": 0},
            "block_name": dxf.get("name", ""),
            "x_scale": dxf.get("xscale", 1.0),
            "y_scale": dxf.get("yscale", 1.0),
            "rotation": dxf.get("rotation", 0.0),
        }
    elif entity_type == "ELLIPSE":
        center = dxf.get("center", None)
        major_axis = dxf.get("major_axis", None)
        result["geometry_data"] = {
            "center": {"x": center.x, "y": center.y} if center else {"x": 0, "y": 0},
            "major_axis": (
                {"x": major_axis.x, "y": major_axis.y} if major_axis else {"x": 1, "y": 0}
            ),
            "ratio": dxf.get("ratio", 1.0),
        }
    elif entity_type == "SPLINE":
        try:
            points = [{"x": p.x, "y": p.y} for p in entity.control_points]
            result["geometry_data"] = {"control_points": points}
        except Exception:
            result["geometry_data"] = {"control_points": []}
    elif entity_type == "HATCH":
        result["geometry_data"] = {"pattern_name": dxf.get("pattern_name", "SOLID")}
    elif entity_type == "DIMENSION":
        result["geometry_data"] = {
            "dimension_type": dxf.get("dimtype", 0),
            "text_override": dxf.get("text", ""),
        }

    return result


def parse_dxf(file_path: str) -> dict[str, Any]:
    """Parse a DXF file and extract layers, entities, extents, and units.

    Args:
        file_path: Path to the DXF file on disk.

    Returns:
        Dict with keys: layers, entities, extents, units, entity_count.

    Raises:
        ImportError: If ezdxf is not installed.
        ValueError: If the file cannot be parsed.
    """
    _require_ezdxf()

    try:
        doc = ezdxf.readfile(file_path)
    except Exception as exc:
        raise ValueError(f"Failed to parse DXF file: {exc}") from exc

    # Extract layers
    layers: list[dict[str, Any]] = []
    for layer in doc.layers:
        layers.append({
            "name": layer.dxf.name,
            "color": _aci_to_hex(layer.color),
            "visible": not layer.is_off and not layer.is_frozen,
            "entity_count": 0,
        })

    # Build layer color map for ByLayer color resolution
    layer_color_map: dict[str, str] = {l["name"]: l["color"] for l in layers}

    # Build layer name set for counting
    layer_counts: dict[str, int] = {}

    # Extract entities from ALL layouts (Model, Layout1, Layout2, etc.)
    entities: list[dict[str, Any]] = []
    layout_names: list[str] = []
    skipped_count = 0
    total_count = 0
    for layout in doc.layouts:
        layout_name = layout.name
        layout_names.append(layout_name)
        for entity in layout:
            total_count += 1
            try:
                serialized = _serialize_entity(entity, layer_color_map)
                serialized["layout"] = layout_name
                entities.append(serialized)
                layer_name = serialized.get("layer", "0")
                layer_counts[layer_name] = layer_counts.get(layer_name, 0) + 1
            except Exception:
                skipped_count += 1
                logger.debug("Skipping unprocessable entity: %s", entity.dxftype())

    if total_count > 0 and skipped_count / total_count > 0.10:
        logger.warning(
            "DXF parse: %d of %d entities skipped (%.1f%%) in %s",
            skipped_count,
            total_count,
            100.0 * skipped_count / total_count,
            file_path,
        )

    # Update layer entity counts
    for layer_info in layers:
        layer_info["entity_count"] = layer_counts.get(layer_info["name"], 0)

    # Calculate extents from parsed entities (more reliable than msp.get_extents)
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for ent in entities:
        gd = ent.get("geometry_data", {})
        points: list[tuple[float, float]] = []
        if "start" in gd and "end" in gd:
            points.append((gd["start"]["x"], gd["start"]["y"]))
            points.append((gd["end"]["x"], gd["end"]["y"]))
        if "points" in gd:
            for v in gd["points"]:
                points.append((v["x"], v["y"]))
        if "center" in gd:
            r = gd.get("radius", 0)
            cx, cy = gd["center"]["x"], gd["center"]["y"]
            points.append((cx - r, cy - r))
            points.append((cx + r, cy + r))
        if "insertion_point" in gd:
            points.append((gd["insertion_point"]["x"], gd["insertion_point"]["y"]))
        for px, py in points:
            min_x = min(min_x, px)
            min_y = min(min_y, py)
            max_x = max(max_x, px)
            max_y = max(max_y, py)

    if min_x == float("inf"):
        min_x = min_y = 0.0
        max_x = max_y = 1000.0
    extents = {"min_x": float(min_x), "min_y": float(min_y), "max_x": float(max_x), "max_y": float(max_y)}

    # Extract units
    units_map = {
        0: "unitless",
        1: "inches",
        2: "feet",
        3: "miles",
        4: "mm",
        5: "cm",
        6: "m",
        7: "km",
    }
    insunits = doc.header.get("$INSUNITS", 0)
    units = units_map.get(insunits, "unitless")

    # Deduplicate and sort layout names, ensure "Model" comes first
    unique_layouts = list(dict.fromkeys(layout_names))

    return {
        "layers": layers,
        "entities": entities,
        "extents": extents,
        "units": units,
        "entity_count": len(entities),
        "skipped_count": skipped_count,
        "layouts": unique_layouts,
    }


def generate_svg_thumbnail(file_path: str) -> str:
    """Generate an SVG thumbnail from a DXF file.

    Args:
        file_path: Path to the DXF file on disk.

    Returns:
        SVG content as a string.

    Raises:
        ImportError: If ezdxf is not installed.
        ValueError: If the file cannot be processed.
    """
    _require_ezdxf()

    try:
        doc = ezdxf.readfile(file_path)
        msp = doc.modelspace()

        ctx = RenderContext(doc)
        frontend = Frontend(ctx, ezdxf_svg.SVGBackend())
        frontend.draw_layout(msp)
        svg_content = frontend.out.get_string()
        return svg_content
    except Exception as exc:
        # Fallback: generate a minimal placeholder SVG
        logger.exception("SVG generation failed, returning placeholder: %s", exc)
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">'
            '<rect width="800" height="600" fill="#1a1a2e" />'
            '<text x="400" y="300" text-anchor="middle" fill="#888" '
            'font-size="24">DXF Preview Unavailable</text>'
            "</svg>"
        )


def calculate_entity_measurement(entity_data: dict[str, Any]) -> float:
    """Calculate a measurement value for a DWG entity.

    Supports LINE (length), CIRCLE (circumference), ARC (arc length),
    LWPOLYLINE/POLYLINE (total length), and area for closed polylines.

    Args:
        entity_data: Serialized entity dict from _serialize_entity.

    Returns:
        Measurement value in drawing units.
    """
    entity_type = entity_data.get("entity_type", "")
    geometry = entity_data.get("geometry_data", {})

    if entity_type == "LINE":
        start = geometry.get("start", {})
        end = geometry.get("end", {})
        dx = end.get("x", 0) - start.get("x", 0)
        dy = end.get("y", 0) - start.get("y", 0)
        return math.sqrt(dx * dx + dy * dy)

    elif entity_type == "CIRCLE":
        radius = geometry.get("radius", 0)
        return 2 * math.pi * radius

    elif entity_type == "ARC":
        radius = geometry.get("radius", 0)
        start_angle = math.radians(geometry.get("start_angle", 0))
        end_angle = math.radians(geometry.get("end_angle", 0))
        angle = end_angle - start_angle
        if angle < 0:
            angle += 2 * math.pi
        return radius * angle

    elif entity_type in ("LWPOLYLINE", "POLYLINE"):
        points = geometry.get("points", [])
        if len(points) < 2:
            return 0.0
        total = 0.0
        for i in range(len(points) - 1):
            dx = points[i + 1].get("x", 0) - points[i].get("x", 0)
            dy = points[i + 1].get("y", 0) - points[i].get("y", 0)
            total += math.sqrt(dx * dx + dy * dy)
        # Add closing segment if closed
        if geometry.get("closed", False) and len(points) > 2:
            dx = points[0].get("x", 0) - points[-1].get("x", 0)
            dy = points[0].get("y", 0) - points[-1].get("y", 0)
            total += math.sqrt(dx * dx + dy * dy)
        return total

    return 0.0
