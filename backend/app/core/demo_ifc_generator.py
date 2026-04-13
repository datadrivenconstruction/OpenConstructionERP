"""Generate minimal IFC files for demo projects.

Creates valid IFC2x3 files with realistic building elements (walls, slabs,
columns, doors, windows) positioned in a recognisable building layout.
These are used as sample BIM models when demo projects are installed.

The generated IFC is deliberately simple (extruded boxes) so the text-based
IFC parser can extract elements, storeys, and quantities without requiring
the DDC converter.  The result is a realistic element list and a 3D preview
that looks like an actual building — not a grid of boxes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# IFC STEP helpers
# ---------------------------------------------------------------------------

_COUNTER = 0


def _next_id() -> int:
    global _COUNTER
    _COUNTER += 1
    return _COUNTER


def _reset():
    global _COUNTER
    _COUNTER = 0


def _guid() -> str:
    """Generate a 22-char IFC GlobalId from a UUID."""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
    u = uuid.uuid4().int
    result = []
    for _ in range(22):
        result.append(chars[u % 64])
        u //= 64
    return "".join(result)


def _ifc_string(s: str) -> str:
    return f"'{s}'"


def _ifc_point(x: float, y: float, z: float) -> str:
    return f"({x:.4f},{y:.4f},{z:.4f})"


# ---------------------------------------------------------------------------
# Element definitions per demo project
# ---------------------------------------------------------------------------

def _residential_berlin_elements() -> list[dict]:
    """48-unit residential complex — 4 storeys."""
    elements = []
    storeys = ["EG (Erdgeschoss)", "1.OG", "2.OG", "3.OG"]
    for si, storey in enumerate(storeys):
        z = si * 3.0
        # Exterior walls (4 per floor)
        for wi, (x, y, dx, dy) in enumerate([
            (0, 0, 20, 0.3), (0, 0, 0.3, 12),
            (20, 0, 0.3, 12), (0, 12, 20, 0.3),
        ]):
            elements.append({
                "type": "IFCWALLSTANDARDCASE", "name": f"Exterior Wall {storey}-{wi+1}",
                "storey": storey, "x": x, "y": y, "z": z,
                "length": max(dx, dy), "width": min(dx, dy) or 0.3, "height": 3.0,
            })
        # Interior walls (3 per floor)
        for wi, x_pos in enumerate([5.0, 10.0, 15.0]):
            elements.append({
                "type": "IFCWALL", "name": f"Interior Wall {storey}-{wi+1}",
                "storey": storey, "x": x_pos, "y": 0.3, "z": z,
                "length": 0.15, "width": 11.4, "height": 3.0,
            })
        # Floor slab
        elements.append({
            "type": "IFCSLAB", "name": f"Floor Slab {storey}",
            "storey": storey, "x": 0, "y": 0, "z": z,
            "length": 20, "width": 12, "height": 0.25,
        })
        # Columns (4 per floor)
        for ci, (cx, cy) in enumerate([(0, 0), (20, 0), (0, 12), (20, 12)]):
            elements.append({
                "type": "IFCCOLUMN", "name": f"Column {storey}-{ci+1}",
                "storey": storey, "x": cx, "y": cy, "z": z,
                "length": 0.4, "width": 0.4, "height": 3.0,
            })
        # Doors (4 per floor)
        for di in range(4):
            elements.append({
                "type": "IFCDOOR", "name": f"Door {storey}-{di+1}",
                "storey": storey, "x": 2.5 + di * 5.0, "y": 0.0, "z": z,
                "length": 1.0, "width": 0.1, "height": 2.1,
            })
        # Windows (6 per floor)
        for wi in range(6):
            elements.append({
                "type": "IFCWINDOW", "name": f"Window {storey}-{wi+1}",
                "storey": storey, "x": 1.5 + wi * 3.0, "y": 12.0, "z": z + 0.9,
                "length": 1.2, "width": 0.1, "height": 1.5,
            })
    # Roof slab
    elements.append({
        "type": "IFCSLAB", "name": "Roof Slab",
        "storey": "Dach", "x": 0, "y": 0, "z": 12.0,
        "length": 20, "width": 12, "height": 0.3,
    })
    # Stair
    elements.append({
        "type": "IFCSTAIR", "name": "Main Staircase",
        "storey": "EG (Erdgeschoss)", "x": 9.0, "y": 4.0, "z": 0,
        "length": 2.5, "width": 4.0, "height": 12.0,
    })
    # Footings
    for fi, (fx, fy) in enumerate([(0, 0), (20, 0), (0, 12), (20, 12), (10, 0), (10, 12)]):
        elements.append({
            "type": "IFCFOOTING", "name": f"Strip Footing {fi+1}",
            "storey": "Foundation", "x": fx, "y": fy, "z": -1.0,
            "length": 1.5, "width": 0.8, "height": 0.5,
        })
    return elements


def _office_london_elements() -> list[dict]:
    """12-storey office tower."""
    elements = []
    storeys = ["Ground Floor"] + [f"Level {i}" for i in range(1, 12)] + ["Roof"]
    for si, storey in enumerate(storeys[:-1]):
        z = si * 3.5
        # Core walls
        for wi, (x, y, dx, dy) in enumerate([
            (12, 5, 6, 0.3), (12, 10, 6, 0.3),
            (12, 5, 0.3, 5), (18, 5, 0.3, 5),
        ]):
            elements.append({
                "type": "IFCWALL", "name": f"Core Wall {storey}-{wi+1}",
                "storey": storey, "x": x, "y": y, "z": z,
                "length": max(dx, dy), "width": min(dx, dy) or 0.3, "height": 3.5,
            })
        # Floor slab
        elements.append({
            "type": "IFCSLAB", "name": f"Slab {storey}",
            "storey": storey, "x": 0, "y": 0, "z": z,
            "length": 30, "width": 15, "height": 0.3,
        })
        # Curtain wall facade (2 sides)
        for side in range(2):
            elements.append({
                "type": "IFCCURTAINWALL", "name": f"Curtain Wall {storey}-{side+1}",
                "storey": storey,
                "x": 0 if side == 0 else 30, "y": 0, "z": z,
                "length": 0.15, "width": 15, "height": 3.5,
            })
        # Columns (6 per floor)
        for ci, (cx, cy) in enumerate([(0, 0), (15, 0), (30, 0), (0, 15), (15, 15), (30, 15)]):
            elements.append({
                "type": "IFCCOLUMN", "name": f"Column {storey}-{ci+1}",
                "storey": storey, "x": cx, "y": cy, "z": z,
                "length": 0.5, "width": 0.5, "height": 3.5,
            })
        # Beams (4 per floor)
        for bi in range(4):
            elements.append({
                "type": "IFCBEAM", "name": f"Beam {storey}-{bi+1}",
                "storey": storey, "x": 0, "y": bi * 5.0, "z": z + 3.2,
                "length": 30, "width": 0.3, "height": 0.5,
            })
    # Roof
    elements.append({
        "type": "IFCSLAB", "name": "Roof Slab",
        "storey": "Roof", "x": 0, "y": 0, "z": 42.0,
        "length": 30, "width": 15, "height": 0.35,
    })
    return elements


def _medical_us_elements() -> list[dict]:
    """Hospital — 3 floors + basement."""
    elements = []
    storeys = ["Basement", "Ground Floor", "First Floor", "Second Floor"]
    for si, storey in enumerate(storeys):
        z = (si - 1) * 4.0  # basement at -4.0
        # Exterior walls
        for wi, (x, y, dx, dy) in enumerate([
            (0, 0, 40, 0.3), (0, 0, 0.3, 25),
            (40, 0, 0.3, 25), (0, 25, 40, 0.3),
        ]):
            elements.append({
                "type": "IFCWALLSTANDARDCASE", "name": f"Ext Wall {storey}-{wi+1}",
                "storey": storey, "x": x, "y": y, "z": z,
                "length": max(dx, dy), "width": min(dx, dy) or 0.3, "height": 4.0,
            })
        # Floor
        elements.append({
            "type": "IFCSLAB", "name": f"Slab {storey}",
            "storey": storey, "x": 0, "y": 0, "z": z,
            "length": 40, "width": 25, "height": 0.3,
        })
        # Interior partitions
        for pi in range(5):
            elements.append({
                "type": "IFCWALL", "name": f"Partition {storey}-{pi+1}",
                "storey": storey, "x": 8.0 * (pi + 1), "y": 0.3, "z": z,
                "length": 0.12, "width": 24.4, "height": 4.0,
            })
        # Doors
        for di in range(8):
            elements.append({
                "type": "IFCDOOR", "name": f"Door {storey}-{di+1}",
                "storey": storey, "x": 4.0 + di * 5.0, "y": 0.0, "z": z,
                "length": 1.2, "width": 0.1, "height": 2.1,
            })
    return elements


# ---------------------------------------------------------------------------
# IFC File Generator
# ---------------------------------------------------------------------------

def generate_demo_ifc(
    demo_id: str,
    project_name: str,
) -> str:
    """Generate a minimal valid IFC2x3 file as a string.

    Returns the IFC content ready to write to a file or pass to the
    IFC processor.
    """
    _reset()

    elements_map = {
        "residential-berlin": _residential_berlin_elements,
        "office-london": _office_london_elements,
        "medical-us": _medical_us_elements,
    }

    gen_func = elements_map.get(demo_id)
    if not gen_func:
        gen_func = _residential_berlin_elements  # fallback

    elements = gen_func()

    # Collect unique storeys
    storey_names = list(dict.fromkeys(e["storey"] for e in elements))

    lines: list[str] = []
    lines.append("ISO-10303-21;")
    lines.append("HEADER;")
    lines.append(f"FILE_DESCRIPTION(('ViewDefinition [CoordinationView_V2.0]'),'2;1');")
    lines.append(f"FILE_NAME('{project_name}.ifc','{datetime.now(timezone.utc).strftime('%Y-%m-%d')}',('OpenConstructionERP'),('DDC'),'','OpenConstructionERP v1.5.0','');")
    lines.append("FILE_SCHEMA(('IFC2X3'));")
    lines.append("ENDSEC;")
    lines.append("DATA;")

    # Fixed entities
    owner_id = _next_id()
    person_id = _next_id()
    org_id = _next_id()
    po_id = _next_id()
    app_id = _next_id()
    units_id = _next_id()
    si_length_id = _next_id()
    si_area_id = _next_id()
    si_volume_id = _next_id()
    ctx_id = _next_id()
    ctx3d_id = _next_id()
    project_id = _next_id()
    site_id = _next_id()
    building_id = _next_id()

    lines.append(f"#{person_id}= IFCPERSON($,'Demo','User',$,$,$,$,$);")
    lines.append(f"#{org_id}= IFCORGANIZATION($,'OpenConstructionERP',$,$,$);")
    lines.append(f"#{po_id}= IFCPERSONANDORGANIZATION(#{person_id},#{org_id},$);")
    lines.append(f"#{app_id}= IFCAPPLICATION(#{org_id},'1.5.0','OpenConstructionERP','OE');")
    lines.append(f"#{owner_id}= IFCOWNERHISTORY(#{po_id},#{app_id},$,.NOCHANGE.,$,$,$,0);")
    lines.append(f"#{si_length_id}= IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);")
    lines.append(f"#{si_area_id}= IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);")
    lines.append(f"#{si_volume_id}= IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.);")
    lines.append(f"#{units_id}= IFCUNITASSIGNMENT((#{si_length_id},#{si_area_id},#{si_volume_id}));")

    # Geometric context
    origin_id = _next_id()
    lines.append(f"#{origin_id}= IFCCARTESIANPOINT((0.0,0.0,0.0));")
    lines.append(f"#{ctx3d_id}= IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.0E-5,#{_next_id()},$);")
    axis_id = _next_id()
    lines.append(f"#{axis_id}= IFCAXIS2PLACEMENT3D(#{origin_id},$,$);")

    lines.append(f"#{project_id}= IFCPROJECT('{_guid()}',#{owner_id},{_ifc_string(project_name)},$,$,$,$,(#{ctx3d_id}),#{units_id});")

    # Site
    site_placement_id = _next_id()
    lines.append(f"#{site_placement_id}= IFCLOCALPLACEMENT($,#{axis_id});")
    lines.append(f"#{site_id}= IFCSITE('{_guid()}',#{owner_id},'Site',$,$,#{site_placement_id},$,$,.ELEMENT.,$,$,$,$,$);")

    # Building
    bld_placement_id = _next_id()
    lines.append(f"#{bld_placement_id}= IFCLOCALPLACEMENT(#{site_placement_id},#{axis_id});")
    lines.append(f"#{building_id}= IFCBUILDING('{_guid()}',#{owner_id},{_ifc_string(project_name)},$,$,#{bld_placement_id},$,$,.ELEMENT.,$,$,$);")

    # Storeys
    storey_ids: dict[str, int] = {}
    for s_name in storey_names:
        sid = _next_id()
        storey_ids[s_name] = sid
        s_placement_id = _next_id()
        lines.append(f"#{s_placement_id}= IFCLOCALPLACEMENT(#{bld_placement_id},#{axis_id});")
        lines.append(f"#{sid}= IFCBUILDINGSTOREY('{_guid()}',#{owner_id},{_ifc_string(s_name)},$,$,#{s_placement_id},$,$,.ELEMENT.,0.0);")

    # Elements with placement and quantities
    storey_element_map: dict[str, list[int]] = {s: [] for s in storey_names}

    for elem in elements:
        eid = _next_id()

        # Placement
        pt_id = _next_id()
        lines.append(f"#{pt_id}= IFCCARTESIANPOINT(({elem['x']:.4f},{elem['y']:.4f},{elem['z']:.4f}));")
        axis_pl_id = _next_id()
        lines.append(f"#{axis_pl_id}= IFCAXIS2PLACEMENT3D(#{pt_id},$,$);")
        lp_id = _next_id()
        parent_pl = bld_placement_id
        if elem["storey"] in storey_ids:
            # Use building placement as parent (simplified)
            pass
        lines.append(f"#{lp_id}= IFCLOCALPLACEMENT(#{parent_pl},#{axis_pl_id});")

        # Quantities
        qty_ids = []
        ln = elem.get("length", 1.0)
        w = elem.get("width", 0.3)
        h = elem.get("height", 3.0)

        ql_id = _next_id()
        lines.append(f"#{ql_id}= IFCQUANTITYLENGTH('Length',$,#{si_length_id},{ln:.4f});")
        qty_ids.append(ql_id)
        qw_id = _next_id()
        lines.append(f"#{qw_id}= IFCQUANTITYLENGTH('Width',$,#{si_length_id},{w:.4f});")
        qty_ids.append(qw_id)
        qh_id = _next_id()
        lines.append(f"#{qh_id}= IFCQUANTITYLENGTH('Height',$,#{si_length_id},{h:.4f});")
        qty_ids.append(qh_id)

        area = ln * w
        if area > 0:
            qa_id = _next_id()
            lines.append(f"#{qa_id}= IFCQUANTITYAREA('Area',$,#{si_area_id},{area:.4f});")
            qty_ids.append(qa_id)

        volume = ln * w * h
        if volume > 0:
            qv_id = _next_id()
            lines.append(f"#{qv_id}= IFCQUANTITYVOLUME('Volume',$,#{si_volume_id},{volume:.4f});")
            qty_ids.append(qv_id)

        eq_id = _next_id()
        qty_refs = ",".join(f"#{q}" for q in qty_ids)
        lines.append(f"#{eq_id}= IFCELEMENTQUANTITY('{_guid()}',#{owner_id},'BaseQuantities',$,$,({qty_refs}));")

        # Element entity
        ifc_type = elem["type"]
        lines.append(f"#{eid}= {ifc_type}('{_guid()}',#{owner_id},{_ifc_string(elem['name'])},$,$,#{lp_id},$,$);")

        # Link quantities to element
        rel_id = _next_id()
        lines.append(f"#{rel_id}= IFCRELDEFINESBYPROPERTIES('{_guid()}',#{owner_id},$,$,(#{eid}),#{eq_id});")

        storey_element_map.setdefault(elem["storey"], []).append(eid)

    # Spatial containment
    for s_name, e_ids in storey_element_map.items():
        if not e_ids or s_name not in storey_ids:
            continue
        rel_id = _next_id()
        refs = ",".join(f"#{e}" for e in e_ids)
        lines.append(f"#{rel_id}= IFCRELCONTAINEDINSPATIALSTRUCTURE('{_guid()}',#{owner_id},$,$,({refs}),#{storey_ids[s_name]});")

    # Aggregation: project > site > building > storeys
    rel_id = _next_id()
    lines.append(f"#{rel_id}= IFCRELAGGREGATES('{_guid()}',#{owner_id},$,$,#{project_id},(#{site_id}));")
    rel_id = _next_id()
    lines.append(f"#{rel_id}= IFCRELAGGREGATES('{_guid()}',#{owner_id},$,$,#{site_id},(#{building_id}));")
    rel_id = _next_id()
    storey_refs = ",".join(f"#{storey_ids[s]}" for s in storey_names)
    lines.append(f"#{rel_id}= IFCRELAGGREGATES('{_guid()}',#{owner_id},$,$,#{building_id},({storey_refs}));")

    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;")

    return "\n".join(lines)
