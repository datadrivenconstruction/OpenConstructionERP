"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression tests for IFC placement/bbox unit scaling (issue #53).

The IfcUnitAssignment parser already rescales IfcQuantity values into
canonical SI metres (covered by ``test_ifc_unit_assignment.py``). This
file covers the *geometry* side of the text-fallback parser: the
``IfcCartesianPoint`` placement coordinates that flow through
``_extract_placements`` into ``_generate_collada_boxes`` and the exported
bounding box.

Before the fix those coordinates were taken verbatim, so a millimetre-
authored model placed an element at e.g. ``(5000, 3000, 0)`` *metres* even
though its box extents were correctly rescaled to metres - yielding a
mangled bounding box (corner 5 km from origin, box only metres wide) that
broke viewer auto-framing and any geometry-derived quantity.

We force the text-fallback path (``find_converter -> None``) so we measure
this pure-Python code and not the DDC binary, mirroring
``test_ifc_unit_assignment.py``.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from app.modules.bim_hub.ifc_processor import process_ifc_file

# ── Fixtures / helpers ──────────────────────────────────────────────


@pytest.fixture
def workdir() -> Path:
    """Scratch dir per test - the parser writes placeholder COLLADA here."""
    d = Path(tempfile.mkdtemp(prefix="ifc_geom_units_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _force_text_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the text-IFC parser path so we measure THIS code, not DDC."""
    monkeypatch.setattr(
        "app.modules.boq.cad_import.find_converter",
        lambda _ext: None,
    )


_IFC_HEADER = """\
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('geom.ifc','2026-06-02',('OE'),('OE'),'','OE','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1= IFCORGANIZATION($,'OE',$,$,$);
#2= IFCAPPLICATION(#1,'1.0','OE','OE');
#3= IFCPERSON($,'OE',$,$,$,$,$,$);
#4= IFCPERSONANDORGANIZATION(#3,#1,$);
#5= IFCOWNERHISTORY(#4,#2,$,.ADDED.,$,$,$,1234567890);
"""

_IFC_FOOTER = """\
ENDSEC;
END-ISO-10303-21;
"""


def _make_placed_wall_ifc(
    unit_block: str,
    *,
    origin: tuple[float, float, float],
    length: float,
    width: float,
    height: float,
) -> str:
    """Synthesise an IFC with a single wall that has a real placement.

    The wall is located at ``origin`` (in the file's declared LENGTHUNIT)
    and carries Length/Width/Height base quantities (also in the declared
    unit). Both the placement and the quantities are expressed in the same
    source unit so the canonical-metre output must rescale both by the same
    factor.

    Args:
        unit_block: The STEP-21 lines declaring the IfcUnitAssignment.
        origin: ``(x, y, z)`` placement, in the source length unit.
        length: Wall length quantity, in the source length unit.
        width: Wall width quantity, in the source length unit.
        height: Wall height quantity, in the source length unit.

    Returns:
        A complete STEP-21 IFC document as a string.
    """
    ox, oy, oz = origin
    body = dedent(
        f"""
        #10= IFCCARTESIANPOINT(({ox},{oy},{oz}));
        #11= IFCAXIS2PLACEMENT3D(#10,$,$);
        #12= IFCLOCALPLACEMENT($,#11);
        #100= IFCBUILDINGSTOREY('storeyGUIDxxxxxxxxxx',#5,'L1',$,$,$,$,$,.ELEMENT.,0.0);
        #101= IFCWALL('wallGUIDxxxxxxxxxxxxxxx',#5,'Wall',$,$,#12,$,$,$);
        #102= IFCRELCONTAINEDINSPATIALSTRUCTURE('relGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#100);
        #200= IFCRELDEFINESBYPROPERTIES('rdpGUIDxxxxxxxxxxxxx',#5,$,$,(#101),#300);
        #300= IFCELEMENTQUANTITY('eqGUIDxxxxxxxxxxxxxxx',#5,'BaseQuantities',$,'OE',(#401,#402,#403));
        #401= IFCQUANTITYLENGTH('Length',$,$,#5,{length});
        #402= IFCQUANTITYLENGTH('Width',$,$,#5,{width});
        #403= IFCQUANTITYLENGTH('Height',$,$,#5,{height});
        """
    ).strip()
    return _IFC_HEADER + dedent(unit_block) + body + "\n" + _IFC_FOOTER


def _write_ifc(content: str, workdir: Path) -> Path:
    p = workdir / "fixture.ifc"
    p.write_text(content, encoding="utf-8")
    return p


def _wall(result: dict) -> dict:
    walls = [e for e in result["elements"] if e["element_type"] == "Wall"]
    assert walls, f"no walls extracted: {result.get('element_count')} elements"
    return walls[0]


# ── 1. Millimetre model: the headline #53 case ──────────────────────


def test_millimetre_placement_and_bbox_are_metres(workdir: Path) -> None:
    """A mm-authored wall at (5000,3000,0) mm must export at (5,3,0) m.

    This is the core regression: before the fix the placement was taken
    verbatim (5000 m) while the extents were correctly rescaled to metres,
    producing a bounding box whose corner sat 5 km from origin while the box
    was only ~4 m wide.
    """
    mm_units = """
    #20= IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
    #21= IFCUNITASSIGNMENT((#20));
    """
    ifc = _make_placed_wall_ifc(
        mm_units,
        origin=(5000.0, 3000.0, 0.0),
        length=4000.0,
        width=240.0,
        height=2700.0,
    )
    result = process_ifc_file(_write_ifc(ifc, workdir), workdir / "out")

    # Sanity: the unit parser saw millimetres.
    assert result["metadata"]["units"]["scale_table"]["LENGTHUNIT"] == pytest.approx(1e-3)

    # Quantities were already canonicalised (existing behaviour) - 4000 mm = 4 m.
    wall = _wall(result)
    assert wall["quantities"]["Length"] == pytest.approx(4.0)

    # Placement: 5000 mm = 5 m, 3000 mm = 3 m. (Was 5000/3000 before the fix.)
    bb = wall["bounding_box"]
    assert bb["min_x"] == pytest.approx(5.0)
    assert bb["min_y"] == pytest.approx(3.0)
    assert bb["min_z"] == pytest.approx(0.0)

    # The box must be internally coherent: max = origin + metre-scale extent.
    # length 4 m, width 0.24 m, height 2.7 m.
    assert bb["max_x"] == pytest.approx(9.0)  # 5.0 + 4.0
    assert bb["max_y"] == pytest.approx(3.24)  # 3.0 + 0.24
    assert bb["max_z"] == pytest.approx(2.7)  # 0.0 + 2.7

    # Global bounding box must match - and crucially be metre-sized, not km.
    gbb = result["bounding_box"]
    assert gbb["min"]["x"] == pytest.approx(5.0)
    assert gbb["max"]["x"] == pytest.approx(9.0)
    span_x = gbb["max"]["x"] - gbb["min"]["x"]
    assert span_x == pytest.approx(4.0)
    # Guard against the 1000x regression explicitly.
    assert span_x < 100.0, "X span looks unscaled (millimetres treated as metres)"


# ── 2. Imperial (feet via IfcConversionBasedUnit) ───────────────────


def test_imperial_feet_placement_is_metres(workdir: Path) -> None:
    """A foot-authored wall at (10,20,0) ft must export at ~3.05/6.10/0 m."""
    feet_units = """
    #20= IFCCONVERSIONBASEDUNIT(#100,.LENGTHUNIT.,'FOOT',$);
    #21= IFCUNITASSIGNMENT((#20));
    """
    ifc = _make_placed_wall_ifc(
        feet_units,
        origin=(10.0, 20.0, 0.0),
        length=13.0,
        width=1.0,
        height=9.0,
    )
    result = process_ifc_file(_write_ifc(ifc, workdir), workdir / "out")

    units = result["metadata"]["units"]
    assert units["unit_system"] == "imperial"
    assert units["scale_table"]["LENGTHUNIT"] == pytest.approx(0.3048)

    wall = _wall(result)
    bb = wall["bounding_box"]
    # 10 ft = 3.048 m, 20 ft = 6.096 m.
    assert bb["min_x"] == pytest.approx(10.0 * 0.3048)
    assert bb["min_y"] == pytest.approx(20.0 * 0.3048)
    # length 13 ft = 3.9624 m -> max_x = 3.048 + 3.9624.
    assert bb["max_x"] == pytest.approx((10.0 + 13.0) * 0.3048)


# ── 3. Regression guard: SI metres must stay unchanged ──────────────


def test_metre_placement_unchanged(workdir: Path) -> None:
    """A wall already authored in SI metres must pass through 1:1.

    Guards against the fix accidentally double-scaling or shifting an
    already-canonical model (length_scale == 1.0 must be a no-op).
    """
    si_units = """
    #20= IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
    #21= IFCUNITASSIGNMENT((#20));
    """
    ifc = _make_placed_wall_ifc(
        si_units,
        origin=(5.0, 3.0, 0.0),
        length=4.0,
        width=0.24,
        height=2.7,
    )
    result = process_ifc_file(_write_ifc(ifc, workdir), workdir / "out")

    assert result["metadata"]["units"]["scale_table"]["LENGTHUNIT"] == pytest.approx(1.0)
    bb = _wall(result)["bounding_box"]
    assert bb["min_x"] == pytest.approx(5.0)
    assert bb["min_y"] == pytest.approx(3.0)
    assert bb["max_x"] == pytest.approx(9.0)
    assert bb["max_z"] == pytest.approx(2.7)
