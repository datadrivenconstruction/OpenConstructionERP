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
``ifc``     ``python.exe converter.py <in> --output <dir>``            a new sub-folder with ``drawing.xlsx``
                                                                       (Objects / Properties / Quantities /
                                                                       SpatialLinks ... sheets), ``data.jsonl``
``dwg``     ``dwg2excel.exe <in> -o <dir> --json``                     a sub-folder with ``<stem>.xlsx``,
                                                                       ``<stem>.dxf``, ``report.json``
==========  =========================================================  =====================================

This module owns three things: building and running those command lines
(:func:`run_converter`), flattening the IFC and RVT output into the
one-row-per-element workbook the rest of the platform parses
(:func:`write_flat_workbook`), and renaming the GLB nodes of an RVT model to
the plain element id the 3D viewer matches on (:func:`normalize_glb_node_names`).

Honest limits, stated where the data comes from rather than papered over:

* IFC: the converter writes no geometry. Elements carry their properties and
  quantity sets, not a mesh.
* RVT: ``properties.jsonl`` is the stored object graph, not a schedule. Only
  elements that have a mesh in the GLB become rows, parameters keep their
  stored labels, and stored real numbers are in Revit's internal units (feet,
  square feet, ...), so they are *not* offered under the length / area / volume
  names the quantity take-off reads. Quantities for RVT come from geometry, not
  from these columns.
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

logger = logging.getLogger(__name__)

#: Sheet of the flattened workbook ``parse_cad_excel`` reads (it takes the active sheet).
FLAT_SHEET = "Elements"

#: Revit built-in category ids that appear as ``category_id`` in the stored
#: graph, with the ``OST_`` names the rest of the platform classifies on. Ids
#: not listed here fall back to ``OST_Category<abs id>``, never to a guess.
_REVIT_CATEGORIES: dict[int, str] = {
    -2000011: "OST_Walls",
    -2000014: "OST_Windows",
    -2000023: "OST_Doors",
    -2000032: "OST_Floors",
    -2000035: "OST_Roofs",
    -2000038: "OST_Ceilings",
    -2000100: "OST_Columns",
    -2000120: "OST_Stairs",
    -2000126: "OST_Railings",
    -2000151: "OST_GenericModel",
    -2000160: "OST_Rooms",
    -2000170: "OST_CurtainWallPanels",
    -2000171: "OST_CurtainWallMullions",
    -2001100: "OST_Furniture",
    -2001300: "OST_StructuralFoundation",
    -2001320: "OST_StructuralFraming",
    -2001330: "OST_StructuralColumns",
}

#: Cheap pre-filter for the two row kinds read from ``properties.jsonl``; the
#: file is dominated by object rows that are not looked at.
_ROW_KIND = re.compile(r'"row"\s*:\s*"(?:record|parameter)"')

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


def build_command(fmt: str, exe: Path, input_path: Path, out_dir: Path) -> list[str]:
    """The argv that converts ``input_path`` into ``out_dir`` for format ``fmt``."""
    prefix = command_prefix(fmt, exe)
    src = str(input_path.resolve())
    if fmt == "rvt":
        return [*prefix, src, "-o", str(out_dir), "--properties"]
    if fmt == "ifc":
        return [*prefix, src, "--output", str(out_dir)]
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
    logger.debug("DDC call: %s", cmd)
    proc = subprocess.run(  # noqa: S603 - argv list, no shell
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(work_dir),
        env=_clean_env(fmt),
        timeout=timeout,
        **kwargs,
    )
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
        for role, name in (("xlsx", "drawing.xlsx"), ("jsonl", "data.jsonl"), ("report", "result.json")):
            if (folder_path / name).is_file():
                run.outputs[role] = folder_path / name
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


def _unwrap(value: Any) -> Any:
    """Reduce an IFC value record (``{"NominalValue": {"ifc_type": .., "value": ..}}``) to a scalar."""
    if isinstance(value, dict):
        if "NominalValue" in value:
            return _unwrap(value["NominalValue"])
        if "value" in value and "ifc_type" in value:
            return _unwrap(value["value"])
        if len(value) == 1:
            return _unwrap(next(iter(value.values())))
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


def _cell_value(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
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


def flatten_ifc_workbook(drawing_xlsx: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Turn the IFC converter's ``drawing.xlsx`` into ``(header, rows)``, one row per occurrence."""
    import openpyxl

    wb = openpyxl.load_workbook(drawing_xlsx, read_only=True, data_only=True)
    try:
        objects: dict[str, dict[str, Any]] = {}
        for row in _sheet_rows(wb, "Objects"):
            objects[str(row.get("ID"))] = row

        parent: dict[str, str] = {}
        for row in _sheet_rows(wb, "SpatialLinks"):
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

        si_values: dict[tuple[str, str], Any] = {}
        for row in _sheet_rows(wb, "NormalizedMeasures"):
            si = row.get("si_value")
            if si is not None:
                si_values[(str(row.get("owner_step_id")), str(row.get("property_step_id")))] = si

        props: dict[str, dict[str, Any]] = {}
        columns: dict[str, None] = {}
        for sheet in ("Properties", "Quantities"):
            for row in _sheet_rows(wb, sheet):
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
    finally:
        wb.close()

    header = ["ID", "GlobalId", "Category", "Name", "Description", "Level", "Building", *columns]
    rows: list[dict[str, Any]] = []
    for step_id, obj in objects.items():
        if str(obj.get("IsType")).lower() == "true":
            continue
        row: dict[str, Any] = {
            "ID": int(step_id) if step_id.isdigit() else step_id,
            "GlobalId": obj.get("GlobalId"),
            "Category": obj.get("Category"),
            "Name": obj.get("Name"),
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


def flatten_rvt_output(glb_path: Path, properties_jsonl: Path | None) -> tuple[list[str], list[dict[str, Any]]]:
    """``(header, rows)`` for the elements of an RVT conversion that have a mesh."""
    ids = read_glb_element_ids(glb_path)
    categories: dict[int, int] = {}
    params: dict[int, dict[str, Any]] = {}
    columns: dict[str, None] = {}
    if properties_jsonl is not None and properties_jsonl.is_file():
        with properties_jsonl.open("r", encoding="utf-8") as fh:
            for line in fh:
                if _ROW_KIND.search(line) is None:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                try:
                    owner = int(rec.get("owner"))
                except (TypeError, ValueError):
                    continue
                if owner not in ids:
                    continue
                kind = rec.get("row")
                if kind == "record":
                    try:
                        categories[owner] = int(rec.get("category_id"))
                    except (TypeError, ValueError):
                        pass
                elif kind == "parameter":
                    label = rec.get("builtin_label") or rec.get("builtin_parameter")
                    if not label:
                        continue
                    value = _param_value(rec.get("fields") or {})
                    if value is None:
                        continue
                    if isinstance(value, float):
                        # Stored reals are in Revit internal units (feet and
                        # derived); keep them out of the quantity column names.
                        label = f"{label} [internal units]"
                    if label not in columns:
                        if len(columns) >= _MAX_PROPERTY_COLUMNS:
                            continue
                        columns[label] = None
                    params.setdefault(owner, {})[label] = value
    header = ["ID", "Category", "Name", *columns]
    rows: list[dict[str, Any]] = []
    for eid in sorted(ids):
        cat_id = categories.get(eid)
        cat = _REVIT_CATEGORIES.get(cat_id) if cat_id is not None else None
        if cat is None:
            cat = f"OST_Category{abs(cat_id)}" if cat_id is not None else "OST_Unknown"
        row: dict[str, Any] = {"ID": eid, "Category": cat, "Name": f"{cat[4:]} {eid}"}
        row.update(params.get(eid, {}))
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
