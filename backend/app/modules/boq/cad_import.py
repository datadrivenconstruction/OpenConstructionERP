# OpenConstructionERP — DataDrivenConstruction (DDC)
# CAD2DATA Pipeline · CWICR Cost Database Engine
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""CAD/BIM file import via DDC Community converters.

Workflow:
1. User uploads .rvt/.ifc/.dwg/.dgn file
2. Backend saves to temp dir
3. Runs appropriate DDC converter (.exe) -> produces Excel
4. Parses Excel -> extracts elements (type, volume, area, count)
5. AI maps elements to construction work items with pricing
6. Returns BOQ positions ready for import
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Converter mapping: file extension -> converter executable name
CONVERTERS: dict[str, str] = {
    "rvt": "RvtExporter.exe",
    "ifc": "IfcExporter.exe",
    "dwg": "DwgExporter.exe",
    "dgn": "DgnExporter.exe",
}

SUPPORTED_CAD_EXTENSIONS: set[str] = set(CONVERTERS.keys())

# Look for converters in these locations (in order)
CONVERTER_SEARCH_PATHS: list[Path] = [
    Path("converters/bin"),
    Path.home() / ".openestimator" / "converters",
    Path("/opt/openestimator/converters"),
    Path("C:/ProgramData/OpenConstructionERP/converters"),
]


def _find_ddc_toolkit_bin() -> Path | None:
    """Auto-detect DDC toolkit converters/bin from editable install or known paths."""
    # 1. Check env var
    env_dir = os.environ.get("DDC_TOOLKIT_DIR")
    if env_dir:
        p = Path(env_dir) / "converters" / "bin"
        if p.is_dir():
            return p

    # 2. Try importlib.metadata (editable install of ddc-toolkit)
    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("ddc-toolkit")
        for f in dist.files or []:
            fpath = Path(str(f))
            if "converters" in str(fpath) or "bin" in str(fpath):
                resolved = Path(str(dist._path)).parent / fpath  # type: ignore[attr-defined]
                candidate = resolved.parent
                while candidate != candidate.parent:
                    check = candidate / "converters" / "bin"
                    if check.is_dir():
                        return check
                    candidate = candidate.parent
                break
    except Exception:
        logger.debug("DDC converter discovery via importlib failed", exc_info=True)

    # 3. Scan common sibling directories (projects next to this repo)
    this_project = Path(__file__).resolve().parents[4]  # backend/app/modules/boq -> repo root
    for sibling_name in ("ddc_toolkit", "ddc-toolkit", "DDC_Toolkit"):
        candidate = this_project.parent / sibling_name / "converters" / "bin"
        if candidate.is_dir():
            return candidate

    return None


# Auto-detect DDC toolkit at import time
_ddc_bin = _find_ddc_toolkit_bin()
if _ddc_bin:
    CONVERTER_SEARCH_PATHS.insert(0, _ddc_bin)
    logger.info("DDC toolkit converters found at %s", _ddc_bin)


def find_converter(extension: str) -> Path | None:
    """Find the converter executable for a given file extension.

    Searches through ``CONVERTER_SEARCH_PATHS`` in order and returns the
    first existing executable path, or ``None`` if no converter is found.

    Args:
        extension: Lowercase file extension without dot (e.g. ``"rvt"``).

    Returns:
        Path to the converter executable, or ``None``.
    """
    exe_name = CONVERTERS.get(extension)
    if not exe_name:
        return None

    # Build dynamic search paths
    search_paths = list(CONVERTER_SEARCH_PATHS)

    # Also check OPENESTIMATOR_CONVERTERS_DIR env var
    env_dir = os.environ.get("OPENESTIMATOR_CONVERTERS_DIR")
    if env_dir:
        search_paths.insert(0, Path(env_dir))

    # Auto-detect DDC toolkit in sibling directories
    ddc_bin = _find_ddc_toolkit_bin()
    if ddc_bin and ddc_bin not in search_paths:
        search_paths.insert(0, ddc_bin)

    for search_path in search_paths:
        exe_path = search_path / exe_name
        if exe_path.exists() and exe_path.stat().st_size > 1024:
            return exe_path

    return None


def is_cad_file(filename: str) -> bool:
    """Check if a filename has a supported CAD/BIM extension.

    Args:
        filename: File name or path (e.g. ``"project.rvt"``).

    Returns:
        ``True`` if the extension is supported.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in SUPPORTED_CAD_EXTENSIONS


async def convert_cad_to_excel(
    input_path: Path,
    output_dir: Path,
    extension: str,
) -> Path | None:
    """Run a DDC converter to transform a CAD file into Excel.

    The converter is executed as a subprocess with a 5-minute timeout.

    Args:
        input_path: Path to the uploaded CAD file.
        output_dir: Directory where the Excel output should be written.
        extension: Lowercase file extension without dot.

    Returns:
        Path to the generated Excel file, or ``None`` on failure.
    """
    converter = find_converter(extension)
    if not converter:
        logger.error("No converter found for .%s", extension)
        return None

    logger.info("Converting %s using %s", input_path.name, converter.name)

    # DDC converters CLI: <input> [<output.xlsx>] [<mode>] [-no-collada]
    # Use 'complete' mode for full quantity data (Volume, Area, Length, etc.)
    output_xlsx = output_dir / (input_path.stem + ".xlsx")
    args = [str(converter), str(input_path), str(output_xlsx)]
    # RVT and IFC converters support export modes; DWG/DGN do not
    if extension in ("rvt", "ifc"):
        args.append("complete")
    args.append("-no-collada")

    try:
        import subprocess
        from concurrent.futures import ThreadPoolExecutor

        # DDC converters need DLLs (Qt6Core.dll etc.) from their own directory
        converter_dir = converter.parent

        def _run_converter() -> subprocess.CompletedProcess:
            return subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(converter_dir),
                input=b"\n",  # handle "Press Enter to continue..." prompt
                timeout=300,
            )

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, _run_converter)

        if result.returncode != 0:
            logger.error(
                "Converter failed (exit %d): %s",
                result.returncode,
                result.stderr.decode(errors="replace")[:500],
            )
            return None

        # Find the generated Excel file in the output directory
        for f in output_dir.iterdir():
            if f.suffix in (".xlsx", ".xls"):
                return f

        # Also check if xlsx was written directly (not in output_dir)
        if output_xlsx.exists():
            return output_xlsx

        logger.error("No Excel output found in %s after conversion", output_dir)
        return None

    except subprocess.TimeoutExpired:
        logger.error("Converter timed out after 300s for %s", input_path.name)
        return None
    except Exception:
        logger.exception("Converter error for %s", input_path.name)
        return None


def parse_cad_excel(excel_path: Path) -> list[dict]:
    """Parse the Excel output produced by a DDC converter.

    DDC converters produce Excel files with columns such as:
    Category, Family, Type Name, Count, Volume, Area, Length, Material, etc.

    Args:
        excel_path: Path to the Excel file generated by the converter.

    Returns:
        List of dicts where each dict represents one element row.
    """
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    if ws is None:
        wb.close()
        return []

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        wb.close()
        return []

    # First row is the header; strip DDC type suffixes like " : String", " : Double"
    raw_headers = [str(h or "").strip() for h in rows[0]]
    headers = [h.split(" : ")[0].strip().lower() if " : " in h else h.lower() for h in raw_headers]

    elements: list[dict] = []
    for row in rows[1:]:
        if not any(row):
            continue

        item: dict = {}
        for i, header in enumerate(headers):
            if i < len(row):
                val = row[i]
                if val is not None:
                    item[header] = val

        if item:
            elements.append(item)

    wb.close()
    return elements


def summarize_cad_elements(elements: list[dict]) -> str:
    """Create a text summary of CAD elements suitable for AI processing.

    The summary is a tabular representation of element categories, types,
    counts, volumes, and areas. Limited to 200 elements to stay within
    AI context window limits.

    Args:
        elements: List of element dicts from ``parse_cad_excel``.

    Returns:
        Human-readable text summary of the CAD model contents.
    """
    if not elements:
        return "No elements found in the CAD file."

    lines = [f"CAD/BIM file contains {len(elements)} elements:\n"]
    lines.append("Category | Type | Count | Volume (m3) | Area (m2)")
    lines.append("-" * 60)

    for el in elements[:200]:  # Limit to 200 elements for AI context
        category = el.get("category", el.get("element type", "unknown"))
        type_name = el.get("type name", el.get("family", el.get("type", "")))
        count = el.get("count", 1)
        volume = el.get("volume", el.get("volume (m3)", ""))
        area = el.get("area", el.get("area (m2)", ""))

        lines.append(f"{category} | {type_name} | {count} | {volume} | {area}")

    if len(elements) > 200:
        lines.append(f"\n... and {len(elements) - 200} more elements (truncated)")

    return "\n".join(lines)


def _to_float(val: object) -> float:
    """Safely convert a value to float, returning 0.0 on failure."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def group_cad_elements(elements: list[dict]) -> dict:
    """Group CAD elements by category and type, summing numeric quantities.

    Produces a structured dict of quantity tables suitable for direct display
    without AI processing. Each category contains type-level rows with summed
    count, volume (m3), area (m2), and length (m).

    Handles DDC column name variations:
    - ``category`` / ``element type`` -> category
    - ``type name`` / ``family`` / ``type`` -> type
    - ``volume`` / ``volume (m3)`` -> volume
    - ``area`` / ``area (m2)`` -> area
    - ``count`` defaults to 1

    Args:
        elements: List of element dicts from ``parse_cad_excel``.

    Returns:
        Dict with ``groups`` (list), ``grand_totals``, and ``total_elements``.
    """
    from collections import OrderedDict

    # category -> type -> aggregated values
    cat_types: dict[str, dict[str, dict]] = OrderedDict()

    for el in elements:
        raw_cat = str(el.get("category", el.get("element type", "Other"))).strip()
        category = raw_cat if raw_cat and raw_cat != "None" else "Other"
        type_name = str(el.get("type name", el.get("family", el.get("type", "Unknown")))).strip() or "Unknown"
        count = _to_float(el.get("count", 1))
        volume = _to_float(el.get("volume", el.get("volume (m3)", 0)))
        area = _to_float(el.get("area", el.get("area (m2)", 0)))
        length = _to_float(el.get("length", 0))
        material = str(el.get("material", "")).strip()

        if category not in cat_types:
            cat_types[category] = OrderedDict()

        if type_name not in cat_types[category]:
            cat_types[category][type_name] = {
                "type": type_name,
                "material": "",
                "count": 0.0,
                "volume_m3": 0.0,
                "area_m2": 0.0,
                "length_m": 0.0,
            }

        entry = cat_types[category][type_name]
        entry["count"] += count
        entry["volume_m3"] += volume
        entry["area_m2"] += area
        entry["length_m"] += length
        if material and not entry["material"]:
            entry["material"] = material

    # Build structured output
    groups: list[dict] = []
    grand_count = 0.0
    grand_volume = 0.0
    grand_area = 0.0
    grand_length = 0.0

    for cat_name, types in cat_types.items():
        items = list(types.values())

        cat_count = sum(it["count"] for it in items)
        cat_volume = sum(it["volume_m3"] for it in items)
        cat_area = sum(it["area_m2"] for it in items)
        cat_length = sum(it["length_m"] for it in items)

        # Round item values
        for it in items:
            it["count"] = round(it["count"], 1)
            it["volume_m3"] = round(it["volume_m3"], 3)
            it["area_m2"] = round(it["area_m2"], 2)
            it["length_m"] = round(it["length_m"], 2)

        groups.append(
            {
                "category": cat_name,
                "items": items,
                "totals": {
                    "count": round(cat_count, 1),
                    "volume_m3": round(cat_volume, 3),
                    "area_m2": round(cat_area, 2),
                    "length_m": round(cat_length, 2),
                },
            }
        )

        grand_count += cat_count
        grand_volume += cat_volume
        grand_area += cat_area
        grand_length += cat_length

    return {
        "total_elements": len(elements),
        "groups": groups,
        "grand_totals": {
            "count": round(grand_count, 1),
            "volume_m3": round(grand_volume, 3),
            "area_m2": round(grand_area, 2),
            "length_m": round(grand_length, 2),
        },
    }


def get_available_columns(elements: list[dict], file_format: str = "rvt") -> dict[str, Any]:
    """Analyze elements and classify columns into grouping/quantity/text categories.

    Scans all elements to discover column names, then classifies each column
    based on its content:
    - **quantity**: >50% numeric values AND name suggests a measurement
      (or is purely numeric across all non-None values).
    - **grouping**: string columns with <500 unique values — suitable for
      GROUP BY operations (e.g. category, type name, level, material).
    - **text**: everything else (ids, long descriptions with too many uniques).

    Also provides ``suggested_grouping``, ``suggested_quantities``,
    format-specific ``presets``, and ``unit_labels`` based on common DDC
    converter output conventions.

    Args:
        elements: List of element dicts from ``parse_cad_excel``.
        file_format: Lowercase file extension without dot (e.g. ``"rvt"``, ``"ifc"``).

    Returns:
        Dict with keys ``grouping``, ``quantity``, ``text``,
        ``suggested_grouping``, ``suggested_quantities``, ``presets``,
        and ``unit_labels``.
    """
    if not elements:
        return {
            "grouping": [],
            "quantity": [],
            "text": [],
            "suggested_grouping": [],
            "suggested_quantities": [],
            "presets": {},
            "unit_labels": {},
            "confidence": {},
        }

    # Collect all unique column names across every element
    all_columns: set[str] = set()
    for el in elements:
        all_columns.update(el.keys())

    # Keywords that indicate a quantity / measurement column
    quantity_keywords = {
        "volume",
        "area",
        "length",
        "width",
        "height",
        "count",
        "weight",
        "perimeter",
        "thickness",
        "depth",
        "radius",
        "diameter",
        "mass",
        "quantity",
    }

    grouping_cols: list[str] = []
    quantity_cols: list[str] = []
    text_cols: list[str] = []

    for col in all_columns:
        # Gather non-None values for this column
        values = [el[col] for el in elements if col in el and el[col] is not None]
        if not values:
            text_cols.append(col)
            continue

        # Check how many values are numeric
        numeric_count = 0
        for v in values:
            try:
                float(v)
                numeric_count += 1
            except (ValueError, TypeError):
                pass

        total = len(values)
        numeric_ratio = numeric_count / total if total > 0 else 0.0

        # Does the column name hint at a quantity?
        col_lower = col.lower()
        name_is_quantity = any(kw in col_lower for kw in quantity_keywords)

        # Classify
        if numeric_ratio > 0.5 and (name_is_quantity or numeric_ratio == 1.0):
            quantity_cols.append(col)
        else:
            # Count unique string values to decide grouping vs text
            unique_values = {str(v) for v in values}
            if len(unique_values) < 500:
                grouping_cols.append(col)
            else:
                text_cols.append(col)

    # Sort each list alphabetically for deterministic output
    grouping_cols.sort()
    quantity_cols.sort()
    text_cols.sort()

    # Suggested defaults based on common DDC converter output
    suggested_grouping: list[str] = []
    suggested_quantities: list[str] = []

    # Preferred grouping columns (in priority order)
    for candidate in ["category", "type name", "family", "level", "material", "workset"]:
        if candidate in grouping_cols:
            suggested_grouping.append(candidate)
    # Default to first two if none of the preferred ones matched
    if not suggested_grouping and grouping_cols:
        suggested_grouping = grouping_cols[:2]

    # Preferred quantity columns
    for candidate in ["volume", "area", "length", "count"]:
        if candidate in quantity_cols:
            suggested_quantities.append(candidate)
    # Fall back to all quantity columns if none matched
    if not suggested_quantities:
        suggested_quantities = quantity_cols[:4]

    # Format-specific QTO presets
    presets: dict[str, dict] = {}

    # "count" is always available — it's computed as number of elements per group
    # (not a column from the file, but calculated during grouping)
    available_qty = set(quantity_cols) | {"count"}

    if file_format in ("rvt", "rfa"):
        presets = {
            "standard": {
                "label": "Standard Revit QTO",
                "description": "Category + Type Name — standard Revit breakdown",
                "group_by": [c for c in ["category", "type name"] if c in grouping_cols],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "detailed": {
                "label": "Detailed (with Level)",
                "description": "Category + Type Name + Level — per-floor breakdown",
                "group_by": [c for c in ["category", "type name", "level"] if c in grouping_cols],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_family": {
                "label": "By Family",
                "description": "Family + Type — for procurement and ordering",
                "group_by": [c for c in ["family", "type name"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
            "summary": {
                "label": "Quick Summary",
                "description": "Category only — high-level overview",
                "group_by": [c for c in ["category"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
        }
    elif file_format == "ifc":
        presets = {
            "standard": {
                "label": "Standard IFC QTO",
                "description": "Group by Category + Type — standard IFC entity breakdown",
                "group_by": [c for c in ["category", "type name", "type"] if c in grouping_cols][:2],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "detailed": {
                "label": "Detailed (with Level)",
                "description": "Category + Type + Level — per-floor breakdown",
                "group_by": [c for c in ["category", "type name", "type", "level"] if c in grouping_cols][:3],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_storey": {
                "label": "By Building Storey",
                "description": "Building Storey + Category + Type — storey-first breakdown",
                "group_by": [c for c in ["level", "category", "type name", "type"] if c in grouping_cols][:3],
                "sum_columns": [c for c in ["volume", "area", "length", "count"] if c in available_qty],
            },
            "by_material": {
                "label": "By Material",
                "description": "Material + Category — material-first grouping for procurement",
                "group_by": [c for c in ["material", "category"] if c in grouping_cols][:2],
                "sum_columns": [c for c in ["volume", "area", "count"] if c in available_qty],
            },
            "summary": {
                "label": "Quick Summary",
                "description": "Category only — high-level element count",
                "group_by": [c for c in ["category"] if c in grouping_cols],
                "sum_columns": [c for c in ["count", "volume", "area"] if c in available_qty],
            },
        }
    elif file_format == "dwg":
        presets = {
            "standard": {
                "label": "Standard DWG QTO",
                "description": "Group by Layer — standard AutoCAD organization",
                "group_by": [c for c in ["layer", "category"] if c in grouping_cols][:1],
                "sum_columns": [c for c in ["count", "length", "area"] if c in available_qty],
            },
        }
    else:
        presets = {
            "standard": {
                "label": "Standard QTO",
                "description": "Default grouping by available categories",
                "group_by": suggested_grouping,
                "sum_columns": suggested_quantities,
            },
        }

    # Remove presets with empty group_by
    presets = {k: v for k, v in presets.items() if v["group_by"]}

    # Confidence scoring: for each column, calculate % of elements with non-null values
    confidence: dict[str, float] = {}
    for col in all_columns:
        non_null = sum(1 for elem in elements if elem.get(col) not in (None, "", "nan", "NaN"))
        confidence[col] = round(non_null / len(elements), 2) if elements else 0

    # Unit labels for quantity columns (+ "count" which is always available)
    unit_labels: dict[str, str] = {"count": "pcs"}
    for col in quantity_cols:
        col_lower = col.lower()
        if "volume" in col_lower:
            unit_labels[col] = "m\u00b3"
        elif "area" in col_lower:
            unit_labels[col] = "m\u00b2"
        elif "length" in col_lower or "perimeter" in col_lower:
            unit_labels[col] = "m"
        elif "weight" in col_lower or "mass" in col_lower:
            unit_labels[col] = "kg"
        elif "count" in col_lower:
            unit_labels[col] = "pcs"
        else:
            unit_labels[col] = ""

    return {
        "grouping": grouping_cols,
        "quantity": quantity_cols,
        "text": text_cols,
        "suggested_grouping": suggested_grouping,
        "suggested_quantities": suggested_quantities,
        "presets": presets,
        "unit_labels": unit_labels,
        "confidence": confidence,
    }


def group_cad_elements_dynamic(
    elements: list[dict],
    group_by: list[str],
    sum_columns: list[str],
) -> dict:
    """Group elements by user-selected columns, sum user-selected quantities.

    This is the interactive counterpart to ``group_cad_elements`` — instead
    of hardcoded category/type grouping, the caller selects which columns
    to group by and which numeric columns to sum.

    Args:
        elements: List of element dicts from ``parse_cad_excel``.
        group_by: Column names to use as group key (e.g. ``["category", "type name"]``).
        sum_columns: Numeric column names to aggregate (e.g. ``["volume", "area"]``).

    Returns:
        Dict with ``total_elements``, ``group_by``, ``sum_columns``, ``groups``
        (list of group dicts), and ``grand_totals``.
    """
    from collections import OrderedDict

    groups: dict[str, dict] = OrderedDict()
    grand_totals: dict[str, float] = dict.fromkeys(sum_columns, 0.0)
    grand_totals["count"] = 0.0

    for el in elements:
        # Build the composite group key
        key_parts: dict[str, str] = {}
        for col in group_by:
            raw = el.get(col)
            val = str(raw).strip() if raw is not None else ""
            key_parts[col] = val if val and val != "None" else "(empty)"

        key = " | ".join(key_parts.values())

        if key not in groups:
            groups[key] = {
                "key": key,
                "key_parts": dict(key_parts),
                "count": 0,
                "sums": dict.fromkeys(sum_columns, 0.0),
            }

        entry = groups[key]
        entry["count"] += 1

        for col in sum_columns:
            entry["sums"][col] += _to_float(el.get(col, 0))

    grand_totals["count"] = float(len(elements))
    for col in sum_columns:
        grand_totals[col] = 0.0

    result_groups: list[dict] = []
    for g in groups.values():
        # Round sums
        for col in sum_columns:
            g["sums"][col] = round(g["sums"][col], 4)
            grand_totals[col] += g["sums"][col]

        result_groups.append(g)

    # Round grand totals
    for col in sum_columns:
        grand_totals[col] = round(grand_totals[col], 4)
    grand_totals["count"] = len(elements)

    return {
        "total_elements": len(elements),
        "group_by": group_by,
        "sum_columns": sum_columns,
        "groups": result_groups,
        "grand_totals": grand_totals,
    }


def _ddc_cad2data_verify() -> bool:
    """DataDrivenConstruction CAD2DATA pipeline verification. DDC-CWICR-2026."""
    _sig = [0x44, 0x44, 0x43, 0x2D, 0x43, 0x57, 0x49, 0x43, 0x52]  # DDC-CWICR
    return all(c > 0 for c in _sig)
