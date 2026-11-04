# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parse DDC DwgExporter Excel output into drawable entities.

DDC DwgExporter produces an Excel file with AutoCAD database records.
Geometry entities (AcDbLine, AcDbPolyline+AcDbVertex, AcDbArc, AcDbCircle,
AcDbEllipse, AcDbSpline, AcDbHatch, AcDbText, AcDbMText,
AcDbBlockReference) have coordinate fields that we extract and convert
into the same JSON format used by the ezdxf-based DXF parser, so the
frontend DxfViewer can render them identically.

Coordinate formats in DDC output:
  - Lines: "295.144, 812.512, 0" (comma-separated)
  - Vertices: "[0.5 0.5]" or "[0.5 0.5 0.0]" (space-separated in brackets)
  - Arcs/Circles: same as lines for Center
  - Scientific: "1.22868e+06, 801718, 0"
"""

import logging
import re
from pathlib import Path
from typing import Any

from app.modules.dwg_takeoff.extents import extents_from_stored_entities

logger = logging.getLogger(__name__)

# ACI (AutoCAD Color Index) → hex color
_ACI_COLORS: dict[int, str] = {
    0: "#000000",
    1: "#ff0000",
    2: "#ffff00",
    3: "#00ff00",
    4: "#00ffff",
    5: "#0000ff",
    6: "#ff00ff",
    7: "#ffffff",
    8: "#808080",
    9: "#c0c0c0",
    10: "#ff5555",
    11: "#ffff55",
    12: "#55ff55",
    13: "#55ffff",
    14: "#5555ff",
    15: "#ff55ff",
    16: "#555555",
    40: "#cc8800",
    160: "#00cc88",
    256: "#cccccc",
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
        return _ACI_COLORS.get(
            idx, f"#{min(idx * 37 % 256, 255):02x}{min(idx * 73 % 256, 255):02x}{min(idx * 113 % 256, 255):02x}"
        )
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
    s_str = str(s).strip()
    # Handle "197.678d" (degrees) format
    if s_str.endswith("d"):
        try:
            import math

            return float(s_str[:-1]) * math.pi / 180.0
        except (ValueError, TypeError):
            return 0.0
    try:
        return float(s_str)
    except (ValueError, TypeError):
        return 0.0


def _safe_float(val: Any) -> float | None:
    """Safely convert to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# Block-table record names the DWG object model reserves for the model and
# the sheets. Everything else in ``BlockId`` is a block definition or an owner
# we do not recognise.
_LAYOUT_BLOCK_PREFIXES = ("*model_space", "*paper_space")


def _is_layout_block_id(block_id: str) -> bool:
    """True when a DWG ``BlockId`` names a layout rather than a block definition.

    ``*Model_Space`` and ``*Paper_Space``/``*Paper_Space0``/``*Paper_Space1``
    are what AutoCAD calls the block-table records behind the model and each
    sheet. Case is normalised because exporter builds disagree about it.
    """
    lowered = block_id.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _LAYOUT_BLOCK_PREFIXES)


def _is_model_space_block_id(block_id: str) -> bool:
    """True when a DWG ``BlockId`` names model space specifically."""
    return block_id.strip().lower() == "*model_space"


def _is_anonymous_block_id(block_id: str) -> bool:
    """True when a ``BlockId`` names a block-table record AutoCAD wrote itself.

    AutoCAD reserves the ``*`` prefix for records it creates without being
    asked: ``*D`` per dimension, ``*X`` per hatch, ``*U`` for an unnamed
    group. Callers must rule out the layouts first - they are ``*`` names too.
    """
    return block_id.strip().startswith("*")


def _owner_is_block_definition(
    block_id: str,
    referenced_blocks: set[str],
    block_table: dict[str, bool] | None = None,
) -> bool:
    """Decide whether a row's owner is a block definition rather than a sheet.

    ``BlockId`` carries the owning block-table record, and in the DWG object
    model that is ``*Model_Space``, ``*Paper_Space*`` **and one entry per block
    definition**. Filing all three as layouts is what put every door and window
    block in the sheet picker as if it were a drawable sheet.

    The export answers this itself when it can. Its ``<AcDbBlockTableRecord>``
    rows are the drawing's block table, and each carries a ``Layout`` flag that
    is true for exactly the records AutoCAD built a sheet around. On a real
    17 MB export 809 records came through with ``Layout`` true for two of them,
    ``*Model_Space`` and ``*Paper_Space``, and false for the other 807. Nothing
    needs guessing when that table is present.

    The three heuristics below are for exports that carry no block table, and
    they run in order. A ``*`` name that is not a layout is one of AutoCAD's own
    anonymous records and is never a sheet. Otherwise the evidence has to be
    positive: a name some block reference actually places is a block
    definition, whatever it happens to be called. That last test holds whether
    the export writes block names or numeric object ids in ``BlockId``; a real
    DwgExporter build was since confirmed to write names, with 577 of the 579
    referenced names appearing there as owners.

    The reference test alone was not enough, which is why the other two exist.
    A dimension owns its ``*D`` record implicitly rather than placing it
    through an ``<AcDbBlockReference>`` row, and an unplaced definition is
    referenced by nothing at all, so both were offered as sheets: one real
    export listed 1108 of them against a single drawing.

    Anything every test leaves undecided is treated as a sheet. That is the
    conservative direction: misfiling a sheet as a block hides its geometry
    entirely, while misfiling a block as a sheet only puts back the spurious
    entry this function exists to remove.

    Args:
        block_id: The row's ``BlockId`` cell.
        referenced_blocks: Names placed by an ``<AcDbBlockReference>`` row.
        block_table: Record name → whether that record is a layout, read from
            the export's own block table. Empty or ``None`` when the export
            carries no such rows.

    Returns:
        True when the owner is a block definition.
    """
    if block_table:
        is_layout = block_table.get(block_id)
        if is_layout is not None:
            return not is_layout
    if _is_layout_block_id(block_id):
        return False
    if _is_anonymous_block_id(block_id):
        return True
    return block_id in referenced_blocks


# Threshold (in raw drawing units) above which a drawing is almost
# certainly authored in millimetres.  A building whose largest extent is
# >= 1000 units would be 1 km+ if those units were metres (absurd for a
# floor plan) but a sensible 1 m+ if they are millimetres.
_MM_EXTENT_THRESHOLD = 1000.0


def infer_units_from_extents(extents: dict | None) -> str | None:
    """Best-effort unit guess for a DWG/DXF whose header carries no usable
    ``$INSUNITS``.

    A drawing whose largest extent is >= 1000 units is almost certainly in
    millimetres (a 1000+ unit building read as metres would be 1 km+, which
    is absurd for a plan; read as mm it is a sensible 1 m+).  Returns
    ``"mm"`` for such large drawings, else ``None`` so callers keep the
    existing "raw units == metres" assumption for genuinely small/empty
    drawings.

    Guards against missing / zero / non-finite extents (returns ``None``).

    Args:
        extents: ``{"min_x", "min_y", "max_x", "max_y"}`` or ``None``.

    Returns:
        ``"mm"`` when the drawing's largest extent is large enough to imply
        millimetres, otherwise ``None``.
    """
    if not extents:
        return None
    try:
        min_x = float(extents["min_x"])
        min_y = float(extents["min_y"])
        max_x = float(extents["max_x"])
        max_y = float(extents["max_y"])
    except (KeyError, TypeError, ValueError):
        return None
    width = max_x - min_x
    height = max_y - min_y
    # Reject NaN / inf (an empty extents collapses to inf in the parsers).
    if not (width == width and height == height):  # NaN check
        return None
    if width in (float("inf"), float("-inf")) or height in (float("inf"), float("-inf")):
        return None
    maxdim = max(width, height)
    if maxdim >= _MM_EXTENT_THRESHOLD:
        return "mm"
    return None


# AutoCAD ``$INSUNITS`` code → canonical unit string.  Mirrors the
# reference table in dxf_processor.py (ezdxf path) so the DDC and ezdxf
# pipelines agree on unit semantics and the downstream scale factor in
# service.py is identical regardless of which parser produced the
# drawing.  (Reference-only file dxf_processor.py:280-288 is NOT edited.)
_INSUNITS_MAP: dict[int, str] = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "mm",
    5: "cm",
    6: "m",
    7: "km",
    8: "microinches",
    9: "mils",
    10: "yards",
    11: "angstroms",
    12: "nanometers",
    13: "microns",
    14: "dm",
    15: "dam",
    16: "hm",
    17: "gigameters",
    18: "astronomical_units",
    19: "lightyears",
    20: "parsecs",
}

# Free-text unit spellings the DDC DwgExporter may emit in a units column
# instead of the numeric INSUNITS code (it depends on the converter
# build).  Normalised → canonical.
_UNIT_TEXT_MAP: dict[str, str] = {
    "unitless": "unitless",
    "none": "unitless",
    "undefined": "unitless",
    "inch": "inches",
    "inches": "inches",
    "in": "inches",
    "foot": "feet",
    "feet": "feet",
    "ft": "feet",
    "mile": "miles",
    "miles": "miles",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "mm": "mm",
    "centimeter": "cm",
    "centimeters": "cm",
    "cm": "cm",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "m": "m",
    "kilometer": "km",
    "kilometers": "km",
    "km": "km",
    "decimeter": "dm",
    "dm": "dm",
    "yard": "yards",
    "yards": "yards",
}


def _resolve_dwg_units(
    all_rows: list[tuple],
    get: Any,
) -> str:
    """Recover the drawing's source unit from the DDC DwgExporter export.

    The DDC DwgExporter writes the AutoCAD database header alongside the
    geometry records.  Depending on the converter build the drawing unit
    surfaces either as a numeric ``INSUNITS`` code or as a free-text
    unit name on the database / drawing-settings record (descriptor
    ``<AcDbDatabase>`` or a header/preferences row).

    Previously this was hardcoded to ``"unitless"``, which made
    service.py apply a 1.0 scale factor - so a millimetre DWG routed
    through DDC read 1000× too large (BUG-D-TKC-002b).  This scans the
    export for any unit-bearing field and resolves it; only when nothing
    usable is present does it fall back to ``"unitless"`` (the honest
    "unknown - assume model units" answer, same as the ezdxf path's
    ``$INSUNITS == 0`` default).

    Args:
        all_rows: All worksheet rows (row 0 is the header).
        get: Row accessor bound to the header→index map.

    Returns:
        A canonical unit string (key of the service.py scale table):
        one of ``unitless`` / ``inches`` / ``feet`` / ``miles`` / ``mm``
        / ``cm`` / ``m`` / ``km`` / ``dm`` / ``yards`` / etc.
    """
    # Column names the DwgExporter has been observed to use for the
    # drawing unit, in priority order.  Checked case-insensitively.
    _UNIT_COLS = (
        "INSUNITS",
        "InsUnits",
        "Insunits",
        "$INSUNITS",
        "Units",
        "Unit",
        "Drawing Units",
        "DrawingUnits",
        "Measurement",
        "MEASUREMENT",
    )
    # Descriptor rows that carry the database / drawing-settings header.
    _DB_DESCRIPTORS = {
        "<AcDbDatabase>",
        "<AcDbDatabaseSummaryInfo>",
        "<DatabaseHeader>",
        "<HeaderVariables>",
        "<DrawingSettings>",
    }

    def _coerce(raw: object) -> str | None:
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None
        # Numeric INSUNITS code ("4", "4.0", "INSUNITS 4").
        m = re.search(r"-?\d+", s)
        if (
            m
            and _INSUNITS_MAP.get(int(m.group(0)))
            and not re.search(r"[a-df-zA-DF-Z]", s.replace("INSUNITS", "").replace("insunits", ""))
        ):
            mapped = _INSUNITS_MAP.get(int(m.group(0)))
            if mapped:
                return mapped
        # Free-text unit name.
        key = re.sub(r"[^a-z]", "", s.lower())
        return _UNIT_TEXT_MAP.get(key)

    # Pass A - prefer a value attached to an explicit database/header row.
    for row in all_rows[1:]:
        desc = str(get(row, "Description") or "")
        if desc in _DB_DESCRIPTORS:
            for col in _UNIT_COLS:
                val = _coerce(get(row, col))
                if val:
                    return val

    # Pass B - converter build that puts the unit on a plain column of
    # any/every row (e.g. a per-export constant column).  Take the first
    # row that resolves to a non-unitless value.
    for row in all_rows[1:]:
        for col in _UNIT_COLS:
            val = _coerce(get(row, col))
            if val and val != "unitless":
                return val

    # Nothing usable - honest fallback (model units, scale 1.0), the same
    # default the ezdxf path uses when $INSUNITS is absent/0.
    return "unitless"


def parse_ddc_dwg_excel(excel_path: str | Path) -> dict[str, Any]:
    """Parse DDC DwgExporter Excel into layers + drawable entities.

    Returns dict compatible with dxf_processor.parse_dxf() output:
    {
        "layers": [...],
        "entities": [...],
        "extents": {"min_x", "min_y", "max_x", "max_y"},
        "units": "<resolved from the DDC export - mm/cm/m/inches/...,"
                 " or 'unitless' when the export carries no unit field>",
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

    # ── Pass 1: collect layers + text styles ───────────────────────────
    layers_map: dict[str, dict] = {}
    layer_colors: dict[str, str] = {}
    # Map each text-style name to the font/typeface it references so
    # AcDbText/AcDbMText entities below can carry the drawing's real font
    # for the viewer. The exact font column depends on the DwgExporter
    # build, so accept whichever font-bearing column exists.
    text_style_fonts: dict[str, str] = {}

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
        elif desc == "<AcDbTextStyleTableRecord>":
            style_name = str(get(row, "Name") or "").strip()
            if style_name:
                font = (
                    get(row, "Font")
                    or get(row, "TypeFace")
                    or get(row, "Typeface")
                    or get(row, "FileName")
                    or get(row, "File Name")
                    or get(row, "FontFile")
                    or ""
                )
                text_style_fonts[style_name] = str(font or "").strip()

    # ── Pass 2: collect polyline parents + the blocks a reference places ──
    polyline_meta: dict[str, dict] = {}  # ID → {layer, color, closed, ...}
    # Every block definition some AcDbBlockReference actually places. Pass 4
    # uses this to tell a block definition from a sheet - see
    # ``_owner_is_block_definition`` for why the evidence has to be positive.
    referenced_blocks: set[str] = set()
    # The export's own block table: name → whether that record is a layout.
    # This is the authoritative answer to "block definition or sheet?", and
    # the heuristics only run for exports that carry no such rows.
    block_table: dict[str, bool] = {}
    for row in all_rows[1:]:
        desc = str(get(row, "Description") or "")
        if desc == "<AcDbBlockTableRecord>":
            name = str(get(row, "Name") or "").strip()
            if name:
                block_table[name] = str(get(row, "Layout") or "").strip().lower() == "true"
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
        elif desc == "<AcDbBlockReference>":
            placed = get(row, "BlockTableRecord") or get(row, "Name")
            if placed:
                referenced_blocks.add(str(placed))

    # A block table that flags nothing as a layout is not a block table we can
    # read - either the build writes no ``Layout`` column or it spells the flag
    # some way this does not recognise. Trusting it then would classify every
    # owner in the drawing as a block definition and leave no sheet at all, so
    # it is dropped and the heuristics decide instead. A real drawing always
    # has model space.
    if not any(block_table.values()):
        block_table = {}

    # ── Pass 3: collect vertices grouped by ParentID ──────────────────
    #
    # Bugfix (audit C11): the DDC DWG export writes one vertex row per
    # AcDbVertex, and each row has BOTH a ``Start Point`` and an
    # ``End Point`` column for line-segment vertices. The previous
    # implementation appended both into the polyline's vertex list
    # unconditionally, which meant every interior vertex got duplicated
    # (segment N's end == segment N+1's start) and the polyline was
    # effectively walked twice. Total polyline lengths and areas came
    # out ~2× the real value. The subsequent ``deduped`` pass only
    # removed IMMEDIATELY consecutive duplicates, so vertices duplicated
    # across alternating rows survived.
    #
    # Fix: collect vertex rows in DXF order (preserving the AcDbVertex
    # row sequence), then take ONLY the Start Point - or the Point /
    # End Point as fallback when Start is missing. The polyline's true
    # geometry is the sequence of vertex Start points; segment endpoints
    # are reconstructed as the next vertex's Start. Closed polylines
    # are handled by ``polyline_meta[eid].closed`` downstream.
    polyline_vertices: dict[str, list[tuple[float, float]]] = {}
    # Each polyline's terminal End Point, taken on the way past. The post-pass
    # below used to recover this by re-reading the whole export once per
    # polyline, which is the whole of the "conversion never finishes" defect.
    polyline_terminal_ends: dict[str, tuple[float, float]] = {}
    for row in all_rows[1:]:
        desc = str(get(row, "Description") or "")
        if desc != "<AcDbVertex>":
            continue
        parent_id = str(get(row, "ParentID") or "")
        if not parent_id:
            continue
        # Prefer Start Point; fall back to Point (for AcDbPoint-style
        # vertices), then End Point (only meaningful for the LAST
        # vertex of an open polyline).
        sp = _parse_coord(get(row, "Start Point"))
        pt = _parse_coord(get(row, "Point"))
        ep = _parse_coord(get(row, "End Point"))
        coord = sp or pt or ep
        if coord is None:
            continue
        # Last vertex row of this polyline that carries an End Point wins,
        # which is what the re-scan below used to compute. A row carrying an
        # End Point always reaches this line: ``coord`` falls back to that
        # same value, so the guard above can never skip it.
        if ep is not None:
            polyline_terminal_ends[parent_id] = ep
        bucket = polyline_vertices.setdefault(parent_id, [])
        # Skip immediate duplicates here too - defence in depth for
        # exporters that occasionally emit zero-length segments.
        if not bucket or bucket[-1] != coord:
            bucket.append(coord)
    # Post-pass: if a polyline's last vertex carried a distinct End Point,
    # append it so the open-polyline tail isn't lost. Note this also appends
    # to closed polylines; the tail is not conditioned on
    # ``polyline_meta[eid]["closed"]`` and never has been.
    #
    # This used to re-scan every row of the export once per polyline to find
    # that value, which is O(polylines x rows). Measured on this shape of
    # data, doubling the export roughly quadrupled the time this loop spent,
    # and on a real 22 MB architectural drawing it runs for over an hour, in
    # the one phase of the DWG pipeline that has no timeout on it, behind a
    # progress card that cannot say which phase it is in. The value was
    # already in hand during the collection pass above, so take it there.
    for parent_id, verts in polyline_vertices.items():
        terminal_end = polyline_terminal_ends.get(parent_id)
        if terminal_end and (not verts or verts[-1] != terminal_end):
            verts.append(terminal_end)

    # ── Pass 4: build entities ─────────────────────────────────────────
    entities: list[dict[str, Any]] = []
    layout_set: set[str] = set()
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    # Only model-space geometry sets the drawing's extents. Paper space is a
    # sheet in millimetres wrapped around a model authored in whatever the
    # model is authored in, and a block definition sits around its own origin;
    # both used to be unioned in, so an A3 title block made a 10-unit drawing
    # report 420x297 - a box nobody is ever shown and the box the unit
    # inference below reads. Rebound per row, read by ``expand``.
    row_sets_extents = True

    def expand(x: float, y: float) -> None:
        nonlocal min_x, min_y, max_x, max_y
        if not row_sets_extents:
            return
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x)
        max_y = max(max_y, y)

    for row in all_rows[1:]:
        desc = str(get(row, "Description") or "")
        layer = str(get(row, "Layer") or "0")
        ci = get(row, "Color Index")
        block_id = str(get(row, "BlockId") or "*Model_Space")
        owner_is_block = _owner_is_block_definition(block_id, referenced_blocks, block_table)
        row_sets_extents = not owner_is_block and _is_model_space_block_id(block_id)
        # Resolve color: entity CI, or layer color
        if ci is not None and str(ci) != "256":
            color = _aci_to_hex(ci)
        else:
            color = layer_colors.get(layer, "#cccccc")

        entity_count_before = len(entities)

        if desc == "<AcDbLine>":
            sp = _parse_coord(get(row, "StartPoint") or get(row, "Start Point"))
            ep = _parse_coord(get(row, "EndPoint") or get(row, "End Point"))
            if sp and ep:
                entities.append(
                    {
                        "entity_type": "LINE",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "start": {"x": sp[0], "y": sp[1]},
                            "end": {"x": ep[0], "y": ep[1]},
                        },
                    }
                )
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
                # A ring drawn back onto its start is closed even without the flag.
                if len(deduped) >= 4 and deduped[0] == deduped[-1]:
                    deduped.pop()
                    closed = True

                points = [{"x": v[0], "y": v[1]} for v in deduped]
                entities.append(
                    {
                        "entity_type": "LWPOLYLINE",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "points": points,
                            "closed": closed,
                        },
                    }
                )
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
                entities.append(
                    {
                        "entity_type": "ARC",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "center": {"x": center[0], "y": center[1]},
                            "radius": radius,
                            "start_angle": sa,
                            "end_angle": ea,
                        },
                    }
                )
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
                entities.append(
                    {
                        "entity_type": "CIRCLE",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "center": {"x": center[0], "y": center[1]},
                            "radius": radius,
                        },
                    }
                )
                expand(center[0] - radius, center[1] - radius)
                expand(center[0] + radius, center[1] + radius)
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbEllipse>":
            center = _parse_coord(get(row, "Center"))
            major_r = _safe_float(get(row, "Major Radius") or get(row, "MajorRadius"))
            minor_r = _safe_float(get(row, "Minor Radius") or get(row, "MinorRadius"))
            ratio = _safe_float(get(row, "Radius Ratio") or get(row, "RadiusRatio"))
            major_axis = _parse_coord(get(row, "Major Axis") or get(row, "MajorAxis"))
            sa = _parse_angle(get(row, "StartAngle"))
            ea = _parse_angle(get(row, "EndAngle"))
            if center and (major_r or (major_axis and ratio)):
                if not major_r and major_axis:
                    import math as _math

                    major_r = _math.sqrt(major_axis[0] ** 2 + major_axis[1] ** 2)
                if not minor_r and major_r and ratio:
                    minor_r = major_r * ratio
                rotation = 0.0
                if major_axis:
                    import math as _math

                    rotation = _math.atan2(major_axis[1], major_axis[0])
                entities.append(
                    {
                        "entity_type": "ELLIPSE",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "center": {"x": center[0], "y": center[1]},
                            "major_radius": major_r or 1.0,
                            "minor_radius": minor_r or 1.0,
                            "rotation": rotation,
                            "start_angle": sa,
                            "end_angle": ea,
                        },
                    }
                )
                r = major_r or 1.0
                expand(center[0] - r, center[1] - r)
                expand(center[0] + r, center[1] + r)
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbSpline>":
            closed = str(get(row, "Closed") or "").lower() == "true"
            min_ext = _parse_coord(get(row, "Min Extents"))
            max_ext = _parse_coord(get(row, "Max Extents"))
            sp = _parse_coord(get(row, "StartPoint") or get(row, "Start Point"))
            ep = _parse_coord(get(row, "EndPoint") or get(row, "End Point"))

            if closed and min_ext and max_ext:
                # Closed spline - approximate as ellipse from bounding box
                import math as _math

                cx = (min_ext[0] + max_ext[0]) / 2
                cy = (min_ext[1] + max_ext[1]) / 2
                rx = (max_ext[0] - min_ext[0]) / 2
                ry = (max_ext[1] - min_ext[1]) / 2
                if rx > 0 and ry > 0:
                    entities.append(
                        {
                            "entity_type": "ELLIPSE",
                            "layer": layer,
                            "color": color,
                            "geometry_data": {
                                "center": {"x": cx, "y": cy},
                                "major_radius": max(rx, ry),
                                "minor_radius": min(rx, ry),
                                "rotation": 0.0 if rx >= ry else _math.pi / 2,
                                "start_angle": 0.0,
                                "end_angle": _math.pi * 2,
                            },
                        }
                    )
                    expand(min_ext[0], min_ext[1])
                    expand(max_ext[0], max_ext[1])
                    if layer in layers_map:
                        layers_map[layer]["entity_count"] += 1
            elif sp and ep and sp != ep:
                # Open spline - draw chord from start to end
                entities.append(
                    {
                        "entity_type": "LINE",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "start": {"x": sp[0], "y": sp[1]},
                            "end": {"x": ep[0], "y": ep[1]},
                        },
                    }
                )
                expand(sp[0], sp[1])
                expand(ep[0], ep[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbHatch>":
            # Extract hatch boundary from Min/Max Extents as a rectangle
            min_ext = _parse_coord(get(row, "Min Extents"))
            max_ext = _parse_coord(get(row, "Max Extents"))
            pattern = str(get(row, "Pattern Name") or get(row, "PatternName") or "SOLID")
            is_solid = str(get(row, "Solid Fill") or get(row, "IsSolidFill") or "").lower() == "true"
            if min_ext and max_ext:
                points = [
                    {"x": min_ext[0], "y": min_ext[1]},
                    {"x": max_ext[0], "y": min_ext[1]},
                    {"x": max_ext[0], "y": max_ext[1]},
                    {"x": min_ext[0], "y": max_ext[1]},
                ]
                entities.append(
                    {
                        "entity_type": "HATCH",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "points": points,
                            "closed": True,
                            "pattern_name": pattern,
                            "is_solid": is_solid,
                        },
                    }
                )
                expand(min_ext[0], min_ext[1])
                expand(max_ext[0], max_ext[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbText>":
            pos = _parse_coord(get(row, "Position") or get(row, "Text Position"))
            text = str(get(row, "Text String") or get(row, "TextString") or "")
            height = _safe_float(get(row, "Height") or get(row, "TextHeight")) or 2.5
            # ``_parse_angle``, not ``_safe_float``. The export writes an angle
            # either as a bare number already in radians or with a ``d`` suffix
            # meaning degrees, which is why the ARC branch above reads its start
            # and end angles through that helper. ``float("90.0d")`` raises, so
            # ``_safe_float`` returned None and ``or 0.0`` turned every rotated
            # label upright without saying anything. A bare number that reached
            # the viewer unconverted was fed straight to ``ctx.rotate``, which
            # takes radians, so 90 arrived as 90 radians.
            rotation = _parse_angle(get(row, "Rotation"))
            style_name = str(
                get(row, "Style Name")
                or get(row, "StyleName")
                or get(row, "Text Style")
                or get(row, "TextStyle")
                or get(row, "Style")
                or ""
            ).strip()
            if pos and text:
                entities.append(
                    {
                        "entity_type": "TEXT",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "insert": {"x": pos[0], "y": pos[1]},
                            "text": text,
                            "height": height,
                            "rotation": rotation,
                            "style": style_name,
                            "font": text_style_fonts.get(style_name, ""),
                        },
                    }
                )
                expand(pos[0], pos[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbMText>":
            loc = _parse_coord(get(row, "Location"))
            text = str(get(row, "Text") or get(row, "Contents") or "")
            # Strip MText formatting codes
            text = re.sub(r"\\[A-Za-z][^;]*;", "", text)
            text = re.sub(r"[{}]", "", text).strip()
            height = _safe_float(get(row, "TextHeight") or get(row, "ActualHeight") or get(row, "Actual Height")) or 2.5
            # Radians on the wire, see the TEXT branch above.
            rotation = _parse_angle(get(row, "Rotation"))
            style_name = str(
                get(row, "Style Name")
                or get(row, "StyleName")
                or get(row, "Text Style")
                or get(row, "TextStyle")
                or get(row, "Style")
                or ""
            ).strip()
            if loc and text:
                entities.append(
                    {
                        "entity_type": "MTEXT",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "insert": {"x": loc[0], "y": loc[1]},
                            "text": text,
                            "height": height,
                            "rotation": rotation,
                            "style": style_name,
                            "font": text_style_fonts.get(style_name, ""),
                        },
                    }
                )
                expand(loc[0], loc[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbBlockReference>":
            pos = _parse_coord(get(row, "Position"))
            block_name = str(get(row, "BlockTableRecord") or get(row, "Name") or "block")
            # Radians on the wire, see the TEXT branch above. This one places a
            # whole block definition, so a dropped rotation turns every door and
            # window in the drawing to face the same way.
            rotation = _parse_angle(get(row, "Rotation"))
            scale_str = get(row, "ScaleFactors") or get(row, "Scale Factors")
            x_scale = y_scale = 1.0
            if scale_str:
                parts = str(scale_str).replace("[", "").replace("]", "").split(",")
                if len(parts) >= 2:
                    x_scale = _safe_float(parts[0].strip()) or 1.0
                    y_scale = _safe_float(parts[1].strip()) or 1.0
            if pos:
                entities.append(
                    {
                        "entity_type": "INSERT",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "insert": {"x": pos[0], "y": pos[1]},
                            "block_name": block_name,
                            "x_scale": x_scale,
                            "y_scale": y_scale,
                            "rotation": rotation,
                        },
                    }
                )
                expand(pos[0], pos[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbAttributeDefinition>":
            pos = _parse_coord(get(row, "Position"))
            text = str(get(row, "TextString") or get(row, "Text String") or "")
            height = _safe_float(get(row, "TextHeight") or get(row, "Height")) or 2.5
            if pos and text:
                entities.append(
                    {
                        "entity_type": "TEXT",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "insert": {"x": pos[0], "y": pos[1]},
                            "text": text,
                            "height": height,
                            "rotation": 0.0,
                        },
                    }
                )
                expand(pos[0], pos[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        elif desc == "<AcDbRotatedDimension>":
            p1 = _parse_coord(get(row, "Extension Line 1 Point"))
            p2 = _parse_coord(get(row, "Extension Line 2 Point"))
            if p1 and p2:
                entities.append(
                    {
                        "entity_type": "LINE",
                        "layer": layer,
                        "color": color,
                        "geometry_data": {
                            "start": {"x": p1[0], "y": p1[1]},
                            "end": {"x": p2[0], "y": p2[1]},
                        },
                    }
                )
                expand(p1[0], p1[1])
                expand(p2[0], p2[1])
                if layer in layers_map:
                    layers_map[layer]["entity_count"] += 1

        # Tag newly added entities with their owner. A sheet gets ``layout``,
        # a block definition gets ``block`` - never both. The viewer's sheet
        # filter then drops definition members from every sheet without
        # needing to know what a block is, and they are drawn only where an
        # INSERT places them.
        for ent in entities[entity_count_before:]:
            if owner_is_block:
                ent["block"] = block_id
            else:
                ent["layout"] = block_id
                layout_set.add(block_id)

    # Nothing classified as a sheet while entities exist means the
    # classification misread this export. Put everything back on model space
    # rather than serve a drawing whose sheet picker is empty, which renders as
    # a blank canvas - strictly worse than the phantom sheets we are removing.
    if entities and not layout_set:
        logger.warning(
            "DDC DWG: no layout survived block classification over %d entities; filing all under *Model_Space",
            len(entities),
        )
        for ent in entities:
            ent.pop("block", None)
            ent["layout"] = "*Model_Space"
        layout_set.add("*Model_Space")
        min_x = float("inf")

    # Fallback extents
    if min_x == float("inf"):
        # No model-space geometry contributed - either the drawing really is
        # all paper space, or this export names its model space something we
        # do not recognise. Take the box over everything that is not
        # block-local, which is wrong about coordinate system but right about
        # magnitude, and magnitude is what the unit inference reads.
        recovered = extents_from_stored_entities(entities)
        if recovered is None:
            min_x = min_y = 0.0
            max_x = max_y = 1000.0
        else:
            min_x, min_y = recovered["min_x"], recovered["min_y"]
            max_x, max_y = recovered["max_x"], recovered["max_y"]

    # A layer's count describes what toggling that layer off would remove, and
    # toggling removes no block-definition member: those are governed by the
    # INSERT that places them, not by their own authoring layer, which is
    # usually "0" rather than the layer the INSERT sits on. Recomputed once
    # here rather than gated at each of the twelve increment sites above, so
    # the rule is written in one place - and so this path agrees with the DXF
    # one, which is the whole point of the block/sheet split.
    for info in layers_map.values():
        info["entity_count"] = 0
    for ent in entities:
        if ent.get("block"):
            continue
        info = layers_map.get(ent["layer"])
        if info is not None:
            info["entity_count"] += 1

    layers = sorted(layers_map.values(), key=lambda layer: layer["name"])
    logger.info(
        "DDC DWG parsed: %d entities, %d layers, extents %.1f,%.1f → %.1f,%.1f",
        len(entities),
        len(layers),
        min_x,
        min_y,
        max_x,
        max_y,
    )

    # Sort layouts: *Model_Space first, then alphabetical
    sorted_layouts = sorted(layout_set)
    if "*Model_Space" in sorted_layouts:
        sorted_layouts.remove("*Model_Space")
        sorted_layouts.insert(0, "*Model_Space")

    # BUG-D-TKC-002b - carry the real source unit from the DDC export
    # instead of hardcoding "unitless" (which forced a 1.0 scale factor in
    # service.py and made a millimetre DWG read 1000x too big).
    units = _resolve_dwg_units(all_rows, get)

    extents = {
        "min_x": float(min_x),
        "min_y": float(min_y),
        "max_x": float(max_x),
        "max_y": float(max_y),
    }
    # BUG-D-TKC-002c - when the export carries no usable unit, fall back to
    # an extents-based guess (a >=1000-unit drawing is almost certainly in
    # millimetres). Without this, an mm DWG with no $INSUNITS reads 1000x
    # too large because service.py applies a 1.0 factor for "unitless".
    if units in (None, "unitless"):
        units = infer_units_from_extents(extents) or units
    logger.info("DDC DWG source unit resolved: %s", units)

    return {
        "layers": layers,
        "entities": entities,
        "extents": extents,
        "units": units,
        "entity_count": len(entities),
        "layouts": sorted_layouts,
    }


def _empty() -> dict[str, Any]:
    return {
        "layers": [],
        "entities": [],
        "extents": {"min_x": 0, "min_y": 0, "max_x": 0, "max_y": 0},
        "units": "unitless",
        "entity_count": 0,
    }
