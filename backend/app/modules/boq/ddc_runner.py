# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run the DDC 2026.10 converters and read what they write.

The release replaced the 18.x ``*Exporter.exe`` programs with three command
lines of a different shape, and none of them writes the single "one row per
element" workbook plus COLLADA file the platform was built around:

==========  =========================================================  =====================================
format      command line                                               what it writes
==========  =========================================================  =====================================
``rvt``     ``RVTconverter.exe <in> -o <dir> --properties``            ``native_graph.glb``, ``properties.jsonl``
                                                                       (a graph of the stored objects),
                                                                       ``summary.json``, ``report.json``
``ifc``     ``python.exe converter.py <in> --output <dir> --glb``      a new sub-folder with ``<stem>.xlsx``
                                                                       (Objects / Properties / Quantities /
                                                                       SpatialLinks ... sheets) and
                                                                       ``<stem>.glb`` (one node per element)
``dwg``     ``dwg2excel.exe <in> -o <dir> --json``                     a sub-folder with ``<stem>.xlsx``,
                                                                       ``<stem>.dxf``, ``report.json``
==========  =========================================================  =====================================

This module owns three things: building and running those command lines
(:func:`run_converter`), flattening the IFC and RVT output into the
one-row-per-element workbook the rest of the platform parses
(:func:`write_flat_workbook`), and renaming the GLB nodes of an RVT or IFC model
to the plain element id the 3D viewer matches on (:func:`normalize_glb_node_names`).

Honest limits, stated where the data comes from rather than papered over:

* IFC: the geometry is the converter's own tessellation (``--glb``): metres,
  glTF Y up, node ``extras.element_id`` = the STEP id (the ``ID`` column) and
  ``extras.global_id`` = the GlobalId. Elements whose geometry the converter
  cannot read have no node. A converter build without ``--glb`` is run again
  without it and yields no geometry, as before.
* RVT: ``properties.jsonl`` is the stored object graph, not a schedule. Only
  elements that have a mesh in the GLB become rows. Category ids are mapped to
  ``OST_`` and display names (:mod:`revit_categories`); level and type follow
  the element's stored links to its ``Level`` and ``SymbolInfo`` objects.
  Stored reals are in Revit's internal units (feet, square feet, ...) and keep
  an ``[internal units]`` label, so the take-off never sums them as metres.
  Area, volume, length, height and thickness are measured on the element's
  mesh (:mod:`glb_quantities`): a beam's length is its cut length, not the
  analytical length between joins.
* DWG: the converter's workbook is a record-by-record decoder log; the take-off
  table is read from the DXF it writes instead.
"""

from __future__ import annotations

import json
import logging
import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.converter_source import PACKAGES, command_prefix
from app.modules.boq.glb_quantities import MESH_QUANTITY_COLUMNS, glb_element_quantities
from app.modules.boq.revit_categories import revit_category_label, revit_category_name

logger = logging.getLogger(__name__)

#: Sheet of the flattened workbook ``parse_cad_excel`` reads (it takes the active sheet).
FLAT_SHEET = "Elements"

#: An xlsx sheet holds 16384 columns; stay well below it.
_MAX_PROPERTY_COLUMNS = 12000


@dataclass
class ConverterRun:
    """Outcome of one converter invocation."""

    fmt: str
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    #: The folder the converter created for this input, when it reported one.
    folder: Path | None = None
    #: Files by role: ``xlsx``, ``dxf``, ``glb``, ``properties``, ``report``.
    outputs: dict[str, Path] = field(default_factory=dict)
    #: Converter-reported status (``CONVERTED``, ``WRITTEN_QUALITY_UNVERIFIED`` ...).
    status: str | None = None

    @property
    def ok(self) -> bool:
        """True when the converter wrote the output this format is read from."""
        needed = {"rvt": "glb", "ifc": "xlsx", "dwg": "xlsx"}[self.fmt]
        return needed in self.outputs and self.outputs[needed].is_file() and self.outputs[needed].stat().st_size > 0


def build_command(fmt: str, exe: Path, input_path: Path, out_dir: Path, *, glb: bool = True) -> list[str]:
    """The argv that converts ``input_path`` into ``out_dir`` for format ``fmt``."""
    prefix = command_prefix(fmt, exe)
    src = str(input_path.resolve())
    if fmt == "rvt":
        return [*prefix, src, "-o", str(out_dir), "--properties"]
    if fmt == "ifc":
        cmd = [*prefix, src, "--output", str(out_dir)]
        return [*cmd, "--glb"] if glb else cmd
    if fmt == "dwg":
        return [*prefix, src, "-o", str(out_dir), "--json", "--no-svg"]
    raise ValueError(f"No DDC converter command line for format {fmt!r}")


def _clean_env(fmt: str) -> dict[str, str] | None:
    """Environment for the child: the embedded Python must not see ours."""
    if fmt != "ifc":
        return None
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONSTARTUP"}}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _last_json_line(text: str) -> dict[str, Any] | None:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def run_converter(fmt: str, exe: Path, input_path: Path, work_dir: Path, *, timeout: float = 600) -> ConverterRun:
    """Convert one file and collect its outputs. Raises ``subprocess.TimeoutExpired``.

    Never raises for a failed conversion: the caller reads :attr:`ConverterRun.ok`
    and the captured ``stderr`` / ``stdout``.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem
    if fmt == "rvt":
        # The RVT converter never overwrites an existing folder.
        out_dir = work_dir / f"{stem}.converted"
        n = 1
        while out_dir.exists():
            n += 1
            out_dir = work_dir / f"{stem}.converted-{n}"
    else:
        out_dir = work_dir / f"{fmt}_out"
        out_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(fmt, exe, input_path, out_dir)
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _call(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        logger.debug("DDC call: %s", argv)
        return subprocess.run(  # noqa: S603 - argv list, no shell
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(work_dir),
            env=_clean_env(fmt),
            timeout=timeout,
            **kwargs,
        )

    proc = _call(cmd)
    if fmt == "ifc" and proc.returncode == 2 and b"--glb" in (proc.stderr or b""):
        # A converter build older than the 3D model option: tables only.
        cmd = build_command(fmt, exe, input_path, out_dir, glb=False)
        proc = _call(cmd)
    run = ConverterRun(
        fmt=fmt,
        command=cmd,
        returncode=proc.returncode,
        stdout=proc.stdout.decode("utf-8", errors="replace"),
        stderr=proc.stderr.decode("utf-8", errors="replace"),
    )
    _collect_outputs(run, out_dir, stem)
    return run


def _collect_outputs(run: ConverterRun, out_dir: Path, stem: str) -> None:
    if run.fmt == "rvt":
        run.folder = out_dir
        for role, name in (
            ("glb", "native_graph.glb"),
            ("properties", "properties.jsonl"),
            ("report", "report.json"),
            ("summary", "summary.json"),
        ):
            if (out_dir / name).is_file():
                run.outputs[role] = out_dir / name
        try:
            run.status = (json.loads((out_dir / "summary.json").read_text(encoding="utf-8")) or {}).get("status")
        except (OSError, ValueError):
            pass
        return

    info = _last_json_line(run.stdout) or {}
    run.status = info.get("status")
    folder = info.get("folder")
    folder_path = Path(folder) if isinstance(folder, str) and folder else None
    if folder_path is None or not folder_path.is_dir():
        # Fall back to the one sub-folder the converter created.
        subs = [p for p in out_dir.iterdir() if p.is_dir()] if out_dir.is_dir() else []
        folder_path = subs[0] if len(subs) == 1 else None
    run.folder = folder_path
    if folder_path is None:
        return
    if run.fmt == "ifc":
        for role, name in (("jsonl", "data.jsonl"), ("report", "result.json")):
            if (folder_path / name).is_file():
                run.outputs[role] = folder_path / name
        # 2.0.0 names the workbook after the model and reports it as ``data``;
        # older builds wrote ``drawing.xlsx``.
        reported = Path(info["data"]) if isinstance(info.get("data"), str) and info["data"] else None
        for cand in (reported, folder_path / f"{stem}.xlsx", folder_path / "drawing.xlsx"):
            if cand is not None and cand.is_file():
                run.outputs["xlsx"] = cand
                break
        else:
            found = sorted(folder_path.glob("*.xlsx"))
            if len(found) == 1:
                run.outputs["xlsx"] = found[0]
        glb = info.get("glb")
        glb_path = Path(glb) if isinstance(glb, str) and glb else None
        if glb_path is None or not glb_path.is_file():
            found = sorted(folder_path.glob("*.glb"))
            glb_path = found[0] if len(found) == 1 else None
        if glb_path is not None and glb_path.stat().st_size > 0:
            run.outputs["glb"] = glb_path
        if info.get("status") == "FAILED":
            run.outputs.pop("xlsx", None)
    else:  # dwg
        for role, name in (
            ("xlsx", f"{stem}.xlsx"),
            ("dxf", f"{stem}.dxf"),
            ("jsonl", f"{stem}.jsonl"),
            ("report", "report.json"),
        ):
            cand = folder_path / name
            if not cand.is_file():
                # The converter may sanitise the stem; fall back to any file of that kind.
                found = sorted(folder_path.glob(f"*{Path(name).suffix}")) if name != "report.json" else []
                cand = found[0] if found else cand
            if cand.is_file():
                run.outputs[role] = cand


# ── Flattening: IFC ────────────────────────────────────────────────────────

#: Tables of the IFC converter's semantic model that the flat table is built from.
_IFC_TABLES = ("Objects", "SpatialLinks", "NormalizedMeasures", "Properties", "Quantities", "TypeLinks")

#: A cell the converter could not write to Excel (too precise or out of range)
#: holds this pointer to ``data.jsonl`` instead of the number.
_XLSX_POINTER_PREFIX = "[See data.jsonl"


def _unwrap(value: Any) -> Any:
    """Reduce an IFC value record to a scalar.

    Handles ``{"NominalValue": {"ifc_type": .., "value": ..}}`` (properties) and
    ``{"LengthValue": 9.6, "Formula": null}`` (quantities).
    """
    if isinstance(value, dict):
        if "NominalValue" in value:
            return _unwrap(value["NominalValue"])
        if "value" in value and "ifc_type" in value:
            return _unwrap(value["value"])
        measures = [k for k in value if k.endswith("Value") and k != "NominalValue"]
        if len(measures) == 1:
            return _unwrap(value[measures[0]])
        if len(value) == 1:
            return _unwrap(next(iter(value.values())))
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.startswith(_XLSX_POINTER_PREFIX):
        return None
    return value


def _cell_value(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw.startswith(_XLSX_POINTER_PREFIX):
            return None
        try:
            return _unwrap(json.loads(raw))
        except ValueError:
            return raw
    return _unwrap(raw)


def _sheet_rows(wb: Any, name: str) -> Any:
    """Yield dict rows of a sheet; nothing when the sheet is absent."""
    if name not in wb.sheetnames:
        return
    rows = wb[name].iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        return
    keys = [str(h or "").strip() for h in header]
    for row in rows:
        if not any(v is not None for v in row):
            continue
        yield dict(zip(keys, row, strict=False))


_TABLE_RE = re.compile(r'"table"\s*:\s*"(\w+)"')


def _ifc_tables_from_jsonl(data_jsonl: Path) -> dict[str, list[dict[str, Any]]]:
    """The needed tables of ``data.jsonl``: exact values, no Excel cell limits, no openpyxl."""
    tables: dict[str, list[dict[str, Any]]] = {t: [] for t in _IFC_TABLES}
    with data_jsonl.open("r", encoding="utf-8") as fh:
        for line in fh:
            m = _TABLE_RE.search(line, 0, 64)
            table = m.group(1) if m else None
            if table not in tables:
                continue
            try:
                record = json.loads(line).get("record")
            except ValueError:
                continue
            if isinstance(record, dict):
                tables[table].append(record)
    return tables


def _ifc_tables_from_xlsx(drawing_xlsx: Path) -> dict[str, list[dict[str, Any]]]:
    import openpyxl

    wb = openpyxl.load_workbook(drawing_xlsx, read_only=True, data_only=True)
    try:
        return {t: list(_sheet_rows(wb, t)) for t in _IFC_TABLES}
    finally:
        wb.close()


def flatten_ifc_workbook(drawing_xlsx: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Turn the IFC converter's output into ``(header, rows)``, one row per occurrence.

    ``data.jsonl`` next to the workbook is read when present: it carries the
    same tables with full-precision values, where the workbook replaces a number
    Excel cannot hold with a pointer string.
    """
    data_jsonl = drawing_xlsx.with_name("data.jsonl")
    tables = None
    if data_jsonl.is_file() and data_jsonl.stat().st_size > 2:
        tables = _ifc_tables_from_jsonl(data_jsonl)
        if not tables["Objects"]:
            tables = None
    if tables is None:
        tables = _ifc_tables_from_xlsx(drawing_xlsx)

    objects: dict[str, dict[str, Any]] = {}
    for row in tables["Objects"]:
        objects[str(row.get("ID"))] = row

    parent: dict[str, str] = {}
    for row in tables["SpatialLinks"]:
        child, par = str(row.get("child_step_id")), str(row.get("parent_step_id"))
        parent.setdefault(child, par)

    def ancestor_name(step_id: str, category: str) -> str:
        seen: set[str] = set()
        cur = parent.get(step_id)
        while cur is not None and cur not in seen:
            seen.add(cur)
            obj = objects.get(cur)
            if obj and str(obj.get("Category")) == category:
                return str(obj.get("Name") or "")
            cur = parent.get(cur)
        return ""

    type_of: dict[str, str] = {}
    for row in tables["TypeLinks"]:
        type_of.setdefault(str(row.get("owner_step_id")), str(row.get("type_step_id")))

    si_values: dict[tuple[str, str], Any] = {}
    for row in tables["NormalizedMeasures"]:
        si = row.get("si_value")
        if isinstance(si, str) and si.startswith(_XLSX_POINTER_PREFIX):
            si = None
        if si is not None:
            si_values[(str(row.get("owner_step_id")), str(row.get("property_step_id")))] = si

    props: dict[str, dict[str, Any]] = {}
    columns: dict[str, None] = {}
    for sheet in ("Properties", "Quantities"):
        for row in tables[sheet]:
            owner = str(row.get("owner_step_id"))
            if str(row.get("scope")) not in {"OCCURRENCE", "None"}:
                continue
            set_name = str(row.get("set_name") or "")
            prop = str(row.get("property_name") or "")
            if not prop:
                continue
            key = f"[{set_name}] {prop}" if set_name else prop
            if key not in columns:
                if len(columns) >= _MAX_PROPERTY_COLUMNS:
                    continue
                columns[key] = None
            value = si_values.get((owner, str(row.get("property_step_id"))))
            if value is None:
                value = _cell_value(row.get("value"))
            props.setdefault(owner, {})[key] = value

    header = ["ID", "GlobalId", "Category", "Name", "Type Name", "Description", "Level", "Building", *columns]
    rows: list[dict[str, Any]] = []
    for step_id, obj in objects.items():
        if str(obj.get("IsType")).lower() == "true":
            continue
        type_obj = objects.get(type_of.get(step_id, ""))
        row: dict[str, Any] = {
            "ID": int(step_id) if step_id.isdigit() else step_id,
            "GlobalId": obj.get("GlobalId"),
            "Category": obj.get("Category"),
            "Name": obj.get("Name"),
            "Type Name": (type_obj.get("Name") if type_obj else None) or None,
            "Description": obj.get("Description"),
            "Level": ancestor_name(step_id, "IfcBuildingStorey") or None,
            "Building": ancestor_name(step_id, "IfcBuilding") or None,
        }
        row.update(props.get(step_id, {}))
        rows.append(row)
    return header, rows


# ── Flattening: RVT ────────────────────────────────────────────────────────


def read_glb_element_ids(glb_path: Path) -> set[int]:
    """Element ids the GLB carries a node for (``extras.element_id``)."""
    json_chunk = _read_glb_json(glb_path)
    ids: set[int] = set()
    for node in json_chunk.get("nodes", []):
        eid = (node.get("extras") or {}).get("element_id")
        if isinstance(eid, int):
            ids.add(eid)
    return ids


def _read_glb_json(glb_path: Path) -> dict[str, Any]:
    with glb_path.open("rb") as fh:
        head = fh.read(20)
        if len(head) < 20 or head[:4] != b"glTF":
            raise ValueError(f"{glb_path.name} is not a GLB file")
        length = struct.unpack("<I", head[12:16])[0]
        return json.loads(fh.read(length).decode("utf-8"))


def normalize_glb_node_names(glb_path: Path) -> int:
    """Rename GLB nodes ``element_<id>`` to ``<id>``; returns nodes renamed.

    The 3D viewer matches a mesh to a table row by node name equal to the row's
    element id. The RVT converter names nodes ``element_<id>`` and keeps the id in
    ``extras.element_id``; rewriting the JSON chunk makes the two agree without
    touching the binary chunk.
    """
    data = glb_path.read_bytes()
    if data[:4] != b"glTF" or data[16:20] != b"JSON":
        raise ValueError(f"{glb_path.name} is not a GLB file")
    json_len = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20 : 20 + json_len].decode("utf-8"))
    renamed = 0
    for node in doc.get("nodes", []):
        eid = (node.get("extras") or {}).get("element_id")
        if isinstance(eid, int) and node.get("name") != str(eid):
            node["name"] = str(eid)
            renamed += 1
    if not renamed:
        return 0
    new_json = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    new_json += b" " * (-len(new_json) % 4)
    rest = data[20 + json_len :]
    total = 12 + 8 + len(new_json) + len(rest)
    out = data[:8] + struct.pack("<I", total) + struct.pack("<I", len(new_json)) + b"JSON" + new_json + rest
    tmp = glb_path.with_suffix(".glb.tmp")
    tmp.write_bytes(out)
    tmp.replace(glb_path)
    return renamed


#: +90 degrees about X: turns a Y-up glTF scene into the Z-up frame the 3D viewer
#: rotates back (it treats every GLB as Z-up, which is what the RVT output is).
_Y_UP_TO_Z_UP = [0.7071067811865476, 0.0, 0.0, 0.7071067811865476]


def orient_glb_for_viewer(glb_path: Path) -> bool:
    """Wrap a Y-up GLB (``extras.up_axis == "Y"``, the IFC converter) in a Z-up root node.

    Only the JSON chunk changes; returns True when the file was rewritten.
    """
    data = glb_path.read_bytes()
    if data[:4] != b"glTF" or data[16:20] != b"JSON":
        raise ValueError(f"{glb_path.name} is not a GLB file")
    json_len = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20 : 20 + json_len].decode("utf-8"))
    extras = doc.get("extras") or {}
    if str(extras.get("up_axis", "")).upper() != "Y":
        return False
    nodes = doc.setdefault("nodes", [])
    scenes = doc.get("scenes") or [{"nodes": list(range(len(nodes)))}]
    scene_index = doc.get("scene") if isinstance(doc.get("scene"), int) else 0
    if not 0 <= scene_index < len(scenes):
        scene_index = 0
    roots = list(scenes[scene_index].get("nodes") or [])
    nodes.append({"name": "ifc_model_root", "rotation": _Y_UP_TO_Z_UP, "children": roots})
    scenes[scene_index]["nodes"] = [len(nodes) - 1]
    doc["scenes"] = scenes
    doc["scene"] = scene_index
    doc["extras"] = {**extras, "up_axis": "Z", "source_up_axis": "Y"}
    new_json = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    new_json += b" " * (-len(new_json) % 4)
    rest = data[20 + json_len :]
    total = 12 + 8 + len(new_json) + len(rest)
    out = data[:8] + struct.pack("<I", total) + struct.pack("<I", len(new_json)) + b"JSON" + new_json + rest
    tmp = glb_path.with_suffix(".glb.tmp")
    tmp.write_bytes(out)
    tmp.replace(glb_path)
    return True


def _param_value(fields: dict[str, Any]) -> Any:
    """The stored value of one ``parameter`` row, or ``None``."""
    record = fields.get("record") if isinstance(fields, dict) else None
    if not isinstance(record, dict):
        return None
    for key, val in record.items():
        if not key.endswith(".m_value") or not isinstance(val, dict):
            continue
        if "text" in val:
            return val["text"]
        if "integer" in val:
            try:
                return int(val["integer"])
            except (TypeError, ValueError):
                return val["integer"]
        if "number" in val:
            return val["number"]
        inner = val.get("record")
        if isinstance(inner, dict):  # ElementId reference
            for v in inner.values():
                ident = (v or {}).get("record", {}) if isinstance(v, dict) else {}
                for iv in ident.values():
                    if isinstance(iv, dict) and "integer" in iv:
                        return int(iv["integer"])
    return None


def _graph_ref(value: Any) -> int | None:
    """The element id an ``ElementId`` field of the stored graph points at."""
    cur = value
    for _ in range(6):
        if not isinstance(cur, dict):
            return None
        if "integer" in cur:
            try:
                return int(cur["integer"])
            except (TypeError, ValueError):
                return None
        rec = cur.get("record")
        if not isinstance(rec, dict) or not rec:
            return None
        cur = next(iter(rec.values()))
    return None


def _graph_text(fields: Any, key: str) -> str | None:
    rec = fields.get("record") if isinstance(fields, dict) else None
    val = rec.get(key) if isinstance(rec, dict) else None
    text = val.get("text") if isinstance(val, dict) else None
    if not isinstance(text, str):
        return None
    return text.strip() or None


#: Fields of an element's own objects that name its level, in order of trust.
_LEVEL_FIELDS = (
    "Element.m_assocLevelId",
    "FamilyInstance.m_scheduleOnlyLevelId",
    "FamInstCurveDriver.m_refLevelId",
    "RoomElem.m_levelId",
    "RbsCurve.m_idLevelStart",
    "Stairs.m_bottomId",
    "FamilyElemRef.m_elemId",
)
#: Field-name endings of an element's own objects that point at its type.
_TYPE_FIELD_ENDINGS = ("AttributesId", "TypeId", "typeId", "SymbolId", "symbolId", "SymId")
_OWNER_RE = re.compile(r'"owner"\s*:\s*"(-?\d+)"')
_ROW_RE = re.compile(r'"row"\s*:\s*"(\w+)"')
_CLASS_RE = re.compile(r'"class_name"\s*:\s*"(?:Level|SymbolInfo)"')
_GRAPH_HINTS = (
    "TypeId",
    "SymId",
    "m_assocLevelId",
    "m_scheduleOnlyLevelId",
    "m_refLevelId",
    "m_levelId",
    "m_bottomId",
    "m_idLevelStart",
    "FamilyLevelRef",
    "AttributesId",
    "m_typeId",
    "m_symbolId",
)


@dataclass
class _RvtGraph:
    categories: dict[int, int] = field(default_factory=dict)
    params: dict[int, dict[str, Any]] = field(default_factory=dict)
    columns: dict[str, None] = field(default_factory=dict)
    level_refs: dict[int, dict[str, int]] = field(default_factory=dict)
    type_refs: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    level_names: dict[int, str] = field(default_factory=dict)
    type_names: dict[int, str] = field(default_factory=dict)


def _read_rvt_graph(properties_jsonl: Path, ids: set[int]) -> _RvtGraph:
    """One streaming pass over ``properties.jsonl``: categories, parameters, level and type links.

    The file is the converter's stored-object graph (often 10-20x the size of
    the model), so lines are pre-filtered on cheap substrings before any JSON
    is parsed.
    """
    g = _RvtGraph()
    with properties_jsonl.open("r", encoding="utf-8") as fh:
        for line in fh:
            kind = _ROW_RE.search(line, 0, 64)
            if kind is None:
                continue
            is_param = kind.group(1) == "parameter"
            is_record = kind.group(1) == "record"
            is_object = kind.group(1) == "object"
            if not (is_param or is_record or is_object):
                continue
            m = _OWNER_RE.search(line)
            if m is None:
                continue
            owner = int(m.group(1))
            if is_object:
                named = _CLASS_RE.search(line) is not None
                linked = owner in ids and any(h in line for h in _GRAPH_HINTS)
                if not (named or linked):
                    continue
            elif owner not in ids:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if is_record:
                try:
                    g.categories[owner] = int(rec.get("category_id"))
                except (TypeError, ValueError):
                    pass
            elif is_param:
                _read_graph_parameter(g, owner, rec)
            else:
                _read_graph_object(g, owner, rec)
    return g


_AREA_WORDS = re.compile(r"\barea\b", re.I)
_VOLUME_WORDS = re.compile(r"\bvolume\b", re.I)
_LENGTH_WORDS = re.compile(
    r"\b(length|height|width|thickness|depth|offset|elevation|radius|diameter|perimeter|"
    r"extension|distance|size|cover|spacing)\b",
    re.I,
)
_NOT_A_MEASURE = re.compile(r"\b(angle|slope|rotation|ratio|factor|count|number|coefficient|material)\b", re.I)
_FT = 0.3048


def _si_factor(label: str) -> float | None:
    """Feet-based internal unit -> SI factor for a parameter name, or ``None`` when unsure."""
    if _NOT_A_MEASURE.search(label):
        return None
    if _VOLUME_WORDS.search(label):
        return _FT**3
    if _AREA_WORDS.search(label):
        return _FT**2
    if _LENGTH_WORDS.search(label):
        return _FT
    return None


def _read_graph_parameter(g: _RvtGraph, owner: int, rec: dict[str, Any]) -> None:
    label = rec.get("builtin_label") or rec.get("builtin_parameter")
    value = _param_value(rec.get("fields") or {}) if label else None
    if value is None:
        return
    if isinstance(value, float):
        # Stored reals are in Revit internal units (feet and derived) and the
        # graph does not say which. A name that is plainly a length, area or
        # volume is converted to SI; anything else keeps the marker so the
        # take-off never sums it as metres.
        factor = _si_factor(label)
        if factor is None:
            label = f"{label} [internal units]"
        else:
            value = round(value * factor, 6)
    if label not in g.columns:
        if len(g.columns) >= _MAX_PROPERTY_COLUMNS:
            return
        g.columns[label] = None
    g.params.setdefault(owner, {})[label] = value


def _read_graph_object(g: _RvtGraph, owner: int, rec: dict[str, Any]) -> None:
    cls = rec.get("class_name")
    fields = rec.get("fields") or {}
    if cls == "Level":
        name = _graph_text(fields, "DatumPlane.m_text")
        if name:
            g.level_names[owner] = name
        return
    if cls == "SymbolInfo":
        name = _graph_text(fields, "SymbolInfo.m_name")
        if name:
            g.type_names[owner] = name
        return
    body = fields.get("record") if isinstance(fields, dict) else None
    if not isinstance(body, dict):
        return
    for key, val in body.items():
        if key in _LEVEL_FIELDS:
            if key == "FamilyElemRef.m_elemId" and cls != "FamilyLevelRef":
                continue
            ref = _graph_ref(val)
            if ref is not None and ref > 0:
                g.level_refs.setdefault(owner, {}).setdefault(key, ref)
        elif key.endswith(_TYPE_FIELD_ENDINGS):
            ref = _graph_ref(val)
            if ref is not None and ref > 0:
                rank = 0 if key == "InstInfoBase.m_symbolId" else 1
                g.type_refs.setdefault(owner, []).append((rank, ref))


def _level_of(g: _RvtGraph, eid: int) -> str | None:
    refs = g.level_refs.get(eid) or {}
    for key in _LEVEL_FIELDS:
        name = g.level_names.get(refs.get(key, 0))
        if name:
            return name
    return None


def _type_of(g: _RvtGraph, eid: int) -> str | None:
    for _rank, ref in sorted(g.type_refs.get(eid) or []):
        name = g.type_names.get(ref)
        if name:
            return name
    return None


def flatten_rvt_output(glb_path: Path, properties_jsonl: Path | None) -> tuple[list[str], list[dict[str, Any]]]:
    """``(header, rows)`` for the elements of an RVT conversion that have a mesh.

    Category, level and type come from the stored graph (``properties.jsonl``);
    area, volume, length and height are measured on the element's mesh in the
    GLB, in metres, because the stored graph holds no calculated quantities.
    """
    ids = read_glb_element_ids(glb_path)
    g = _RvtGraph()
    if properties_jsonl is not None and properties_jsonl.is_file():
        g = _read_rvt_graph(properties_jsonl, ids)
    try:
        measured = glb_element_quantities(glb_path)
    except Exception:  # noqa: BLE001 - a mesh we cannot read still leaves the semantic table
        logger.warning("Could not measure the GLB meshes of %s", glb_path.name, exc_info=True)
        measured = {}
    qty_cols = [c for c in MESH_QUANTITY_COLUMNS if any(c in q for q in measured.values())]
    header = ["ID", "Category", "Category Name", "Name", "Type Name", "Level", *qty_cols, *g.columns]
    rows: list[dict[str, Any]] = []
    for eid in sorted(ids):
        cat_id = g.categories.get(eid)
        label = revit_category_label(cat_id)
        type_name = _type_of(g, eid)
        row: dict[str, Any] = {
            "ID": eid,
            "Category": revit_category_name(cat_id),
            "Category Name": label,
            "Name": f"{type_name} {eid}" if type_name else f"{label} {eid}",
            "Type Name": type_name,
            "Level": _level_of(g, eid),
        }
        row.update(measured.get(eid, {}))
        row.update(g.params.get(eid, {}))
        rows.append(row)
    return header, rows


# ── Writing the flat workbook ──────────────────────────────────────────────


def write_flat_workbook(run: ConverterRun, out_xlsx: Path) -> Path:
    """Write the one-row-per-element workbook for an IFC or RVT run; returns its path."""
    if run.fmt == "ifc":
        header, rows = flatten_ifc_workbook(run.outputs["xlsx"])
    elif run.fmt == "rvt":
        header, rows = flatten_rvt_output(run.outputs["glb"], run.outputs.get("properties"))
    else:
        raise ValueError(f"{run.fmt!r} output is already a flat table")
    import openpyxl

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(FLAT_SHEET)
    ws.append(header)
    for row in rows:
        ws.append([_xlsx_safe(row.get(col)) for col in header])
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_xlsx)
    return out_xlsx


def _xlsx_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            # openpyxl refuses control characters in cells.
            return "".join(ch for ch in value if ch >= " " or ch in "\t\n\r")[:32000]
        return value
    return str(value)


def tool_label(fmt: str) -> str:
    pkg = PACKAGES[fmt]
    return f"{pkg.name} {pkg.version}"
