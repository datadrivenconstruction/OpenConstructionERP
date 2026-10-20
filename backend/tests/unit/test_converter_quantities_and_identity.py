# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the DDC 2026.10 converter output turns into: quantities, levels, types, categories.

The RVT converter stores no calculated quantities and only numeric category ids,
the IFC converter writes base quantities under ``Qto_*`` sets and no geometry,
and the DWG converter's own workbook is a decoder log. These tests pin how the
platform reads each of them.
"""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import Any

import pytest

from app.modules.bim_hub import ifc_processor
from app.modules.boq import cad_import, ddc_runner
from app.modules.boq.glb_quantities import glb_element_quantities, measure_triangles
from app.modules.boq.revit_categories import revit_category_label, revit_category_name

np = pytest.importorskip("numpy")


# ── Mesh quantities ─────────────────────────────────────────────────────────


def _box(sx: float, sy: float, sz: float) -> Any:
    """Closed box triangles ``(12, 3, 3)`` spanning ``[0, s]`` on each axis."""
    v = np.array([[x, y, z] for x in (0, sx) for y in (0, sy) for z in (0, sz)], dtype=float)
    faces = [
        (0, 1, 3, 2),
        (4, 6, 7, 5),
        (0, 4, 5, 1),
        (2, 3, 7, 6),
        (0, 2, 6, 4),
        (1, 5, 7, 3),
    ]
    tris = []
    for a, b, c, d in faces:
        tris += [(a, b, c), (a, c, d)]
    return v[np.array(tris)]


def test_a_closed_box_has_its_volume_and_surface() -> None:
    q = measure_triangles(_box(2.0, 2.0, 2.0))
    assert q["Volume"] == pytest.approx(8.0)
    assert q["Surface Area"] == pytest.approx(24.0)
    assert q["Height"] == pytest.approx(2.0)


def test_a_wall_reads_as_a_plate_with_one_face_area() -> None:
    # 5 m long (x), 3 m high (y, glTF up), 0.2 m thick (z).
    q = measure_triangles(_box(5.0, 3.0, 0.2))
    assert q["Area"] == pytest.approx(15.0)
    assert q["Thickness"] == pytest.approx(0.2)
    assert q["Length"] == pytest.approx(5.0)
    assert q["Height"] == pytest.approx(3.0)
    assert q["Volume"] == pytest.approx(3.0)


def test_a_beam_reads_as_linear() -> None:
    q = measure_triangles(_box(6.0, 0.4, 0.3))
    assert q["Length"] == pytest.approx(6.0)
    assert "Area" not in q


def test_an_open_mesh_gets_no_volume() -> None:
    q = measure_triangles(_box(2.0, 2.0, 2.0)[:-2])  # one face missing
    assert "Volume" not in q
    assert q["Surface Area"] == pytest.approx(20.0)


def _glb_with_box(scale: float) -> bytes:
    tris = _box(1.0, 1.0, 1.0).reshape(-1, 3).astype("<f4")
    binary = tris.tobytes()
    doc = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {
                "name": "element_77",
                "extras": {"element_id": 77},
                "mesh": 0,
                "matrix": [scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1],
            }
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(tris), "type": "VEC3"}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}],
        "buffers": [{"byteLength": len(binary)}],
    }
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    binary += b"\x00" * (-len(binary) % 4)
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


def test_the_node_matrix_scales_feet_to_metres(tmp_path: Path) -> None:
    glb = tmp_path / "native_graph.glb"
    glb.write_bytes(_glb_with_box(0.3048))  # a 1 ft cube, as the RVT converter writes it
    q = glb_element_quantities(glb)[77]
    assert q["Volume"] == pytest.approx(0.3048**3, rel=1e-3)
    assert q["Height"] == pytest.approx(0.3048, rel=1e-3)


# ── RVT: categories, levels, types from the converter IFC ─────────────────────────────


def test_revit_category_ids_get_their_builtin_and_display_names() -> None:
    assert revit_category_name(-2001320) == "OST_StructuralFraming"
    assert revit_category_label(-2001320) == "Structural Framing"
    assert revit_category_name(-2008044) == "OST_PipeCurves"
    assert revit_category_label(-2999999) == "Category -2999999"


def _rvt_ifc_output(folder: Path, qto: dict[str, Any] | None = None) -> tuple[Path, Path]:
    from tests.unit.test_ddc_runner import native_graph_ifc

    folder.mkdir(parents=True)
    glb = folder / "native_graph.glb"
    glb.write_bytes(_glb_with_box(1.0))
    pipe = {
        "id": 77,
        "identity": {
            "CategoryId": -2008044,
            "CategoryName": "Pipes",
            "TypeName": "Standard 50 mm",
            "LevelName": "Level 1",
        },
        "qto": qto or {},
    }
    ifc = folder / "native_graph.ifc"
    ifc.write_text(native_graph_ifc([pipe]), encoding="ascii")
    return glb, ifc


def test_rvt_rows_carry_level_type_category_and_measured_quantities(tmp_path: Path) -> None:
    glb, ifc = _rvt_ifc_output(tmp_path / "m.converted")

    header, rows = ddc_runner.flatten_rvt_output(glb, ifc)

    (pipe,) = rows
    assert pipe["Category"] == "OST_PipeCurves"
    assert pipe["Category Name"] == "Pipes"
    assert pipe["Level"] == "Level 1"
    assert pipe["Type Name"] == "Standard 50 mm"
    assert pipe["Name"] == "Standard 50 mm 77"
    # No quantity set in the IFC: measured on the mesh.
    assert pipe["Volume"] == pytest.approx(1.0)
    assert {"Volume", "Surface Area", "Height"} <= set(header)


def test_revit_base_quantities_win_over_the_mesh(tmp_path: Path) -> None:
    qto = {
        "Qto_PipeSegmentBaseQuantities": {"Length": ("LENGTH", 3.25)},
        "RVT_TessellationQuantities": {"Volume": ("VOLUME", 0.9), "SurfaceArea": ("AREA", 5.5)},
    }
    glb, ifc = _rvt_ifc_output(tmp_path / "m.converted", qto)

    _, (pipe,) = ddc_runner.flatten_rvt_output(glb, ifc)

    assert pipe["Length"] == 3.25
    assert pipe["Volume"] == 0.9
    assert pipe["Surface Area"] == 5.5
    assert pipe["[Qto_PipeSegmentBaseQuantities] Length"] == 3.25


def test_step_strings_are_decoded() -> None:
    from app.modules.boq.rvt_ifc_reader import _decode_step_string

    assert _decode_step_string("m\\X2\\00B2\\X0\\") == "m²"
    assert _decode_step_string("it''s") == "it's"
    assert _decode_step_string("\\X2\\041F0435\\X0\\") == "Пе"


def test_rvt_rows_show_revit_category_names_in_the_model(tmp_path: Path) -> None:
    """The BIM hub's element type is Revit's display name, not a split OST_ token."""
    rows = [
        {"id": 77, "category": "OST_Cornices", "category name": "Wall Sweeps", "name": "Sweep 77", "volume": 0.2},
        {"id": 78, "category": "OST_Walls", "name": "Wall 78"},
    ]
    result = ifc_processor._excel_elements_to_bim_result(rows, tmp_path)
    types = {e["name"]: e["element_type"] for e in result["elements"]}
    assert types == {"Sweep 77": "Wall Sweeps", "Wall 78": "Walls"}


# ── IFC: base quantity sets, placeholder geometry ───────────────────────────


def test_ifc_base_quantity_sets_fill_the_quantities() -> None:
    row = {
        "[qto_wallbasequantities] netsidearea": 12.5,
        "[qto_wallbasequantities] grosssidearea": 14.0,
        "[qto_wallbasequantities] netvolume": 2.5,
        "[qto_wallbasequantities] length": 5.0,
        "[pset_wallcommon] isexternal": True,
    }
    q = ifc_processor._ifc_quantity_set_values(row)
    assert q == {"Area": 12.5, "Volume": 2.5, "Length": 5.0}


def test_a_converter_run_is_not_reported_as_an_absent_converter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "Tiny.ifc"
    src.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    fake_exe = tmp_path / "ifc_windows" / "runtime" / "python.exe"

    def _fake_run(fmt: str, exe: Path, input_path: Path, work_dir: Path, *, timeout: float = 600) -> Any:
        from tests.unit.test_ddc_runner import _write_ifc_workbook

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

    assert result["converter_used"] is True


# ── CAD -> BOQ columns ──────────────────────────────────────────────────────


def test_ids_and_internal_unit_reals_are_not_offered_as_quantities() -> None:
    elements = [
        {"ID": 100 + i, "Category": "OST_Walls", "Volume": 1.0 + i, "Length [internal units]": 10.0 + i}
        for i in range(5)
    ]
    cols = cad_import.get_available_columns(elements, "rvt")
    assert "ID" not in cols["quantity"]
    assert "Length [internal units]" not in cols["quantity"]
    assert cols["suggested_quantities"] == ["Volume"] or "Volume" in cols["quantity"]


def test_flags_and_internal_unit_reals_are_neither_summed_nor_grouping_keys() -> None:
    elements = [
        {
            "Category": "OST_Walls",
            "Volume": 1.0 + i,
            "[Pset_WallCommon] IsExternal": i % 2 == 0,
            "[Revit_Parameters] Offset [internal units]": 0.5 * i,
        }
        for i in range(5)
    ]
    cols = cad_import.get_available_columns(elements, "rvt")
    assert "[Pset_WallCommon] IsExternal" in cols["grouping"]
    assert "[Pset_WallCommon] IsExternal" not in cols["quantity"]
    assert "[Revit_Parameters] Offset [internal units]" not in cols["grouping"] + cols["quantity"]


def test_numeric_layer_names_stay_a_grouping_column() -> None:
    elements = [{"Category": str(i % 3), "Type Name": "LINE", "Length": 1.0 + i, "Count": 1} for i in range(6)]
    cols = cad_import.get_available_columns(elements, "dwg")
    assert "Category" in cols["grouping"]
    assert "Category" not in cols["quantity"]


def test_a_dwg_is_read_through_the_dxf_its_converter_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ezdxf = pytest.importorskip("ezdxf")
    out = tmp_path / "out"
    folder = out / "dwg_out"
    folder.mkdir(parents=True)
    doc = ezdxf.new(units=6)  # metres
    doc.layers.add("A-WALL")
    doc.modelspace().add_line((0, 0), (4, 0), dxfattribs={"layer": "A-WALL"})
    dxf = folder / "plan.dxf"
    doc.saveas(dxf)
    log_xlsx = folder / "plan.xlsx"
    log_xlsx.write_bytes(b"not used")
    src = tmp_path / "plan.dwg"
    src.write_bytes(b"AC1032")

    async def _ensure(_ext: str) -> Path:
        return tmp_path / "dwg2excel.exe"

    def _fake_run(fmt: str, exe: Path, input_path: Path, work_dir: Path, *, timeout: float = 600) -> Any:
        return ddc_runner.ConverterRun(
            fmt=fmt,
            command=[],
            returncode=0,
            status="CONVERTED",
            folder=folder,
            outputs={"xlsx": log_xlsx, "dxf": dxf},
        )

    monkeypatch.setattr(cad_import, "ensure_converter_async", _ensure)
    monkeypatch.setattr(ddc_runner, "run_converter", _fake_run)

    table = asyncio.run(cad_import.convert_cad_to_excel(src, out, "dwg"))

    assert table is not None and table != log_xlsx
    elements = cad_import.parse_cad_excel(table)
    assert any(str(e.get("category") or e.get("Category")) == "A-WALL" for e in elements)


# ── Quantity rules on converter imports ─────────────────────────────────────


def test_a_quantity_rule_reads_the_keys_a_converter_import_stores() -> None:
    from decimal import Decimal
    from types import SimpleNamespace

    from app.modules.bim_hub.service import BIMHubService

    wall = SimpleNamespace(quantities={"Area": 15.0, "Volume": 3.0, "Length": 5.0}, properties={})
    assert BIMHubService._extract_quantity(wall, "area_m2") == Decimal("15.0")
    assert BIMHubService._extract_quantity(wall, "volume_m3") == Decimal("3.0")
    assert BIMHubService._extract_quantity(wall, "weight_kg") is None


@pytest.mark.parametrize(
    ("element_type", "discipline"),
    [
        ("Structural Framing", "structural"),
        ("Structural Foundations", "structural"),
        ("Floors", "structural"),
        ("Curtain Wall Mullions", "architecture"),
        ("Furniture", "architecture"),
        ("Pipe Fittings", "mep"),
        ("Lighting Fixtures", "mep"),
        ("Walls", "structural"),
        ("IfcDoor", "architecture"),
    ],
)
def test_revit_category_names_get_a_discipline(element_type: str, discipline: str) -> None:
    assert ifc_processor._classify_discipline(element_type) == discipline


def test_categories_outside_the_curated_list_still_get_their_builtin_name() -> None:
    assert revit_category_name(-2005301) == "OST_BoundaryConditions"
    assert revit_category_label(-2005301) == "Boundary Conditions"


def test_an_rvt_with_no_3d_elements_is_told_apart_from_a_failed_conversion(tmp_path: Path) -> None:
    from types import SimpleNamespace

    (tmp_path / "summary.json").write_text(
        json.dumps({"totals": {"active_elements": 5047, "mesh_elements": 0}}), encoding="utf-8"
    )
    assert ifc_processor._converter_saw_no_meshes(SimpleNamespace(folder=tmp_path)) is True
    (tmp_path / "summary.json").write_text(
        json.dumps({"totals": {"active_elements": 5047, "mesh_elements": 12}}), encoding="utf-8"
    )
    assert ifc_processor._converter_saw_no_meshes(SimpleNamespace(folder=tmp_path)) is False
    assert ifc_processor._converter_saw_no_meshes(SimpleNamespace(folder=tmp_path / "missing")) is False


def _failing_dwg_run(stdout: str, seen: dict[str, float]) -> Any:
    def _run(fmt: str, exe: Path, input_path: Path, work_dir: Path, *, timeout: float = 600) -> Any:
        seen["timeout"] = timeout
        return ddc_runner.ConverterRun(fmt=fmt, command=[], returncode=1, stdout=stdout, status="FAILED")

    return _run


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ({"code": "DWG_DAMAGED", "message_en": "Bad file.", "detail": "ContainerError: Cancelled"}, "convert_timeout"),
        ({"code": "DWG_DAMAGED", "message_en": "The DWG file is damaged.", "detail": "x"}, "DWG_DAMAGED - The DWG"),
    ],
)
def test_a_failed_takeoff_conversion_names_the_converter_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: dict[str, str], expected: str
) -> None:
    """A timeout or a refusal must not read as "ensure the converter is installed"."""
    seen: dict[str, float] = {}

    async def _ensure(_ext: str) -> Path:
        return tmp_path / "dwg2excel.exe"

    monkeypatch.setattr(cad_import, "ensure_converter_async", _ensure)
    monkeypatch.setattr(ddc_runner, "run_converter", _failing_dwg_run(json.dumps({"error": error}), seen))
    monkeypatch.delenv("OE_DWG_CONVERT_TIMEOUT_S", raising=False)
    src = tmp_path / "plan.dwg"
    src.write_bytes(b"AC1032")

    async def _convert_then_explain() -> tuple[Any, str]:
        table = await cad_import.convert_cad_to_excel(src, tmp_path / "out", "dwg")
        return table, cad_import.conversion_failed_detail("dwg")

    table, detail = asyncio.run(_convert_then_explain())

    assert table is None
    assert expected in detail
    assert "installed" not in detail
    assert seen["timeout"] == 900
