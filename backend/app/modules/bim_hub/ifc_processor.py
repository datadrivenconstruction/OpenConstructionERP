"""IFC/RVT file processor — uses DDC cad2data when available, text parser as fallback.

Processing pipeline:
1. Try DDC cad2data (external tool) → full DataFrame + COLLADA geometry
2. Fallback: text-based IFC STEP parser → extracts entities, properties, quantities
3. Generates simplified COLLADA boxes for 3D preview

For full geometry: install DDC cad2data or use Advanced Mode to upload CSV + DAE.

Identity mapping (DDC RvtExporter):
    The DDC COLLADA pass emits numeric ``<node id="N">`` values where ``N`` is
    the Revit ElementId (``Element.Id.IntegerValue``). The DDC Excel pass emits
    the same ElementId in its first column (header ``ID``). We use that ID as
    the element's ``mesh_ref`` so the 3D viewer can pair each BIM element row
    with its DAE node for filtering and isolation.
"""

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_COLLADA_NS = "http://www.collada.org/2005/11/COLLADASchema"

logger = logging.getLogger(__name__)

# IFC entity types we care about — includes IFC2x3, IFC4, and IFC4x3 civil types
_ELEMENT_TYPES = {
    # ── Structural / architectural (IFC2x3+) ──
    "IFCWALL", "IFCWALLSTANDARDCASE", "IFCSLAB", "IFCCOLUMN", "IFCBEAM",
    "IFCDOOR", "IFCWINDOW", "IFCROOF", "IFCSTAIR", "IFCRAILING",
    "IFCCURTAINWALL", "IFCPLATE", "IFCMEMBER", "IFCFOOTING",
    "IFCPILE", "IFCBUILDINGELEMENTPROXY",
    # ── MEP ──
    "IFCFLOWSEGMENT", "IFCFLOWTERMINAL", "IFCFLOWFITTING",
    "IFCDISTRIBUTIONELEMENT", "IFCFURNISHINGELEMENT",
    "IFCCOVERING", "IFCSPACE",
    # ── Civil infrastructure (IFC4x3 + common proxies) ──
    "IFCALIGNMENT", "IFCALIGNMENTHORIZONTAL", "IFCALIGNMENTVERTICAL",
    "IFCALIGNMENTSEGMENT", "IFCALIGNMENTCANT",
    "IFCBRIDGE", "IFCBRIDGEPART",
    "IFCROAD", "IFCROADPART",
    "IFCRAILWAY", "IFCRAILWAYPART",
    "IFCFACILITY", "IFCFACILITYPART",
    "IFCPAVEMENT", "IFCKERB", "IFCCOURSE",
    "IFCEARTHWORKSFILL", "IFCEARTHWORKSCUT", "IFCEARTHWORKSELEMENT",
    "IFCREINFORCEDSOIL", "IFCGEOTECHNICELEMENT", "IFCGEOTECHNICSTRATUM",
    "IFCDEEPFOUNDATION", "IFCCAISSONFOOTING",
    "IFCBEARING", "IFCTENDON", "IFCTENDONANCHOR", "IFCTENDONCONDUIT",
    "IFCSURFACEFEATURE", "IFCVOIDINGELEMENT",
    # ── Generic / catch-all ──
    "IFCCIVILELEMENT", "IFCGEOGRAPHICELEMENT",
    "IFCTRANSPORTELEMENT", "IFCVIRTUALELEMENT",
    "IFCEXTERNALSPATIALELEMENT",
}

# Spatial structure types used as "storey" equivalents (IFC4x3 uses
# IfcFacilityPart for road stations, bridge spans, etc.)
_STOREY_TYPES = {"IFCBUILDINGSTOREY", "IFCFACILITYPART", "IFCBRIDGEPART", "IFCROADPART", "IFCRAILWAYPART"}

# Regex for IFC STEP line: #123= IFCWALL('guid', #owner, 'name', ...)
_LINE_RE = re.compile(r"^#(\d+)\s*=\s*(\w+)\s*\((.*)\)\s*;", re.DOTALL)
_STRING_RE = re.compile(r"'([^']*)'")


def _try_cad2data(ifc_path: Path, output_dir: Path, *, conversion_depth: str = "standard") -> dict[str, Any] | None:
    """Try to convert CAD files using DDC converters.

    Pipeline (tried in order):
    1. DDC Community Converter (RvtExporter.exe / IfcExporter.exe) → Excel → elements
    2. cad2data binary on PATH → CSV + DAE
    """
    ext = ifc_path.suffix.lower().lstrip(".")

    # --- Method 1: DDC Community Converter (same pipeline as Data Explorer) ---
    # The DDC RvtExporter / IfcExporter is dispatched by the OUTPUT FILE
    # EXTENSION: .xlsx/.xls → Excel, .dae → COLLADA, .pdf → PDF.
    # We invoke it TWICE so we get both:
    #   1. Element list as Excel (parsed into BIMElement records)
    #   2. Real 3D geometry as native COLLADA (saved as geometry.dae)
    # The second call replaces the simplified box-grid we used to generate
    # from element bounding boxes.
    #
    # CRITICAL: DDC needs cwd=converter.parent (Qt6Core.dll lives there),
    # so all paths must be absolute or the converter reports "File does not exist".
    try:
        from app.modules.boq.cad_import import find_converter, parse_cad_excel

        converter = find_converter(ext)
        if converter:
            import subprocess
            logger.info("Using DDC Community Converter: %s", converter)
            output_dir.mkdir(parents=True, exist_ok=True)

            input_abs = ifc_path.resolve()

            def _run_ddc(out_path: Path, *extra_args: str) -> tuple[int, bytes, bytes]:
                """Invoke RvtExporter / IfcExporter with the given output target."""
                args_list = [str(converter), str(input_abs), str(out_path)]
                if ext in ("rvt", "ifc"):
                    # User-selected depth: 'standard' (fast), 'medium' (balanced), 'complete' (full)
                    # DDC RvtExporter accepts: standard, complete. 'medium' maps to 'standard'
                    # because DDC has no separate medium mode — the difference is handled
                    # by our property extraction (medium = standard DDC + full property promotion).
                    ddc_mode = "complete" if conversion_depth == "complete" else "standard"
                    args_list.append(ddc_mode)
                args_list.extend(extra_args)
                logger.debug("DDC call: %s", args_list)
                proc = subprocess.run(
                    args_list,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(converter.parent),
                    input=b"\n",
                    timeout=600,
                )
                return proc.returncode, proc.stdout, proc.stderr

            # ── Passes 1 + 2 in parallel: Excel + native COLLADA ──────
            # DDC RvtExporter has to load the entire RVT file from scratch
            # for each invocation (no shared state between processes), so
            # running the Excel and COLLADA passes sequentially used to
            # double the effective conversion time.  The two output files
            # are independent — both passes only read the input and write
            # to a different target — so we run them in parallel threads.
            # Wall-time drops to roughly max(Excel, COLLADA) instead of sum.
            #
            # The previously-present third synchronous pass for PDF sheet
            # export was removed: it triples upload latency, frequently
            # times out, and the PDF can be regenerated on demand from the
            # original RVT/IFC blob (which is already saved by the router
            # before this processor runs).
            import concurrent.futures

            output_xlsx = (output_dir / (ifc_path.stem + ".xlsx")).resolve()
            real_dae = (output_dir / "geometry.dae").resolve()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _pool:
                fut_xlsx = _pool.submit(_run_ddc, output_xlsx, "-no-collada")
                fut_dae = _pool.submit(_run_ddc, real_dae)

                try:
                    rc, _stdout, stderr = fut_xlsx.result()
                except subprocess.TimeoutExpired:
                    logger.error("DDC Excel pass timed out for %s", ifc_path.name)
                    return None
                if rc != 0:
                    logger.warning(
                        "DDC Excel pass exit %d: %s",
                        rc, stderr.decode(errors="replace")[:300],
                    )
                    return None

                excel_path: Path | None = None
                if output_xlsx.exists() and output_xlsx.stat().st_size > 0:
                    excel_path = output_xlsx
                else:
                    for f in output_dir.iterdir():
                        if f.suffix in (".xlsx", ".xls") and f.stat().st_size > 0:
                            excel_path = f
                            break
                if not excel_path:
                    logger.warning("DDC Excel pass produced no output file in %s", output_dir)
                    return None

                raw_elements = parse_cad_excel(excel_path)
                if not raw_elements:
                    logger.warning("DDC Excel pass produced empty file")
                    return None
                logger.info(
                    "DDC converter extracted %d raw rows from %s",
                    len(raw_elements), ifc_path.name,
                )

                try:
                    rc2, _stdout2, stderr2 = fut_dae.result()
                except subprocess.TimeoutExpired:
                    logger.warning("DDC COLLADA pass timed out — will fall back to box geometry")
                    rc2 = -1
                    stderr2 = b""

            real_dae_path: Path | None = None
            if rc2 == 0 and real_dae.exists() and real_dae.stat().st_size > 0:
                real_dae_path = real_dae
                logger.info(
                    "DDC native COLLADA generated: %d bytes",
                    real_dae.stat().st_size,
                )
            else:
                logger.warning(
                    "DDC COLLADA pass failed (rc=%s, stderr=%s) — using box fallback",
                    rc2, stderr2.decode(errors="replace")[:200] if stderr2 else "",
                )

            return _excel_elements_to_bim_result(
                raw_elements,
                output_dir,
                real_dae_path=real_dae_path,
            )
    except ImportError:
        logger.debug("cad_import module not available")
    except Exception as e:
        logger.warning("DDC Community Converter error: %s", e, exc_info=True)

    # --- Method 2: cad2data binary on PATH ---
    import csv
    import shutil

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
        csv_raw_rows: list[dict[str, Any]] = []
        storeys_set: set[str] = set()
        disciplines_set: set[str] = set()

        if csv_path.exists():
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    csv_raw_rows.append(dict(row))
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
                        "properties": {
                        k: v for k, v in row.items()
                        if k not in ("global_id", "id", "type", "name", "storey", "discipline")
                    },
                        "quantities": quantities,
                        "geometry_hash": hashlib.md5(str(row).encode()).hexdigest()[:16],
                        "bounding_box": None,
                    })

        has_geometry = dae_path.exists()

        # DAE → GLB post-processing
        glb_path: Path | None = None
        if has_geometry:
            glb_path = _convert_dae_to_glb(dae_path, output_dir)

        return {
            "elements": elements,
            "storeys": sorted(storeys_set),
            "disciplines": sorted(disciplines_set),
            "element_count": len(elements),
            "has_geometry": has_geometry,
            "geometry_path": str(dae_path) if has_geometry else None,
            "glb_path": str(glb_path) if glb_path else None,
            "bounding_box": None,
            "geometry_type": "real" if has_geometry else "placeholder",
            "raw_elements": csv_raw_rows,
        }
    except Exception as e:
        logger.warning("cad2data error: %s", e)
        return None


def _excel_elements_to_bim_result(
    raw_elements: list[dict[str, Any]],
    output_dir: Path,
    *,
    real_dae_path: Path | None = None,
) -> dict[str, Any]:
    """Convert parsed Excel elements (from DDC converter) into BIM result format.

    DDC RvtExporter produces Excel rows with Revit-specific columns:
    - ``category`` like "OST_Walls", "OST_Doors", "OST_PipeFitting"
    - ``name``, ``type name``, ``family name``
    - ``uniqueid`` (Revit GUID)
    - ``level`` for storey, ``length``/``area``/``volume`` for quantities
    - Many BuiltIn parameters like ``width``, ``height``, ``thickness``, etc.

    We filter out non-element rows (sun studies, materials, viewports, etc.)
    and map the meaningful Revit categories into our generic element model.

    If ``real_dae_path`` is provided (output of a separate RvtExporter call to
    .dae), we use the real Revit COLLADA geometry instead of the placeholder
    box-grid generated from element bounding boxes.
    """
    # Skip these categories — they're not building elements.
    # Expanded set covers views, sheets, materials, annotations, tags,
    # dimensions, analytical model, model groups, revisions, schedules,
    # legends, and other non-physical Revit categories.
    SKIP_CATEGORIES: set[str | None] = {
        None, "",
        # Views, sheets, materials, settings
        "ost_materials", "ost_sunstudy", "ost_views", "ost_viewports",
        "ost_grids", "ost_levels", "ost_sheets", "ost_titleblocks",
        "ost_phases", "ost_previewlegendcomponents", "ost_designoptions",
        "ost_paramelemelectricalloadclassification", "ost_hvac_load_space_types",
        "ost_hvac_load_building_types", "ost_filldrawcolor", "ost_filllinepattern",
        # Annotations, tags, dimensions
        "ost_dimensions", "ost_textnotes", "ost_genericannotation",
        "ost_doortags", "ost_windowtags", "ost_roomtags", "ost_walltags",
        "ost_areatags", "ost_keynotetags", "ost_materialtags",
        "ost_areaschemelines", "ost_sketchlines", "ost_weakdims",
        "ost_detailcomponents", "ost_colorfilllegends", "ost_colorfillschema",
        "ost_spotdimensions", "ost_spotcoordinates", "ost_spotslopes",
        "ost_spotelevsymbols", "ost_callouts", "ost_callouthead", "ost_calloutheads",
        "ost_elevationmarks", "ost_sectionmarks", "ost_sectionbox",
        "ost_scopeboxes", "ost_referencepoints", "ost_referenceplane",
        "ost_referenceline", "ost_gridheads", "ost_levelheads",
        "ost_matchline", "ost_viewportlabel",
        # Detail & drafting
        "ost_detailitems", "ost_lines", "ost_clines",
        "ost_rasterimages", "ost_schedulegraphics",
        "ost_tilepatterns", "ost_divisionrules",
        # Revision clouds & tags
        "ost_revisionclouds", "ost_revisioncloudtags",
        "ost_revisions", "ost_revisionnumberingsequences",
        # Analytical / structural analysis
        "ost_analyticalnodes", "ost_analyticalmember", "ost_analyticalsurface",
        "ost_analyticalfloor", "ost_analyticalwall",
        "ost_analyticalpipeconnections", "ost_linksanalytical",
        "ost_loadcases", "ost_constraints",
        # Model groups, design options, arrays
        "ost_iosmodelgroups", "ost_iosdetailgroups", "ost_editcuts",
        "ost_iossketchgrid", "ost_iosgeolocations", "ost_iosgeosite",
        "ost_iosarrays",
        # Schedules, legends
        "ost_schedules", "ost_legendcomponents",
        # Profile / reference / misc
        "ost_profilefamilies", "ost_profileplane",
        "ost_referenceviewersymbol", "ost_multireferenceannotations",
        "ost_sectionheads",
        # Project / system info (not physical)
        "ost_projectinformation", "ost_projectbasepoint",
        "ost_sharedbasepoint", "ost_coordinatesystem",
        "ost_eaconstructions", "ost_covertype",
        # Topography / site context (huge meshes that obscure the building)
        "ost_topography", "ost_toposurface", "ost_topo",
        "ost_site", "ost_sitepad", "ost_siteregion",
        "ost_buildingpad", "ost_pad",
        "ost_entourage", "ost_planting",
        # IFC spatial/project types (from DDC IfcExporter — not physical elements)
        "ifcproject", "ifcsite", "ifcbuilding", "ifcbuildingstorey",
        "ifcownerhistory", "ifcapplication", "ifcpersonandorganization",
        "ifcperson", "ifcorganization", "ifcunitassignment",
        "ifcgeometricrepresentationcontext",
        # HVAC schedules / load (analytical, not physical)
        "ost_hvacloadschedules", "ost_hvac_load_schedules",
        # Room/area separation (lines, not geometry)
        "ost_roomseparationlines", "ost_areaschemes",
    }

    elements: list[dict[str, Any]] = []
    storeys_set: set[str] = set()
    disciplines_set: set[str] = set()

    # Patch DDC COLLADA node names: DDC writes name="node" for every element
    # but the frontend ColladaLoader uses `name` (not `id`) for Object3D.name.
    # Without this patch, mesh_ref matching in the 3D viewer is 0%.
    if real_dae_path and real_dae_path.exists():
        _patch_collada_node_names(real_dae_path)

    # Pre-parse the DAE (if provided) to extract per-node bounding boxes
    # keyed by the numeric Revit ElementId written into <node id="...">.
    dae_bboxes: dict[int, dict[str, float]] = {}
    if real_dae_path and real_dae_path.exists():
        try:
            dae_bboxes = _extract_dae_bboxes_by_node_id(real_dae_path)
            logger.info(
                "Extracted %d per-element bounding boxes from DAE",
                len(dae_bboxes),
            )
        except Exception as exc:
            logger.warning("Failed to extract DAE bboxes: %s", exc)

    for i, row in enumerate(raw_elements):
        # Normalize keys to lowercase for tolerant lookup
        lc_row = {k.lower(): v for k, v in row.items()}

        category = lc_row.get("category")
        cat_lower = str(category or "").lower()

        # Skip non-element rows: those with no category at all (likely orphan
        # parameter rows from the DDC converter), and known non-element categories.
        # DDC writes the literal string "None" for elements without a Revit
        # category — treat it the same as Python None.
        if not category or cat_lower in SKIP_CATEGORIES or cat_lower in ("none", "null", "", "n/a"):
            continue

        # Friendly element type derived from OST_ category name.
        # DDC writes raw Revit built-in category names like
        # "OST_CurtainWallMullions" — we strip the prefix, split
        # CamelCase into words, and title-case the result so the
        # filter panel shows "Curtain Wall Mullions" instead of
        # "Curtainwallmullions".
        if cat_lower.startswith("ost_"):
            raw_name = str(category)[4:]  # preserve original casing
            # Split CamelCase: "CurtainWallMullions" → "Curtain Wall Mullions"
            spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_name)
            spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
            etype = spaced.replace("_", " ").strip()
        else:
            etype = str(category) if category else "Unknown"

        # Best-effort name resolution
        name = (
            lc_row.get("name")
            or lc_row.get("type name")
            or lc_row.get("family name")
            or lc_row.get("mark")
            or f"{etype}-{i}"
        )
        name = str(name)[:200]

        # Storey: DDC writes the actual building level under "Level" for most
        # categories, but walls/columns sometimes only fill "Base Constraint"
        # or "Reference Level". Fall back through all known synonyms.
        storey = (
            lc_row.get("level")
            or lc_row.get("storey")
            or lc_row.get("buildingstorey")
            or lc_row.get("building storey")
            or lc_row.get("base constraint")
            or lc_row.get("base level")
            or lc_row.get("reference level")
            or lc_row.get("schedule level")
            or lc_row.get("associated level")
            or ""
        )
        storey = str(storey).strip() if storey else ""
        if storey.lower() == "none":
            storey = ""

        discipline = _classify_discipline(etype)
        if storey:
            storeys_set.add(storey)
        disciplines_set.add(discipline)

        # Numeric quantity fields — handle Revit native (mm/m²/m³) units.
        # DDC Excel columns have exact names; we map them all.
        quantities: dict[str, float] = {}
        for src_key, dest_key in (
            ("length", "Length"), ("area", "Area"), ("volume", "Volume"),
            ("width", "Width"), ("height", "Height"), ("thickness", "Thickness"),
            ("perimeter", "Perimeter"), ("count", "Count"),
            ("gross area", "Gross Area"), ("gross volume", "Gross Volume"),
            ("floor area", "Floor Area"), ("floor volume", "Floor Volume"),
            ("surface area", "Surface Area"),
            ("cut length", "Cut Length"), ("unconnected height", "Unconnected Height"),
            # DDC IfcExporter uses [BaseQuantities] prefix
            ("[basequantities] length", "Length"),
            ("[basequantities] width", "Width"),
            ("[basequantities] height", "Height"),
            ("[basequantities] area", "Area"),
            ("[basequantities] volume", "Volume"),
            ("overallwidth", "Width"), ("overallheight", "Height"),
        ):
            val = lc_row.get(src_key)
            if val is None:
                continue
            try:
                fval = float(val)
                if fval != 0.0:
                    quantities[dest_key] = fval
            except (ValueError, TypeError):
                pass

        # Stable ID — prefer Revit uniqueid, fall back to type ifcguid, then row index
        stable_id = str(
            lc_row.get("uniqueid")
            or lc_row.get("type ifcguid")
            or lc_row.get("globalid")
            or lc_row.get("id")
            or i
        )

        # mesh_ref — numeric Revit ElementId that matches the DAE <node id="...">.
        # DDC's Excel ``ID`` column IS ``Element.Id.IntegerValue``. If it is
        # missing we can still recover it from the last segment of ``UniqueId``
        # (which encodes the ElementId in hex).
        mesh_ref_int = _extract_revit_element_id(lc_row)
        mesh_ref: str | None = str(mesh_ref_int) if mesh_ref_int is not None else None

        # Bounding box — DDC RvtExporter Excel does NOT emit bbox columns at
        # all, so we compute bbox per element from the DAE geometry (in metres;
        # COLLADA is unit-normalised by DDC).
        bbox: dict[str, float] | None = None
        if mesh_ref_int is not None:
            bbox = dae_bboxes.get(mesh_ref_int)

        # Properties: preserve EVERY DDC column from the dataframe so the
        # viewer never loses information.  Only skip keys that are
        # genuinely duplicated as top-level fields (id → stable_id,
        # category → element_type, name → name) or in the dedicated
        # ``quantities`` map (length, area, volume, …).  Keys like
        # "design option", "workset", "versionguid" are intentionally kept
        # because designers do query them and dropping them silently
        # destroys data the user explicitly asked to preserve.
        DUPLICATE_PROP_KEYS = {
            # Already in stable_id
            "id", "uniqueid", "globalid", "type ifcguid",
            # Already in element_type
            "category",
            # Already in top-level name
            "name",
            # Already in quantities map (BuiltIn measurement params)
            "length", "area", "volume", "width", "height", "thickness",
            "perimeter", "count",
            "gross area", "gross volume", "floor area", "floor volume",
            "surface area", "cut length", "unconnected height",
            # IFC BaseQuantities mirrors of the above
            "[basequantities] length", "[basequantities] width",
            "[basequantities] height", "[basequantities] area",
            "[basequantities] volume",
        }
        properties: dict[str, str] = {}
        for k, v in row.items():
            if k.lower() in DUPLICATE_PROP_KEYS:
                continue
            if v is None:
                continue
            sval = str(v).strip()
            # Drop only truly empty values; keep "0" because for some Revit
            # parameters (e.g. counts, structural flags) zero is meaningful.
            if not sval or sval.lower() in ("none", "null", "n/a"):
                continue
            # Cap value length to keep payloads reasonable
            properties[k] = sval[:500]

        # Promote Revit hierarchy fields into properties under clean keys
        # so the frontend can build Category -> Family -> Type Name trees.
        # Use the friendly etype (with spaces) rather than the raw OST_ name.
        if etype and etype.lower() not in ("none", "null", "n/a", "-", "unknown"):
            properties["category"] = etype
        raw_family = lc_row.get("family name") or lc_row.get("familyname") or ""
        raw_family = str(raw_family).strip()
        if raw_family and raw_family.lower() not in ("none", "null", "n/a", "-"):
            properties["family"] = raw_family
        raw_type_name = lc_row.get("type name") or lc_row.get("typename") or ""
        raw_type_name = str(raw_type_name).strip()
        if raw_type_name and raw_type_name.lower() not in ("none", "null", "n/a", "-"):
            properties["type_name"] = raw_type_name

        # ENSURE critical DDC columns are stored in properties under clean keys,
        # even if the generic property loop above missed them (capped, filtered, etc.).
        _KEY_DDC_COLUMNS = {
            "level": "level", "base constraint": "base_constraint",
            "base level": "base_level", "top level": "top_level",
            "top constraint": "top_constraint",
            "fire rating": "fire_rating", "material": "material",
            "phase": "phase", "phase created": "phase_created",
            "assembly code": "assembly_code",
            "assembly description": "assembly_description",
            "type mark": "type_mark", "mark": "mark",
            "structural": "structural", "function": "function",
            "family and type": "family_and_type",
            "cost": "cost", "keynote": "keynote",
            "comments": "comments", "description": "description",
            "type comments": "type_comments",
        }
        for ddc_key, prop_key in _KEY_DDC_COLUMNS.items():
            if prop_key in properties:
                continue  # already populated by generic loop or hierarchy promotion
            val = lc_row.get(ddc_key)
            if val is not None:
                sval = str(val).strip()
                if sval and sval.lower() not in ("none", "0", ""):
                    properties[prop_key] = sval[:500]

        elements.append({
            "stable_id": stable_id,
            "element_type": etype,
            "name": name,
            "storey": storey or None,
            "discipline": discipline,
            "properties": properties,
            "quantities": quantities,
            "geometry_hash": hashlib.md5(f"{stable_id}:{etype}:{name}".encode()).hexdigest()[:16],
            "bounding_box": bbox,
            "mesh_ref": mesh_ref,
        })

    # Geometry: prefer the real Revit COLLADA from the second DDC pass.
    # Fall back to the simplified box-grid only when the real .dae is missing.
    geometry_path: Path | None = None
    bounding_box = None
    if real_dae_path and real_dae_path.exists() and real_dae_path.stat().st_size > 0:
        # Already named geometry.dae in output_dir — use as-is.
        geometry_path = real_dae_path
        logger.info(
            "Using real Revit COLLADA geometry: %s (%d KB)",
            real_dae_path.name, real_dae_path.stat().st_size // 1024,
        )
    elif elements:
        try:
            geometry_path, bounding_box = _generate_collada_boxes(elements, output_dir)
            logger.info("Generated placeholder box geometry (no real COLLADA available)")
        except Exception as e:
            logger.warning("COLLADA box generation failed: %s", e)

    # Convert DAE → GLB for 2x smaller transfer + faster browser parsing.
    # trimesh loses COLLADA node names, but we patch them back into the
    # GLB JSON chunk using the original DAE node IDs (0.09s overhead).
    glb_path: Path | None = None
    if geometry_path and geometry_path.exists():
        glb_path = _convert_dae_to_glb(geometry_path, output_dir)

    return {
        "elements": elements,
        "storeys": sorted(storeys_set),
        "disciplines": sorted(disciplines_set),
        "element_count": len(elements),
        "has_geometry": geometry_path is not None,
        "geometry_path": str(geometry_path) if geometry_path else None,
        "glb_path": str(glb_path) if glb_path else None,
        "bounding_box": bounding_box,
        "geometry_type": "real" if (real_dae_path and real_dae_path.exists()) else "placeholder",
        # Full DDC dataframe (all 1000+ columns) for Parquet cold storage.
        # The hot table only keeps ~12 indexed fields; analytical queries
        # run against the Parquet via DuckDB.
        "raw_elements": raw_elements,
    }


def _dae_element_bboxes(
    dae_path: Path,
) -> tuple[dict[str, tuple[float, float, float, float, float, float]], dict[str, str]]:
    """Parse a DDC COLLADA file and return per-element bounding boxes.

    Returns:
        element_bboxes: ``{element_id: (min_x, min_y, min_z, max_x, max_y, max_z)}``
        element_to_shape: ``{element_id: shape_id}`` (for diagnostics).

    The DDC ``RvtExporter`` writes one top-level
    ``<visual_scene>/<node id="{RevitElementId}">`` per element, each with a
    single ``<instance_geometry url="#shapeN-lib">`` pointing at the shape
    definition in ``<library_geometries>``.  We read every shape's
    ``<float_array>`` of positions to compute its axis-aligned bbox.  Under
    ``trimesh`` vertex-deduplication the count changes, but bbox is invariant
    (it's derived from coordinate extrema), which makes it a stable
    fingerprint for matching DAE shapes back to GLB meshes.
    """
    element_bboxes: dict[str, tuple[float, float, float, float, float, float]] = {}
    element_to_shape: dict[str, str] = {}
    try:
        tree = ET.parse(str(dae_path))
    except ET.ParseError as exc:
        logger.debug("DAE bbox extraction: XML parse error: %s", exc)
        return element_bboxes, element_to_shape

    ns = {"c": _COLLADA_NS}
    geoms = {
        g.get("id", ""): g
        for g in tree.findall(".//c:library_geometries/c:geometry", ns)
    }

    def _shape_bbox(
        shape_id: str,
    ) -> tuple[float, float, float, float, float, float] | None:
        g = geoms.get(shape_id)
        if g is None:
            return None
        # DDC writes positions as the first <source>/<float_array> inside <mesh>.
        fa = g.find("c:mesh/c:source/c:float_array", ns)
        if fa is None or not fa.text:
            return None
        try:
            vals = [float(x) for x in fa.text.split()]
        except ValueError:
            return None
        if len(vals) < 3:
            return None
        xs = vals[0::3]
        ys = vals[1::3]
        zs = vals[2::3]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    for node in tree.findall(".//c:visual_scene/c:node", ns):
        nid = node.get("id", "") or ""
        # Only numeric ids — Revit ElementId. Lights/cameras/named nodes skipped.
        if not nid.isdigit():
            continue
        ig = node.find("c:instance_geometry", ns)
        if ig is None:
            continue
        shape_id = (ig.get("url", "") or "").lstrip("#")
        if not shape_id:
            continue
        bb = _shape_bbox(shape_id)
        if bb is None:
            continue
        element_bboxes[nid] = bb
        element_to_shape[nid] = shape_id

    return element_bboxes, element_to_shape


def _convert_dae_to_glb(dae_path: Path, output_dir: Path) -> Path | None:
    """Convert a COLLADA .dae file to binary glTF (.glb) using trimesh.

    Returns the GLB path on success, ``None`` on failure.  Failure is
    non-fatal — the DAE file remains available as a fallback.

    Trimesh handles DAE -> GLB natively (via collada-exporter + numpy).
    Typical conversion: 32 MB DAE -> 9.5 MB GLB (3.4x smaller).
    With server-side gzip the transfer shrinks to ~1.7 MB (19x smaller).

    **Important**: trimesh.load() on DAE files does NOT guarantee that GLB
    ``node.name`` still corresponds to the mesh at ``node.mesh``.  Trimesh
    internally reorders/regroups meshes by material, so the node-name and
    mesh-geometry pairing is unreliable (observed in the wild: node named
    "135248" pointing at the roof geometry of element 140056, and vice-versa).

    We therefore rebuild the name↔geometry pairing post-export by matching
    each GLB mesh's POSITION bbox against the per-element bboxes parsed
    directly from the DAE ``<visual_scene>/<node>/<instance_geometry>``
    chain.  Bounding boxes survive trimesh's vertex-deduplication /
    primitive-splitting unchanged, making them a robust fingerprint.
    """
    glb_target = (output_dir / "geometry.glb").resolve()
    try:
        import trimesh

        scene = trimesh.load(str(dae_path))
        glb_data: bytes = scene.export(file_type="glb")  # type: ignore[union-attr]

        # Post-process: reassign GLB node/mesh names using bbox matching
        # against DAE shapes.  This replaces the previous approach which
        # blindly trusted trimesh's scene-graph names.
        try:
            import struct as _struct
            import json as _json

            element_bboxes, _element_to_shape = _dae_element_bboxes(dae_path)
            if element_bboxes:
                # Parse GLB: header(12) + json_chunk_header(8) + json
                json_len = _struct.unpack("<I", glb_data[12:16])[0]
                gltf = _json.loads(glb_data[20 : 20 + json_len])
                glb_nodes = gltf.get("nodes", [])
                glb_meshes = gltf.get("meshes", [])
                accessors = gltf.get("accessors", [])

                def _mesh_bbox(
                    mesh_idx: int,
                ) -> tuple[float, float, float, float, float, float] | None:
                    """Union bbox over every primitive's POSITION accessor."""
                    if mesh_idx >= len(glb_meshes):
                        return None
                    primitives = glb_meshes[mesh_idx].get("primitives", [])
                    lo = [float("inf")] * 3
                    hi = [float("-inf")] * 3
                    any_found = False
                    for prim in primitives:
                        pos_idx = prim.get("attributes", {}).get("POSITION")
                        if pos_idx is None or pos_idx >= len(accessors):
                            continue
                        acc = accessors[pos_idx]
                        mn = acc.get("min")
                        mx = acc.get("max")
                        if not mn or not mx or len(mn) < 3 or len(mx) < 3:
                            continue
                        for i in range(3):
                            if mn[i] < lo[i]:
                                lo[i] = mn[i]
                            if mx[i] > hi[i]:
                                hi[i] = mx[i]
                        any_found = True
                    if not any_found:
                        return None
                    return (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])

                # Build a spatial bucket over DAE element bboxes keyed by
                # rounded bbox-center.  This turns O(N*M) into O(N+M) for
                # typical models (5k+ elements).  Collisions are resolved by
                # scoring all candidates in the bucket.
                def _key(
                    bb: tuple[float, float, float, float, float, float],
                ) -> tuple[int, int, int]:
                    # 0.5-unit bucket — trimesh preserves coords exactly, so
                    # the match is effectively exact; the bucket is only a
                    # prefilter for speed.
                    cx = (bb[0] + bb[3]) * 0.5
                    cy = (bb[1] + bb[4]) * 0.5
                    cz = (bb[2] + bb[5]) * 0.5
                    return (int(cx * 2), int(cy * 2), int(cz * 2))

                buckets: dict[tuple[int, int, int], list[str]] = {}
                for eid, bb in element_bboxes.items():
                    buckets.setdefault(_key(bb), []).append(eid)

                def _score(
                    a: tuple[float, float, float, float, float, float],
                    b: tuple[float, float, float, float, float, float],
                ) -> float:
                    return sum(abs(a[i] - b[i]) for i in range(6))

                # Size of a typical model is ~5k elements; searching all
                # buckets in a 1-unit radius is cheap and handles float
                # rounding at bucket boundaries.
                def _find_element(
                    bb: tuple[float, float, float, float, float, float],
                ) -> tuple[str | None, float]:
                    k = _key(bb)
                    best_eid: str | None = None
                    best_score = float("inf")
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            for dz in (-1, 0, 1):
                                neighbors = buckets.get((k[0] + dx, k[1] + dy, k[2] + dz))
                                if not neighbors:
                                    continue
                                for eid in neighbors:
                                    s = _score(bb, element_bboxes[eid])
                                    if s < best_score:
                                        best_score = s
                                        best_eid = eid
                    return best_eid, best_score

                # Tolerance: trimesh preserves coordinates exactly, so a
                # perfect match is ~0.  We accept up to 0.01 (1 cm summed
                # over 6 floats) to tolerate float round-trips.
                match_tol = 0.01
                matched = 0
                total_mesh_nodes = 0
                assigned_mesh: set[int] = set()
                for node in glb_nodes:
                    if "mesh" not in node:
                        continue
                    total_mesh_nodes += 1
                    mi = node["mesh"]
                    mb = _mesh_bbox(mi)
                    if mb is None:
                        continue
                    eid, s = _find_element(mb)
                    if eid is not None and s <= match_tol:
                        node["name"] = eid
                        if mi not in assigned_mesh and mi < len(glb_meshes):
                            glb_meshes[mi]["name"] = eid
                            assigned_mesh.add(mi)
                        matched += 1

                logger.info(
                    "GLB post-process: bbox-matched %d/%d mesh nodes to "
                    "DAE element ids (of %d DAE elements)",
                    matched,
                    total_mesh_nodes,
                    len(element_bboxes),
                )

                if matched > 0:
                    # Rebuild GLB with patched JSON
                    new_json = _json.dumps(gltf, separators=(",", ":")).encode("utf-8")
                    # Pad to 4-byte alignment
                    while len(new_json) % 4:
                        new_json += b" "
                    bin_offset = 20 + json_len
                    # Find binary chunk
                    bin_chunk = glb_data[bin_offset:]
                    total = 12 + 8 + len(new_json) + len(bin_chunk)
                    glb_data = (
                        _struct.pack("<III", 0x46546C67, 2, total)
                        + _struct.pack("<II", len(new_json), 0x4E4F534A)
                        + new_json
                        + bin_chunk
                    )
        except Exception as patch_err:  # noqa: BLE001 — non-fatal post-process
            logger.debug("GLB node-name patching skipped: %s", patch_err, exc_info=True)

        glb_target.write_bytes(glb_data)

        if glb_target.stat().st_size > 1000:
            logger.info(
                "GLB conversion: %d bytes DAE -> %d bytes GLB (%.1fx smaller)",
                dae_path.stat().st_size,
                glb_target.stat().st_size,
                dae_path.stat().st_size / max(glb_target.stat().st_size, 1),
            )
            return glb_target

        logger.warning(
            "GLB conversion produced a suspiciously small file (%d bytes)",
            glb_target.stat().st_size,
        )
    except ImportError:
        logger.warning("GLB conversion skipped: trimesh not installed (pip install trimesh)")
    except Exception as exc:
        logger.warning("GLB conversion failed: %s", exc, exc_info=True)
    return None


def process_ifc_file(
    ifc_path: Path,
    output_dir: Path,
    conversion_depth: str = "standard",
) -> dict[str, Any]:
    """Process an IFC/RVT file.

    Pipeline:
    1. Try DDC cad2data (full conversion with geometry)
    2. Fallback: text-based IFC parser (elements only, box geometry)

    Args:
        conversion_depth: 'standard' (~15 key columns, faster) or
            'complete' (~1000+ Revit parameters, slower). Passed
            to the DDC converter as the export mode argument.

    Returns dict with elements, storeys, disciplines, geometry info.
    """
    # Step 1: Try cad2data
    cad_result = _try_cad2data(ifc_path, output_dir, conversion_depth=conversion_depth)
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

    # Extract storeys (IFC2x3 IfcBuildingStorey + IFC4x3 facility parts)
    storeys: dict[int, str] = {}
    for eid, ent in entities.items():
        if ent["type"] in _STOREY_TYPES:
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
                # Both bbox and mesh_ref are populated post-loop from the
                # placeholder COLLADA we generate (node id = "n{index}").
                "bounding_box": None,
                "mesh_ref": None,
            })

    # Try to extract real placement coordinates from IFC before generating geometry
    _extract_placements(elements, entities)

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
        "geometry_type": "placeholder",
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
    # Check architecture first — curtainwall contains "wall" so must precede structural
    if any(x in t for x in ["door", "window", "curtainwall", "covering", "furnishing"]):
        return "architecture"
    if any(x in t for x in ["wall", "slab", "column", "beam", "footing", "pile", "stair", "railing", "roof",
                             "plate", "member", "tendon", "bearing"]):
        return "structural"
    if any(x in t for x in ["flow", "distribution", "pipe", "duct", "cable"]):
        return "mep"
    if any(x in t for x in ["alignment", "road", "railway", "bridge", "pavement", "kerb", "course",
                             "earthworks", "civil", "facility", "geographic", "geotechnic",
                             "caisson", "deepfoundation", "surfacefeature", "transport",
                             "reinforcedsoil"]):
        return "civil"
    if "space" in t:
        return "architecture"
    return "other"


_TYPE_DISPLAY_MAP: dict[str, str] = {
    "IFCWALLSTANDARDCASE": "Wall",
    "IFCBUILDINGELEMENTPROXY": "Generic Element",
    "IFCALIGNMENT": "Alignment",
    "IFCALIGNMENTHORIZONTAL": "Horizontal Alignment",
    "IFCALIGNMENTVERTICAL": "Vertical Alignment",
    "IFCALIGNMENTSEGMENT": "Alignment Segment",
    "IFCALIGNMENTCANT": "Alignment Cant",
    "IFCBRIDGE": "Bridge",
    "IFCBRIDGEPART": "Bridge Part",
    "IFCROAD": "Road",
    "IFCROADPART": "Road Part",
    "IFCRAILWAY": "Railway",
    "IFCRAILWAYPART": "Railway Part",
    "IFCPAVEMENT": "Pavement",
    "IFCKERB": "Kerb",
    "IFCCOURSE": "Course",
    "IFCEARTHWORKSFILL": "Earthworks Fill",
    "IFCEARTHWORKSCUT": "Earthworks Cut",
    "IFCEARTHWORKSELEMENT": "Earthworks Element",
    "IFCREINFORCEDSOIL": "Reinforced Soil",
    "IFCGEOTECHNICELEMENT": "Geotechnic Element",
    "IFCGEOTECHNICSTRATUM": "Geotechnic Stratum",
    "IFCDEEPFOUNDATION": "Deep Foundation",
    "IFCCAISSONFOOTING": "Caisson Footing",
    "IFCBEARING": "Bearing",
    "IFCTENDON": "Tendon",
    "IFCTENDONANCHOR": "Tendon Anchor",
    "IFCTENDONCONDUIT": "Tendon Conduit",
    "IFCSURFACEFEATURE": "Surface Feature",
    "IFCCIVILELEMENT": "Civil Element",
    "IFCGEOGRAPHICELEMENT": "Geographic Element",
    "IFCFACILITY": "Facility",
    "IFCFACILITYPART": "Facility Part",
}


def _simplify_type(ifc_type: str) -> str:
    """Simplify IFC type name for display."""
    up = ifc_type.upper()
    if up in _TYPE_DISPLAY_MAP:
        return _TYPE_DISPLAY_MAP[up]
    return ifc_type.replace("IFC", "").title()


def _extract_placements(
    elements: list[dict[str, Any]],
    entities: dict[int, dict],
) -> None:
    """Try to extract real XYZ placement coordinates from IFC entities.

    Parses ``IfcLocalPlacement → IfcAxis2Placement3D → IfcCartesianPoint``
    and stores the result in ``elem["_placement"]`` as ``(x, y, z)``.
    Elements without recoverable placement keep ``_placement = None``.
    """
    # Build map: element_ifc_id → placement ref
    placement_map: dict[int, tuple[float, float, float]] = {}

    for eid, ent in entities.items():
        if ent["type"] == "IFCCARTESIANPOINT":
            nums = re.findall(r"[-\d.]+(?:E[+-]?\d+)?", ent["args_raw"])
            if len(nums) >= 3:
                try:
                    placement_map[eid] = (float(nums[0]), float(nums[1]), float(nums[2]))
                except ValueError:
                    pass
            elif len(nums) == 2:
                try:
                    placement_map[eid] = (float(nums[0]), float(nums[1]), 0.0)
                except ValueError:
                    pass

    # Build IfcAxis2Placement3D → location point
    axis_to_point: dict[int, tuple[float, float, float]] = {}
    for eid, ent in entities.items():
        if ent["type"] in ("IFCAXIS2PLACEMENT3D", "IFCAXIS2PLACEMENT2D"):
            refs = re.findall(r"#(\d+)", ent["args_raw"])
            if refs:
                pt_id = int(refs[0])
                if pt_id in placement_map:
                    axis_to_point[eid] = placement_map[pt_id]

    # Build IfcLocalPlacement → resolved point (simplified: only direct placements)
    local_placement_pt: dict[int, tuple[float, float, float]] = {}
    for eid, ent in entities.items():
        if ent["type"] == "IFCLOCALPLACEMENT":
            refs = re.findall(r"#(\d+)", ent["args_raw"])
            for ref_str in refs:
                ref_id = int(ref_str)
                if ref_id in axis_to_point:
                    local_placement_pt[eid] = axis_to_point[ref_id]
                    break

    # Map elements to their placements via ObjectPlacement ref (typically #N in arg index 5)
    for elem in elements:
        ifc_id = elem.get("properties", {}).get("ifc_id")
        if ifc_id is None:
            elem["_placement"] = None
            continue

        ent = entities.get(ifc_id)
        if not ent:
            elem["_placement"] = None
            continue

        # The ObjectPlacement reference is typically the 6th arg in IFC entity definition.
        # We look for any ref that points to a known IfcLocalPlacement.
        refs = re.findall(r"#(\d+)", ent["args_raw"])
        placed = False
        for ref_str in refs:
            ref_id = int(ref_str)
            if ref_id in local_placement_pt:
                elem["_placement"] = local_placement_pt[ref_id]
                placed = True
                break
        if not placed:
            elem["_placement"] = None

    placed_count = sum(1 for e in elements if e.get("_placement") is not None)
    logger.info("Placement extraction: %d/%d elements have coordinates", placed_count, len(elements))


def _assign_logical_grid_positions(elements: list[dict[str, Any]]) -> None:
    """Assign logical XYZ positions so placeholder boxes form a building-like layout.

    Layout rules:
    - **Z axis** = storey height.  Each storey is stacked vertically at
      ``storey_index * STOREY_HEIGHT``.  Elements without a storey go to Z=0.
    - **Y axis** = discipline lane.  Each discipline (structural, architecture,
      MEP, civil, other) occupies its own Y-offset lane within the storey.
    - **X axis** = sequential placement within the discipline lane.

    The result is a recognisable building silhouette: floors stacked
    vertically, trades separated horizontally, elements in reading order.
    """
    STOREY_HEIGHT = 3.5   # metres between storey base planes
    DISCIPLINE_SPACING = 6.0  # Y gap between discipline lanes
    ELEM_SPACING = 2.5        # X gap between elements in a lane
    MAX_PER_ROW = 25          # wrap to next sub-row after this many

    # Discover unique storeys in the order they appear, then sort
    storey_order: list[str] = []
    seen_storeys: set[str] = set()
    for elem in elements:
        s = elem.get("storey") or ""
        if s and s not in seen_storeys:
            storey_order.append(s)
            seen_storeys.add(s)
    storey_order.sort()  # alphabetical ≈ floor order for most naming schemes

    # Add a pseudo-storey for elements without one
    storey_index: dict[str, int] = {}
    for idx, name in enumerate(storey_order):
        storey_index[name] = idx + 1  # Z starts at STOREY_HEIGHT for first real storey
    storey_index[""] = 0  # unassigned → ground level

    discipline_order = ["structural", "architecture", "mep", "civil", "other"]
    discipline_lane: dict[str, int] = {d: i for i, d in enumerate(discipline_order)}

    # Counters: (storey, discipline) → next element index within that lane
    lane_counter: dict[tuple[str, str], int] = {}

    for elem in elements:
        storey = elem.get("storey") or ""
        disc = elem.get("discipline", "other")
        if disc not in discipline_lane:
            disc = "other"

        key = (storey, disc)
        idx = lane_counter.get(key, 0)
        lane_counter[key] = idx + 1

        q = elem.get("quantities", {})
        ln = max(float(q.get("Length", q.get("Laenge", 1.0))), 0.5)

        col = idx % MAX_PER_ROW
        sub_row = idx // MAX_PER_ROW

        x = col * max(ln + 0.5, ELEM_SPACING)
        y = discipline_lane[disc] * DISCIPLINE_SPACING + sub_row * 3.0
        z = storey_index.get(storey, 0) * STOREY_HEIGHT

        elem["_grid_pos"] = (x, y, z)


def _generate_collada_boxes(
    elements: list[dict],
    output_dir: Path,
    *,
    max_elements: int = 2000,
) -> tuple[Path | None, dict | None]:
    """Generate simplified COLLADA with box placeholders per element.

    When real IFC placement coordinates are available (populated by
    ``_extract_placements``), elements are positioned at their actual
    locations.  Otherwise falls back to a grid layout.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dae_path = output_dir / "geometry.dae"

    NS = "http://www.collada.org/2005/11/COLLADASchema"
    root = ET.Element("COLLADA", xmlns=NS, version="1.4.1")

    asset = ET.SubElement(root, "asset")
    ET.SubElement(asset, "up_axis").text = "Z_UP"

    lib_geom = ET.SubElement(root, "library_geometries")
    lib_scenes = ET.SubElement(root, "library_visual_scenes")
    vscene = ET.SubElement(lib_scenes, "visual_scene", id="Scene", name="Scene")

    # Check how many elements have real placements
    has_real_coords = sum(1 for e in elements if e.get("_placement")) > len(elements) * 0.3

    # ── Build logical layout when no real coordinates ──────────────────
    # Group elements by storey, then by discipline within each storey.
    # Each storey is placed at a different Z level (floor height).
    # Within a storey, disciplines are arranged along Y axis.
    # Elements within a discipline group run along X axis.
    if not has_real_coords:
        _assign_logical_grid_positions(elements[:max_elements])

    # Track global bounding box
    g_min_x = g_min_y = g_min_z = float("inf")
    g_max_x = g_max_y = g_max_z = float("-inf")

    for i, elem in enumerate(elements[:max_elements]):
        q = elem.get("quantities", {})
        w = max(float(q.get("Width", q.get("Breite", 0.3))), 0.05)
        h = max(float(q.get("Height", q.get("Hoehe", 3.0))), 0.05)
        ln = max(float(q.get("Length", q.get("Laenge", 1.0))), 0.05)

        # Use real placement if available, otherwise pre-computed logical grid
        placement = elem.get("_placement")
        if has_real_coords and placement:
            x, y, z = placement
        else:
            grid = elem.get("_grid_pos", (0.0, 0.0, 0.0))
            x, y, z = grid

        # Update global bbox
        g_min_x = min(g_min_x, x)
        g_min_y = min(g_min_y, y)
        g_min_z = min(g_min_z, z)
        g_max_x = max(g_max_x, x + ln)
        g_max_y = max(g_max_y, y + w)
        g_max_z = max(g_max_z, z + h)

        # Use the element's original mesh_ref (Revit ElementId) as the
        # COLLADA node id so the frontend viewer can match meshes to
        # elements by name. Fall back to stable_id or index.
        node_id = str(elem.get("mesh_ref") or elem.get("stable_id") or f"n{i}")
        elem["mesh_ref"] = node_id
        elem["bounding_box"] = {
            "min_x": float(x),
            "min_y": float(y),
            "min_z": float(z),
            "max_x": float(x + ln),
            "max_y": float(y + w),
            "max_z": float(z + h),
        }

        gid = f"g{i}"
        geom = ET.SubElement(lib_geom, "geometry", id=gid, name=elem.get("name", f"e{i}"))
        mesh_el = ET.SubElement(geom, "mesh")

        verts = [
            (0, 0, 0), (ln, 0, 0), (ln, w, 0), (0, w, 0),
            (0, 0, h), (ln, 0, h), (ln, w, h), (0, w, h),
        ]
        pos_str = " ".join(f"{v[0]:.4f} {v[1]:.4f} {v[2]:.4f}" for v in verts)

        src = ET.SubElement(mesh_el, "source", id=f"{gid}-p")
        fa = ET.SubElement(src, "float_array", id=f"{gid}-pa", count=str(len(verts) * 3))
        fa.text = pos_str
        tc = ET.SubElement(src, "technique_common")
        acc = ET.SubElement(tc, "accessor", source=f"#{gid}-pa", count=str(len(verts)), stride="3")
        ET.SubElement(acc, "param", name="X", type="float")
        ET.SubElement(acc, "param", name="Y", type="float")
        ET.SubElement(acc, "param", name="Z", type="float")

        vs = ET.SubElement(mesh_el, "vertices", id=f"{gid}-v")
        ET.SubElement(vs, "input", semantic="POSITION", source=f"#{gid}-p")

        tri = ET.SubElement(mesh_el, "triangles", count="12")
        ET.SubElement(tri, "input", semantic="VERTEX", source=f"#{gid}-v", offset="0")
        p = ET.SubElement(tri, "p")
        p.text = "0 1 2 0 2 3 4 6 5 4 7 6 0 4 5 0 5 1 2 6 7 2 7 3 0 3 7 0 7 4 1 5 6 1 6 2"

        node = ET.SubElement(vscene, "node", id=node_id, name=elem.get("name", f"e{i}"))
        mat = ET.SubElement(node, "matrix", sid="transform")
        mat.text = f"1 0 0 {x:.4f} 0 1 0 {y:.4f} 0 0 1 {z:.4f} 0 0 0 1"
        ET.SubElement(node, "instance_geometry", url=f"#{gid}")

    scene = ET.SubElement(root, "scene")
    ET.SubElement(scene, "instance_visual_scene", url="#Scene")

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(dae_path), xml_declaration=True, encoding="utf-8")

    n = min(len(elements), max_elements)
    if g_min_x == float("inf"):
        g_min_x = g_min_y = g_min_z = 0.0
        g_max_x = g_max_y = g_max_z = 10.0
    bb = {
        "min": {"x": g_min_x, "y": g_min_y, "z": g_min_z},
        "max": {"x": g_max_x, "y": g_max_y, "z": g_max_z},
    }

    logger.info(
        "Generated COLLADA boxes: %d elements (%s coordinates)",
        n,
        "real" if has_real_coords else "grid",
    )
    return dae_path, bb


def _extract_revit_element_id(lc_row: dict[str, Any]) -> int | None:
    """Pull the Revit ``Element.Id.IntegerValue`` out of a DDC Excel row.

    Tries, in order:
    1. The lowercase ``id`` column (DDC's first column, already an integer).
    2. The last hyphenated segment of ``uniqueid`` parsed as hex — the Revit
       UniqueId format is ``<EpisodeGUID>-<ElementIdHex>``.
    3. Any column whose normalised name matches one of the known aliases for
       "revit element id".

    Returns ``None`` if no numeric id can be recovered.
    """
    # 1) Direct ID column from DDC RvtExporter.
    raw = lc_row.get("id")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass

    # 2) UniqueId -> hex element id
    uid = lc_row.get("uniqueid")
    if isinstance(uid, str) and "-" in uid:
        last = uid.rsplit("-", 1)[-1]
        try:
            return int(last, 16)
        except ValueError:
            pass

    # 3) Alternate column names used by other CAD tools.
    for key in ("element_id", "elementid", "revit_id", "revitid", "elem_id"):
        val = lc_row.get(key)
        if val is None:
            continue
        try:
            return int(val)
        except (TypeError, ValueError):
            continue

    return None


def _extract_dae_bboxes_by_node_id(dae_path: Path) -> dict[int, dict[str, float]]:
    """Parse a COLLADA file and compute a bounding box per scene node.

    Returns a mapping ``{revit_element_id: {min_x, min_y, min_z,
    max_x, max_y, max_z}}`` keyed by the integer ``<node id="...">`` value
    (which DDC RvtExporter sets to the Revit ElementId).

    Non-numeric node ids are skipped — they correspond to lights, cameras,
    and other auxiliary scene entries that do not map to BIM elements.

    Coordinates are returned in the DAE's own units (DDC emits metres).
    """
    tree = ET.parse(str(dae_path))
    root = tree.getroot()
    ns = {"c": _COLLADA_NS}

    # Index geometries by id so we can resolve <instance_geometry url="#gid">.
    geom_positions: dict[str, list[tuple[float, float, float]]] = {}
    for geom in root.findall(".//c:library_geometries/c:geometry", ns):
        gid = geom.get("id") or ""
        # Prefer the <vertices>-referenced <source> when present; otherwise
        # fall back to the first float_array in the mesh.
        fa = geom.find(".//c:mesh//c:float_array", ns)
        if fa is None or not fa.text:
            continue
        try:
            nums = [float(x) for x in fa.text.split()]
        except ValueError:
            continue
        # Positions are 3-tuples. Ignore trailing values.
        pts = [(nums[i], nums[i + 1], nums[i + 2]) for i in range(0, len(nums) - 2, 3)]
        if pts:
            geom_positions[gid] = pts

    result: dict[int, dict[str, float]] = {}

    def _parse_matrix(text: str) -> tuple[float, ...] | None:
        try:
            vals = tuple(float(v) for v in text.split())
        except ValueError:
            return None
        return vals if len(vals) == 16 else None

    def _apply_matrix(
        m: tuple[float, ...],
        pt: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        x, y, z = pt
        # COLLADA matrices are row-major 4x4.
        nx = m[0] * x + m[1] * y + m[2] * z + m[3]
        ny = m[4] * x + m[5] * y + m[6] * z + m[7]
        nz = m[8] * x + m[9] * y + m[10] * z + m[11]
        return nx, ny, nz

    for node in root.findall(".//c:visual_scene//c:node", ns):
        nid = node.get("id") or ""
        if not nid.isdigit():
            continue
        elem_id = int(nid)

        # Collect parent-chain transforms — DDC usually flattens geometry,
        # but we still respect any direct <matrix> on the node.
        matrix: tuple[float, ...] | None = None
        mat_el = node.find("c:matrix", ns)
        if mat_el is not None and mat_el.text:
            matrix = _parse_matrix(mat_el.text)

        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")

        for inst in node.findall("c:instance_geometry", ns):
            url = inst.get("url") or ""
            if not url.startswith("#"):
                continue
            pts = geom_positions.get(url[1:])
            if not pts:
                continue
            for pt in pts:
                tp = _apply_matrix(matrix, pt) if matrix else pt
                if tp[0] < min_x:
                    min_x = tp[0]
                if tp[1] < min_y:
                    min_y = tp[1]
                if tp[2] < min_z:
                    min_z = tp[2]
                if tp[0] > max_x:
                    max_x = tp[0]
                if tp[1] > max_y:
                    max_y = tp[1]
                if tp[2] > max_z:
                    max_z = tp[2]

        if min_x == float("inf"):
            continue  # No geometry attached — skip.

        result[elem_id] = {
            "min_x": round(min_x, 4),
            "min_y": round(min_y, 4),
            "min_z": round(min_z, 4),
            "max_x": round(max_x, 4),
            "max_y": round(max_y, 4),
            "max_z": round(max_z, 4),
        }

    return result


def _patch_collada_node_names(dae_path: Path) -> int:
    """Rewrite COLLADA ``<node name="...">`` to match ``<node id="...">``.

    DDC RvtExporter writes ``<node id="ELEMENT_ID" name="node">`` for every
    element. Three.js ColladaLoader uses the ``name`` attribute (not ``id``)
    to set ``Object3D.name``, so every mesh ends up with ``name="node"`` and
    the frontend element-to-mesh matching fails (0% match rate).

    This function rewrites each ``<node>`` so ``name`` equals ``id``, which
    lets the existing ``stableIdToElement.get(nodeName)`` lookup succeed.

    Returns the number of nodes patched.
    """
    try:
        tree = ET.parse(str(dae_path))
    except ET.ParseError as exc:
        logger.warning("Cannot patch COLLADA node names: XML parse error: %s", exc)
        return 0

    root = tree.getroot()
    patched = 0

    for node in root.iter(f"{{{_COLLADA_NS}}}node"):
        nid = node.get("id") or ""
        nname = node.get("name") or ""
        # Only patch element nodes (numeric id from DDC) that have a generic
        # name like "node" — leave lights/cameras/named nodes alone.
        if nid and nid != nname and (nname in ("node", "") or nid.isdigit()):
            node.set("name", nid)
            patched += 1

    if patched > 0:
        ET.indent(tree, space="  ")
        tree.write(str(dae_path), xml_declaration=True, encoding="utf-8")
        logger.info(
            "Patched %d COLLADA node name attributes to match id in %s",
            patched,
            dae_path.name,
        )
    return patched


def _empty_result() -> dict[str, Any]:
    return {
        "elements": [],
        "storeys": [],
        "disciplines": [],
        "element_count": 0,
        "has_geometry": False,
        "geometry_path": None,
        "bounding_box": None,
        "status": "error",
        "error_message": "No elements could be extracted. The converter may not support this file format.",
        "geometry_type": "unknown",
    }
