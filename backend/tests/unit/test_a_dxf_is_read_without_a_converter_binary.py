"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A DXF must open on a host that has no converter binary for its CPU.

The DWG, RVT and DGN converters are proprietary x86-64 binaries. ``.dxf`` was
routed to the DWG one through a format alias, so an ARM host could not open a
DXF even though the platform already reads DXF in pure Python for the takeoff
module. These tests pin the native path and, more importantly, pin the reason
the alias made it invisible: the caller resolves the alias BEFORE calling the
conversion, so the extension argument says "dwg" for a file that is a DXF.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf", reason="ezdxf is a base dependency; skip only where it is absent")

from app.modules.boq.cad_import import convert_cad_to_excel, parse_cad_excel  # noqa: E402
from app.modules.boq.dxf_native import convert_dxf_to_excel, is_natively_readable  # noqa: E402

# A rectangle 5000 x 3000 drawing units, one straight run of 4000, and a circle
# of radius 1000. In millimetres that is a 16 m perimeter enclosing 15 m2, a 4 m
# line, and a circle of 2*pi m circumference enclosing pi m2.
_RECT = [(0, 0), (5000, 0), (5000, 3000), (0, 3000)]
_LINE = ((0, 0), (4000, 0))
_CIRCLE_RADIUS = 1000


def _write_drawing(path: Path, insunits: int | None) -> None:
    """Author a small DXF. ``insunits`` None leaves the header unit unset."""
    doc = ezdxf.new()
    if insunits is not None:
        doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    msp.add_lwpolyline(_RECT, close=True, dxfattribs={"layer": "SLABS"})
    msp.add_line(_LINE[0], _LINE[1], dxfattribs={"layer": "WALLS"})
    msp.add_circle((10000, 10000), _CIRCLE_RADIUS, dxfattribs={"layer": "COLUMNS"})
    doc.saveas(path)


def _rows_by_layer(elements: list[dict]) -> dict[str, dict]:
    return {str(row.get("category")): row for row in elements}


def test_a_millimetre_drawing_measures_in_metres(tmp_path: Path) -> None:
    """Lengths and areas arrive already scaled, because the consumer assumes metres.

    ``group_cad_elements`` sums the ``length`` and ``area`` columns straight
    into ``length_m`` and ``area_m2`` without asking what unit they were in, so
    the scaling has to have happened by the time the row is written.
    """
    source = tmp_path / "plan.dxf"
    _write_drawing(source, insunits=4)  # 4 = millimetres
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = convert_dxf_to_excel(source, out_dir)

    assert written is not None and written.exists()
    rows = _rows_by_layer(parse_cad_excel(written))

    assert rows["WALLS"]["length"] == pytest.approx(4.0)
    assert rows["SLABS"]["length"] == pytest.approx(16.0)
    assert rows["SLABS"]["area"] == pytest.approx(15.0)
    assert rows["COLUMNS"]["length"] == pytest.approx(2 * math.pi)
    assert rows["COLUMNS"]["area"] == pytest.approx(math.pi)


def test_the_layer_becomes_the_category_and_the_entity_the_type(tmp_path: Path) -> None:
    """The grouping an estimator already works in is the layer."""
    source = tmp_path / "plan.dxf"
    _write_drawing(source, insunits=4)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    rows = parse_cad_excel(convert_dxf_to_excel(source, out_dir))  # type: ignore[arg-type]

    by_layer = _rows_by_layer(rows)
    assert set(by_layer) == {"SLABS", "WALLS", "COLUMNS"}
    assert by_layer["WALLS"]["type name"] == "LINE"
    assert by_layer["SLABS"]["type name"] == "LWPOLYLINE"
    assert by_layer["COLUMNS"]["type name"] == "CIRCLE"
    # One row per entity, so the multiplier column stays at the single instance
    # the row represents. A row that claimed count 0 would vanish downstream.
    assert all(row["count"] == 1 for row in rows)


def test_a_drawing_with_no_usable_unit_reports_no_measurement(tmp_path: Path) -> None:
    """An unscalable drawing leaves the cells empty instead of printing raw units.

    A blank tells the estimator to set a scale. A number that is 1000x wrong
    tells them nothing and is believed.
    """
    source = tmp_path / "sketch.dxf"
    # Unitless AND small enough that the extents heuristic cannot infer
    # millimetres for it, which is what leaves the drawing genuinely unscaled.
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0
    doc.modelspace().add_line((0, 0), (7, 0), dxfattribs={"layer": "SKETCH"})
    doc.saveas(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    rows = parse_cad_excel(convert_dxf_to_excel(source, out_dir))  # type: ignore[arg-type]

    assert len(rows) == 1
    assert "length" not in rows[0], f"expected no length for an unscaled drawing, got {rows[0]!r}"
    assert rows[0]["source units"] == "unitless"


async def test_a_dxf_labelled_dwg_by_the_alias_still_reads_natively(tmp_path: Path) -> None:
    """The regression that hid this: the caller aliases dxf to dwg first.

    ``takeoff.router`` passes ``_CONVERTER_FORMAT_ALIASES.get(ext, ext)``, so a
    DXF upload reaches the conversion labelled "dwg". Routing on that label
    would send it to a binary that this host may not have. Routing on the file
    decides correctly, and this test would fail on a label-based check.
    """
    source = tmp_path / "plan.dxf"
    _write_drawing(source, insunits=6)  # 6 = metres
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = await convert_cad_to_excel(source, out_dir, "dwg")

    assert written is not None, "a DXF mislabelled dwg by the alias must still be read in-process"
    rows = _rows_by_layer(parse_cad_excel(written))
    # Authored in metres, so the numbers pass through unscaled.
    assert rows["WALLS"]["length"] == pytest.approx(4000.0)


@pytest.mark.parametrize("spelling", ["dxf", ".dxf", "DXF", ".DXF"])
def test_the_native_format_check_accepts_the_spellings_callers_pass(spelling: str) -> None:
    """Callers hold the extension with a dot, without one, and in either case."""
    assert is_natively_readable(spelling)


@pytest.mark.parametrize("needs_binary", ["dwg", "rvt", "dgn", "ifc", "rfa"])
def test_the_formats_that_need_a_binary_are_not_claimed(needs_binary: str) -> None:
    """Claiming a format is native would skip the converter and fail the upload."""
    assert not is_natively_readable(needs_binary)


# ── What a drawing shows twice must still be built once ────────────────────
#
# ``parse_dxf`` serves the viewer, so it returns every layout and the contents
# of every referenced block definition. Measured as delivered, a plan that also
# appears inside a titleblock sheet reports twice the concrete that will be
# poured, and a door template reports a door nobody placed. Neither shows up as
# an error anywhere; the table just reads high.


def _write_drawing_with_a_titleblock_sheet(path: Path) -> None:
    """A 10x5 m slab in the model, shown again on a sheet, plus two doors."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True, dxfattribs={"layer": "SLABS"})

    block = doc.blocks.new(name="DOOR")
    block.add_lwpolyline([(0, 0), (1, 0), (1, 2), (0, 2)], close=True, dxfattribs={"layer": "DOORS"})
    msp.add_blockref("DOOR", (2, 2), dxfattribs={"layer": "DOORS"})
    msp.add_blockref("DOOR", (6, 2), dxfattribs={"layer": "DOORS"})

    doc.layout("Layout1").add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True, dxfattribs={"layer": "SLABS"})
    doc.saveas(path)


def test_a_plan_shown_on_a_sheet_is_measured_once(tmp_path: Path) -> None:
    """The reported quantity is what gets built, not what gets drawn."""
    source = tmp_path / "with_sheet.dxf"
    _write_drawing_with_a_titleblock_sheet(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = convert_dxf_to_excel(source, out_dir)

    assert written is not None
    slabs = [row for row in parse_cad_excel(written) if row.get("category") == "SLABS"]
    assert len(slabs) == 1, f"the sheet layout added a second slab row: {slabs}"
    assert slabs[0]["area"] == pytest.approx(50.0), "50 m2 of slab, not the 100 m2 the drawing shows"


def test_a_block_definition_is_not_a_placed_element(tmp_path: Path) -> None:
    """Two doors are placed, so two doors are counted, and the template is not one."""
    source = tmp_path / "with_blocks.dxf"
    _write_drawing_with_a_titleblock_sheet(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = convert_dxf_to_excel(source, out_dir)

    assert written is not None
    doors = [row for row in parse_cad_excel(written) if row.get("category") == "DOORS"]
    assert len(doors) == 2, f"expected the two INSERTs and not the definition behind them: {doors}"
    assert {str(row.get("type name")) for row in doors} == {"INSERT"}


def test_a_drawing_living_entirely_on_one_sheet_is_still_measured(tmp_path: Path) -> None:
    """Some 2D exports leave the model empty. One sheet cannot double anything."""
    source = tmp_path / "sheet_only.dxf"
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    doc.layout("Layout1").add_lwpolyline([(0, 0), (8, 0), (8, 4), (0, 4)], close=True, dxfattribs={"layer": "SLABS"})
    doc.saveas(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = convert_dxf_to_excel(source, out_dir)

    assert written is not None
    slabs = [row for row in parse_cad_excel(written) if row.get("category") == "SLABS"]
    assert len(slabs) == 1
    assert slabs[0]["area"] == pytest.approx(32.0)


def test_several_sheets_and_an_empty_model_measure_nothing(tmp_path: Path) -> None:
    """Refusing to guess is the point: picking one sheet is how the double came back.

    An empty table sends the estimator back to the drawing. A table built from
    whichever sheet happened to sort first sends them to a tender.
    """
    from app.modules.boq.dxf_native import measurable_entities

    parsed = {
        "entities": [
            {"entity_type": "LWPOLYLINE", "layer": "SLABS", "layout": "Layout1"},
            {"entity_type": "LWPOLYLINE", "layer": "SLABS", "layout": "Layout2"},
        ]
    }

    assert measurable_entities(parsed) == []
