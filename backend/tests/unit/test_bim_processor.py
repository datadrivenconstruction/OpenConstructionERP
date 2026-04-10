"""Tests for BIM file processing pipeline (ifc_processor.py).

Covers:
- Text-based IFC parser fallback (works without DDC converters)
- DDC converter integration (skipped if RvtExporter.exe not installed)
- Element extraction, storey detection, COLLADA generation
- Path handling (relative vs absolute paths)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.modules.bim_hub.ifc_processor import (
    _classify_discipline,
    _empty_result,
    _excel_elements_to_bim_result,
    process_ifc_file,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


MINIMAL_IFC = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('test.ifc','2026-04-10',('Test'),('OE'),'','OE','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1= IFCORGANIZATION($,'OE',$,$,$);
#2= IFCAPPLICATION(#1,'1.0','OE','OE');
#5= IFCOWNERHISTORY(#1,#2,$,.READWRITE.,$,$,$,0);
#10= IFCPROJECT('0001',#5,'TestProject',$,$,$,$,$,$);
#40= IFCBUILDINGSTOREY('0004',#5,'Ground Floor',$,$,$,$,$,.ELEMENT.,0.0);
#41= IFCBUILDINGSTOREY('0005',#5,'First Floor',$,$,$,$,$,.ELEMENT.,3.0);
#50= IFCWALL('0010',#5,'External Wall A',$,$,$,$,$);
#51= IFCWALL('0011',#5,'External Wall B',$,$,$,$,$);
#52= IFCSLAB('0012',#5,'Floor Slab',$,$,$,$,$);
#53= IFCCOLUMN('0013',#5,'Column C1',$,$,$,$,$);
#54= IFCBEAM('0014',#5,'Beam B1',$,$,$,$,$);
#55= IFCDOOR('0015',#5,'Front Door',$,$,$,$,$);
#56= IFCWINDOW('0016',#5,'Window W1',$,$,$,$,$);
#60= IFCRELCONTAINEDINSPATIALSTRUCTURE('0020',#5,'Floor1','Contains',#50,#51,#52,#53,#54,#55,#56,#40);
ENDSEC;
END-ISO-10303-21;
"""


@pytest.fixture()
def temp_dir():
    """Provide a fresh temp directory for each test."""
    d = Path(tempfile.mkdtemp(prefix="bim_test_"))
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def minimal_ifc_file(temp_dir):
    """Write a minimal IFC file and return its path."""
    f = temp_dir / "test.ifc"
    f.write_text(MINIMAL_IFC, encoding="utf-8")
    return f


# ─── Discipline classification ──────────────────────────────────────────────


class TestClassifyDiscipline:
    def test_walls_are_structural(self):
        assert _classify_discipline("IFCWALL") == "structural"
        assert _classify_discipline("Wall") == "structural"
        assert _classify_discipline("Walls") == "structural"

    def test_doors_are_architecture(self):
        assert _classify_discipline("IFCDOOR") == "architecture"
        assert _classify_discipline("Door") == "architecture"

    def test_pipes_are_mep(self):
        assert _classify_discipline("Pipefitting") == "mep"
        assert _classify_discipline("DuctFitting") == "mep"
        assert _classify_discipline("FlowSegment") == "mep"

    def test_unknown_is_other(self):
        assert _classify_discipline("ElectricalLoadClassification") == "other"


# ─── Text-based IFC parser ──────────────────────────────────────────────────


class TestProcessIFCFile:
    def test_minimal_ifc_extracts_all_elements(self, minimal_ifc_file, temp_dir, monkeypatch):
        """The IFC text parser should extract walls, slab, column, beam, door, window.

        We force the text-parser path by monkey-patching find_converter to return
        None so that the test runs identically with and without DDC installed.
        """
        out_dir = temp_dir / "output"
        out_dir.mkdir()

        # Force text-parser fallback (skip DDC converter if installed)
        monkeypatch.setattr(
            "app.modules.boq.cad_import.find_converter",
            lambda ext: None,
        )

        result = process_ifc_file(minimal_ifc_file, out_dir)

        # Expect at least the 7 building elements declared in MINIMAL_IFC
        assert result["element_count"] >= 7, f"Expected ≥7 elements, got {result['element_count']}"
        # Verify each declared element type appears
        types = {e["element_type"].lower() for e in result["elements"]}
        assert any("wall" in t for t in types), "Wall not found"
        assert any("slab" in t for t in types), "Slab not found"
        assert any("column" in t for t in types), "Column not found"
        assert any("beam" in t for t in types), "Beam not found"
        assert any("door" in t for t in types), "Door not found"
        assert any("window" in t for t in types), "Window not found"
        # Storey assignment via IFCRELCONTAINEDINSPATIALSTRUCTURE
        assert "Ground Floor" in result["storeys"]
        assert result["has_geometry"] is True
        assert result["geometry_path"] is not None

    def test_minimal_ifc_geometry_dae_created(self, minimal_ifc_file, temp_dir):
        """A COLLADA .dae file should be created in the output dir."""
        out_dir = temp_dir / "output"
        out_dir.mkdir()

        result = process_ifc_file(minimal_ifc_file, out_dir)

        dae = Path(result["geometry_path"])
        assert dae.exists()
        assert dae.suffix == ".dae"
        assert dae.stat().st_size > 0
        # Validate it's actual COLLADA XML
        content = dae.read_text(encoding="utf-8")
        assert "COLLADA" in content
        assert "library_geometries" in content

    def test_minimal_ifc_disciplines_classified(self, minimal_ifc_file, temp_dir):
        """Walls/slab/column/beam should classify as structural; door/window as architecture."""
        out_dir = temp_dir / "output"
        out_dir.mkdir()

        result = process_ifc_file(minimal_ifc_file, out_dir)

        assert "structural" in result["disciplines"]
        assert "architecture" in result["disciplines"]

    def test_nonexistent_file_returns_empty(self, temp_dir):
        """Missing file should return _empty_result without crashing."""
        out_dir = temp_dir / "output"
        out_dir.mkdir()
        result = process_ifc_file(temp_dir / "nope.ifc", out_dir)
        assert result["element_count"] == 0

    def test_empty_file_returns_empty(self, temp_dir):
        """Empty file should not crash."""
        empty = temp_dir / "empty.ifc"
        empty.write_text("", encoding="utf-8")
        out_dir = temp_dir / "output"
        out_dir.mkdir()
        result = process_ifc_file(empty, out_dir)
        assert result["element_count"] == 0

    def test_relative_path_handled(self, minimal_ifc_file, temp_dir, monkeypatch):
        """Relative input paths should be resolved correctly (regression for DDC bug)."""
        out_dir = temp_dir / "output"
        out_dir.mkdir()
        # Use a relative path explicitly
        monkeypatch.chdir(temp_dir)
        result = process_ifc_file(Path(minimal_ifc_file.name), out_dir)
        assert result["element_count"] >= 1


# ─── Excel→BIM result mapping ───────────────────────────────────────────────


class TestExcelElementsToBIMResult:
    def test_filters_skip_categories(self, temp_dir):
        """Materials, sun studies, viewports should be excluded."""
        raw = [
            {"id": 1, "category": "OST_Materials", "name": "Brick"},
            {"id": 2, "category": "OST_Walls", "name": "Wall A", "level": "L1"},
            {"id": 3, "category": "OST_SunStudy", "name": "Solar"},
            {"id": 4, "category": "OST_Doors", "name": "Door A", "level": "L1"},
        ]
        result = _excel_elements_to_bim_result(raw, temp_dir)
        # Only walls and doors should remain
        assert result["element_count"] == 2
        types = {e["element_type"] for e in result["elements"]}
        assert "Walls" in types
        assert "Doors" in types

    def test_filters_none_category(self, temp_dir):
        """Rows with category=None should be skipped."""
        raw = [
            {"id": 1, "category": None, "name": "Orphan"},
            {"id": 2, "category": "OST_Walls", "name": "Wall A"},
        ]
        result = _excel_elements_to_bim_result(raw, temp_dir)
        assert result["element_count"] == 1

    def test_extracts_quantities(self, temp_dir):
        """Length/area/volume/width/height should be parsed as floats."""
        raw = [
            {
                "id": 1,
                "category": "OST_Walls",
                "name": "Wall",
                "length": "5000",
                "height": "2700",
                "width": "200",
                "area": "13.5",
            },
        ]
        result = _excel_elements_to_bim_result(raw, temp_dir)
        elem = result["elements"][0]
        assert elem["quantities"]["Length"] == 5000.0
        assert elem["quantities"]["Height"] == 2700.0
        assert elem["quantities"]["Width"] == 200.0
        assert elem["quantities"]["Area"] == 13.5

    def test_uniqueid_used_as_stable_id(self, temp_dir):
        raw = [
            {
                "id": 1,
                "category": "OST_Walls",
                "name": "Wall",
                "uniqueid": "abc-def-123",
            },
        ]
        result = _excel_elements_to_bim_result(raw, temp_dir)
        assert result["elements"][0]["stable_id"] == "abc-def-123"

    def test_storey_detection(self, temp_dir):
        raw = [
            {"id": 1, "category": "OST_Walls", "name": "W1", "level": "Ground Floor"},
            {"id": 2, "category": "OST_Walls", "name": "W2", "level": "Level 2"},
            {"id": 3, "category": "OST_Walls", "name": "W3", "level": "Ground Floor"},
        ]
        result = _excel_elements_to_bim_result(raw, temp_dir)
        assert set(result["storeys"]) == {"Ground Floor", "Level 2"}

    def test_property_caps(self, temp_dir):
        """Properties dict should cap at 30 entries to keep payloads small."""
        raw = [{"id": 1, "category": "OST_Walls", "name": "W"}]
        # Add 50 extra properties
        raw[0].update({f"prop_{i}": f"value_{i}" for i in range(50)})
        result = _excel_elements_to_bim_result(raw, temp_dir)
        assert len(result["elements"][0]["properties"]) <= 30


# ─── Empty result baseline ──────────────────────────────────────────────────


def test_empty_result_shape():
    r = _empty_result()
    assert r["element_count"] == 0
    assert r["elements"] == []
    assert r["storeys"] == []
    assert r["has_geometry"] is False
