# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DWG/DXF file processor - ezdxf wrapper.

Parses DXF files to extract layers, entities, extents, and units.
Generates SVG thumbnail previews and calculates entity measurements.

ezdxf is an optional dependency - functions degrade gracefully with a
clear error message if it is not installed.
"""

import logging
import math
from typing import Any

from app.modules.dwg_takeoff.extents import model_space_extents

logger = logging.getLogger(__name__)

try:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing import svg as ezdxf_svg
    from ezdxf.lldxf.encoding import (
        decode_dxf_unicode,
        decode_mif_to_unicode,
        has_dxf_unicode,
        has_mif_encoding,
    )
    from ezdxf.tools.text import plain_mtext

    HAS_EZDXF = True
except ImportError:
    HAS_EZDXF = False
    logger.info("ezdxf not installed - DXF processing will be unavailable")


def _require_ezdxf() -> None:
    """Raise ImportError with a helpful message if ezdxf is not available."""
    if not HAS_EZDXF:
        # ezdxf is in requirements-desktop.lock, so a bundle that cannot import
        # it is damaged rather than lean and the reader needs the repair
        # wording; DESKTOP_NO_EXTRA would deny shipping what it ships.
        from app.core.self_upgrade import repair_hint  # noqa: PLC0415

        raise ImportError(
            "ezdxf is required for DXF processing. " + repair_hint("Install it with: pip install 'ezdxf>=0.18.0'")
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


def decode_dxf_text(value: Any) -> Any:
    r"""Decode DXF in-string unicode escapes into real characters.

    DXF files written as R2000 with an ANSI code page (what the DWG converter
    emits) carry every non-ASCII character as ``\U+XXXX`` and East Asian
    multibyte text as ``\M+NXXXX``. ezdxf leaves both untouched for these
    versions, so layer names and text reached the UI as raw escapes. Non-string
    values pass through unchanged.

    Args:
        value: A string read from the DXF, or anything else.

    Returns:
        The decoded string, or ``value`` itself when it is not a string.
    """
    if not isinstance(value, str) or "\\" not in value:
        return value
    try:
        if has_mif_encoding(value):
            value = decode_mif_to_unicode(value)
        if has_dxf_unicode(value):
            value = decode_dxf_unicode(value)
    except Exception:  # noqa: BLE001 - a malformed escape keeps the raw text
        logger.debug("Could not decode DXF escapes in %r", value[:80])
    return value


_TEXT_KEYS = ("text", "text_override", "block_name")


def _decode_entity_strings(entity: dict[str, Any]) -> None:
    """Decode the human-readable strings of one serialized entity in place."""
    for key in ("layer", "block"):
        if key in entity:
            entity[key] = decode_dxf_text(entity[key])
    geometry = entity.get("geometry_data")
    if isinstance(geometry, dict):
        for key in _TEXT_KEYS:
            if key in geometry:
                geometry[key] = decode_dxf_text(geometry[key])


def _collect_xrefs(doc: Any, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """List the external references the drawing depends on but does not contain.

    An xref is a BLOCK whose flags carry bit 4 (attached) or 8 (overlay); its
    geometry lives in another file, so a converted drawing shows only the host
    sheet. An INSERT naming a block that is not defined at all is the same
    situation seen from the other side, and is reported too.

    Args:
        doc: The open ezdxf document.
        entities: Serialized entities, still carrying raw block names.

    Returns:
        One ``{"name", "path"}`` dict per unresolved reference, names decoded.
    """
    found: dict[str, dict[str, Any]] = {}
    try:
        for block in doc.blocks:
            try:
                flags = int(block.block.dxf.get("flags", 0) or 0)
            except Exception:  # noqa: BLE001 - one unreadable BLOCK record
                continue
            if flags & (4 | 8):
                path = block.block.dxf.get("xref_path", "") or ""
                found[block.name] = {"name": decode_dxf_text(block.name), "path": decode_dxf_text(path) or None}
    except Exception:  # noqa: BLE001 - no readable block table
        logger.debug("Could not read the block table for xrefs")
    for entity in entities:
        if entity.get("entity_type") != "INSERT":
            continue
        name = entity.get("geometry_data", {}).get("block_name")
        if not name or name in found:
            continue
        try:
            missing = doc.blocks.get(name) is None
        except Exception:  # noqa: BLE001
            missing = True
        if missing:
            found[name] = {"name": decode_dxf_text(name), "path": None}
    return sorted(found.values(), key=lambda x: str(x["name"]))


def _serialize_entity(
    entity: Any,
    layer_colors: dict[str, str] | None = None,
    styles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Convert an ezdxf entity to a JSON-serializable dict.

    ``styles`` maps a text-style name to the font file it references (built
    once from the STYLE table in :func:`parse_dxf`). TEXT/MTEXT entities
    carry both their style name and resolved font so the viewer can render
    the drawing's real font instead of a generic fallback. A missing style
    resolves to an empty font string, never a crash.
    """
    if styles is None:
        styles = {}
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
        style_name = dxf.get("style", "Standard")
        result["geometry_data"] = {
            "insert": {"x": insert.x, "y": insert.y} if insert else {"x": 0, "y": 0},
            "text": dxf.get("text", ""),
            "height": dxf.get("height", 1.0),
            # ezdxf reports rotation in DEGREES; the wire format is radians
            # (the viewer feeds it straight to ctx.rotate, and the DDC parser
            # emits radians). Text authored at 90 degrees was rendering at 90
            # radians. Same conversion the ARC angles above already do.
            "rotation": math.radians(dxf.get("rotation", 0.0)),
            "style": style_name,
            "font": styles.get(style_name, ""),
        }
    elif entity_type == "MTEXT":
        insert = dxf.get("insert", None)
        style_name = dxf.get("style", "Standard")
        result["geometry_data"] = {
            "insert": {"x": insert.x, "y": insert.y} if insert else {"x": 0, "y": 0},
            # Decode escapes before stripping format codes: plain_mtext would
            # otherwise read a ``\M+`` sequence as an unknown format code.
            "text": plain_mtext(decode_dxf_text(entity.text)),
            "height": dxf.get("char_height", 1.0),
            "style": style_name,
            "font": styles.get(style_name, ""),
        }
    elif entity_type == "INSERT":
        insert = dxf.get("insert", None)
        result["geometry_data"] = {
            "insert": {"x": insert.x, "y": insert.y} if insert else {"x": 0, "y": 0},
            "block_name": dxf.get("name", ""),
            "x_scale": dxf.get("xscale", 1.0),
            "y_scale": dxf.get("yscale", 1.0),
            # Radians on the wire - see the TEXT branch above.
            "rotation": math.radians(dxf.get("rotation", 0.0)),
        }
    elif entity_type == "ELLIPSE":
        center = dxf.get("center", None)
        major_axis = dxf.get("major_axis", None)
        result["geometry_data"] = {
            "center": {"x": center.x, "y": center.y} if center else {"x": 0, "y": 0},
            "major_axis": ({"x": major_axis.x, "y": major_axis.y} if major_axis else {"x": 1, "y": 0}),
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


def _serialize_block_definitions(
    doc: Any,
    placed_entities: list[dict[str, Any]],
    layer_colors: dict[str, str],
    styles: dict[str, str],
) -> list[dict[str, Any]]:
    """Serialize the contents of every block definition an INSERT actually places.

    An INSERT on its own says only "the door block goes here" - the door is in
    the block definition, which this path never read, so the viewer drew a
    marker where the door should be. On an architectural drawing that is the
    doors, windows, furniture, grids and the title block, which is most of what
    the drawing is.

    Each entity is tagged ``block`` and carries **no** ``layout``, so it is
    never drawn as sheet content and never reaches the extents; it is drawn
    only where an INSERT places it, transformed by that INSERT's insertion
    point, scale factors and rotation. Sending the definition once rather than
    expanding it per placement is what keeps this affordable: a block placed
    500 times costs one copy of its geometry, not 500.

    Only definitions some INSERT references are emitted, followed transitively
    so a block nested inside another block still arrives. A drawing with no
    INSERTs grows by nothing. ``doc.blocks`` also holds the layout blocks
    (``*Model_Space``, ``*Paper_Space``) and every anonymous ``*D``/``*U``
    block a dimension or hatch left behind; starting from what is referenced
    rather than from the block table is what keeps those out.

    Args:
        doc: The open ezdxf document.
        placed_entities: Already-serialized layout entities, scanned for INSERTs.
        layer_colors: Layer name to hex colour, for ByLayer resolution.
        styles: Text style name to font file.

    Returns:
        Serialized block-definition entities, each tagged with its block name.
    """
    pending: list[str] = []
    for entity in placed_entities:
        if entity.get("entity_type") == "INSERT":
            block_name = entity.get("geometry_data", {}).get("block_name")
            if block_name:
                pending.append(str(block_name))

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            block = doc.blocks.get(name)
        except Exception:  # noqa: BLE001 - a missing definition is a drawing defect, not ours
            continue
        if block is None:
            continue
        for entity in block:
            try:
                serialized = _serialize_entity(entity, layer_colors, styles)
            except Exception:  # noqa: BLE001 - skip one unreadable member, keep the block
                logger.debug("Skipping unprocessable block entity in %s", name)
                continue
            serialized["block"] = name
            out.append(serialized)
            if serialized["entity_type"] == "INSERT":
                nested = serialized.get("geometry_data", {}).get("block_name")
                if nested:
                    pending.append(str(nested))
    return out


def parse_dxf(file_path: str) -> dict[str, Any]:
    """Parse a DXF file and extract layers, entities, extents, and units.

    Args:
        file_path: Path to the DXF file on disk.

    Returns:
        Dict with keys: layers, entities, extents, units, entity_count,
        skipped_count, layouts, xrefs.

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
    #
    # BUG-005: ``not layer.is_off and not layer.is_frozen`` returned
    # False for every layer on certain DXF imports (notably layer "0"
    # on R2018-vintage files).  ezdxf reports ``is_off`` based on the
    # signed-color encoding which some CAD packages don't honour, so
    # we now default to visible and only flip to hidden when the
    # source file *explicitly* marks the layer off.  Pulls each bit
    # in its own try/except - ezdxf 1.4 occasionally raises on
    # malformed layer entries, and a single exception used to silently
    # collapse the whole expression to False (the canvas would then
    # render empty after import).
    layers: list[dict[str, Any]] = []
    for layer in doc.layers:
        is_off = False
        is_frozen = False
        try:
            is_off = bool(layer.is_off)
        except Exception:  # noqa: BLE001 - defensive: see comment above
            pass
        try:
            is_frozen = bool(layer.is_frozen)
        except Exception:  # noqa: BLE001
            pass
        layers.append(
            {
                "name": layer.dxf.name,
                "color": _aci_to_hex(layer.color),
                "visible": not (is_off or is_frozen),
                "entity_count": 0,
            }
        )

    # Build layer color map for ByLayer color resolution
    layer_color_map: dict[str, str] = {layer["name"]: layer["color"] for layer in layers}

    # Read the STYLE table once: map each text-style name to the font it
    # references so TEXT/MTEXT entities can carry the drawing's real font
    # for the viewer. Defensive on every axis - ``doc.styles`` may be empty
    # or raise on a malformed record; a missing font degrades to "" rather
    # than crashing the whole parse.
    styles: dict[str, str] = {}
    try:
        for style in doc.styles:
            try:
                styles[style.dxf.name] = style.dxf.get("font", "") or style.dxf.get("bigfont", "") or ""
            except Exception:  # noqa: BLE001 - skip a single malformed style record
                continue
    except Exception:  # noqa: BLE001 - no/unreadable STYLE table
        styles = {}

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
                serialized = _serialize_entity(entity, layer_color_map, styles)
                serialized["layout"] = layout_name
                entities.append(serialized)
                layer_name = serialized.get("layer", "0")
                layer_counts[layer_name] = layer_counts.get(layer_name, 0) + 1
            except Exception:
                skipped_count += 1
                logger.debug("Skipping unprocessable entity: %s", entity.dxftype())

    # Block definitions travel alongside the layout entities, tagged ``block``
    # rather than ``layout``. They are counted in ``entity_count`` because they
    # are records on the wire, but deliberately NOT in ``layer_counts``: the
    # layer panel governs what a toggle removes, and a block's members are
    # governed by the INSERT that places them, not by their own layer.
    entities.extend(_serialize_block_definitions(doc, entities, layer_color_map, styles))
    xrefs = _collect_xrefs(doc, entities)

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

    # Calculate extents from parsed entities (more reliable than msp.get_extents).
    #
    # Model space only. The loop that used to live here unioned every layout,
    # so an A3 title block in Layout1 made a 10-unit drawing report 420x297 -
    # a box the user is never shown, and the box the unit inference below
    # reads. It also looked for ``insertion_point``, which no writer in this
    # codebase emits, so every block placement was invisible to it while the
    # service's copy of the same rule saw them. Both callers now share
    # ``extents.model_space_extents``; see that module for why one rule.
    #
    # A drawing that genuinely has no model-space content keeps its real
    # paper-space box rather than falling through to the 0..1000 placeholder.
    try:
        model_space_name = doc.modelspace().name
    except Exception:  # noqa: BLE001 - malformed document: fall back to every layout
        model_space_name = None
    extents = model_space_extents(
        entities,
        model_space_names={model_space_name} if model_space_name else None,
    )
    if extents is None:
        extents = {"min_x": 0.0, "min_y": 0.0, "max_x": 1000.0, "max_y": 1000.0}

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

    # BUG-D-TKC-002c - when $INSUNITS is absent/0 ("unitless") fall back to
    # an extents-based guess. A drawing whose largest extent is >=1000 units
    # is almost certainly authored in millimetres; without this an mm DXF
    # with no header reads 1000x too large (service.py applies a 1.0 factor
    # for "unitless"). Mirrors the DDC parser path.
    if units == "unitless":
        from app.modules.dwg_takeoff.ddc_dwg_parser import infer_units_from_extents

        units = infer_units_from_extents(extents) or units

    # Deduplicate and sort layout names, ensure "Model" comes first
    unique_layouts = list(dict.fromkeys(layout_names))

    # Decode last: block lookups above need the raw names the file uses.
    for entity in entities:
        _decode_entity_strings(entity)
    for layer_info in layers:
        layer_info["name"] = decode_dxf_text(layer_info["name"])

    return {
        "layers": layers,
        "entities": entities,
        "extents": extents,
        "units": units,
        "entity_count": len(entities),
        "skipped_count": skipped_count,
        "layouts": unique_layouts,
        "xrefs": xrefs,
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

        # ezdxf 1.4 reorganised the drawing add-on: the SVG bytes now come
        # from ``backend.get_string()`` (or its xml-tree variant), not
        # ``frontend.out`` - that attribute was removed when the backend
        # registry replaced the legacy ``Frontend.out`` slot (BUG-014).
        # Fall through to the placeholder branch only on real errors -
        # don't let a single AttributeError silently downgrade the
        # thumbnail for every drawing.
        ctx = RenderContext(doc)
        backend = ezdxf_svg.SVGBackend()
        Frontend(ctx, backend).draw_layout(msp)
        if hasattr(backend, "get_string"):
            # ezdxf 1.1+ changed the signature to ``get_string(page)`` where
            # ``page`` is a ``layout.Page`` describing the output size;
            # ``Page(0, 0)`` auto-fits the page to the drawing extents. Older
            # 0.x builds exposed ``get_string()`` with no argument, so fall
            # back to that when the new signature isn't accepted.
            try:
                from ezdxf.addons.drawing import layout as ezdxf_layout

                return backend.get_string(ezdxf_layout.Page(0, 0))
            except TypeError:
                return backend.get_string()
        # ezdxf 1.5+ - backend exposes ``get_xml_root()`` instead; fall
        # back to that and serialise via the stdlib.
        if hasattr(backend, "get_xml_root"):
            from xml.etree import ElementTree

            return ElementTree.tostring(backend.get_xml_root(), encoding="unicode")
        raise RuntimeError(
            "SVGBackend exposes neither get_string nor get_xml_root; "
            "ezdxf API may have shifted again - bump the dependency pin."
        )
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
        # Bugfix (C3): start_angle/end_angle are ALREADY in radians (see
        # _extract_geometry above which writes math.radians(dxf.start_angle)).
        # The previous code applied math.radians() a second time, so arc
        # lengths came out off by (π/180)² ≈ 3.05e-4 - a 90° arc rendered
        # as ~0 metres. Use the stored radians directly; defensive modulo
        # 2π keeps sweep angles in [0, 2π) regardless of source orientation.
        radius = geometry.get("radius", 0)
        start_angle = geometry.get("start_angle", 0)
        end_angle = geometry.get("end_angle", 0)
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
