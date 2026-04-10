"""IFC/RVT file processor — uses DDC cad2data when available, text parser as fallback.

Processing pipeline:
1. Try DDC cad2data (external tool) → full DataFrame + COLLADA geometry
2. Fallback: text-based IFC STEP parser → extracts entities, properties, quantities
3. Generates simplified COLLADA boxes for 3D preview

For full geometry: install DDC cad2data or use Advanced Mode to upload CSV + DAE.
"""

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# IFC entity types we care about
_ELEMENT_TYPES = {
    "IFCWALL", "IFCWALLSTANDARDCASE", "IFCSLAB", "IFCCOLUMN", "IFCBEAM",
    "IFCDOOR", "IFCWINDOW", "IFCROOF", "IFCSTAIR", "IFCRAILING",
    "IFCCURTAINWALL", "IFCPLATE", "IFCMEMBER", "IFCFOOTING",
    "IFCPILE", "IFCBUILDINGELEMENTPROXY",
    "IFCFLOWSEGMENT", "IFCFLOWTERMINAL", "IFCFLOWFITTING",
    "IFCDISTRIBUTIONELEMENT", "IFCFURNISHINGELEMENT",
    "IFCCOVERING", "IFCSPACE",
}

_STOREY_TYPE = "IFCBUILDINGSTOREY"

# Regex for IFC STEP line: #123= IFCWALL('guid', #owner, 'name', ...)
_LINE_RE = re.compile(r"^#(\d+)\s*=\s*(\w+)\s*\((.*)\)\s*;", re.DOTALL)
_STRING_RE = re.compile(r"'([^']*)'")


def _try_cad2data(ifc_path: Path, output_dir: Path) -> dict[str, Any] | None:
    """Try to convert CAD files using DDC converters.

    Pipeline (tried in order):
    1. DDC Community Converter (RvtExporter.exe / IfcExporter.exe) → Excel → elements
    2. cad2data binary on PATH → CSV + DAE
    """
    ext = ifc_path.suffix.lower().lstrip(".")

    # --- Method 1: DDC Community Converter (same pipeline as Data Explorer) ---
    try:
        from app.modules.boq.cad_import import find_converter, parse_cad_excel

        converter = find_converter(ext)
        if converter:
            import subprocess
            logger.info("Using DDC Community Converter: %s", converter)

            output_dir.mkdir(parents=True, exist_ok=True)
            output_xlsx = output_dir / (ifc_path.stem + ".xlsx")
            args = [str(converter), str(ifc_path), str(output_xlsx)]
            if ext in ("rvt", "ifc"):
                args.append("complete")

            converter_dir = converter.parent
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(converter_dir),
                input=b"\n",
                timeout=300,
            )

            if result.returncode != 0:
                logger.warning("DDC converter failed (exit %d): %s", result.returncode, result.stderr.decode(errors="replace")[:500])
            else:
                # Find output Excel
                excel_path = None
                for f in output_dir.iterdir():
                    if f.suffix in (".xlsx", ".xls"):
                        excel_path = f
                        break
                if not excel_path and output_xlsx.exists():
                    excel_path = output_xlsx

                if excel_path:
                    raw_elements = parse_cad_excel(excel_path)
                    if raw_elements:
                        return _excel_elements_to_bim_result(raw_elements, output_dir)
                    logger.warning("DDC converter produced Excel but no elements")
                else:
                    logger.warning("DDC converter produced no Excel output")
    except ImportError:
        logger.debug("cad_import module not available")
    except Exception as e:
        logger.warning("DDC Community Converter error: %s", e)

    # --- Method 2: cad2data binary on PATH ---
    import shutil
    import csv

    cad2data_bin = shutil.which("cad2data")
    if not cad2data_bin:
        return None

    logger.info("Using DDC cad2data for conversion: %s", cad2data_bin)
    try:
        import subprocess

        result = subprocess.run(
            [cad2data_bin, str(ifc_path), "--output-dir", str(output_dir), "--format", "csv,dae"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning("cad2data failed: %s", result.stderr[:500])
            return None

        csv_path = output_dir / "elements.csv"
        dae_path = output_dir / "geometry.dae"
        if not csv_path.exists():
            for p in output_dir.glob("*.csv"):
                csv_path = p
                break

        elements: list[dict[str, Any]] = []
        storeys_set: set[str] = set()
        disciplines_set: set[str] = set()

        if csv_path.exists():
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    storey = row.get("storey", row.get("level", ""))
                    discipline = row.get("discipline", _classify_discipline(row.get("type", "")))
                    if storey:
                        storeys_set.add(storey)
                    disciplines_set.add(discipline)

                    quantities: dict[str, float] = {}
                    for qkey in ("area", "volume", "length", "width", "height"):
                        if qkey in row and row[qkey]:
                            try:
                                quantities[qkey.title()] = float(row[qkey])
                            except ValueError:
                                pass

                    elements.append({
                        "stable_id": row.get("global_id", row.get("id", str(len(elements)))),
                        "element_type": row.get("type", "Unknown"),
                        "name": row.get("name", ""),
                        "storey": storey or None,
                        "discipline": discipline,
                        "properties": {k: v for k, v in row.items() if k not in ("global_id", "id", "type", "name", "storey", "discipline")},
                        "quantities": quantities,
                        "geometry_hash": hashlib.md5(str(row).encode()).hexdigest()[:16],
                        "bounding_box": None,
                    })

        has_geometry = dae_path.exists()
        return {
            "elements": elements,
            "storeys": sorted(storeys_set),
            "disciplines": sorted(disciplines_set),
            "element_count": len(elements),
            "has_geometry": has_geometry,
            "geometry_path": str(dae_path) if has_geometry else None,
            "bounding_box": None,
        }
    except Exception as e:
        logger.warning("cad2data error: %s", e)
        return None


def _excel_elements_to_bim_result(
    raw_elements: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    """Convert parsed Excel elements (from DDC converter) into BIM result format."""
    elements: list[dict[str, Any]] = []
    storeys_set: set[str] = set()
    disciplines_set: set[str] = set()

    for i, row in enumerate(raw_elements):
        etype = str(row.get("Type", row.get("type", row.get("Category", ""))))
        name = str(row.get("Name", row.get("name", row.get("Family", ""))))
        storey = str(row.get("Level", row.get("level", row.get("Storey", ""))))
        discipline = _classify_discipline(etype)

        if storey:
            storeys_set.add(storey)
        disciplines_set.add(discipline)

        quantities: dict[str, float] = {}
        for qkey in ("Area", "Volume", "Length", "Width", "Height", "Count",
                      "area", "volume", "length", "width", "height", "count"):
            val = row.get(qkey)
            if val is not None:
                try:
                    quantities[qkey.title()] = float(val)
                except (ValueError, TypeError):
                    pass

        stable_id = str(row.get("GlobalId", row.get("global_id", row.get("Id", row.get("id", i)))))

        elements.append({
            "stable_id": stable_id,
            "element_type": etype or "Unknown",
            "name": name or etype or f"Element-{i}",
            "storey": storey or None,
            "discipline": discipline,
            "properties": {k: str(v) for k, v in row.items() if k.lower() not in (
                "globalid", "global_id", "id", "type", "name", "level", "storey",
                "category", "family", "area", "volume", "length", "width", "height", "count",
            ) and v is not None and str(v).strip()},
            "quantities": quantities,
            "geometry_hash": hashlib.md5(f"{stable_id}:{etype}:{name}".encode()).hexdigest()[:16],
            "bounding_box": None,
        })

    # Generate COLLADA boxes for 3D preview
    geometry_path = None
    bounding_box = None
    if elements:
        try:
            geometry_path, bounding_box = _generate_collada_boxes(elements, output_dir)
        except Exception as e:
            logger.warning("COLLADA generation failed for DDC converter output: %s", e)

    return {
        "elements": elements,
        "storeys": sorted(storeys_set),
        "disciplines": sorted(disciplines_set),
        "element_count": len(elements),
        "has_geometry": geometry_path is not None,
        "geometry_path": str(geometry_path) if geometry_path else None,
        "bounding_box": bounding_box,
    }


def process_ifc_file(
    ifc_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Process an IFC/RVT file.

    Pipeline:
    1. Try DDC cad2data (full conversion with geometry)
    2. Fallback: text-based IFC parser (elements only, box geometry)

    Returns dict with elements, storeys, disciplines, geometry info.
    """
    # Step 1: Try cad2data
    cad_result = _try_cad2data(ifc_path, output_dir)
    if cad_result and cad_result["element_count"] > 0:
        logger.info("cad2data conversion successful: %d elements", cad_result["element_count"])
        return cad_result

    # Step 2: Fallback to text parser (IFC only)
    ext = ifc_path.suffix.lower()
    if ext != ".ifc":
        logger.warning("Text parser only supports IFC, not %s. Use cad2data for RVT.", ext)
        return _empty_result()

    try:
        content = ifc_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error("Failed to read IFC file %s: %s", ifc_path, e)
        return _empty_result()

    # Verify it's IFC
    if not content.strip().startswith("ISO-10303-21") and "%PDF" not in content[:20]:
        # Try to detect if it's at least STEP format
        if "HEADER;" not in content[:500] and "DATA;" not in content[:2000]:
            logger.warning("File does not appear to be valid IFC: %s", ifc_path.name)
            return _empty_result()

    logger.info("Processing IFC (text parser): %s (%d bytes)", ifc_path.name, len(content))

    # Parse all entities
    entities: dict[int, dict] = {}
    for line in content.split("\n"):
        line = line.strip()
        m = _LINE_RE.match(line)
        if m:
            eid = int(m.group(1))
            etype = m.group(2).upper()
            args_str = m.group(3)
            entities[eid] = {
                "id": eid,
                "type": etype,
                "args_raw": args_str,
                "strings": _STRING_RE.findall(args_str),
            }

    logger.info("Parsed %d IFC entities", len(entities))

    # Extract storeys
    storeys: dict[int, str] = {}
    for eid, ent in entities.items():
        if ent["type"] == _STOREY_TYPE:
            name = ent["strings"][1] if len(ent["strings"]) > 1 else f"Storey-{eid}"
            storeys[eid] = name

    # Extract spatial containment (IfcRelContainedInSpatialStructure)
    element_to_storey: dict[int, str] = {}
    for ent in entities.values():
        if ent["type"] == "IFCRELCONTAINEDINSPATIALSTRUCTURE":
            # Last arg before closing is the spatial element ref
            refs = re.findall(r"#(\d+)", ent["args_raw"])
            if refs:
                spatial_id = int(refs[-1])
                storey_name = storeys.get(spatial_id, "")
                # All other refs (except first 4 standard args) are contained elements
                for ref_str in refs[:-1]:
                    ref_id = int(ref_str)
                    if ref_id in entities and storey_name:
                        element_to_storey[ref_id] = storey_name

    # Extract building elements
    elements: list[dict[str, Any]] = []
    storeys_set: set[str] = set()
    disciplines_set: set[str] = set()

    for eid, ent in entities.items():
        if ent["type"] in _ELEMENT_TYPES:
            strings = ent["strings"]
            global_id = strings[0] if strings else str(eid)
            name = strings[1] if len(strings) > 1 else ""

            ifc_type = ent["type"]
            discipline = _classify_discipline(ifc_type)
            storey = element_to_storey.get(eid, "")
            simplified_type = _simplify_type(ifc_type)

            if storey:
                storeys_set.add(storey)
            disciplines_set.add(discipline)

            # Extract quantities from related IfcElementQuantity (simplified)
            quantities = _extract_quantities_for_element(eid, entities)

            geo_hash = hashlib.md5(f"{global_id}:{ifc_type}:{name}".encode()).hexdigest()[:16]

            elements.append({
                "stable_id": global_id,
                "element_type": simplified_type,
                "name": name or simplified_type,
                "storey": storey or None,
                "discipline": discipline,
                "properties": {"ifc_type": ifc_type, "ifc_id": eid},
                "quantities": quantities,
                "geometry_hash": geo_hash,
                "bounding_box": None,
            })

    # Generate simplified COLLADA
    geometry_path = None
    has_geometry = False
    bounding_box = None

    if elements:
        try:
            geometry_path, bounding_box = _generate_collada_boxes(elements, output_dir)
            has_geometry = geometry_path is not None
        except Exception as e:
            logger.warning("COLLADA generation failed: %s", e)

    logger.info(
        "IFC text-parsed: %d elements, %d storeys, %d disciplines",
        len(elements), len(storeys_set), len(disciplines_set),
    )

    return {
        "elements": elements,
        "storeys": sorted(storeys_set),
        "disciplines": sorted(disciplines_set),
        "element_count": len(elements),
        "has_geometry": has_geometry,
        "geometry_path": str(geometry_path) if geometry_path else None,
        "bounding_box": bounding_box,
    }


def _extract_quantities_for_element(
    element_id: int,
    entities: dict[int, dict],
) -> dict[str, float]:
    """Try to find quantities related to an element via IfcRelDefinesByProperties."""
    quantities: dict[str, float] = {}

    for ent in entities.values():
        if ent["type"] == "IFCRELDEFINESBYPROPERTIES":
            refs = re.findall(r"#(\d+)", ent["args_raw"])
            if not refs:
                continue
            # Check if this element is in the related objects
            if str(element_id) not in [r for r in refs[:-1]]:
                continue
            # Last ref is the property definition
            pdef_id = int(refs[-1])
            pdef = entities.get(pdef_id)
            if not pdef:
                continue
            if pdef["type"] == "IFCELEMENTQUANTITY":
                # Find quantity refs in the element quantity
                q_refs = re.findall(r"#(\d+)", pdef["args_raw"])
                for qr in q_refs:
                    q_ent = entities.get(int(qr))
                    if not q_ent:
                        continue
                    if q_ent["type"] in (
                        "IFCQUANTITYLENGTH", "IFCQUANTITYAREA",
                        "IFCQUANTITYVOLUME", "IFCQUANTITYWEIGHT", "IFCQUANTITYCOUNT",
                    ):
                        q_strings = q_ent["strings"]
                        q_name = q_strings[0] if q_strings else "unknown"
                        # Try to extract numeric value
                        nums = re.findall(r"[\d.]+(?:E[+-]?\d+)?", q_ent["args_raw"])
                        for n in nums:
                            try:
                                val = float(n)
                                if val > 0:
                                    quantities[q_name] = val
                                    break
                            except ValueError:
                                continue

    return quantities


def _classify_discipline(ifc_type: str) -> str:
    """Classify IFC type into a discipline."""
    t = ifc_type.lower()
    if any(x in t for x in ["wall", "slab", "column", "beam", "footing", "pile", "stair", "railing", "roof"]):
        return "structural"
    if any(x in t for x in ["door", "window", "curtainwall", "covering", "furnishing"]):
        return "architecture"
    if any(x in t for x in ["flow", "distribution", "pipe", "duct", "cable"]):
        return "mep"
    if "space" in t:
        return "architecture"
    return "other"


def _simplify_type(ifc_type: str) -> str:
    """Simplify IFC type name for display."""
    return (
        ifc_type
        .replace("IFCWALLSTANDARDCASE", "Wall")
        .replace("IFC", "")
        .title()
    )


def _generate_collada_boxes(
    elements: list[dict],
    output_dir: Path,
) -> tuple[Path | None, dict | None]:
    """Generate simplified COLLADA with box placeholders per element."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dae_path = output_dir / "geometry.dae"

    NS = "http://www.collada.org/2005/11/COLLADASchema"
    root = ET.Element("COLLADA", xmlns=NS, version="1.4.1")

    asset = ET.SubElement(root, "asset")
    ET.SubElement(asset, "up_axis").text = "Z_UP"

    lib_geom = ET.SubElement(root, "library_geometries")
    lib_scenes = ET.SubElement(root, "library_visual_scenes")
    vscene = ET.SubElement(lib_scenes, "visual_scene", id="Scene", name="Scene")

    # Layout elements in a grid if no coordinates
    for i, elem in enumerate(elements[:500]):  # Cap at 500 for performance
        q = elem.get("quantities", {})
        w = q.get("Width", q.get("Breite", 0.3))
        h = q.get("Height", q.get("Hoehe", 3.0))
        ln = q.get("Length", q.get("Laenge", 1.0))

        # Grid placement
        row = i // 20
        col = i % 20
        x = col * 4.0
        y = row * 4.0
        z = 0.0

        gid = f"g{i}"
        geom = ET.SubElement(lib_geom, "geometry", id=gid, name=elem.get("name", f"e{i}"))
        mesh = ET.SubElement(geom, "mesh")

        verts = [
            (0, 0, 0), (ln, 0, 0), (ln, w, 0), (0, w, 0),
            (0, 0, h), (ln, 0, h), (ln, w, h), (0, w, h),
        ]
        pos_str = " ".join(f"{v[0]:.2f} {v[1]:.2f} {v[2]:.2f}" for v in verts)

        src = ET.SubElement(mesh, "source", id=f"{gid}-p")
        fa = ET.SubElement(src, "float_array", id=f"{gid}-pa", count=str(len(verts) * 3))
        fa.text = pos_str
        tc = ET.SubElement(src, "technique_common")
        acc = ET.SubElement(tc, "accessor", source=f"#{gid}-pa", count=str(len(verts)), stride="3")
        ET.SubElement(acc, "param", name="X", type="float")
        ET.SubElement(acc, "param", name="Y", type="float")
        ET.SubElement(acc, "param", name="Z", type="float")

        vs = ET.SubElement(mesh, "vertices", id=f"{gid}-v")
        ET.SubElement(vs, "input", semantic="POSITION", source=f"#{gid}-p")

        tri = ET.SubElement(mesh, "triangles", count="12")
        ET.SubElement(tri, "input", semantic="VERTEX", source=f"#{gid}-v", offset="0")
        p = ET.SubElement(tri, "p")
        p.text = "0 1 2 0 2 3 4 6 5 4 7 6 0 4 5 0 5 1 2 6 7 2 7 3 0 3 7 0 7 4 1 5 6 1 6 2"

        node = ET.SubElement(vscene, "node", id=f"n{i}", name=elem.get("name", f"e{i}"))
        mat = ET.SubElement(node, "matrix", sid="transform")
        mat.text = f"1 0 0 {x:.2f} 0 1 0 {y:.2f} 0 0 1 {z:.2f} 0 0 0 1"
        ET.SubElement(node, "instance_geometry", url=f"#{gid}")

    scene = ET.SubElement(root, "scene")
    ET.SubElement(scene, "instance_visual_scene", url="#Scene")

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(dae_path), xml_declaration=True, encoding="utf-8")

    n = min(len(elements), 500)
    cols = min(n, 20)
    rows = (n + 19) // 20
    bb = {
        "min": {"x": 0, "y": 0, "z": 0},
        "max": {"x": cols * 4.0, "y": rows * 4.0, "z": 3.0},
    }

    logger.info("Generated COLLADA boxes: %d elements", n)
    return dae_path, bb


def _empty_result() -> dict[str, Any]:
    return {
        "elements": [],
        "storeys": [],
        "disciplines": [],
        "element_count": 0,
        "has_geometry": False,
        "geometry_path": None,
        "bounding_box": None,
    }
