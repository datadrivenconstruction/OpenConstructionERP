"""The DDC 2026.10 converters' output, read the way the platform reads it.

The release replaced the 18.x ``*Exporter.exe`` programs. None of the new
command lines writes the one-row-per-element workbook plus COLLADA file the BIM
pipeline was built around, so ``app.modules.boq.ddc_runner`` flattens what they
do write. These tests use synthetic output with the same shape as the real
files (taken from real runs of the released converters on small open models);
no converter binary is needed.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from app.core.converter_source import PACKAGES
from app.modules.bim_hub import ifc_processor
from app.modules.boq import cad_import, ddc_runner

# ── IFC: drawing.xlsx -> flat table ───────────────────────────────────────


def _write_ifc_workbook(path: Path) -> None:
    """The sheets the IFC converter writes, with the columns it writes."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def sheet(name: str, header: list[str], rows: list[list[Any]]) -> None:
        ws = wb.create_sheet(name)
        ws.append(header)
        for r in rows:
            ws.append(r)

    sheet(
        "Objects",
        ["ID", "GlobalId", "StableKey", "Category", "Name", "Description", "IsType", "Attributes"],
        [
            ["11", "P", "k#11", "IfcProject", "Tiny", None, "False", "{}"],
            ["14", "B", "k#14", "IfcBuilding", "Bldg", None, "False", "{}"],
            ["15", "S", "k#15", "IfcBuildingStorey", "L1", None, "False", "{}"],
            ["16", "W1", "k#16", "IfcWallStandardCase", "Wall A", None, "False", "{}"],
            ["17", "W2", "k#17", "IfcWallStandardCase", "Wall B", None, "False", "{}"],
            ["18", "T1", "k#18", "IfcWallType", "Type X", None, "True", "{}"],
        ],
    )
    sheet(
        "SpatialLinks",
        ["child_step_id", "parent_step_id", "relation_step_id", "kind"],
        [
            ["14", "11", "1", "IfcRelAggregates"],
            ["15", "14", "2", "IfcRelAggregates"],
            ["16", "15", "3", "IfcRelContainedInSpatialStructure"],
            ["17", "15", "3", "IfcRelContainedInSpatialStructure"],
        ],
    )
    prop_header = ["owner_step_id", "scope", "set_name", "property_step_id", "property_name", "value"]
    sheet(
        "Properties",
        prop_header,
        [
            [
                "16",
                "OCCURRENCE",
                "Pset_WallCommon",
                "22",
                "FireRating",
                '{"NominalValue":{"ifc_type":"IfcLabel","value":"2HR"}}',
            ],
            [
                "17",
                "OCCURRENCE",
                "Pset_WallCommon",
                "22",
                "FireRating",
                '{"NominalValue":{"ifc_type":"IfcLabel","value":"1HR"}}',
            ],
            [
                "18",
                "TYPE",
                "Pset_WallCommon",
                "23",
                "FireRating",
                '{"NominalValue":{"ifc_type":"IfcLabel","value":"TYPEVALUE"}}',
            ],
        ],
    )
    sheet(
        "Quantities",
        prop_header,
        [
            ["16", "OCCURRENCE", "BaseQuantities", "25", "NetSideArea", '{"AreaValue":12.5}'],
            ["17", "OCCURRENCE", "BaseQuantities", "26", "Length", '{"LengthValue":3000.0}'],
        ],
    )
    sheet(
        "NormalizedMeasures",
        ["owner_step_id", "scope", "property_step_id", "si_value", "status"],
        [["17", "OCCURRENCE", "26", 3.0, "RESOLVED"]],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def test_ifc_workbook_is_flattened_to_one_row_per_occurrence(tmp_path: Path) -> None:
    xlsx = tmp_path / "drawing.xlsx"
    _write_ifc_workbook(xlsx)

    header, rows = ddc_runner.flatten_ifc_workbook(xlsx)

    by_id = {r["ID"]: r for r in rows}
    assert 18 not in by_id, "type objects are not occurrences"
    wall_a, wall_b = by_id[16], by_id[17]
    assert wall_a["Category"] == "IfcWallStandardCase"
    assert wall_a["Level"] == "L1" and wall_a["Building"] == "Bldg"
    assert wall_a["[Pset_WallCommon] FireRating"] == "2HR"
    assert wall_b["[Pset_WallCommon] FireRating"] == "1HR"
    assert wall_a["[BaseQuantities] NetSideArea"] == 12.5
    # The unit-normalised value wins over the raw model-unit value.
    assert wall_b["[BaseQuantities] Length"] == 3.0
    assert "[Pset_WallCommon] FireRating" in header


def test_flattened_ifc_table_is_read_by_the_platform_parser(tmp_path: Path) -> None:
    xlsx = tmp_path / "drawing.xlsx"
    _write_ifc_workbook(xlsx)
    run = ddc_runner.ConverterRun(fmt="ifc", command=[], returncode=0, outputs={"xlsx": xlsx})
    flat = ddc_runner.write_flat_workbook(run, tmp_path / "model.xlsx")

    rows = cad_import.parse_cad_excel(flat)
    walls = [r for r in rows if r.get("category") == "IfcWallStandardCase"]
    assert len(walls) == 2
    assert walls[0]["[basequantities] netsidearea"] == 12.5

    result = ifc_processor._excel_elements_to_bim_result(rows, tmp_path / "work", geometry_supported=True)
    assert result["element_count"] == 2
    assert result["storeys"] == ["L1"]
    # No geometry from the IFC converter: boxes, and they say so.
    assert result["geometry_quality"] == "placeholder"


# ── RVT: GLB + properties.jsonl -> flat table ─────────────────────────────


def _glb(nodes: list[dict[str, Any]]) -> bytes:
    doc = {"asset": {"version": "2.0"}, "nodes": nodes, "scenes": [{"nodes": list(range(len(nodes)))}], "scene": 0}
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    binary = b"\x00\x00\x00\x00"
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (
        b"glTF"
        + struct.pack("<II", 2, total)
        + struct.pack("<I", len(js))
        + b"JSON"
        + js
        + struct.pack("<I", len(binary))
        + b"BIN\x00"
        + binary
    )


def _rvt_output(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True)
    glb = folder / "native_graph.glb"
    glb.write_bytes(
        _glb(
            [
                {"name": "element_2645", "extras": {"element_id": 2645}},
                {"name": "element_2870", "extras": {"element_id": 2870}},
            ]
        )
    )

    def param(owner: int, label: str, storage: str, value_key: str, value: Any) -> dict[str, Any]:
        return {
            "row": "parameter",
            "owner": str(owner),
            "builtin_label": label,
            "storage": storage,
            "fields": {"record": {f"{storage}.m_value": {value_key: value}}},
        }

    rows: list[dict[str, Any]] = [
        {"row": "document", "schema": "native_stored_properties/2"},
        {"row": "record", "owner": "2645", "category_id": "-2000011"},
        {"row": "record", "owner": "2870", "category_id": "-2000032"},
        {"row": "record", "owner": "9999", "category_id": "-2000011"},  # no mesh: not a row
        param(2645, "Unconnected Height", "ParamValueDouble", "number", 11.5),
        param(2645, "Structural", "ParamValueInt", "integer", "1"),
        param(2645, "Cross-Section Rotation", "ParamValueDouble", "number", 0.5),
        param(2870, "Comments", "ParamValueAString", "text", "slab"),
        param(9999, "Comments", "ParamValueAString", "text", "ignored"),
    ]
    props = folder / "properties.jsonl"
    props.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n", encoding="utf-8")
    return glb, props


def test_rvt_elements_are_the_ones_with_a_mesh(tmp_path: Path) -> None:
    glb, props = _rvt_output(tmp_path / "m.converted")

    header, rows = ddc_runner.flatten_rvt_output(glb, props)

    assert [r["ID"] for r in rows] == [2645, 2870]
    wall, floor = rows
    assert wall["Category"] == "OST_Walls"
    assert floor["Category"] == "OST_Floors"
    assert floor["Comments"] == "slab"
    assert wall["Structural"] == 1
    # Stored reals are in Revit's internal units (feet): a plain length is converted,
    # anything the name does not pin down keeps the marker and is not offered as a quantity.
    assert wall["Unconnected Height"] == pytest.approx(11.5 * 0.3048)
    assert wall["Cross-Section Rotation [internal units]"] == 0.5
    assert "Cross-Section Rotation" not in header


def test_an_unknown_revit_category_is_labelled_not_guessed(tmp_path: Path) -> None:
    glb, props = _rvt_output(tmp_path / "m.converted")
    props.write_text(json.dumps({"row": "record", "owner": "2645", "category_id": "-2999999"}) + "\n", encoding="utf-8")
    _, rows = ddc_runner.flatten_rvt_output(glb, props)
    assert rows[0]["Category"] == "OST_Category2999999"


def test_glb_nodes_are_renamed_to_the_element_id(tmp_path: Path) -> None:
    glb, _ = _rvt_output(tmp_path / "m.converted")

    assert ddc_runner.normalize_glb_node_names(glb) == 2
    assert ddc_runner.normalize_glb_node_names(glb) == 0, "idempotent"

    doc = ddc_runner._read_glb_json(glb)
    assert [n["name"] for n in doc["nodes"]] == ["2645", "2870"]
    # Still a well-formed GLB: the binary chunk follows the (4-aligned) JSON chunk.
    data = glb.read_bytes()
    assert struct.unpack("<I", data[8:12])[0] == len(data)
    json_len = struct.unpack("<I", data[12:16])[0]
    assert json_len % 4 == 0
    assert data[20 + json_len + 4 : 20 + json_len + 8] == b"BIN\x00"


def test_rvt_glb_is_used_as_the_model_geometry(tmp_path: Path) -> None:
    glb, props = _rvt_output(tmp_path / "m.converted")
    ddc_runner.normalize_glb_node_names(glb)
    run = ddc_runner.ConverterRun(fmt="rvt", command=[], returncode=0, outputs={"glb": glb, "properties": props})
    flat = ddc_runner.write_flat_workbook(run, tmp_path / "model.xlsx")
    raw = cad_import.parse_cad_excel(flat)

    result = ifc_processor._excel_elements_to_bim_result(raw, tmp_path / "work", real_glb_path=glb)

    assert result["element_count"] == 2
    assert result["geometry_quality"] == "real"
    assert result["has_geometry"] is True
    assert result["glb_path"] == str(glb)
    assert result["geometry_path"] is None
    assert {e["mesh_ref"] for e in result["elements"]} == {"2645", "2870"}


# ── Running a converter ───────────────────────────────────────────────────


def test_each_format_gets_its_own_command_line(tmp_path: Path) -> None:
    src = tmp_path / "in" / "Model.x"
    out = tmp_path / "out"
    rvt = ddc_runner.build_command("rvt", tmp_path / "rvt_windows" / "cli" / "RVTconverter.exe", src, out)
    assert rvt[1:] == [str(src.resolve()), "-o", str(out), "--properties"]

    dwg = ddc_runner.build_command("dwg", tmp_path / "dwg_windows" / "cli" / "dwg2excel.exe", src, out)
    assert dwg[1:] == [str(src.resolve()), "-o", str(out), "--json", "--no-svg"]

    py = tmp_path / "ifc_windows" / "runtime" / "python.exe"
    ifc = ddc_runner.build_command("ifc", py, src, out)
    assert ifc[0] == str(py)
    assert Path(ifc[1]) == tmp_path / "ifc_windows" / "sources" / "ifc-excel" / "converter.py"
    assert ifc[2:] == [str(src.resolve()), "--output", str(out), "--glb"]
    plain = ddc_runner.build_command("ifc", py, src, out, glb=False)
    assert plain[2:] == [str(src.resolve()), "--output", str(out)]

    with pytest.raises(ValueError):
        ddc_runner.build_command("dgn", py, src, out)


def test_outputs_are_found_through_the_json_line_the_converter_prints(tmp_path: Path) -> None:
    out_dir = tmp_path / "ifc_out"
    folder = out_dir / "Model-abc123"
    _write_ifc_workbook(folder / "drawing.xlsx")
    (folder / "data.jsonl").write_text("{}\n", encoding="utf-8")
    run = ddc_runner.ConverterRun(
        fmt="ifc",
        command=[],
        returncode=0,
        stdout="noise\n" + json.dumps({"status": "CONVERTED_WITH_LIMITS", "folder": str(folder)}) + "\n",
    )
    ddc_runner._collect_outputs(run, out_dir, "Model")

    assert run.ok
    assert run.status == "CONVERTED_WITH_LIMITS"
    assert run.folder == folder


def test_the_2_0_workbook_named_after_the_model_is_found_through_data(tmp_path: Path) -> None:
    """IFC to Excel 2.0.0 writes ``<stem>.xlsx`` (not ``drawing.xlsx``) and reports it as ``data``."""
    out_dir = tmp_path / "ifc_out"
    folder = out_dir / "01_AC20-FZK-Haus"
    xlsx = folder / "01_AC20-FZK-Haus.xlsx"
    _write_ifc_workbook(xlsx)
    (folder / "result.json").write_text("{}", encoding="utf-8")
    line = {"status": "CONVERTED_WITH_LIMITS", "folder": str(folder), "data": str(xlsx)}
    run = ddc_runner.ConverterRun(fmt="ifc", command=[], returncode=0, stdout=json.dumps(line))
    ddc_runner._collect_outputs(run, out_dir, "01_AC20-FZK-Haus")

    assert run.ok
    assert run.outputs["xlsx"] == xlsx
    assert run.outputs["report"] == folder / "result.json"

    # Without the ``data`` key the stem-named workbook is still found.
    run2 = ddc_runner.ConverterRun(fmt="ifc", command=[], returncode=0, stdout=json.dumps({"folder": str(folder)}))
    ddc_runner._collect_outputs(run2, out_dir, "01_AC20-FZK-Haus")
    assert run2.outputs["xlsx"] == xlsx


def test_a_failed_conversion_is_not_ok_even_if_a_file_exists(tmp_path: Path) -> None:
    out_dir = tmp_path / "ifc_out"
    folder = out_dir / "Model-abc123"
    _write_ifc_workbook(folder / "drawing.xlsx")
    run = ddc_runner.ConverterRun(
        fmt="ifc",
        command=[],
        returncode=1,
        stdout=json.dumps({"status": "FAILED", "folder": str(folder)}),
    )
    ddc_runner._collect_outputs(run, out_dir, "Model")
    assert not run.ok


def test_dwg_outputs_are_the_workbook_and_the_dxf(tmp_path: Path) -> None:
    out_dir = tmp_path / "dwg_out"
    folder = out_dir / "Plan"
    folder.mkdir(parents=True)
    (folder / "Plan.xlsx").write_bytes(b"x")
    (folder / "Plan.dxf").write_bytes(b"0\nEOF\n")
    run = ddc_runner.ConverterRun(
        fmt="dwg",
        command=[],
        returncode=0,
        stdout=json.dumps({"status": "CONVERTED", "folder": str(folder)}),
    )
    ddc_runner._collect_outputs(run, out_dir, "Plan")
    assert run.ok
    assert run.outputs["dxf"] == folder / "Plan.dxf"


# ── The processor end to end, with the converter replaced ─────────────────


def test_process_ifc_file_uses_the_new_converter_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``process_ifc_file`` -> ensure_converter -> run_converter -> flat table -> elements."""
    src = tmp_path / "Tiny.ifc"
    src.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    fake_exe = tmp_path / "ifc_windows" / "runtime" / "python.exe"

    def _fake_run(fmt: str, exe: Path, input_path: Path, work_dir: Path, *, timeout: float = 600) -> Any:
        folder = work_dir / "ifc_out" / "Tiny-1"
        _write_ifc_workbook(folder / "drawing.xlsx")
        return ddc_runner.ConverterRun(
            fmt=fmt,
            command=[],
            returncode=0,
            status="CONVERTED",
            folder=folder,
            outputs={"xlsx": folder / "drawing.xlsx"},
        )

    monkeypatch.setattr(cad_import, "ensure_converter", lambda _ext: fake_exe)
    monkeypatch.setattr(ddc_runner, "run_converter", _fake_run)

    result = ifc_processor.process_ifc_file(src, tmp_path / "work")

    assert result["element_count"] == 2
    assert {e["name"] for e in result["elements"]} == {"Wall A", "Wall B"}
    assert result["converter_status"] == "CONVERTED"


def test_a_converter_that_wrote_nothing_falls_through_to_the_text_parser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "Tiny.ifc"
    src.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    fake_exe = tmp_path / "ifc_windows" / "runtime" / "python.exe"

    def _fake_run(fmt: str, exe: Path, input_path: Path, work_dir: Path, *, timeout: float = 600) -> Any:
        return ddc_runner.ConverterRun(fmt=fmt, command=[], returncode=1, stderr="boom")

    monkeypatch.setattr(cad_import, "ensure_converter", lambda _ext: fake_exe)
    monkeypatch.setattr(ddc_runner, "run_converter", _fake_run)

    result = ifc_processor.process_ifc_file(src, tmp_path / "work")

    assert result["element_count"] == 0  # the empty IFC has nothing for the text parser either


def test_the_packages_the_runner_speaks_are_the_ones_the_installer_ships() -> None:
    for fmt in ("rvt", "ifc", "dwg"):
        assert ddc_runner.tool_label(fmt).startswith(PACKAGES[fmt].name)


# ── IFC geometry: the converter's GLB instead of placeholder boxes ────────


def _ifc_glb(path: Path, ids: list[int]) -> Path:
    """A Y-up GLB as the IFC converter writes it: one node per element, ids in extras."""
    nodes = [
        {"name": f"G{i}", "mesh": 0, "translation": [1.0, 2.0, -3.0], "extras": {"element_id": i, "global_id": f"G{i}"}}
        for i in ids
    ]
    doc = {
        "asset": {"version": "2.0"},
        "nodes": nodes,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "scene": 0,
        "extras": {"units": "m", "up_axis": "Y"},
    }
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    binary = b"\x00\x00\x00\x00"
    total = 12 + 8 + len(js) + 8 + len(binary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"glTF"
        + struct.pack("<II", 2, total)
        + struct.pack("<I", len(js))
        + b"JSON"
        + js
        + struct.pack("<I", len(binary))
        + b"BIN\x00"
        + binary
    )
    return path


def test_ifc_glb_and_workbook_are_found_through_the_json_line(tmp_path: Path) -> None:
    out_dir = tmp_path / "ifc_out"
    folder = out_dir / "Model"
    _write_ifc_workbook(folder / "Model.xlsx")
    glb = _ifc_glb(folder / "Model.glb", [16, 17])
    line = {
        "status": "CONVERTED_WITH_LIMITS",
        "folder": str(folder),
        "data": str(folder / "Model.xlsx"),
        "glb": str(glb),
    }
    run = ddc_runner.ConverterRun(fmt="ifc", command=[], returncode=0, stdout=json.dumps(line))
    ddc_runner._collect_outputs(run, out_dir, "Model")

    assert run.ok
    assert run.outputs["xlsx"] == folder / "Model.xlsx"
    assert run.outputs["glb"] == glb


def test_y_up_glb_is_wrapped_for_the_z_up_viewer(tmp_path: Path) -> None:
    glb = _ifc_glb(tmp_path / "m.glb", [16, 17])

    assert ddc_runner.orient_glb_for_viewer(glb) is True
    assert ddc_runner.orient_glb_for_viewer(glb) is False, "idempotent"

    doc = ddc_runner._read_glb_json(glb)
    root = doc["nodes"][doc["scenes"][0]["nodes"][0]]
    assert len(doc["scenes"][0]["nodes"]) == 1
    assert root["children"] == [0, 1]
    assert root["rotation"] == pytest.approx([0.70710678, 0.0, 0.0, 0.70710678])
    assert doc["extras"]["up_axis"] == "Z"
    data = glb.read_bytes()
    assert struct.unpack("<I", data[8:12])[0] == len(data)
    json_len = struct.unpack("<I", data[12:16])[0]
    assert data[20 + json_len + 4 : 20 + json_len + 8] == b"BIN\x00"


def test_rvt_glb_is_not_reoriented(tmp_path: Path) -> None:
    glb, _ = _rvt_output(tmp_path / "m.converted")
    before = glb.read_bytes()
    assert ddc_runner.orient_glb_for_viewer(glb) is False
    assert glb.read_bytes() == before


def test_an_older_ifc_converter_without_the_glb_option_is_run_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    class _Proc:
        def __init__(self, returncode: int, stderr: bytes) -> None:
            self.returncode, self.stdout, self.stderr = returncode, b"", stderr

    def _fake(argv: list[str], **_kw: Any) -> _Proc:
        calls.append(list(argv))
        if "--glb" in argv:
            return _Proc(2, b"converter.py: error: unrecognized arguments: --glb")
        return _Proc(0, b"")

    monkeypatch.setattr(ddc_runner.subprocess, "run", _fake)
    py = tmp_path / "ifc_windows" / "runtime" / "python.exe"
    run = ddc_runner.run_converter("ifc", py, tmp_path / "M.ifc", tmp_path / "work")

    assert [("--glb" in c) for c in calls] == [True, False]
    assert run.returncode == 0
    assert "--glb" not in run.command


def test_process_ifc_file_shows_the_converter_geometry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "Tiny.ifc"
    src.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    fake_exe = tmp_path / "ifc_windows" / "runtime" / "python.exe"

    def _fake_run(fmt: str, exe: Path, input_path: Path, work_dir: Path, *, timeout: float = 600) -> Any:
        folder = work_dir / "ifc_out" / "Tiny"
        _write_ifc_workbook(folder / "Tiny.xlsx")
        glb = _ifc_glb(folder / "Tiny.glb", [16, 17])
        return ddc_runner.ConverterRun(
            fmt=fmt,
            command=[],
            returncode=0,
            status="CONVERTED_WITH_LIMITS",
            folder=folder,
            outputs={"xlsx": folder / "Tiny.xlsx", "glb": glb},
        )

    monkeypatch.setattr(cad_import, "ensure_converter", lambda _ext: fake_exe)
    monkeypatch.setattr(ddc_runner, "run_converter", _fake_run)

    result = ifc_processor.process_ifc_file(src, tmp_path / "work")

    assert result["element_count"] == 2
    assert result["geometry_quality"] == "real"
    assert result["glb_path"] and result["glb_path"].endswith("Tiny.glb")
    assert not any(e.get("is_placeholder") for e in result["elements"])
    assert {e["mesh_ref"] for e in result["elements"]} == {"16", "17"}
    doc = ddc_runner._read_glb_json(Path(result["glb_path"]))
    assert [n["name"] for n in doc["nodes"][:2]] == ["16", "17"]  # node name == mesh_ref
    assert doc["extras"]["up_axis"] == "Z"
